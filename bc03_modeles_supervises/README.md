# BC03 — Modèles supervisés

Entraîne et compare trois configurations sur les 400 000 transactions labellisées du socle
[BC01](../bc01_socle_donnees/docs/BC01.md)/[BC02](../bc02_analyse_exploratoire/README.md), avec
un split **temporel** (train jusqu'au 19/10/2025, test au-delà) :

- **Logistic Regression** — référence, sans rééquilibrage
- **Logistic Regression + SMOTE** (30 % de la classe majoritaire) — mesure l'effet réel de SMOTE
- **LightGBM** (Gradient Boosting) — déséquilibre géré nativement par `scale_pos_weight`

Notebooks (à exécuter dans l'ordre, cellule par cellule) :

```bash
jupyter notebook bc03_modeles_supervises/scripts/entrainement_modeles.ipynb
jupyter notebook bc03_modeles_supervises/scripts/explicabilite_shap.ipynb   # à lancer après (réutilise le modèle sauvegardé)
```

Produit les graphiques dans `outputs/`, le modèle retenu dans
`models/modele_lightgbm.joblib`, et les résumés chiffrés `outputs/resume_bc03.json` /
`outputs/resume_shap.json`. `explicabilite_shap.ipynb` ajoute la vue globale (beeswarm) et
l'explication d'une décision individuelle (waterfall) — réponse concrète à l'exigence RGPD Art. 22.

Document détaillé : [docs/bc03-explication-v2.pdf](docs/bc03-explication-v2.pdf).

## Résultats clés (dernier run)

| Modèle | AUC-ROC | Avg. Precision | Précision @0,5 | Rappel @0,5 | F1 @0,5 |
|---|---|---|---|---|---|
| Logistic Regression | 0,983 | 0,670 | 80,0 % | 45,5 % | 0,580 |
| Logistic Regression + SMOTE | 0,984 | 0,605 | 23,4 % | 86,6 % | 0,368 |
| **LightGBM** | **0,998** | **0,921** | 60,9 % | 96,6 % | 0,747 |

Seuil optimisé (F1 max) pour LightGBM : **0,98** → précision 88,5 % / rappel 76,8 % / F1 0,822
(contre 60,9 % / 96,6 % / 0,747 au seuil par défaut 0,50).

**Constats clés :** SMOTE augmente le rappel mais dégrade le F1 de la régression logistique
(effet non systématiquement bénéfique, mesuré plutôt que supposé) ; LightGBM apporte un gain net
sur l'average precision (0,670 → 0,921), confirmant que la fraude multi-signature identifiée au
BC02 nécessite un modèle combinant plusieurs variables. Le choix du seuil final relève d'un
arbitrage métier (coût fraude manquée vs fausse alerte), formalisé au
[BC06](../bc06_gestion_projet/README.md).

`pays_transaction` / `pays_residence` sont exclus des features : séparateur parfait identifié au
BC02, artefact de la génération synthétique plutôt qu'un signal représentatif.
