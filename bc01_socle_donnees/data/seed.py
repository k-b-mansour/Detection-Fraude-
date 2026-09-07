"""
BC01 — Génération des données synthétiques et chargement dans le
socle de données (staging -> dwh -> mart), voie batch.

Le script ne touche jamais dwh.fact_transactions directement : il
charge les dimensions (référentiel stable), puis les transactions
dans staging.raw_transactions, puis appelle
dwh.charger_faits_transactions('batch') — la même fonction que le
consumer Kafka utilise côté streaming. Idempotent : rejouable sans
créer de doublons (clé métier `transaction_bk` déterministe).

Usage :
    python data/seed.py --clients 5000 --transactions 400000 --fraud-rate 0.015
"""
import argparse
import io
import logging
import os
import time
import uuid
from datetime import datetime, timedelta

import numpy as np
import psycopg2
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s:%(funcName)s:%(lineno)d - %(message)s",
)
log = logging.getLogger("seed")

RNG = np.random.default_rng(seed=42)  # seed fixe -> jeu de données reproductible

# ------------------------------------------------------------------
# Référentiels fixes
# ------------------------------------------------------------------
AGENCES = [
    ("AG01", "Agence Paris Opéra", "Île-de-France", "Paris"),
    ("AG02", "Agence Lyon Part-Dieu", "Auvergne-Rhône-Alpes", "Lyon"),
    ("AG03", "Agence Marseille Vieux-Port", "Provence-Alpes-Côte d'Azur", "Marseille"),
    ("AG04", "Agence Toulouse Capitole", "Occitanie", "Toulouse"),
    ("AG05", "Agence Nantes Centre", "Pays de la Loire", "Nantes"),
    ("AG06", "Agence Lille Grand-Place", "Hauts-de-France", "Lille"),
    ("AG07", "Agence Bordeaux Chartrons", "Nouvelle-Aquitaine", "Bordeaux"),
    ("AG08", "Agence Strasbourg Centre", "Grand Est", "Strasbourg"),
    ("AG09", "Agence Rennes Centre", "Bretagne", "Rennes"),
    ("AG10", "Agence Nice Masséna", "Provence-Alpes-Côte d'Azur", "Nice"),
]

# (canal, mcc_code, mcc_libelle, is_online, is_contactless)
CANAUX = [
    ("en_ligne", "5411", "Supermarché en ligne", True, False),
    ("en_ligne", "5311", "Grand magasin en ligne", True, False),
    ("en_ligne", "4829", "Transfert d'argent", True, False),
    ("sans_contact", "5812", "Restaurant", False, True),
    ("sans_contact", "5912", "Pharmacie", False, True),
    ("puce", "5541", "Station essence", False, False),
    ("puce", "5411", "Supermarché", False, False),
    ("puce", "5921", "Vente d'alcool / tabac", False, False),
    ("distributeur", "6011", "Retrait DAB", False, False),
]

PAYS_ETRANGERS_RISQUE = ["RO", "NG", "CN", "RU", "BR"]
PAYS_VOISINS = ["ES", "DE", "IT", "GB", "BE"]

FRAUD_TYPES = [
    "usurpation_identite",
    "fraude_en_ligne",
    "skimming",
    "test_carte",
    "vol_carte_physique",
    "ingenierie_sociale",
]

SEGMENTS = ["particulier", "premium", "professionnel"]
SEGMENT_WEIGHTS = [0.70, 0.20, 0.10]

DATE_DEBUT = datetime(2025, 1, 1, 0, 0, 0)
DATE_FIN = datetime(2025, 12, 31, 23, 0, 0)


def get_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5434"),
        dbname=os.getenv("POSTGRES_DB", "frauddetect"),
        user=os.getenv("POSTGRES_USER", "fraud_admin"),
        password=os.getenv("POSTGRES_PASSWORD", "fraud_secret"),
    )


def copy_from_buffer(conn, table: str, columns: list[str], rows: list[tuple]):
    buf = io.StringIO()
    for row in rows:
        buf.write(
            "\t".join("\\N" if v is None else str(v).replace("\t", " ") for v in row)
            + "\n"
        )
    buf.seek(0)
    with conn.cursor() as cur:
        cur.copy_expert(
            f"COPY {table} ({', '.join(columns)}) FROM STDIN WITH (FORMAT text, NULL '\\N')",
            buf,
        )
    conn.commit()


def truncate_all(conn):
    with conn.cursor() as cur:
        cur.execute(
            "TRUNCATE dwh.fact_card_blocks, dwh.fact_transactions, staging.raw_transactions, "
            "dwh.dim_clients, dwh.dim_agences, dwh.dim_temps, dwh.dim_canal "
            "RESTART IDENTITY CASCADE;"
        )
    conn.commit()
    log.info("Tables vidées (RESTART IDENTITY) — nouveau chargement à blanc")


def log_chargement_debut(conn, source: str, mode: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ops.log_chargement (source, mode, statut) "
            "VALUES (%s, %s, 'EN_COURS') RETURNING log_id;",
            (source, mode),
        )
        log_id = cur.fetchone()[0]
    conn.commit()
    return log_id


def log_chargement_fin(conn, log_id: int, nb_lignes: int, duree_ms: int, statut: str, message: str = None):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE ops.log_chargement SET nb_lignes=%s, duree_ms=%s, statut=%s, "
            "message=%s, termine_at=now() WHERE log_id=%s;",
            (nb_lignes, duree_ms, statut, message, log_id),
        )
    conn.commit()


def seed_unknown_members(conn):
    """Recrée les membres 'Inconnu' (clé 0) que TRUNCATE vient de vider.
    dwh.charger_faits_transactions() s'y replie quand un horodatage ou un
    canal streaming ne matche aucune dimension — voir 04_transform.sql."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO dwh.dim_temps (temps_key, horodatage, date_jour, annee, mois, jour, "
            "heure, jour_semaine, is_weekend, is_nuit) "
            "VALUES (0, '1900-01-01 00:00:00', '1900-01-01', 1900, 1, 1, 0, 1, FALSE, FALSE);"
        )
        cur.execute(
            "INSERT INTO dwh.dim_canal (canal_key, canal, mcc_code, mcc_libelle, is_online, is_contactless) "
            "VALUES (0, 'inconnu', '0000', 'Canal non résolu', FALSE, FALSE);"
        )
    conn.commit()
    log.info("Membres 'Inconnu' (clé 0) recréés dans dim_temps et dim_canal")


def seed_agences(conn):
    copy_from_buffer(conn, "dwh.dim_agences", ["code_agence", "nom", "region", "ville"], AGENCES)
    log.info("dwh.dim_agences : %d lignes", len(AGENCES))


def seed_canal(conn):
    copy_from_buffer(
        conn, "dwh.dim_canal",
        ["canal", "mcc_code", "mcc_libelle", "is_online", "is_contactless"],
        CANAUX,
    )
    log.info("dwh.dim_canal : %d lignes", len(CANAUX))


def seed_temps(conn):
    rows = []
    current = DATE_DEBUT
    while current <= DATE_FIN:
        jour_semaine = current.isoweekday()  # 1=lundi ... 7=dimanche
        rows.append((
            current.isoformat(sep=" "), current.date().isoformat(),
            current.year, current.month, current.day, current.hour,
            jour_semaine, jour_semaine >= 6, current.hour < 6,
        ))
        current += timedelta(hours=1)

    copy_from_buffer(
        conn, "dwh.dim_temps",
        ["horodatage", "date_jour", "annee", "mois", "jour", "heure",
         "jour_semaine", "is_weekend", "is_nuit"],
        rows,
    )
    log.info("dwh.dim_temps : %d lignes (%s -> %s)", len(rows), DATE_DEBUT, DATE_FIN)
    return len(rows)


def seed_clients(conn, n_clients: int):
    today = datetime(2025, 12, 31)
    ages = RNG.integers(18, 85, size=n_clients)
    dates_naissance = [
        (today - timedelta(days=int(a * 365.25) + int(RNG.integers(0, 365)))).date().isoformat()
        for a in ages
    ]
    segments = RNG.choice(SEGMENTS, size=n_clients, p=SEGMENT_WEIGHTS)
    agence_keys = RNG.integers(1, len(AGENCES) + 1, size=n_clients)

    revenu_base = {"particulier": 2200, "premium": 5500, "professionnel": 4200}
    revenus = [round(float(RNG.lognormal(mean=np.log(revenu_base[s]), sigma=0.35)), 2) for s in segments]

    departements = [f"{RNG.integers(1, 96):02d}" for _ in range(n_clients)]
    codes_postaux = [f"{d}{RNG.integers(100, 999)}" for d in departements]

    anciennete_jours = RNG.integers(30, 3650, size=n_clients)
    dates_entree = [(today - timedelta(days=int(d))).date().isoformat() for d in anciennete_jours]

    rows = [
        (
            str(uuid.uuid4()), int(agence_keys[i]), dates_naissance[i], codes_postaux[i],
            departements[i], segments[i], revenus[i], "actif", dates_entree[i],
        )
        for i in range(n_clients)
    ]

    copy_from_buffer(
        conn, "dwh.dim_clients",
        ["client_id", "agence_key", "date_naissance", "code_postal", "departement",
         "segment", "revenu_mensuel_net", "statut", "date_entree_relation"],
        rows,
    )
    log.info("dwh.dim_clients : %d lignes", n_clients)
    return rows  # (client_id, ...) — on a besoin des client_id pour la génération des transactions


# Poids horaires (24 valeurs) : activité plus forte 8h-22h, creuse la nuit
HEURE_WEIGHTS = np.array(
    [0.3, 0.2, 0.15, 0.1, 0.1, 0.2, 0.6, 1.2, 1.8, 2.0, 2.0, 2.2,
     2.4, 2.2, 2.0, 2.0, 2.2, 2.6, 2.8, 2.6, 2.2, 1.8, 1.0, 0.5]
)
HEURE_WEIGHTS = HEURE_WEIGHTS / HEURE_WEIGHTS.sum()


def _pick_horodatages(n: int, n_temps_rows: int) -> list[str]:
    n_jours = n_temps_rows // 24
    jours = RNG.integers(0, n_jours, size=n)
    heures = RNG.choice(24, size=n, p=HEURE_WEIGHTS)
    return [
        (DATE_DEBUT + timedelta(days=int(j), hours=int(h))).isoformat(sep=" ")
        for j, h in zip(jours, heures)
    ]


def seed_staging_transactions(conn, client_ids: list[str], n_temps_rows: int, n_tx: int, fraud_rate: float):
    n_fraud = int(n_tx * fraud_rate)
    is_fraud = np.zeros(n_tx, dtype=bool)
    fraud_idx = RNG.choice(n_tx, size=n_fraud, replace=False)
    is_fraud[fraud_idx] = True
    fraud_type_arr = np.full(n_tx, None, dtype=object)
    fraud_type_arr[fraud_idx] = RNG.choice(FRAUD_TYPES, size=n_fraud)

    client_idx = RNG.integers(0, len(client_ids), size=n_tx)
    canal_idx = RNG.integers(0, len(CANAUX), size=n_tx)
    horodatages = _pick_horodatages(n_tx, n_temps_rows)

    montant = RNG.lognormal(mean=np.log(45), sigma=0.9, size=n_tx).round(2)
    distance_km = np.abs(RNG.normal(loc=8, scale=15, size=n_tx)).round(2)
    pays_transaction = np.full(n_tx, "FR", dtype=object)
    authentification = RNG.choice(["puce_pin", "3ds", "none"], size=n_tx, p=[0.55, 0.35, 0.10])
    canal_libelle = np.array([CANAUX[i][0] for i in canal_idx], dtype=object)
    mcc_code = np.array([CANAUX[i][1] for i in canal_idx], dtype=object)

    # --- surcharge des lignes frauduleuses selon leur typologie ---
    en_ligne_idx = [i for i, c in enumerate(CANAUX) if c[0] == "en_ligne"]
    puce_idx = [i for i, c in enumerate(CANAUX) if c[0] == "puce"]
    contact_puce_idx = [i for i, c in enumerate(CANAUX) if c[0] in ("sans_contact", "puce")]

    for i in fraud_idx:
        ftype = fraud_type_arr[i]
        base_dt = datetime.fromisoformat(horodatages[i])
        if ftype == "usurpation_identite":
            authentification[i] = "none"
            distance_km[i] = abs(RNG.normal(800, 400))
            pays_transaction[i] = RNG.choice(PAYS_ETRANGERS_RISQUE)
        elif ftype == "fraude_en_ligne":
            ci = RNG.choice(en_ligne_idx)
            canal_libelle[i], mcc_code[i] = CANAUX[ci][0], CANAUX[ci][1]
            montant[i] = RNG.lognormal(mean=np.log(250), sigma=0.6)
            horodatages[i] = base_dt.replace(hour=int(RNG.integers(1, 6))).isoformat(sep=" ")
        elif ftype == "skimming":
            ci = RNG.choice(puce_idx)
            canal_libelle[i], mcc_code[i] = CANAUX[ci][0], CANAUX[ci][1]
            horodatages[i] = base_dt.replace(hour=int(RNG.integers(0, 6))).isoformat(sep=" ")
            montant[i] = round(float(RNG.uniform(10, 60)), 2)
        elif ftype == "test_carte":
            ci = RNG.choice(en_ligne_idx)
            canal_libelle[i], mcc_code[i] = CANAUX[ci][0], CANAUX[ci][1]
            montant[i] = round(float(RNG.uniform(0.5, 3)), 2)
            authentification[i] = "none"
        elif ftype == "vol_carte_physique":
            ci = RNG.choice(contact_puce_idx)
            canal_libelle[i], mcc_code[i] = CANAUX[ci][0], CANAUX[ci][1]
            distance_km[i] = abs(RNG.normal(150, 80))
            horodatages[i] = base_dt.replace(hour=int(RNG.integers(0, 6))).isoformat(sep=" ")
        elif ftype == "ingenierie_sociale":
            ci = RNG.choice(en_ligne_idx)
            canal_libelle[i], mcc_code[i] = CANAUX[ci][0], CANAUX[ci][1]
            montant[i] = RNG.lognormal(mean=np.log(900), sigma=0.4)
            authentification[i] = "3ds"  # la victime valide elle-même la transaction
            pays_transaction[i] = RNG.choice(PAYS_VOISINS + ["FR"])

    montant = np.clip(montant, 0.5, None).round(2)
    distance_km = distance_km.round(2)

    rows = [
        (
            f"TX-{i + 1:09d}",
            client_ids[client_idx[i]],
            horodatages[i],
            float(montant[i]),
            canal_libelle[i],
            mcc_code[i],
            pays_transaction[i],
            float(distance_km[i]),
            authentification[i],
            bool(is_fraud[i]),
            fraud_type_arr[i],
            "batch",
        )
        for i in range(n_tx)
    ]

    copy_from_buffer(
        conn, "staging.raw_transactions",
        ["transaction_bk", "client_id", "horodatage", "montant", "canal", "mcc_code",
         "pays_transaction", "distance_domicile_km", "authentification",
         "is_fraud", "fraud_type", "mode_ingestion"],
        rows,
    )
    log.info("staging.raw_transactions : %d lignes | fraudes : %d (%.2f%%)", n_tx, n_fraud, 100 * n_fraud / n_tx)


def charger_faits(conn, mode: str) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT dwh.charger_faits_transactions(%s);", (mode,))
        n = cur.fetchone()[0]
    conn.commit()
    return n


def main():
    parser = argparse.ArgumentParser(description="Génération des données BC01 (voie batch)")
    parser.add_argument("--clients", type=int, default=5000)
    parser.add_argument("--transactions", type=int, default=400_000)
    parser.add_argument("--fraud-rate", type=float, default=0.015)
    args = parser.parse_args()

    log.info(
        "Démarrage seed : %d clients | %d transactions | taux fraude cible %.2f%%",
        args.clients, args.transactions, args.fraud_rate * 100,
    )

    conn = get_connection()
    t0 = time.perf_counter()
    log_id = log_chargement_debut(conn, "seed.py", "batch")
    try:
        truncate_all(conn)
        seed_unknown_members(conn)
        seed_agences(conn)
        seed_canal(conn)
        n_temps_rows = seed_temps(conn)
        client_rows = seed_clients(conn, args.clients)
        client_ids = [r[0] for r in client_rows]
        seed_staging_transactions(conn, client_ids, n_temps_rows, args.transactions, args.fraud_rate)

        n_inserted = charger_faits(conn, "batch")
        duree_ms = int((time.perf_counter() - t0) * 1000)
        log_chargement_fin(conn, log_id, n_inserted, duree_ms, "OK")
        log.info(
            "dwh.charger_faits_transactions('batch') : %d faits insérés en %d ms",
            n_inserted, duree_ms,
        )
    except Exception as exc:
        duree_ms = int((time.perf_counter() - t0) * 1000)
        log_chargement_fin(conn, log_id, 0, duree_ms, "ERREUR", str(exc))
        raise
    finally:
        conn.close()

    log.info("Seed terminé avec succès.")


if __name__ == "__main__":
    main()
