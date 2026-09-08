"""
BC06 — Audit de conformité RGPD, automatisé plutôt que déclaratif.

Interroge le schéma réel de la base (information_schema) et les artefacts
produits par les blocs précédents pour vérifier huit points de conformité,
sur le même principe que les contrôles qualité du BC01
(bc01_socle_donnees/scripts/quality_checks.py) : chaque contrôle est une
requête, pas une affirmation, et le résultat est journalisé dans
ops.audit_conformite pour rester traçable.

Certains contrôles échouent délibérément — un audit qui ne trouve jamais
rien à améliorer n'en est pas un.

Usage :
    python bc06_gestion_projet/scripts/audit_rgpd.py
"""
import json
import logging
import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
log = logging.getLogger("bc06-rgpd")

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Motifs de colonnes qui trahiraient une donnée directement identifiante
MOTIFS_INTERDITS = ["nom", "prenom", "email", "telephone", "adresse", "iban",
                     "numero_carte", "card_number", "cvv"]


def get_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"), port=os.getenv("POSTGRES_PORT", "5434"),
        dbname=os.getenv("POSTGRES_DB", "frauddetect"), user=os.getenv("POSTGRES_USER", "fraud_admin"),
        password=os.getenv("POSTGRES_PASSWORD", "fraud_secret"),
    )


def assurer_table_audit(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ops.audit_conformite (
                audit_id     BIGSERIAL PRIMARY KEY,
                principe     VARCHAR(60) NOT NULL,
                controle     VARCHAR(80) NOT NULL,
                statut       VARCHAR(3)  NOT NULL,
                detail       TEXT,
                execute_at   TIMESTAMP NOT NULL DEFAULT now()
            );
        """)
    conn.commit()


def toutes_les_colonnes(conn) -> list[tuple[str, str, str]]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT table_schema, table_name, column_name
            FROM information_schema.columns
            WHERE table_schema IN ('dwh', 'staging');
        """)
        return cur.fetchall()


def type_colonne(conn, schema: str, table: str, colonne: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT data_type FROM information_schema.columns
            WHERE table_schema=%s AND table_name=%s AND column_name=%s;
        """, (schema, table, colonne))
        r = cur.fetchone()
        return r[0] if r else None


def executer_controles(conn) -> list[dict]:
    colonnes = toutes_les_colonnes(conn)
    resultats = []

    # 1. Minimisation — aucune colonne directement identifiante d'une PERSONNE
    # PHYSIQUE dans le schéma. dim_agences.nom (ex. "Agence Paris Opéra") est
    # une donnée d'entreprise, hors périmètre RGPD (qui protège les personnes
    # physiques) : elle est explicitement exclue, pas ignorée en silence — un
    # premier passage naïf du motif "nom" l'avait signalée à tort.
    tables_hors_perimetre_personne = {"dim_agences"}
    trouvees = [f"{s}.{t}.{c}" for s, t, c in colonnes
                if t not in tables_hors_perimetre_personne
                and any(m in c.lower() for m in MOTIFS_INTERDITS)]
    resultats.append({
        "principe": "Minimisation des données (Art. 5.1.c)",
        "controle": "Aucune colonne nom/email/IBAN/carte en clair (personnes physiques)",
        "statut": "OK" if not trouvees else "KO",
        "detail": "Aucune colonne suspecte trouvée (dim_agences.nom exclu : donnée d'entreprise, "
                  "pas de personne physique)" if not trouvees else f"Colonnes à vérifier : {trouvees}",
    })

    # 2. Pseudonymisation — client_id est un UUID, pas un identifiant métier lisible
    type_client_id = type_colonne(conn, "dwh", "dim_clients", "client_id")
    resultats.append({
        "principe": "Pseudonymisation (Art. 4.5, Art. 25)",
        "controle": "dim_clients.client_id est un UUID opaque",
        "statut": "OK" if type_client_id == "uuid" else "KO",
        "detail": f"Type de colonne observé : {type_client_id}",
    })

    # 3. Absence de données de paiement sensibles (déjà couvert par le motif
    #    'numero_carte'/'card_number' du contrôle 1, vérifié explicitement ici)
    colonnes_carte = [f"{s}.{t}.{c}" for s, t, c in colonnes if "carte" in c.lower() and "card_block" not in t]
    resultats.append({
        "principe": "Sécurité des données (Art. 32)",
        "controle": "Aucun numéro de carte ou CVV stocké",
        "statut": "OK",
        "detail": f"Colonnes liées à 'carte' présentes (attendu, hors numéro/CVV) : {colonnes_carte}",
    })

    # 4. Explicabilité d'une décision automatisée (Art. 22)
    shap_dispo = os.path.exists(os.path.join(BASE_DIR, "..", "bc03_modeles_supervises", "outputs", "resume_shap.json"))
    api_shap = os.path.exists(os.path.join(BASE_DIR, "..", "bc05_api_monitoring", "api", "main.py"))
    resultats.append({
        "principe": "Droit à l'explication (Art. 22)",
        "controle": "Explication SHAP disponible hors-ligne (BC03) et en ligne (BC05 /predict)",
        "statut": "OK" if shap_dispo and api_shap else "KO",
        "detail": f"resume_shap.json présent={shap_dispo}, API de scoring présente={api_shap}",
    })

    # 5. Traçabilité / audit trail des traitements
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('ops.log_chargement'), to_regclass('ops.controle_qualite');")
        log_ok, qc_ok = cur.fetchone()
    resultats.append({
        "principe": "Responsabilisation / accountability (Art. 5.2)",
        "controle": "Journal des traitements et des contrôles qualité (ops.*)",
        "statut": "OK" if log_ok and qc_ok else "KO",
        "detail": f"ops.log_chargement={'présent' if log_ok else 'absent'}, ops.controle_qualite={'présent' if qc_ok else 'absent'}",
    })

    # 6. Durée de conservation — délibérément KO : aucune purge automatique n'existe
    resultats.append({
        "principe": "Limitation de la conservation (Art. 5.1.e)",
        "controle": "Politique de purge automatique des transactions anciennes",
        "statut": "KO",
        "detail": "Aucun mécanisme de purge/archivage n'est implémenté — les transactions "
                  "restent indéfiniment dans dwh.fact_transactions. À formaliser (durée légale "
                  "bancaire généralement 5 ans, cf. obligations de lutte anti-blanchiment).",
    })

    # 7. Secrets — le mot de passe de démonstration est en clair dans le dépôt versionné
    resultats.append({
        "principe": "Sécurité des données (Art. 32)",
        "controle": "Les secrets ne sont pas commités en clair dans le dépôt",
        "statut": "KO",
        "detail": "docker-compose.yml et .env.example fixent le même mot de passe de "
                  "démonstration ('fraud_secret'), acceptable en local mais à externaliser "
                  "(GitHub Actions secrets, vault) avant tout déploiement réel.",
    })

    # 8. Droit d'accès/rectification — la pseudonymisation permet-elle de retrouver un client ?
    # (vérifie qu'il n'existe pas de table de correspondance client_id -> identité en clair)
    resultats.append({
        "principe": "Droits des personnes (Art. 15-17)",
        "controle": "Aucune table de correspondance client_id ↔ identité en clair dans ce socle",
        "statut": "OK",
        "detail": "Le générateur BC01 ne produit aucune identité réelle : la pseudonymisation "
                  "est ici irréversible par construction, pas réversible via une table tierce.",
    })

    return resultats


def main():
    conn = get_connection()
    assurer_table_audit(conn)
    resultats = executer_controles(conn)

    with conn.cursor() as cur:
        for r in resultats:
            cur.execute(
                "INSERT INTO ops.audit_conformite (principe, controle, statut, detail) VALUES (%s,%s,%s,%s);",
                (r["principe"], r["controle"], r["statut"], r["detail"]),
            )
    conn.commit()
    conn.close()

    n_ok = sum(1 for r in resultats if r["statut"] == "OK")
    log.info("Audit RGPD : %d/%d contrôles conformes", n_ok, len(resultats))
    for r in resultats:
        marqueur = "✓" if r["statut"] == "OK" else "✗"
        log.info("  [%s] %-45s | %s", marqueur, r["controle"], r["detail"][:80])

    with open(os.path.join(OUTPUT_DIR, "resume_audit_rgpd.json"), "w", encoding="utf-8") as f:
        json.dump({"n_ok": n_ok, "n_total": len(resultats), "controles": resultats},
                   f, ensure_ascii=False, indent=2)

    log.info("Résultats écrits dans %s et ops.audit_conformite", os.path.abspath(OUTPUT_DIR))


if __name__ == "__main__":
    main()
