"""
BC02 — Analyse exploratoire : déséquilibre de classes, profiling des
fraudeurs, statistiques descriptives, détection d'anomalies univariées.

Lit les transactions labellisées (voie batch) du socle BC01 et produit :
  - des graphiques PNG dans bc02_analyse_exploratoire/outputs/
  - un résumé chiffré bc02_analyse_exploratoire/outputs/resume_bc02.json
    (nombres exacts réutilisés tels quels dans la documentation du bloc)

Usage :
    python bc02_analyse_exploratoire/scripts/analyse_exploratoire.py
"""
import json
import logging
import os
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg2
from dotenv import load_dotenv

load_dotenv()
warnings.filterwarnings("ignore", category=UserWarning, module="pandas")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
log = logging.getLogger("bc02")

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

COLOR_LEGIT = "#164b60"
COLOR_FRAUD = "#a5433a"
COLOR_NEUTRAL = "#5b6472"

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.size": 10.5,
    "axes.edgecolor": "#c7cedb",
    "axes.labelcolor": "#1c2230",
    "text.color": "#1c2230",
    "xtick.color": "#3a4454",
    "ytick.color": "#3a4454",
    "axes.grid": True,
    "grid.color": "#e6eaf0",
    "grid.linewidth": 0.7,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
})


def get_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5434"),
        dbname=os.getenv("POSTGRES_DB", "frauddetect"),
        user=os.getenv("POSTGRES_USER", "fraud_admin"),
        password=os.getenv("POSTGRES_PASSWORD", "fraud_secret"),
    )


def charger_donnees() -> pd.DataFrame:
    """Charge les transactions batch (labellisées) enrichies des dimensions.
    Le flux streaming (is_fraud encore NULL) est exclu : on analyse une
    population entièrement statuée, pas un mélange labellisé/non labellisé."""
    query = """
        SELECT
            f.montant, f.distance_domicile_km, f.authentification,
            f.pays_transaction, f.pays_residence, f.is_fraud, f.fraud_type,
            c.segment, c.revenu_mensuel_net,
            t.heure, t.jour_semaine, t.is_weekend, t.is_nuit, t.mois,
            ca.canal, ca.mcc_libelle, ca.is_online, ca.is_contactless
        FROM dwh.fact_transactions f
        JOIN dwh.dim_clients c ON c.client_key = f.client_key
        JOIN dwh.dim_temps t   ON t.temps_key = f.temps_key
        JOIN dwh.dim_canal ca  ON ca.canal_key = f.canal_key
        WHERE f.mode_ingestion = 'batch';
    """
    conn = get_connection()
    df = pd.read_sql(query, conn)
    conn.close()
    df["pays_inhabituel"] = df["pays_transaction"] != df["pays_residence"]
    log.info("Données chargées : %d transactions (voie batch, labellisées)", len(df))
    return df


# ------------------------------------------------------------------
# 1. Déséquilibre de classes
# ------------------------------------------------------------------
def analyse_desequilibre(df: pd.DataFrame) -> dict:
    n_total = len(df)
    n_fraud = int(df["is_fraud"].sum())
    n_legit = n_total - n_fraud
    taux_pct = 100 * n_fraud / n_total
    ratio = round(n_legit / n_fraud)

    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    bars = ax.bar(["Légitimes", "Fraudes"], [n_legit, n_fraud],
                   color=[COLOR_LEGIT, COLOR_FRAUD], width=0.55)
    ax.set_yscale("log")
    ax.set_ylabel("Nombre de transactions (échelle log)")
    ax.set_title(f"Déséquilibre de classes — {taux_pct:.2f} % de fraudes (1 pour {ratio})")
    for bar, val in zip(bars, [n_legit, n_fraud]):
        ax.text(bar.get_x() + bar.get_width() / 2, val * 1.15, f"{val:,}".replace(",", " "),
                ha="center", fontsize=9.5, color="#1c2230")
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "01_desequilibre_classes.png"), dpi=150)
    plt.close(fig)

    log.info("Déséquilibre : %d fraudes / %d transactions (%.2f%%, ratio 1:%d)",
              n_fraud, n_total, taux_pct, ratio)
    return {"n_total": n_total, "n_fraud": n_fraud, "n_legit": n_legit,
            "taux_fraude_pct": round(taux_pct, 3), "ratio_1_pour": ratio}


# ------------------------------------------------------------------
# 2. Profiling des fraudeurs
# ------------------------------------------------------------------
def analyse_profiling(df: pd.DataFrame) -> dict:
    def taux(groupby_col):
        g = df.groupby(groupby_col)["is_fraud"].agg(["mean", "count"])
        g["mean"] = 100 * g["mean"]
        return g.sort_values("mean", ascending=False)

    par_canal = taux("canal")
    par_heure = df.groupby("heure")["is_fraud"].mean() * 100
    par_auth = taux("authentification")
    par_pays = taux("pays_inhabituel")
    par_segment = taux("segment")

    fig, axes = plt.subplots(2, 2, figsize=(11, 7.5))

    ax = axes[0, 0]
    ax.barh(par_canal.index, par_canal["mean"], color=COLOR_FRAUD)
    ax.set_xlabel("Taux de fraude (%)")
    ax.set_title("Par canal de paiement")
    ax.invert_yaxis()

    ax = axes[0, 1]
    ax.plot(par_heure.index, par_heure.values, color=COLOR_FRAUD, marker="o", markersize=3)
    ax.axvspan(0, 6, color=COLOR_NEUTRAL, alpha=0.08, label="nuit (0h-6h)")
    ax.set_xlabel("Heure de la journée")
    ax.set_ylabel("Taux de fraude (%)")
    ax.set_title("Par heure")
    ax.legend(fontsize=8.5)

    ax = axes[1, 0]
    ax.barh(par_auth.index, par_auth["mean"], color=COLOR_FRAUD)
    ax.set_xlabel("Taux de fraude (%)")
    ax.set_title("Par méthode d'authentification")
    ax.invert_yaxis()

    ax = axes[1, 1]
    labels = ["Pays habituel", "Pays inhabituel"]
    values = [par_pays.loc[False, "mean"] if False in par_pays.index else 0,
              par_pays.loc[True, "mean"] if True in par_pays.index else 0]
    ax.bar(labels, values, color=[COLOR_LEGIT, COLOR_FRAUD])
    ax.set_ylabel("Taux de fraude (%)")
    ax.set_title("Selon la géographie de la transaction")

    fig.suptitle("Profiling des fraudeurs — taux de fraude par dimension", fontsize=13, y=1.01)
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "02_profiling_fraudeurs.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)

    log.info("Profiling : canal le plus exposé = %s (%.2f%%)", par_canal.index[0], par_canal["mean"].iloc[0])
    log.info("Profiling : heure la plus exposée = %sh (%.2f%%)", par_heure.idxmax(), par_heure.max())

    return {
        "par_canal": par_canal["mean"].round(2).to_dict(),
        "par_authentification": par_auth["mean"].round(2).to_dict(),
        "par_segment": par_segment["mean"].round(2).to_dict(),
        "pays_habituel_pct": round(values[0], 2),
        "pays_inhabituel_pct": round(values[1], 2),
        "heure_pic_fraude": int(par_heure.idxmax()),
        "taux_heure_pic": round(float(par_heure.max()), 2),
    }


# ------------------------------------------------------------------
# 3. Statistiques descriptives
# ------------------------------------------------------------------
def analyse_statistiques(df: pd.DataFrame) -> dict:
    stats_montant = df.groupby("is_fraud")["montant"].describe()
    stats_distance = df.groupby("is_fraud")["distance_domicile_km"].describe()

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))

    ax = axes[0]
    data_legit = df.loc[~df["is_fraud"], "montant"]
    data_fraud = df.loc[df["is_fraud"], "montant"]
    ax.hist(np.log10(data_legit.clip(lower=0.5)), bins=50, alpha=0.6, color=COLOR_LEGIT,
            density=True, label="Légitimes")
    ax.hist(np.log10(data_fraud.clip(lower=0.5)), bins=50, alpha=0.6, color=COLOR_FRAUD,
            density=True, label="Fraudes")
    ax.set_xlabel("Montant (log10 €)")
    ax.set_ylabel("Densité")
    ax.set_title("Distribution du montant")
    ax.legend(fontsize=9)

    ax = axes[1]
    box = ax.boxplot(
        [df.loc[~df["is_fraud"], "distance_domicile_km"], df.loc[df["is_fraud"], "distance_domicile_km"]],
        labels=["Légitimes", "Fraudes"], patch_artist=True, showfliers=False,
    )
    for patch, color in zip(box["boxes"], [COLOR_LEGIT, COLOR_FRAUD]):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)
    ax.set_ylabel("Distance au domicile (km)")
    ax.set_title("Distance domicile ↔ lieu de transaction")

    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "03_statistiques_descriptives.png"), dpi=150)
    plt.close(fig)

    log.info("Montant moyen : légitime=%.2f€ | fraude=%.2f€",
              stats_montant.loc[False, "mean"], stats_montant.loc[True, "mean"])
    log.info("Distance moyenne : légitime=%.1fkm | fraude=%.1fkm",
              stats_distance.loc[False, "mean"], stats_distance.loc[True, "mean"])

    return {
        "montant": {str(k): v.round(2).to_dict() for k, v in stats_montant.iterrows()},
        "distance_domicile_km": {str(k): v.round(2).to_dict() for k, v in stats_distance.iterrows()},
    }


# ------------------------------------------------------------------
# 4. Détection d'anomalies univariées
# ------------------------------------------------------------------
def _evaluer_detecteur(flag: pd.Series, is_fraud: pd.Series) -> dict:
    vp = int((flag & is_fraud).sum())
    fp = int((flag & ~is_fraud).sum())
    fn = int((~flag & is_fraud).sum())
    precision = vp / (vp + fp) if (vp + fp) else 0.0
    recall = vp / (vp + fn) if (vp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"n_signales": int(flag.sum()), "vrais_positifs": vp, "faux_positifs": fp,
            "precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3)}


def analyse_anomalies(df: pd.DataFrame) -> dict:
    montant = df["montant"]
    mean, std = montant.mean(), montant.std()
    zscore = (montant - mean) / std
    flag_z = zscore.abs() > 3

    q1, q3 = montant.quantile([0.25, 0.75])
    iqr = q3 - q1
    borne_haute = q3 + 1.5 * iqr
    flag_iqr = montant > borne_haute

    resultat_z = _evaluer_detecteur(flag_z, df["is_fraud"])
    resultat_iqr = _evaluer_detecteur(flag_iqr, df["is_fraud"])

    fig, ax = plt.subplots(figsize=(9, 4.5))
    sample = df.sample(n=min(20000, len(df)), random_state=42)
    ax.scatter(sample.index, sample["montant"], s=4, alpha=0.35, color=COLOR_LEGIT,
               label="Légitimes")
    fraud_sample = sample[sample["is_fraud"]]
    ax.scatter(fraud_sample.index, fraud_sample["montant"], s=10, alpha=0.9, color=COLOR_FRAUD,
               label="Fraudes")
    ax.axhline(mean + 3 * std, color=COLOR_NEUTRAL, linestyle="--", linewidth=1,
               label="seuil z-score = 3")
    ax.axhline(borne_haute, color="#8a6a1f", linestyle=":", linewidth=1.3,
               label="seuil IQR (Q3 + 1,5×IQR)")
    ax.set_yscale("log")
    ax.set_ylabel("Montant (€, échelle log)")
    ax.set_xlabel("Transaction (échantillon de 20 000)")
    ax.set_title("Anomalies univariées sur le montant — recouvrement avec la fraude réelle")
    ax.legend(fontsize=8.5, loc="upper right")
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "04_anomalies_univariees.png"), dpi=150)
    plt.close(fig)

    log.info("Détecteur z-score(3) : précision=%.1f%% | rappel=%.1f%%",
              100 * resultat_z["precision"], 100 * resultat_z["recall"])
    log.info("Détecteur IQR(1.5)  : précision=%.1f%% | rappel=%.1f%%",
              100 * resultat_iqr["precision"], 100 * resultat_iqr["recall"])

    return {"zscore_seuil_3": resultat_z, "iqr_1_5": resultat_iqr}


def main():
    df = charger_donnees()

    resume = {
        "desequilibre_classes": analyse_desequilibre(df),
        "profiling_fraudeurs": analyse_profiling(df),
        "statistiques_descriptives": analyse_statistiques(df),
        "anomalies_univariees": analyse_anomalies(df),
    }

    resume_path = os.path.join(OUTPUT_DIR, "resume_bc02.json")
    with open(resume_path, "w", encoding="utf-8") as f:
        json.dump(resume, f, ensure_ascii=False, indent=2)

    log.info("Analyse terminée — graphiques et résumé écrits dans %s", os.path.abspath(OUTPUT_DIR))


if __name__ == "__main__":
    main()
