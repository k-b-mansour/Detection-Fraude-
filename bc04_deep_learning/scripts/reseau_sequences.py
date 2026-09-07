"""
BC04 — Réseau de neurones sur embeddings de séquences de transactions.

Contrairement au BC03 (une transaction = une ligne indépendante), ce modèle
reçoit, pour chaque transaction, les L transactions précédentes du MÊME
client comme contexte temporel. Les variables catégorielles (canal,
authentification, segment) sont apprises comme des embeddings plutôt
qu'encodées en one-hot, et la séquence est résumée par un LSTM avant la
décision finale.

Compare ensuite ce modèle au LightGBM du BC03, sur EXACTEMENT le même
sous-ensemble de transactions de test (celles qui disposent d'assez
d'historique pour former une séquence), pour isoler l'apport réel du
contexte temporel.

Usage :
    python bc04_deep_learning/scripts/reseau_sequences.py
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
from sklearn.metrics import (
    average_precision_score, confusion_matrix, f1_score, precision_score,
    recall_score, roc_auc_score, roc_curve, precision_recall_curve,
)
from sklearn.preprocessing import StandardScaler

import keras
from keras import layers, callbacks

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
log = logging.getLogger("bc04-seq")

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
MODEL_DIR = os.path.join(BASE_DIR, "models")
LGBM_PATH = os.path.join(BASE_DIR, "..", "bc03_modeles_supervises", "models", "modele_lightgbm.joblib")
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(MODEL_DIR, exist_ok=True)

COLOR_LSTM = "#164b60"
COLOR_LGBM = "#a8631f"
COLOR_FRAUD = "#a5433a"

plt.rcParams.update({
    "font.family": "sans-serif", "font.size": 10.5,
    "axes.edgecolor": "#c7cedb", "axes.labelcolor": "#1c2230", "text.color": "#1c2230",
    "xtick.color": "#3a4454", "ytick.color": "#3a4454",
    "axes.grid": True, "grid.color": "#e6eaf0", "grid.linewidth": 0.7,
    "figure.facecolor": "white", "axes.facecolor": "white",
})

L = 5  # longueur de séquence (nombre de transactions de contexte)
CANAUX = ["en_ligne", "puce", "sans_contact", "distributeur"]
AUTHENTIFICATIONS = ["puce_pin", "3ds", "none"]
SEGMENTS = ["particulier", "premium", "professionnel"]
NUM_SEQ_COLS = ["montant", "distance_domicile_km", "heure"]
CUTOFF_RATIO = 0.8  # même proportion que le BC03
FEATURE_COLUMNS_LGBM = [
    "montant", "distance_domicile_km", "revenu_mensuel_net", "heure", "jour_semaine", "mois",
    "is_weekend", "is_nuit", "authentification", "canal", "segment",
]


def get_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"), port=os.getenv("POSTGRES_PORT", "5434"),
        dbname=os.getenv("POSTGRES_DB", "frauddetect"), user=os.getenv("POSTGRES_USER", "fraud_admin"),
        password=os.getenv("POSTGRES_PASSWORD", "fraud_secret"),
    )


def charger_donnees() -> pd.DataFrame:
    query = """
        SELECT
            c.client_id, f.montant, f.distance_domicile_km, f.authentification, f.is_fraud, f.fraud_type,
            c.segment, c.revenu_mensuel_net,
            t.horodatage, t.heure, t.jour_semaine, t.is_weekend, t.is_nuit, t.mois,
            ca.canal
        FROM dwh.fact_transactions f
        JOIN dwh.dim_clients c ON c.client_key = f.client_key
        JOIN dwh.dim_temps t   ON t.temps_key = f.temps_key
        JOIN dwh.dim_canal ca  ON ca.canal_key = f.canal_key
        WHERE f.mode_ingestion = 'batch'
        ORDER BY c.client_id, t.horodatage;
    """
    conn = get_connection()
    df = pd.read_sql(query, conn)
    conn.close()
    df["is_weekend"] = df["is_weekend"].astype(int)
    df["is_nuit"] = df["is_nuit"].astype(int)
    df["canal_idx"] = df["canal"].map({c: i for i, c in enumerate(CANAUX)})
    df["auth_idx"] = df["authentification"].map({c: i for i, c in enumerate(AUTHENTIFICATIONS)})
    df["segment_idx"] = df["segment"].map({c: i for i, c in enumerate(SEGMENTS)})
    return df


def construire_sequences(df: pd.DataFrame, scaler: StandardScaler):
    """Fenêtres glissantes de longueur L par client, entièrement vectorisées
    (sliding_window_view) — la boucle Python ne porte que sur les clients.

    Chaque fenêtre couvre les L DERNIÈRES transactions du client, la
    transaction à classer étant elle-même le dernier pas de la séquence
    (pas seulement son historique) : c'est elle qui porte l'essentiel du
    signal (montant, distance, canal — cf. BC02/BC03), le reste de la
    fenêtre n'apportant qu'un contexte temporel additionnel.
    """
    df_scaled_num = scaler.transform(df[NUM_SEQ_COLS])

    seq_num_all, seq_canal_all, seq_auth_all = [], [], []
    static_segment_all, static_revenu_all = [], []
    targets_all, horodatage_all, fraud_type_all, target_rows_all = [], [], [], []

    pos = 0
    for _, g in df.groupby("client_id", sort=False):
        n = len(g)
        pos_fin = pos + n
        if n >= L:
            num = df_scaled_num[pos:pos_fin]
            canal = g["canal_idx"].values
            auth = g["auth_idx"].values
            is_fraud = g["is_fraud"].values
            horodatage = g["horodatage"].values
            fraud_type = g["fraud_type"].values

            # sliding_window_view(arr, L)[j] == arr[j : j+L] ; la cible est
            # le DERNIER élément de chaque fenêtre, donc is_fraud[L-1:].
            fen_num = np.lib.stride_tricks.sliding_window_view(num, L, axis=0)  # (n-L+1, k, L)
            fen_num = np.transpose(fen_num, (0, 2, 1))  # (n-L+1, L, k)
            fen_canal = np.lib.stride_tricks.sliding_window_view(canal, L)
            fen_auth = np.lib.stride_tricks.sliding_window_view(auth, L)

            n_fenetres = n - L + 1
            seq_num_all.append(fen_num)
            seq_canal_all.append(fen_canal)
            seq_auth_all.append(fen_auth)
            static_segment_all.append(np.full(n_fenetres, g["segment_idx"].iloc[0]))
            static_revenu_all.append(np.full(n_fenetres, g["revenu_mensuel_net"].iloc[0], dtype="float64"))
            targets_all.append(is_fraud[L - 1:])
            horodatage_all.append(horodatage[L - 1:])
            fraud_type_all.append(fraud_type[L - 1:])
            # Ligne brute de la transaction CIBLE (celle qu'on prédit), portée telle
            # quelle : c'est ce qui permet de réévaluer le LightGBM du BC03 sur
            # EXACTEMENT les mêmes transactions, sans jointure fragile a posteriori
            # (horodatage seul n'est pas une clé unique — granularité horaire,
            # partagée par des milliers de transactions de clients différents).
            target_rows_all.append(g[FEATURE_COLUMNS_LGBM].iloc[L - 1:])
        pos = pos_fin

    return (
        np.concatenate(seq_num_all).astype("float32"),
        np.concatenate(seq_canal_all).astype("int32"),
        np.concatenate(seq_auth_all).astype("int32"),
        np.concatenate(static_segment_all).astype("int32"),
        np.concatenate(static_revenu_all).astype("float32"),
        np.concatenate(targets_all).astype("int32"),
        np.concatenate(horodatage_all),
        np.concatenate(fraud_type_all),
        pd.concat(target_rows_all, ignore_index=True),
    )


def construire_modele(n_num: int) -> keras.Model:
    in_num = layers.Input(shape=(L, n_num), name="seq_num")
    in_canal = layers.Input(shape=(L,), name="seq_canal")
    in_auth = layers.Input(shape=(L,), name="seq_auth")
    in_segment = layers.Input(shape=(1,), name="segment")
    in_revenu = layers.Input(shape=(1,), name="revenu")

    emb_canal = layers.Embedding(len(CANAUX), 3)(in_canal)
    emb_auth = layers.Embedding(len(AUTHENTIFICATIONS), 2)(in_auth)
    emb_segment = layers.Flatten()(layers.Embedding(len(SEGMENTS), 2)(in_segment))

    fusion_seq = layers.Concatenate(axis=-1)([in_num, emb_canal, emb_auth])
    sortie_lstm = layers.LSTM(32)(fusion_seq)

    fusion_finale = layers.Concatenate()([sortie_lstm, emb_segment, in_revenu])
    x = layers.Dense(16, activation="relu")(fusion_finale)
    x = layers.Dropout(0.2)(x)
    sortie = layers.Dense(1, activation="sigmoid")(x)

    modele = keras.Model([in_num, in_canal, in_auth, in_segment, in_revenu], sortie, name="lstm_fraude")
    modele.compile(optimizer=keras.optimizers.Adam(5e-4, clipnorm=1.0), loss="binary_crossentropy",
                    metrics=[keras.metrics.AUC(name="auc")])
    return modele


def evaluer(y_true, y_proba, seuil=0.5) -> dict:
    y_pred = (y_proba >= seuil).astype(int)
    return {
        "seuil": seuil,
        "auc_roc": round(roc_auc_score(y_true, y_proba), 4),
        "average_precision": round(average_precision_score(y_true, y_proba), 4),
        "precision": round(precision_score(y_true, y_pred, zero_division=0), 4),
        "recall": round(recall_score(y_true, y_pred, zero_division=0), 4),
        "f1": round(f1_score(y_true, y_pred, zero_division=0), 4),
    }


def main():
    df = charger_donnees()
    log.info("Données chargées : %d transactions, %d clients", len(df), df["client_id"].nunique())

    cutoff = df["horodatage"].quantile(CUTOFF_RATIO)
    scaler = StandardScaler().fit(df.loc[df["horodatage"] < cutoff, NUM_SEQ_COLS])

    (seq_num, seq_canal, seq_auth, static_segment, static_revenu,
     y, horodatage, fraud_type, target_rows) = construire_sequences(df, scaler)
    log.info("%d séquences construites (longueur %d)", len(y), L)

    # Le revenu n'était pas normalisé : une entrée statique à l'échelle de
    # plusieurs milliers d'euros, combinée à un poids de classe élevé,
    # déstabilisait l'entraînement du LSTM (dégradé jusqu'à un AUC proche
    # de 0,5 avant ce correctif).
    scaler_revenu = StandardScaler().fit(static_revenu[horodatage < np.datetime64(cutoff)].reshape(-1, 1))
    static_revenu = scaler_revenu.transform(static_revenu.reshape(-1, 1)).ravel().astype("float32")

    est_train = horodatage < np.datetime64(cutoff)
    log.info("Train : %d séquences (%d fraudes, %.2f%%) | Test : %d séquences (%d fraudes, %.2f%%)",
              est_train.sum(), y[est_train].sum(), 100 * y[est_train].mean(),
              (~est_train).sum(), y[~est_train].sum(), 100 * y[~est_train].mean())

    def sous_ensemble(masque):
        return (
            [seq_num[masque], seq_canal[masque], seq_auth[masque],
             static_segment[masque].reshape(-1, 1), static_revenu[masque].reshape(-1, 1)],
            y[masque],
        )

    X_train, y_train = sous_ensemble(est_train)
    X_test, y_test = sous_ensemble(~est_train)

    rng = np.random.default_rng(42)
    idx_val = rng.choice(len(y_train), size=int(0.1 * len(y_train)), replace=False)
    masque_val = np.zeros(len(y_train), dtype=bool)
    masque_val[idx_val] = True
    X_fit = [x[~masque_val] for x in X_train]
    X_val = [x[masque_val] for x in X_train]
    y_fit, y_val = y_train[~masque_val], y_train[masque_val]

    modele = construire_modele(n_num=len(NUM_SEQ_COLS))
    # Racine carrée du ratio brut (≈66) plutôt que le ratio complet : un poids de
    # classe aussi extrême appliqué à un entraînement par mini-lots (SGD/Adam)
    # produit des gradients disproportionnés dès qu'un lot contient une fraude,
    # ce qui déstabilise l'apprentissage — contrairement à scale_pos_weight en
    # gradient boosting (BC03), appliqué arbre par arbre sur tout le jeu de
    # données et donc beaucoup moins sensible à cet effet.
    ratio_brut = (y_fit == 0).sum() / (y_fit == 1).sum()
    poids_classe = {0: 1.0, 1: float(np.sqrt(ratio_brut))}
    log.info("Ratio brut = %.1f -> poids de classe (racine carrée) = %.1f", ratio_brut, poids_classe[1])

    arret = callbacks.EarlyStopping(monitor="val_auc", mode="max", patience=5, restore_best_weights=True)
    historique = modele.fit(
        X_fit, y_fit, validation_data=(X_val, y_val), class_weight=poids_classe,
        epochs=40, batch_size=512, callbacks=[arret], verbose=0,
    )
    n_epochs_reels = len(historique.history["loss"])
    log.info("LSTM entraîné en %d époques", n_epochs_reels)

    # ------------------------------------------------------------
    # Figure 1 — courbes d'apprentissage
    # ------------------------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    axes[0].plot(historique.history["loss"], color=COLOR_LSTM, label="Train")
    axes[0].plot(historique.history["val_loss"], color=COLOR_LGBM, label="Validation")
    axes[0].set_xlabel("Époque"); axes[0].set_ylabel("Perte (binary cross-entropy)")
    axes[0].set_title("Perte"); axes[0].legend()
    axes[1].plot(historique.history["auc"], color=COLOR_LSTM, label="Train")
    axes[1].plot(historique.history["val_auc"], color=COLOR_LGBM, label="Validation")
    axes[1].set_xlabel("Époque"); axes[1].set_ylabel("AUC-ROC")
    axes[1].set_title("AUC"); axes[1].legend()
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "04_lstm_courbes_apprentissage.png"), dpi=150)
    plt.close(fig)

    proba_lstm = modele.predict(X_test, verbose=0).ravel()
    resultat_lstm = evaluer(y_test, proba_lstm)
    log.info("LSTM séquences — AUC=%.4f AP=%.4f F1@0.5=%.4f",
              resultat_lstm["auc_roc"], resultat_lstm["average_precision"], resultat_lstm["f1"])

    # ------------------------------------------------------------
    # Comparaison avec le LightGBM du BC03, sur LE MÊME sous-ensemble
    # de transactions de test (celles qui ont une séquence valide)
    # ------------------------------------------------------------
    pipe_lgbm = joblib.load(LGBM_PATH)
    target_rows_test = target_rows.iloc[~est_train].reset_index(drop=True)
    proba_lgbm_matched = pipe_lgbm.predict_proba(target_rows_test[FEATURE_COLUMNS_LGBM])[:, 1]
    y_lgbm_matched = y_test  # même lignes cibles, même ordre — plus besoin de jointure
    resultat_lgbm_matched = evaluer(y_lgbm_matched, proba_lgbm_matched)
    log.info("LightGBM (BC03) sur le même sous-ensemble — AUC=%.4f AP=%.4f F1@0.5=%.4f",
              resultat_lgbm_matched["auc_roc"], resultat_lgbm_matched["average_precision"],
              resultat_lgbm_matched["f1"])

    # ------------------------------------------------------------
    # Figure 2 — ROC / PR : LSTM vs LightGBM, même sous-ensemble de test
    # ------------------------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6))
    for proba, y_ref, label, color in [
        (proba_lstm, y_test, "LSTM (séquences)", COLOR_LSTM),
        (proba_lgbm_matched, y_lgbm_matched, "LightGBM (BC03, même test)", COLOR_LGBM),
    ]:
        fpr, tpr, _ = roc_curve(y_ref, proba)
        axes[0].plot(fpr, tpr, color=color, label=f"{label} (AUC={roc_auc_score(y_ref, proba):.3f})")
        prec, rec, _ = precision_recall_curve(y_ref, proba)
        axes[1].plot(rec, prec, color=color, label=f"{label} (AP={average_precision_score(y_ref, proba):.3f})")
    axes[0].plot([0, 1], [0, 1], "--", color="#c7cedb", linewidth=1)
    axes[0].set_xlabel("Taux de faux positifs"); axes[0].set_ylabel("Taux de vrais positifs")
    axes[0].set_title("Courbe ROC"); axes[0].legend(fontsize=8.5)
    axes[1].set_xlabel("Rappel"); axes[1].set_ylabel("Précision")
    axes[1].set_title("Courbe Précision/Rappel"); axes[1].legend(fontsize=8.5)
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "05_lstm_vs_lgbm.png"), dpi=150)
    plt.close(fig)

    # ------------------------------------------------------------
    # Table de complémentarité — fraudes capturées par l'un, l'autre, les deux
    # ------------------------------------------------------------
    seuil_lstm = 0.5
    flag_lstm = proba_lstm >= seuil_lstm
    flag_lgbm = proba_lgbm_matched >= seuil_lstm
    est_fraude = y_test.astype(bool)
    complementarite = {
        "capturee_par_les_deux": int((flag_lstm & flag_lgbm & est_fraude).sum()),
        "capturee_par_lstm_seul": int((flag_lstm & ~flag_lgbm & est_fraude).sum()),
        "capturee_par_lgbm_seul": int((~flag_lstm & flag_lgbm & est_fraude).sum()),
        "manquee_par_les_deux": int((~flag_lstm & ~flag_lgbm & est_fraude).sum()),
    }
    log.info("Complémentarité (seuil 0,5) : %s", complementarite)

    modele.save(os.path.join(MODEL_DIR, "lstm_sequences.keras"))
    joblib.dump(scaler, os.path.join(MODEL_DIR, "scaler_sequences.joblib"))

    resume = {
        "longueur_sequence": L,
        "n_sequences_train": int(est_train.sum()), "n_sequences_test": int((~est_train).sum()),
        "n_epochs": n_epochs_reels,
        "poids_classe_fraude": round(poids_classe[1], 2),
        "lstm": resultat_lstm,
        "lightgbm_meme_test": resultat_lgbm_matched,
        "complementarite": complementarite,
    }
    with open(os.path.join(OUTPUT_DIR, "resume_lstm.json"), "w", encoding="utf-8") as f:
        json.dump(resume, f, ensure_ascii=False, indent=2)

    log.info("Réseau de séquences terminé — résultats écrits dans %s", os.path.abspath(OUTPUT_DIR))


if __name__ == "__main__":
    main()
