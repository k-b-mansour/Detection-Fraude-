# BC02 — Analyse exploratoire & profiling

Analyse des 400 000 transactions labellisées (voie batch) du socle [BC01](../bc01_socle_donnees/docs/BC01.md) :
déséquilibre de classes, profiling des fraudeurs, statistiques descriptives, détection d'anomalies
univariées (z-score, IQR).

```bash
python bc02_analyse_exploratoire/scripts/analyse_exploratoire.py
```

Produit les graphiques dans `outputs/` et le résumé chiffré `outputs/resume_bc02.json`.

Document détaillé : [docs/bc02-explication.pdf](docs/bc02-explication.pdf).

## Résultats clés (dernier run)

| Indicateur | Valeur |
|---|---|
| Transactions analysées | 400 000 |
| Fraudes | 6 000 (1,50 %, soit 1 pour 66) |
| Canal le plus exposé | en_ligne (2,43 %) |
| Heure la plus exposée | 4h (33,05 %) |
| Détecteur z-score (montant, seuil 3) | précision 20,9 % · rappel 21,0 % |
| Détecteur IQR (montant) | précision 6,2 % · rappel 29,8 % |

La détection univariée plafonne à ~30 % de rappel car la fraude simulée porte 6 signatures
différentes, dont 3 ne se manifestent pas sur le montant — ce qui motive objectivement le passage
aux modèles multivariés du [BC03](../bc03_modeles_supervises/README.md).
