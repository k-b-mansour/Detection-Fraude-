# BC04 — Deep Learning

Deux approches complémentaires au modèle supervisé du [BC03](../bc03_modeles_supervises/README.md),
sur les mêmes 400 000 transactions labellisées :

```bash
python bc04_deep_learning/scripts/autoencodeur_anomalies.py   # non supervisé
python bc04_deep_learning/scripts/reseau_sequences.py         # LSTM + embeddings, compare au LightGBM du BC03
```

Produit les graphiques dans `outputs/`, les modèles dans `models/`, et les résumés chiffrés
`outputs/resume_autoencodeur.json` / `outputs/resume_lstm.json`.

Document détaillé : [docs/bc04-explication.pdf](docs/bc04-explication.pdf).

## Résultats clés (dernier run)

**Autoencodeur** (entraîné uniquement sur transactions légitimes, jamais sur le label) :

| Indicateur | Valeur |
|---|---|
| AUC-ROC (erreur de reconstruction) | 0,886 |
| Rappel / Précision au seuil calibré (p99 train légitime) | 45,3 % / 36,7 % |

Détection par typologie : quasi parfaite sur les anomalies **ponctuelles**
(`ingenierie_sociale` 99,1 %, `usurpation_identite` 93,6 %), nulle sur les anomalies
**contextuelles** (`skimming` 0 %, `test_carte` 0 %) — un autoencodeur classique ne voit que ce
qui est individuellement extrême, pas ce qui est anormal en combinaison.

**Réseau de séquences (LSTM + embeddings)**, comparé au LightGBM du BC03 sur exactement le même
sous-ensemble de test :

| Modèle | AUC-ROC | Avg. Precision | F1 @0,5 |
|---|---|---|---|
| LSTM (séquences de 5 transactions) | 0,997 | 0,897 | 0,696 |
| LightGBM (BC03, même test) | 0,998 | 0,921 | 0,747 |

**Constat clé :** le contexte temporel n'apporte pas de gain mesurable ici, parce que le
générateur du BC01 définit chaque typologie de fraude par les attributs d'une transaction
**unique**, jamais par une relation entre plusieurs transactions successives — `skimming`
(pensé comme une rafale) est en réalité généré comme des transactions indépendantes. C'est une
limite du générateur de données, pas de l'architecture séquentielle (voir le rapport, section 8).

`pays_transaction` reste exclu des features (cf. BC02/BC03). Le LightGBM du BC03 demeure le
modèle de référence pour le BC05 ; l'autoencodeur est envisagé comme signal secondaire (score
d'anomalie complémentaire) plutôt que remplacement.
