# BC06 — Gestion de projet, conformité RGPD, KPIs métier

Clôt le projet par deux livrables exécutables plutôt que déclaratifs :

```bash
python bc06_gestion_projet/scripts/audit_rgpd.py     # audit RGPD sur le schéma réel (information_schema)
python bc06_gestion_projet/scripts/kpis_metier.py    # impact financier des seuils du BC03
```

Document détaillé : [docs/bc06-explication.pdf](docs/bc06-explication.pdf).

## Résultats clés (dernier run)

**Audit RGPD** — 6/8 contrôles conformes (résultats dans `ops.audit_conformite` et
`outputs/resume_audit_rgpd.json`) :
- ✅ Minimisation, pseudonymisation (UUID), pas de données de carte, explicabilité SHAP (Art. 22),
  traçabilité (`ops.*`), pas de table de correspondance identité↔pseudonyme
- ❌ Pas de politique de purge/rétention automatique
- ❌ Secrets de développement en clair dans le dépôt (`fraud_secret`)

Un faux positif (`dwh.dim_agences.nom`, confondu avec une donnée personnelle) a été trouvé et
corrigé avant publication — voir le script pour la justification.

**KPIs métier** — sur 80 000 transactions de test (297 239 € de fraude totale) :

| Seuil | Fraude évitée | Fraude manquée | Coût fausses alertes | Bénéfice net |
|---|---|---|---|---|
| 0,50 (défaut) | 292 884 € | 4 355 € | 6 064 € (758 × 8 €) | **286 820 €** |
| 0,98 (optimisé F1, BC03) | 266 895 € | 30 344 € | 976 € (122 × 8 €) | 265 919 € |

**Constat clé :** le seuil optimisé au sens F1 (BC03) n'est **pas** le plus rentable
économiquement — le seuil par défaut dégage 20 901 € de bénéfice net en plus sur la période de
test, parce que le coût d'une fraude manquée (montant réel) dépasse largement le coût d'une
fausse alerte (8 €, hypothèse à valider avec le métier). Confirme chiffres à l'appui la réserve
posée au BC03 section 6.

Voir le rapport pour le bilan complet du projet (rétrospective BC01→BC05, 11 incidents réels
documentés, décisions structurantes, limites et feuille de route).
