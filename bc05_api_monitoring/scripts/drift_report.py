"""
BC05 — Monitoring de dérive avec Evidently AI.

Compare la distribution des variables du modèle (référence = train du BC03)
à deux scénarios de production :
  - "normal"  : le test du BC03 tel quel — même génératif, dérive attendue faible
  - "derive"  : le même test, avec un changement simulé sur 3 variables
    (heure, montant, mois) — reproduit une évolution des habitudes de fraude,
    à détecter avant qu'elle ne dégrade silencieusement le modèle en
    production.

Usage :
    python bc05_api_monitoring/scripts/drift_report.py
"""
import json
import logging
import os

import numpy as np
import pandas as pd
import psycopg2
from dotenv import load_dotenv
from evidently.metric_preset import DataDriftPreset
from evidently.report import Report

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
log = logging.getLogger("bc05-drift")

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

FEATURE_COLUMNS = [
    "montant", "distance_domicile_km", "revenu_mensuel_net", "heure", "jour_semaine", "mois",
    "is_weekend", "is_nuit", "authentification", "canal", "segment",
]
SEUIL_ALERTE_PART_COLONNES = 0.20  # cohérent avec le seuil du BC01 (dwh) pour rester comparable


def get_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"), port=os.getenv("POSTGRES_PORT", "5434"),
        dbname=os.getenv("POSTGRES_DB", "frauddetect"), user=os.getenv("POSTGRES_USER", "fraud_admin"),
        password=os.getenv("POSTGRES_PASSWORD", "fraud_secret"),
    )


def charger_donnees() -> pd.DataFrame:
    query = """
        SELECT
            f.montant, f.distance_domicile_km, f.authentification,
            c.segment, c.revenu_mensuel_net,
            t.horodatage, t.heure, t.jour_semaine, t.is_weekend, t.is_nuit, t.mois,
            ca.canal
        FROM dwh.fact_transactions f
        JOIN dwh.dim_clients c ON c.client_key = f.client_key
        JOIN dwh.dim_temps t   ON t.temps_key = f.temps_key
        JOIN dwh.dim_canal ca  ON ca.canal_key = f.canal_key
        WHERE f.mode_ingestion = 'batch'
        ORDER BY t.horodatage;
    """
    conn = get_connection()
    df = pd.read_sql(query, conn)
    conn.close()
    df["is_weekend"] = df["is_weekend"].astype(int)
    df["is_nuit"] = df["is_nuit"].astype(int)
    return df


def simuler_derive(df: pd.DataFrame) -> pd.DataFrame:
    """Simule une évolution du comportement des fraudeurs sur 3 variables,
    laissant les 8 autres inchangées — comparable au scénario du BC01
    ('les fraudeurs ont changé leurs habitudes horaires et temporelles')."""
    rng = np.random.default_rng(7)
    df = df.copy()
    df["heure"] = (df["heure"] + 9) % 24  # bascule vers un créneau différent
    df["montant"] = (df["montant"] * 1.8).round(2)  # inflation des montants
    df["mois"] = ((df["mois"] - 1 + rng.integers(4, 7, size=len(df))) % 12) + 1
    return df


def generer_rapport(reference: pd.DataFrame, courant: pd.DataFrame, nom: str) -> dict:
    report = Report(metrics=[DataDriftPreset()])
    report.run(reference_data=reference, current_data=courant)

    chemin_html = os.path.join(OUTPUT_DIR, f"drift_{nom}.html")
    report.save_html(chemin_html)

    resultat_global = report.as_dict()["metrics"][0]["result"]  # DatasetDriftMetric
    resultat_detail = report.as_dict()["metrics"][1]["result"]  # DataDriftTable (détail par colonne)
    part_colonnes_derivees = resultat_global["share_of_drifted_columns"]
    n_colonnes_derivees = resultat_global["number_of_drifted_columns"]
    colonnes_derivees = [
        col for col, detail in resultat_detail["drift_by_columns"].items() if detail["drift_detected"]
    ]
    alerte = part_colonnes_derivees > SEUIL_ALERTE_PART_COLONNES

    log.info("[%s] %d/%d colonnes en dérive (%.1f%%) — alerte=%s — colonnes : %s",
              nom, n_colonnes_derivees, len(FEATURE_COLUMNS), 100 * part_colonnes_derivees,
              alerte, colonnes_derivees)

    return {
        "scenario": nom,
        "n_colonnes_totales": len(FEATURE_COLUMNS),
        "n_colonnes_derivees": n_colonnes_derivees,
        "part_colonnes_derivees_pct": round(100 * part_colonnes_derivees, 2),
        "seuil_alerte_pct": 100 * SEUIL_ALERTE_PART_COLONNES,
        "alerte_declenchee": alerte,
        "colonnes_derivees": colonnes_derivees,
        "rapport_html": os.path.basename(chemin_html),
    }


def main():
    df = charger_donnees()
    idx = int(len(df) * 0.8)
    train, test = df.iloc[:idx], df.iloc[idx:]
    log.info("Référence (train) : %d lignes | Test (production simulée) : %d lignes", len(train), len(test))

    reference = train[FEATURE_COLUMNS].sample(n=20000, random_state=42)
    courant_normal = test[FEATURE_COLUMNS].sample(n=20000, random_state=42, replace=True)
    courant_derive = simuler_derive(courant_normal)

    resultats = {
        "normal": generer_rapport(reference, courant_normal, "normal"),
        "derive": generer_rapport(reference, courant_derive, "derive"),
    }

    with open(os.path.join(OUTPUT_DIR, "resume_drift.json"), "w", encoding="utf-8") as f:
        json.dump(resultats, f, ensure_ascii=False, indent=2)

    log.info("Monitoring terminé — rapports écrits dans %s", os.path.abspath(OUTPUT_DIR))


if __name__ == "__main__":
    main()
