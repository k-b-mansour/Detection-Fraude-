"""
BC04 — Autoencodeur pour la détection d'anomalies (approche non supervisée).

Contrairement au BC03, ce modèle n'apprend JAMAIS à partir du label
is_fraud : il apprend uniquement à reconstruire des transactions
légitimes, sur les données d'entraînement. Une transaction que le modèle
reconstruit mal (erreur de reconstruction élevée) est signalée comme
anomalie. Les labels ne servent qu'à ÉVALUER le résultat a posteriori,
jamais à l'entraînement — c'est toute la différence avec un classifieur
supervisé, et l'intérêt principal de l'approche : elle ne présuppose
aucune connaissance préalable des typologies de fraude.

Usage :
    python bc04_deep_learning/scripts/autoencodeur_anomalies.py
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
from sklearn.compose import ColumnTransformer
from sklearn.metrics import (
    average_precision_score, confusion_matrix, f1_score, precision_score,
    recall_score, roc_auc_score, roc_curve,
)
from sklearn.preprocessing import OneHotEncoder, StandardScaler

import keras
from keras import layers, callbacks

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
log = logging.getLogger("bc04-ae")

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
MODEL_DIR = os.path.join(BASE_DIR, "models")
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(MODEL_DIR, exist_ok=True)

COLOR_LEGIT = "#164b60"
COLOR_FRAUD = "#a5433a"
COLOR_VAL = "#a8631f"

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
        host=os.getenv("POSTGRES_HOST", "localhost"), port=os.getenv("POSTGRES_PORT", "5434"),
        dbname=os.getenv("POSTGRES_DB", "frauddetect"), user=os.getenv("POSTGRES_USER", "fraud_admin"),
        password=os.getenv("POSTGRES_PASSWORD", "fraud_secret"),
    )


def charger_donnees() -> pd.DataFrame:
    """Même requête et même exclusion de pays_transaction que le BC03 —
    voir bc03-explication.pdf section 2 pour la justification."""
    query = """
        SELECT
            f.montant, f.distance_domicile_km, f.authentification, f.is_fraud, f.fraud_type,
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


def split_temporel(df: pd.DataFrame, ratio_train: float = 0.8):
    idx = int(len(df) * ratio_train)
    return df.iloc[:idx], df.iloc[idx:]


def construire_preprocesseur() -> ColumnTransformer:
    return ColumnTransformer([
        ("num", StandardScaler(), NUMERIC_FEATURES),
        ("bin", "passthrough", BINARY_FEATURES),
        ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL_FEATURES),
    ])


def construire_autoencodeur(dim_entree: int) -> keras.Model:
    entree = layers.Input(shape=(dim_entree,))
    x = layers.Dense(12, activation="relu")(entree)
    x = layers.Dense(6, activation="relu")(x)
    goulot = layers.Dense(3, activation="relu", name="goulot")(x)
    x = layers.Dense(6, activation="relu")(goulot)
    x = layers.Dense(12, activation="relu")(x)
    sortie = layers.Dense(dim_entree, activation="linear")(x)
    modele = keras.Model(entree, sortie, name="autoencodeur")
    modele.compile(optimizer=keras.optimizers.Adam(1e-3), loss="mse")
    return modele


def main():
    df = charger_donnees()
    train, test = split_temporel(df)
    log.info("Train : %d lignes (%d fraudes) | Test : %d lignes (%d fraudes)",
              len(train), train["is_fraud"].sum(), len(test), test["is_fraud"].sum())

    prep = construire_preprocesseur()
    X_train_enc = prep.fit_transform(train[FEATURE_COLUMNS])
    X_test_enc = prep.transform(test[FEATURE_COLUMNS])
    y_test = test["is_fraud"].astype(int).values

    # ------------------------------------------------------------
    # Entraînement UNIQUEMENT sur les transactions légitimes du train —
    # l'autoencodeur n'a jamais accès au label, ni pendant l'entraînement
    # ni pendant le calibrage du seuil (percentile de l'erreur sur le
    # train légitime uniquement).
    # ------------------------------------------------------------
    X_train_legit = X_train_enc[train["is_fraud"].values == 0]
    log.info("Autoencodeur entraîné sur %d transactions légitimes uniquement (aucun label utilisé)",
              len(X_train_legit))

    rng = np.random.default_rng(42)
    idx = rng.permutation(len(X_train_legit))
    coupure = int(0.9 * len(idx))
    X_fit, X_val = X_train_legit[idx[:coupure]], X_train_legit[idx[coupure:]]

    modele = construire_autoencodeur(X_train_enc.shape[1])
    arret = callbacks.EarlyStopping(monitor="val_loss", patience=5, restore_best_weights=True)
    historique = modele.fit(
        X_fit, X_fit, validation_data=(X_val, X_val),
        epochs=60, batch_size=256, callbacks=[arret], verbose=0,
    )
    n_epochs_reels = len(historique.history["loss"])
    log.info("Entraînement terminé en %d époques (arrêt anticipé)", n_epochs_reels)

    # ------------------------------------------------------------
    # Figure 1 — courbe d'apprentissage
    # ------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(historique.history["loss"], color=COLOR_LEGIT, label="Perte (train, légitimes)")
    ax.plot(historique.history["val_loss"], color=COLOR_VAL, label="Perte (validation, légitimes)")
    ax.set_xlabel("Époque")
    ax.set_ylabel("Erreur quadratique moyenne (MSE)")
    ax.set_title("Courbe d'apprentissage de l'autoencodeur")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "01_ae_courbe_apprentissage.png"), dpi=150)
    plt.close(fig)

    # ------------------------------------------------------------
    # Erreur de reconstruction — calibrage du seuil sur le train légitime
    # SEUL (jamais sur le test, jamais avec les labels de fraude)
    # ------------------------------------------------------------
    def erreur_reconstruction(X):
        X_hat = modele.predict(X, verbose=0)
        return np.mean(np.square(X - X_hat), axis=1)

    erreur_train_legit = erreur_reconstruction(X_train_legit)
    seuil = float(np.percentile(erreur_train_legit, 99))
    log.info("Seuil d'anomalie (percentile 99 de l'erreur sur train légitime) = %.4f", seuil)

    erreur_test = erreur_reconstruction(X_test_enc)
    auc = roc_auc_score(y_test, erreur_test)
    ap = average_precision_score(y_test, erreur_test)
    y_pred = (erreur_test >= seuil).astype(int)
    resultat = {
        "seuil_p99_train_legit": round(seuil, 4),
        "auc_roc": round(auc, 4),
        "average_precision": round(ap, 4),
        "precision": round(precision_score(y_test, y_pred, zero_division=0), 4),
        "recall": round(recall_score(y_test, y_pred, zero_division=0), 4),
        "f1": round(f1_score(y_test, y_pred, zero_division=0), 4),
    }
    log.info("Autoencodeur — AUC=%.4f AP=%.4f Précision=%.4f Rappel=%.4f F1=%.4f",
              auc, ap, resultat["precision"], resultat["recall"], resultat["f1"])

    # ------------------------------------------------------------
    # Figure 2 — distribution de l'erreur de reconstruction
    # ------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(8, 4.4))
    ax.hist(np.log10(erreur_test[y_test == 0] + 1e-6), bins=60, alpha=0.6, color=COLOR_LEGIT,
            density=True, label="Légitimes")
    ax.hist(np.log10(erreur_test[y_test == 1] + 1e-6), bins=60, alpha=0.6, color=COLOR_FRAUD,
            density=True, label="Fraudes")
    ax.axvline(np.log10(seuil + 1e-6), color="#1c2230", linestyle="--", linewidth=1.2,
               label=f"seuil (percentile 99 train légitime)")
    ax.set_xlabel("Erreur de reconstruction (log10 MSE)")
    ax.set_ylabel("Densité")
    ax.set_title("Distribution de l'erreur de reconstruction — test")
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "02_ae_distribution_erreur.png"), dpi=150)
    plt.close(fig)

    # ------------------------------------------------------------
    # Figure 3 — taux de détection par typologie de fraude
    # ------------------------------------------------------------
    test_fraud = test[test["is_fraud"]].copy()
    test_fraud["detectee"] = y_pred[y_test == 1].astype(bool)
    taux_par_type = test_fraud.groupby("fraud_type")["detectee"].mean().sort_values(ascending=False) * 100

    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    ax.barh(taux_par_type.index, taux_par_type.values, color=COLOR_FRAUD)
    ax.set_xlabel("Taux de détection par l'autoencodeur (%)")
    ax.set_title(f"Détection par typologie de fraude (seuil = percentile 99)")
    ax.invert_yaxis()
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "03_ae_detection_par_typologie.png"), dpi=150)
    plt.close(fig)
    log.info("Détection par typologie : %s", taux_par_type.round(1).to_dict())

    modele.save(os.path.join(MODEL_DIR, "autoencodeur.keras"))
    joblib.dump(prep, os.path.join(MODEL_DIR, "preprocesseur_ae.joblib"))

    resume = {
        "n_train": len(train), "n_train_legit": len(X_train_legit), "n_test": len(test),
        "n_epochs": n_epochs_reels, "resultat": resultat,
        "taux_detection_par_typologie": taux_par_type.round(2).to_dict(),
    }
    with open(os.path.join(OUTPUT_DIR, "resume_autoencodeur.json"), "w", encoding="utf-8") as f:
        json.dump(resume, f, ensure_ascii=False, indent=2)

    log.info("Autoencodeur terminé — résultats écrits dans %s", os.path.abspath(OUTPUT_DIR))


if __name__ == "__main__":
    main()
