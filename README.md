# Détection de Fraude — Transactions Bancaires

Projet portfolio — Titre RNCP — Pipeline ML/DL end-to-end de détection de fraude sur transactions financières.

**Projet complet, BC01 → BC06.** Dépôt : https://github.com/k-b-mansour/Detection-Fraude-

Données simulées — 5 000 clients · 400 000 transactions (paramétrable, voir [bc01_socle_donnees/docs/BC01.md](bc01_socle_donnees/docs/BC01.md))

Infrastructure (Docker, dépendances Python) mutualisée à la racine ; chaque bloc de compétences
a son propre dossier, autonome, avec son code et sa documentation.

## Structure du projet

```
projet_expo/
├── docker-compose.yml         infra partagée : Postgres, Redis, Kafka, Adminer, Kafka UI, API
├── requirements.txt           dépendances Python partagées (entraînement/analyse)
├── .github/workflows/ci-cd.yml
├── .env.example
│
├── bc01_socle_donnees/        ✅ architecture Data Warehouse, ingestion batch + streaming
├── bc02_analyse_exploratoire/ ✅ déséquilibre de classes, profiling, anomalies univariées
├── bc03_modeles_supervises/   ✅ Logistic Regression, LightGBM, SMOTE, SHAP, seuil de décision
├── bc04_deep_learning/        ✅ autoencodeur non supervisé, LSTM + embeddings de séquences
├── bc05_api_monitoring/       ✅ API FastAPI temps réel, monitoring Evidently, Docker, CI/CD
└── bc06_gestion_projet/       ✅ audit RGPD exécutable, KPIs métier, bilan de projet
```

## Blocs de compétences

| Bloc | Contenu | Rapport |
|---|---|---|
| **BC01** | Architecture Data Warehouse (schéma en étoile staging/dwh/mart/ops), ingestion streaming Kafka, PostgreSQL + Redis | [PDF](bc01_socle_donnees/docs/BC01-explication.pdf) |
| **BC02** | Déséquilibre de classes, profiling des fraudeurs, statistiques descriptives, anomalies univariées | [PDF](bc02_analyse_exploratoire/docs/bc02-explication.pdf) |
| **BC03** | Logistic Regression, LightGBM, SMOTE, SHAP, optimisation du seuil de décision | [PDF](bc03_modeles_supervises/docs/bc03-explication-v2.pdf) |
| **BC04** | Autoencodeur non supervisé, réseau LSTM sur embeddings de séquences | [PDF](bc04_deep_learning/docs/bc04-explication.pdf) |
| **BC05** | API de scoring temps réel, monitoring de dérive (Evidently), conteneurisation Docker, CI/CD GitHub Actions | [PDF](bc05_api_monitoring/docs/bc05-explication-v2.pdf) |
| **BC06** | Audit RGPD exécutable, KPIs métier (impact financier des seuils), bilan de projet | [PDF](bc06_gestion_projet/docs/bc06-explication.pdf) |

## Démarrage rapide

```bash
# 1. Copier la config d'environnement
cp .env.example .env

# 2. Démarrer l'infrastructure (Postgres, Redis, Kafka, Adminer, Kafka UI, API)
docker compose up -d --build

# 3. Installer les dépendances Python (entraînement/analyse)
pip install -r requirements.txt

# 4. Socle de données (BC01)
python bc01_socle_donnees/data/seed.py --clients 5000 --transactions 400000 --fraud-rate 0.015
python bc01_socle_donnees/scripts/quality_checks.py

# 5. Analyse, modèles, deep learning (BC02 → BC04, notebooks Jupyter
#    à exécuter dans l'ordre, cellule par cellule)
jupyter notebook bc02_analyse_exploratoire/scripts/analyse_exploratoire.ipynb
jupyter notebook bc03_modeles_supervises/scripts/entrainement_modeles.ipynb
jupyter notebook bc03_modeles_supervises/scripts/explicabilite_shap.ipynb
jupyter notebook bc04_deep_learning/scripts/autoencodeur_anomalies.ipynb
jupyter notebook bc04_deep_learning/scripts/reseau_sequences.ipynb

# 6. Monitoring et conformité (BC05 → BC06)
python bc05_api_monitoring/scripts/drift_report.py
python bc06_gestion_projet/scripts/audit_rgpd.py
python bc06_gestion_projet/scripts/kpis_metier.py
```

| Interface | URL |
|---|---|
| Adminer (PostgreSQL) | http://localhost:8080 |
| Kafka UI | http://localhost:8090 |
| API de scoring (santé) | http://localhost:8001/health |
| API de scoring (Swagger) | http://localhost:8001/docs |

## Résultat final

- **Modèle retenu** : LightGBM (BC03), AUC-ROC 0,998, servi en production (BC05) à 24-60 ms/requête
- **Socle** : 400 000 transactions, 10/10 contrôles qualité (BC01), 6/8 conformité RGPD (BC06)
- **CI/CD** : pipeline réellement vert sur GitHub Actions après 3 itérations documentées (BC05)
- **KPI métier** : le seuil optimisé au sens F1 (0,98) n'est pas le plus rentable économiquement —
  le seuil par défaut (0,50) dégage 20 901 € de bénéfice net en plus sur la période de test (BC06)
- **11 incidents réels** rencontrés et corrigés sur l'ensemble du projet, tous documentés dans les
  rapports plutôt que dissimulés (détail : [bc06_gestion_projet/docs/bc06-explication.pdf](bc06_gestion_projet/docs/bc06-explication.pdf))
