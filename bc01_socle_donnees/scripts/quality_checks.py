"""
BC01 — Contrôles qualité du socle de données.

Exécute une série de vérifications SQL sur le socle (staging + dwh),
journalise chaque résultat dans ops.controle_qualite et affiche un
résumé. À lancer après chaque chargement (batch ou streaming) pour
détecter une régression avant qu'elle n'atteigne les blocs suivants.

Usage :
    python scripts/quality_checks.py
"""
import logging
import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
log = logging.getLogger("quality_checks")


def get_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5434"),
        dbname=os.getenv("POSTGRES_DB", "frauddetect"),
        user=os.getenv("POSTGRES_USER", "fraud_admin"),
        password=os.getenv("POSTGRES_PASSWORD", "fraud_secret"),
    )


# Chaque contrôle : une requête qui renvoie UNE valeur scalaire, une
# fonction qui juge cette valeur, et le seuil affiché pour référence.
CHECKS = [
    dict(
        nom="fk_completes_fact", categorie="completude",
        detail="Aucune clé étrangère NULL dans dwh.fact_transactions",
        sql="SELECT COUNT(*) FROM dwh.fact_transactions "
            "WHERE client_key IS NULL OR temps_key IS NULL OR canal_key IS NULL;",
        seuil=0, ok=lambda v: v == 0,
    ),
    dict(
        nom="integrite_client_staging", categorie="integrite",
        detail="Tout client_id du staging existe dans dwh.dim_clients",
        sql="SELECT COUNT(*) FROM staging.raw_transactions s "
            "LEFT JOIN dwh.dim_clients c ON c.client_id = s.client_id WHERE c.client_key IS NULL;",
        seuil=0, ok=lambda v: v == 0,
    ),
    dict(
        nom="unicite_transaction_bk", categorie="unicite",
        detail="Aucun doublon de clé métier dans dwh.fact_transactions",
        sql="SELECT COUNT(*) - COUNT(DISTINCT transaction_bk) FROM dwh.fact_transactions;",
        seuil=0, ok=lambda v: v == 0,
    ),
    dict(
        nom="montants_positifs", categorie="coherence",
        detail="Aucun montant nul ou négatif",
        sql="SELECT COUNT(*) FROM dwh.fact_transactions WHERE montant <= 0;",
        seuil=0, ok=lambda v: v == 0,
    ),
    dict(
        nom="distance_non_negative", categorie="coherence",
        detail="Aucune distance au domicile négative",
        sql="SELECT COUNT(*) FROM dwh.fact_transactions WHERE distance_domicile_km < 0;",
        seuil=0, ok=lambda v: v == 0,
    ),
    dict(
        nom="coherence_label_fraude", categorie="coherence",
        detail="fraud_type renseigné si et seulement si is_fraud = TRUE",
        sql="SELECT COUNT(*) FROM dwh.fact_transactions "
            "WHERE (is_fraud IS TRUE AND fraud_type IS NULL) OR (is_fraud IS FALSE AND fraud_type IS NOT NULL);",
        seuil=0, ok=lambda v: v == 0,
    ),
    dict(
        nom="taux_fraude_plausible", categorie="plausibilite",
        detail="Taux de fraude (transactions labellisées) dans [0.5 %, 3.0 %]",
        sql="SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE is_fraud) "
            "/ NULLIF(COUNT(*) FILTER (WHERE is_fraud IS NOT NULL), 0), 3) FROM dwh.fact_transactions;",
        seuil=3.0, ok=lambda v: v is not None and 0.5 <= v <= 3.0,
    ),
    dict(
        nom="staging_transforme", categorie="completude",
        detail="Aucune ligne de staging non transformée depuis plus de 10 minutes",
        sql="SELECT COUNT(*) FROM staging.raw_transactions "
            "WHERE traite = FALSE AND ingested_at < now() - interval '10 minutes';",
        seuil=0, ok=lambda v: v == 0,
    ),
    dict(
        nom="referentiel_agences", categorie="completude",
        detail="dwh.dim_agences contient les 10 agences attendues",
        sql="SELECT COUNT(*) FROM dwh.dim_agences;",
        seuil=10, ok=lambda v: v == 10,
    ),
    dict(
        nom="referentiel_canaux", categorie="completude",
        detail="dwh.dim_canal contient les 9 combinaisons attendues + le membre 'Inconnu' (clé 0)",
        sql="SELECT COUNT(*) FROM dwh.dim_canal;",
        seuil=10, ok=lambda v: v == 10,
    ),
]


def main():
    conn = get_connection()
    results = []
    with conn.cursor() as cur:
        for chk in CHECKS:
            cur.execute(chk["sql"])
            valeur = cur.fetchone()[0]
            valeur_f = float(valeur) if valeur is not None else None
            statut = "OK" if chk["ok"](valeur_f) else "KO"
            cur.execute(
                "INSERT INTO ops.controle_qualite (nom_controle, categorie, statut, valeur, seuil, detail) "
                "VALUES (%s, %s, %s, %s, %s, %s);",
                (chk["nom"], chk["categorie"], statut, valeur_f, chk["seuil"], chk["detail"]),
            )
            results.append((chk["nom"], statut, valeur_f, chk["detail"]))
    conn.commit()
    conn.close()

    n_ok = sum(1 for r in results if r[1] == "OK")
    log.info("Résultat des contrôles qualité : %d/%d au vert", n_ok, len(results))
    for nom, statut, valeur, detail in results:
        marqueur = "✓" if statut == "OK" else "✗"
        log.info("  [%s] %-24s valeur=%-8s | %s", marqueur, nom, valeur, detail)

    if n_ok < len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
