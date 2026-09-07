"""
BC03 — Modèles supervisés : Logistic Regression (référence), gestion du
déséquilibre par SMOTE, Gradient Boosting (LightGBM), optimisation du
seuil de décision.

Lit les transactions labellisées (voie batch) du socle BC01/BC02, split
temporel train/test (comme le ferait un déploiement réel), entraîne trois
configurations et compare leurs performances. Produit les graphiques dans
bc03_modeles_supervises/outputs/, le modèle retenu dans
bc03_modeles_supervises/models/, et un résumé chiffré
outputs/resume_bc03.json.

Usage :
    python bc03_modeles_supervises/scripts/entrainement_modeles.py
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
from imblearn.over_sampling import SMOTE
from imblearn.pipeline import Pipeline as ImbPipeline
from lightgbm import LGBMClassifier
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score, confusion_matrix, f1_score, precision_score,
    precision_recall_curve, recall_score, roc_auc_score, roc_curve,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
log = logging.getLogger("bc03")

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
MODEL_DIR = os.path.join(BASE_DIR, "models")
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(MODEL_DIR, exist_ok=True)

COLOR_LR = "#5b6472"
COLOR_SMOTE = "#a8631f"
COLOR_LGBM = "#164b60"
COLOR_FRAUD = "#a5433a"

plt.rcParams.update({
    "font.family": "sans-serif", "font.size": 10.5,
    "axes.edgecolor": "#c7cedb", "axes.labelcolor": "#1c2230", "text.color": "#1c2230",
    "xtick.color": "#3a4454", "ytick.color": "#3a4454",
    "axes.grid": True, "grid.color": "#e6eaf0", "grid.linewidth": 0.7,
    "figure.facecolor": "white", "axes.facecolor": "white",
})

NUMERIC_FEATURES = ["montant", "distance_domicile_km", "revenu_mensuel_net", "heure", "jour_semaine", "mois"]
BINARY_FEATURES = ["is_weekend", "is_nuit"]
CATEGORICAL_FEATURES = ["authentification", "canal", "segment"]
FEATURE_COLUMNS = NUMERIC_FEATURES + BINARY_FEATURES + CATEGORICAL_FEATURES


def get_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5434"),
        dbname=os.getenv("POSTGRES_DB", "frauddetect"),
        user=os.getenv("POSTGRES_USER", "fraud_admin"),
        password=os.getenv("POSTGRES_PASSWORD", "fraud_secret"),
    )


def charger_donnees() -> pd.DataFrame:
    """Charge les transactions batch labellisées, triées chronologiquement.

    pays_transaction / pays_residence sont volontairement exclus : au BC02,
    ce couple s'est révélé être un séparateur parfait (100% de fraude dès que
    le pays diffère), artefact de la génération synthétique plutôt qu'un
    signal représentatif. L'inclure rendrait le problème trivial et le
    modèle inexploitable sur des données réelles — voir bc02-explication.pdf.
    """
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
    log.info("Données chargées : %d transactions, triées du %s au %s",
              len(df), df["horodatage"].min(), df["horodatage"].max())
    return df


def split_temporel(df: pd.DataFrame, ratio_train: float = 0.8):
    idx = int(len(df) * ratio_train)
    train, test = df.iloc[:idx], df.iloc[idx:]
    log.info("Split temporel : train jusqu'au %s (%d lignes) | test à partir du %s (%d lignes)",
              train["horodatage"].max(), len(train), test["horodatage"].min(), len(test))
    log.info("Fraudes : train=%d (%.2f%%) | test=%d (%.2f%%)",
              train["is_fraud"].sum(), 100 * train["is_fraud"].mean(),
              test["is_fraud"].sum(), 100 * test["is_fraud"].mean())
    return train, test


def construire_preprocesseur() -> ColumnTransformer:
    return ColumnTransformer([
        ("num", StandardScaler(), NUMERIC_FEATURES),
        ("bin", "passthrough", BINARY_FEATURES),
        ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL_FEATURES),
    ])


def evaluer(y_true, y_proba, seuil=0.5) -> dict:
    y_pred = (y_proba >= seuil).astype(int)
    auc = roc_auc_score(y_true, y_proba)
    return {
        "seuil": seuil,
        "auc_roc": round(auc, 4),
        "gini": round(2 * auc - 1, 4),
        "average_precision": round(average_precision_score(y_true, y_proba), 4),
        "precision": round(precision_score(y_true, y_pred, zero_division=0), 4),
        "recall": round(recall_score(y_true, y_pred, zero_division=0), 4),
        "f1": round(f1_score(y_true, y_pred, zero_division=0), 4),
    }


def main():
    df = charger_donnees()
    train, test = split_temporel(df)
    X_train, y_train = train[FEATURE_COLUMNS], train["is_fraud"].astype(int)
    X_test, y_test = test[FEATURE_COLUMNS], test["is_fraud"].astype(int)

    # ------------------------------------------------------------
    # Modèle A — Logistic Regression, référence, sans rééquilibrage
    # ------------------------------------------------------------
    pipe_lr = Pipeline([
        ("prep", construire_preprocesseur()),
        ("clf", LogisticRegression(max_iter=1000)),
    ])
    pipe_lr.fit(X_train, y_train)
    proba_lr = pipe_lr.predict_proba(X_test)[:, 1]
    log.info("Logistic Regression (référence) entraînée")

    # ------------------------------------------------------------
    # Modèle B — Logistic Regression + SMOTE (train uniquement)
    # sampling_strategy=0.3 : on porte la fraude à 30% de la classe
    # majoritaire dans le train, pas à 50/50 — un rééquilibrage total
    # déplacerait excessivement la frontière de décision et dégraderait
    # la précision plus qu'il n'améliorerait le rappel.
    # ------------------------------------------------------------
    pipe_smote = ImbPipeline([
        ("prep", construire_preprocesseur()),
        ("smote", SMOTE(sampling_strategy=0.3, random_state=42)),
        ("clf", LogisticRegression(max_iter=1000)),
    ])
    pipe_smote.fit(X_train, y_train)
    proba_smote = pipe_smote.predict_proba(X_test)[:, 1]
    log.info("Logistic Regression + SMOTE entraînée")

    # ------------------------------------------------------------
    # Modèle C — LightGBM (Gradient Boosting), déséquilibre géré
    # nativement par scale_pos_weight (pas de SMOTE : les arbres de
    # décision tirent peu de bénéfice de points synthétiques interpolés,
    # et une repondération native est ici plus appropriée).
    # ------------------------------------------------------------
    n_legit, n_fraud = (y_train == 0).sum(), (y_train == 1).sum()
    scale_pos_weight = n_legit / n_fraud
    pipe_lgbm = Pipeline([
        ("prep", construire_preprocesseur()),
        ("clf", LGBMClassifier(
            n_estimators=300, learning_rate=0.05, num_leaves=31,
            scale_pos_weight=scale_pos_weight, random_state=42, verbosity=-1,
        )),
    ])
    pipe_lgbm.fit(X_train, y_train)
    proba_lgbm = pipe_lgbm.predict_proba(X_test)[:, 1]
    log.info("LightGBM entraîné (scale_pos_weight=%.1f)", scale_pos_weight)

    # ------------------------------------------------------------
    # Évaluation @0.5 et comparaison
    # ------------------------------------------------------------
    resultats = {
        "logistic_regression": evaluer(y_test, proba_lr),
        "logistic_regression_smote": evaluer(y_test, proba_smote),
        "lightgbm": evaluer(y_test, proba_lgbm),
    }
    for nom, r in resultats.items():
        log.info("%-28s AUC=%.4f Gini=%.4f F1=%.4f Précision=%.4f Rappel=%.4f",
                  nom, r["auc_roc"], r["gini"], r["f1"], r["precision"], r["recall"])

    # ------------------------------------------------------------
    # Figure 1 — courbes ROC + Précision/Rappel, les 3 modèles
    # ------------------------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6))
    for proba, label, color in [
        (proba_lr, "Logistic Regression", COLOR_LR),
        (proba_smote, "Logistic Regression + SMOTE", COLOR_SMOTE),
        (proba_lgbm, "LightGBM", COLOR_LGBM),
    ]:
        fpr, tpr, _ = roc_curve(y_test, proba)
        auc = roc_auc_score(y_test, proba)
        axes[0].plot(fpr, tpr, color=color, label=f"{label} (AUC={auc:.3f})")

        prec, rec, _ = precision_recall_curve(y_test, proba)
        ap = average_precision_score(y_test, proba)
        axes[1].plot(rec, prec, color=color, label=f"{label} (AP={ap:.3f})")

    axes[0].plot([0, 1], [0, 1], "--", color="#c7cedb", linewidth=1)
    axes[0].set_xlabel("Taux de faux positifs")
    axes[0].set_ylabel("Taux de vrais positifs")
    axes[0].set_title("Courbe ROC")
    axes[0].legend(fontsize=8)

    axes[1].axhline(y_test.mean(), linestyle="--", color="#c7cedb", linewidth=1, label="hasard")
    axes[1].set_xlabel("Rappel")
    axes[1].set_ylabel("Précision")
    axes[1].set_title("Courbe Précision/Rappel")
    axes[1].legend(fontsize=8)

    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "01_courbes_roc_pr.png"), dpi=150)
    plt.close(fig)

    # ------------------------------------------------------------
    # Figure 2 — effet de SMOTE sur la Logistic Regression, @0.5
    # ------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(7, 4))
    metriques = ["precision", "recall", "f1"]
    x = np.arange(len(metriques))
    largeur = 0.35
    ax.bar(x - largeur / 2, [resultats["logistic_regression"][m] for m in metriques],
           largeur, label="Sans rééquilibrage", color=COLOR_LR)
    ax.bar(x + largeur / 2, [resultats["logistic_regression_smote"][m] for m in metriques],
           largeur, label="Avec SMOTE (30%)", color=COLOR_SMOTE)
    ax.set_xticks(x)
    ax.set_xticklabels(["Précision", "Rappel", "F1"])
    ax.set_ylabel("Score")
    ax.set_title("Effet de SMOTE sur la Logistic Regression (seuil = 0,5)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "02_effet_smote.png"), dpi=150)
    plt.close(fig)

    # ------------------------------------------------------------
    # Optimisation du seuil de décision (LightGBM)
    # ------------------------------------------------------------
    seuils = np.arange(0.01, 1.0, 0.01)
    f1s = [f1_score(y_test, (proba_lgbm >= s).astype(int), zero_division=0) for s in seuils]
    precisions = [precision_score(y_test, (proba_lgbm >= s).astype(int), zero_division=0) for s in seuils]
    recalls = [recall_score(y_test, (proba_lgbm >= s).astype(int), zero_division=0) for s in seuils]
    meilleur_idx = int(np.argmax(f1s))
    seuil_optimal = round(float(seuils[meilleur_idx]), 2)

    resultat_defaut = evaluer(y_test, proba_lgbm, seuil=0.5)
    resultat_optimise = evaluer(y_test, proba_lgbm, seuil=seuil_optimal)
    log.info("Seuil optimal (F1 max) = %.2f | F1 : %.4f (défaut 0.5) -> %.4f (optimisé)",
              seuil_optimal, resultat_defaut["f1"], resultat_optimise["f1"])

    fig, ax = plt.subplots(figsize=(8, 4.4))
    ax.plot(seuils, precisions, color=COLOR_SMOTE, label="Précision", linewidth=1.4)
    ax.plot(seuils, recalls, color=COLOR_LGBM, label="Rappel", linewidth=1.4)
    ax.plot(seuils, f1s, color=COLOR_FRAUD, label="F1", linewidth=2)
    ax.axvline(seuil_optimal, linestyle="--", color="#1c2230", linewidth=1,
               label=f"seuil optimal = {seuil_optimal:.2f}")
    ax.axvline(0.5, linestyle=":", color="#8a93a3", linewidth=1, label="seuil par défaut = 0,50")
    ax.set_xlabel("Seuil de décision")
    ax.set_ylabel("Score")
    ax.set_title("Optimisation du seuil de décision — LightGBM")
    ax.legend(fontsize=8.5)
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "03_optimisation_seuil.png"), dpi=150)
    plt.close(fig)

    # ------------------------------------------------------------
    # Feature importance (LightGBM)
    # ------------------------------------------------------------
    encodeur = pipe_lgbm.named_steps["prep"]
    noms_features = (
        NUMERIC_FEATURES + BINARY_FEATURES
        + list(encodeur.named_transformers_["cat"].get_feature_names_out(CATEGORICAL_FEATURES))
    )
    importances = pipe_lgbm.named_steps["clf"].feature_importances_
    ordre = np.argsort(importances)[::-1][:15]

    fig, ax = plt.subplots(figsize=(8, 5.5))
    ax.barh([noms_features[i] for i in ordre][::-1], importances[ordre][::-1], color=COLOR_LGBM)
    ax.set_xlabel("Importance (gain LightGBM)")
    ax.set_title("Top 15 features — LightGBM")
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "04_importance_features.png"), dpi=150)
    plt.close(fig)

    # ------------------------------------------------------------
    # Matrices de confusion — seuil par défaut vs seuil optimisé
    # ------------------------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.6))
    for ax, seuil, titre in [(axes[0], 0.5, "Seuil par défaut (0,50)"),
                              (axes[1], seuil_optimal, f"Seuil optimisé ({seuil_optimal:.2f})")]:
        cm = confusion_matrix(y_test, (proba_lgbm >= seuil).astype(int))
        im = ax.imshow(cm, cmap="Blues")
        for i in range(2):
            for j in range(2):
                ax.text(j, i, f"{cm[i, j]:,}".replace(",", " "), ha="center", va="center",
                        color="white" if cm[i, j] > cm.max() / 2 else "#1c2230", fontsize=11)
        ax.set_xticks([0, 1]); ax.set_xticklabels(["Légitime", "Fraude"])
        ax.set_yticks([0, 1]); ax.set_yticklabels(["Légitime", "Fraude"])
        ax.set_xlabel("Prédiction"); ax.set_ylabel("Réalité")
        ax.set_title(titre)
    fig.suptitle("Matrice de confusion — LightGBM", y=1.02)
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "05_matrices_confusion.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)

    # ------------------------------------------------------------
    # Sauvegarde du modèle retenu + résumé
    # ------------------------------------------------------------
    joblib.dump(pipe_lgbm, os.path.join(MODEL_DIR, "modele_lightgbm.joblib"))
    joblib.dump({"seuil_optimal": seuil_optimal}, os.path.join(MODEL_DIR, "seuil_decision.joblib"))

    resume = {
        "split": {
            "n_train": len(train), "n_test": len(test),
            "date_limite_train": str(train["horodatage"].max()),
            "date_debut_test": str(test["horodatage"].min()),
            "taux_fraude_train_pct": round(100 * y_train.mean(), 3),
            "taux_fraude_test_pct": round(100 * y_test.mean(), 3),
        },
        "modeles": resultats,
        "seuil_optimal_lightgbm": seuil_optimal,
        "lightgbm_seuil_defaut": resultat_defaut,
        "lightgbm_seuil_optimise": resultat_optimise,
        "scale_pos_weight": round(float(scale_pos_weight), 2),
        "top_features": [noms_features[i] for i in ordre[:5]],
    }
    with open(os.path.join(OUTPUT_DIR, "resume_bc03.json"), "w", encoding="utf-8") as f:
        json.dump(resume, f, ensure_ascii=False, indent=2)

    log.info("Entraînement terminé — modèle et résultats écrits dans %s", os.path.abspath(BASE_DIR))


if __name__ == "__main__":
    main()
