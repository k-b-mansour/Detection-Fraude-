"""
BC06 — KPIs métier : traduire le compromis statistique du BC03 (précision
vs rappel) en impact financier, seul terrain sur lequel un arbitrage de
seuil se décide réellement en entreprise.

Recharge le modèle et le split du BC03 plutôt que de recopier des chiffres
déjà vus : la matrice de confusion à chaque seuil est recalculée ici.

Hypothèse de coût explicitée (à ajuster avec les équipes métier réelles) :
une fausse alerte coûte COUT_FAUSSE_ALERTE € de traitement (vérification
cliente, temps d'analyste) — le montant d'une fraude, lui, est une donnée
du jeu de test, pas une hypothèse.

Usage :
    python bc06_gestion_projet/scripts/kpis_metier.py
"""
import json
import logging
import os

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg2
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
log = logging.getLogger("bc06-kpis")

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
LGBM_PATH = os.path.join(BASE_DIR, "..", "bc03_modeles_supervises", "models", "modele_lightgbm.joblib")
os.makedirs(OUTPUT_DIR, exist_ok=True)

FEATURE_COLUMNS = [
    "montant", "distance_domicile_km", "revenu_mensuel_net", "heure", "jour_semaine", "mois",
    "is_weekend", "is_nuit", "authentification", "canal", "segment",
]
COUT_FAUSSE_ALERTE = 8.0    # € — hypothèse explicite : vérification cliente + temps analyste
FACTEUR_ANNUALISATION = 12 / 2.5  # le test couvre ~2,5 mois (dernier 20 % de l'année simulée)

COLOR_EVITE = "#2f6b4f"
COLOR_MANQUE = "#a5433a"
COLOR_COUT = "#a8631f"

plt.rcParams.update({
    "font.family": "sans-serif", "font.size": 10.5,
    "axes.edgecolor": "#c7cedb", "axes.labelcolor": "#1c2230", "text.color": "#1c2230",
    "xtick.color": "#3a4454", "ytick.color": "#3a4454",
    "axes.grid": True, "grid.color": "#e6eaf0", "grid.linewidth": 0.7,
    "figure.facecolor": "white", "axes.facecolor": "white",
})


def get_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"), port=os.getenv("POSTGRES_PORT", "5434"),
        dbname=os.getenv("POSTGRES_DB", "frauddetect"), user=os.getenv("POSTGRES_USER", "fraud_admin"),
        password=os.getenv("POSTGRES_PASSWORD", "fraud_secret"),
    )


def charger_test() -> pd.DataFrame:
    query = """
        SELECT
            f.montant, f.distance_domicile_km, f.authentification, f.is_fraud,
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
    idx = int(len(df) * 0.8)
    return df.iloc[idx:].reset_index(drop=True)  # même split que le BC03 : test = derniers 20 %


def kpis_a_seuil(test: pd.DataFrame, proba: np.ndarray, seuil: float) -> dict:
    y_pred = proba >= seuil
    y_true = test["is_fraud"].astype(bool).values
    montant = test["montant"].values

    montant_evite = float(montant[y_pred & y_true].sum())       # fraudes détectées
    montant_manque = float(montant[~y_pred & y_true].sum())     # fraudes non détectées
    n_fausses_alertes = int((y_pred & ~y_true).sum())
    cout_fausses_alertes = n_fausses_alertes * COUT_FAUSSE_ALERTE
    benefice_net = montant_evite - cout_fausses_alertes

    return {
        "seuil": seuil,
        "montant_fraude_evite_eur": round(montant_evite, 2),
        "montant_fraude_manque_eur": round(montant_manque, 2),
        "n_fausses_alertes": n_fausses_alertes,
        "cout_fausses_alertes_eur": round(cout_fausses_alertes, 2),
        "benefice_net_eur": round(benefice_net, 2),
        "benefice_net_annualise_eur": round(benefice_net * FACTEUR_ANNUALISATION, 2),
    }


def main():
    test = charger_test()
    pipeline = joblib.load(LGBM_PATH)
    proba = pipeline.predict_proba(test[FEATURE_COLUMNS])[:, 1]

    montant_fraude_totale = float(test.loc[test["is_fraud"], "montant"].sum())
    log.info("Test : %d transactions | %d fraudes | montant total des fraudes = %.2f €",
              len(test), int(test["is_fraud"].sum()), montant_fraude_totale)

    kpis_defaut = kpis_a_seuil(test, proba, 0.5)
    kpis_optimise = kpis_a_seuil(test, proba, 0.98)

    for nom, k in [("seuil 0,50", kpis_defaut), ("seuil 0,98", kpis_optimise)]:
        log.info("[%s] évité=%.0f€ manqué=%.0f€ FA=%d coût_FA=%.0f€ bénéfice_net=%.0f€ (annualisé≈%.0f€)",
                  nom, k["montant_fraude_evite_eur"], k["montant_fraude_manque_eur"],
                  k["n_fausses_alertes"], k["cout_fausses_alertes_eur"], k["benefice_net_eur"],
                  k["benefice_net_annualise_eur"])

    # ------------------------------------------------------------
    # Figure — impact financier comparé des deux seuils
    # ------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(8, 4.6))
    categories = ["Fraude évitée", "Fraude manquée", "Coût des fausses alertes", "Bénéfice net"]
    valeurs_defaut = [kpis_defaut["montant_fraude_evite_eur"], kpis_defaut["montant_fraude_manque_eur"],
                       kpis_defaut["cout_fausses_alertes_eur"], kpis_defaut["benefice_net_eur"]]
    valeurs_optimise = [kpis_optimise["montant_fraude_evite_eur"], kpis_optimise["montant_fraude_manque_eur"],
                         kpis_optimise["cout_fausses_alertes_eur"], kpis_optimise["benefice_net_eur"]]
    x = np.arange(len(categories))
    largeur = 0.35
    ax.bar(x - largeur / 2, valeurs_defaut, largeur, label="Seuil par défaut (0,50)", color="#5b6472")
    ax.bar(x + largeur / 2, valeurs_optimise, largeur, label="Seuil optimisé (0,98)", color="#164b60")
    ax.set_xticks(x)
    ax.set_xticklabels(categories, rotation=12, ha="right")
    ax.set_ylabel("Montant sur la période de test (€)")
    ax.set_title("Impact financier comparé des deux seuils — sur 80 000 transactions de test")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "01_impact_financier_seuils.png"), dpi=150)
    plt.close(fig)

    resume = {
        "hypotheses": {
            "cout_fausse_alerte_eur": COUT_FAUSSE_ALERTE,
            "facteur_annualisation": round(FACTEUR_ANNUALISATION, 2),
            "note": "Test = derniers ~2,5 mois de l'année simulée ; annualisation = extrapolation linéaire, pas une mesure.",
        },
        "montant_fraude_totale_test_eur": round(montant_fraude_totale, 2),
        "seuil_defaut_0_5": kpis_defaut,
        "seuil_optimise_0_98": kpis_optimise,
    }
    with open(os.path.join(OUTPUT_DIR, "resume_kpis_metier.json"), "w", encoding="utf-8") as f:
        json.dump(resume, f, ensure_ascii=False, indent=2)

    log.info("KPIs métier écrits dans %s", os.path.abspath(OUTPUT_DIR))


if __name__ == "__main__":
    main()
