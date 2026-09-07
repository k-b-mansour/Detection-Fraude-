"""
BC03 — Explicabilité SHAP du modèle LightGBM retenu.

Complète l'importance par gain (figure 5 du rapport) par une lecture SHAP :
le SENS de l'impact de chaque variable (pas seulement son ampleur agrégée),
et l'explication d'une décision individuelle — la brique qui répond
concrètement à l'exigence RGPD Art. 22 (explicabilité d'une décision
automatisée aux effets significatifs, au niveau de CHAQUE décision, pas
seulement en moyenne sur le portefeuille).

Réutilise le modèle déjà entraîné par entrainement_modeles.py : lancer ce
script après lui.

Usage :
    python bc03_modeles_supervises/scripts/explicabilite_shap.py
"""
import json
import logging
import os
import sys

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import shap

sys.path.insert(0, os.path.dirname(__file__))
from entrainement_modeles import (  # noqa: E402
    BASE_DIR, CATEGORICAL_FEATURES, FEATURE_COLUMNS, MODEL_DIR, NUMERIC_FEATURES,
    BINARY_FEATURES, OUTPUT_DIR, charger_donnees, split_temporel,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
log = logging.getLogger("bc03-shap")

N_ECHANTILLON = 3000  # taille de l'échantillon pour le résumé SHAP global


def vers_explication_binaire(expl: shap.Explanation) -> shap.Explanation:
    """Normalise la sortie SHAP (les versions/API renvoient parfois une
    dimension supplémentaire par classe) vers la classe positive (fraude)."""
    values = expl.values
    base_values = expl.base_values
    if values.ndim == 3:
        values = values[:, :, 1]
    if np.ndim(base_values) >= 1 and np.ndim(base_values) == 2:
        base_values = base_values[:, 1]
    return shap.Explanation(
        values=values, base_values=base_values, data=expl.data, feature_names=expl.feature_names,
    )


def main():
    df = charger_donnees()
    _, test = split_temporel(df)
    X_test = test[FEATURE_COLUMNS].reset_index(drop=True)
    y_test = test["is_fraud"].astype(int).reset_index(drop=True)

    pipeline = joblib.load(os.path.join(MODEL_DIR, "modele_lightgbm.joblib"))
    prep = pipeline.named_steps["prep"]
    modele = pipeline.named_steps["clf"]
    noms_features = (
        NUMERIC_FEATURES + BINARY_FEATURES
        + list(prep.named_transformers_["cat"].get_feature_names_out(CATEGORICAL_FEATURES))
    )
    log.info("Modèle et prétraitement chargés (%d features)", len(noms_features))

    explainer = shap.TreeExplainer(modele)

    # ------------------------------------------------------------
    # 1. Vue globale — échantillon (calcul SHAP coûteux sur 80 000 lignes)
    # ------------------------------------------------------------
    echantillon = X_test.sample(n=min(N_ECHANTILLON, len(X_test)), random_state=42)
    X_ech_enc = prep.transform(echantillon)
    explication = vers_explication_binaire(explainer(X_ech_enc))
    explication.feature_names = noms_features

    plt.figure(figsize=(9, 6.5))
    shap.plots.beeswarm(explication, max_display=15, show=False)
    plt.title("Impact SHAP par variable (échantillon de 3 000 transactions test)")
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "06_shap_summary.png"), dpi=150, bbox_inches="tight")
    plt.close()
    log.info("Résumé SHAP (beeswarm) enregistré")

    # ------------------------------------------------------------
    # 2. Décision individuelle — la fraude détectée avec la plus forte
    # confiance, pour illustrer une explication opposable au client / à
    # l'équipe conformité (RGPD Art. 22).
    # ------------------------------------------------------------
    proba_test = pipeline.predict_proba(X_test)[:, 1]
    est_vraie_fraude_bien_detectee = (y_test == 1) & (proba_test >= 0.5)
    idx_exemple = int(np.argmax(np.where(est_vraie_fraude_bien_detectee, proba_test, -1)))

    ligne_brute = X_test.iloc[[idx_exemple]]
    ligne_enc = prep.transform(ligne_brute)
    explication_ligne = vers_explication_binaire(explainer(ligne_enc))
    explication_ligne.feature_names = noms_features

    plt.figure(figsize=(8.5, 5.5))
    shap.plots.waterfall(explication_ligne[0], max_display=10, show=False)
    plt.title(f"Explication d'une décision individuelle — score = {proba_test[idx_exemple]:.3f}")
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "07_shap_decision_individuelle.png"), dpi=150, bbox_inches="tight")
    plt.close()

    contributions = sorted(
        zip(noms_features, explication_ligne.values[0]), key=lambda t: abs(t[1]), reverse=True
    )[:5]
    exemple = {
        "score_predit": round(float(proba_test[idx_exemple]), 4),
        "valeurs_brutes": {c: (ligne_brute.iloc[0][c] if c in ligne_brute.columns else None)
                            for c in FEATURE_COLUMNS},
        "top_contributions_shap": [{"feature": f, "impact": round(float(v), 4)} for f, v in contributions],
    }
    log.info("Décision individuelle expliquée — score=%.4f, top facteurs : %s",
              proba_test[idx_exemple], [f for f, _ in contributions])

    resume_path = os.path.join(OUTPUT_DIR, "resume_shap.json")
    with open(resume_path, "w", encoding="utf-8") as f:
        json.dump(exemple, f, ensure_ascii=False, indent=2, default=str)

    log.info("Explicabilité SHAP terminée — graphiques et résumé écrits dans %s", os.path.abspath(OUTPUT_DIR))


if __name__ == "__main__":
    main()
