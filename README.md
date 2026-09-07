# Détection de Fraude — Transactions Bancaires

Projet portfolio — Titre RNCP — Pipeline ML/DL end-to-end de détection de fraude sur transactions financières.

Données simulées — 5 000 clients · 400 000 transactions (paramétrable, voir [bc01_socle_donnees/docs/BC01.md](bc01_socle_donnees/docs/BC01.md))

Infrastructure (Docker, dépendances Python) mutualisée à la racine ; chaque bloc de compétences
a son propre dossier, autonome, avec son code et sa documentation.

## Structure du projet

```
projet_expo/
├── docker-compose.yml         infra partagée : Postgres, Redis, Kafka, Adminer, Kafka UI
├── requirements.txt           dépendances Python partagées
├── .env.example
│
├── bc01_socle_donnees/        ✅ architecture Data Warehouse, ingestion batch + streaming
│   ├── sql/                   schéma en étoile (staging → dwh → mart → ops)
│   ├── data/seed.py           génération des données synthétiques (voie batch)
│   ├── streaming/             producer.py / consumer.py (voie Kafka)
│   ├── scripts/quality_checks.py
│   └── docs/                  BC01.md, story map, page "socle de données"
│
├── bc02_analyse_exploratoire/ à venir — déséquilibre de classes, profiling, anomalies univariées
├── bc03_modeles_supervises/   à venir — Logistic Regression, Gradient Boosting, SMOTE
├── bc04_deep_learning/        à venir — autoencodeurs, embeddings de séquences
├── bc05_api_monitoring/       à venir — API FastAPI, monitoring de dérive Evidently
└── bc06_gestion_projet/       à venir — conformité RGPD, KPIs métier, documentation finale
```

## Blocs de compétences

| Bloc | Contenu | Statut |
|---|---|---|
| **BC01** | Architecture Data Warehouse (schéma en étoile), ingestion streaming simulée avec Kafka, stockage PostgreSQL + Redis | ✅ [bc01_socle_donnees/](bc01_socle_donnees/docs/BC01.md) |
| **BC02** | Analyse du déséquilibre de classes, profiling des fraudeurs, statistiques descriptives, détection d'anomalies univariées | [à venir](bc02_analyse_exploratoire/README.md) |
| **BC03** | Modèles supervisés (Logistic Regression, Gradient Boosting), SMOTE, optimisation du seuil de décision | [à venir](bc03_modeles_supervises/README.md) |
| **BC04** | Autoencoders, réseaux de neurones sur embeddings de séquences | [à venir](bc04_deep_learning/README.md) |
| **BC05** | API temps réel, scoring en production, monitoring de dérive (Evidently), conteneurisation | [à venir](bc05_api_monitoring/README.md) |
| **BC06** | Gestion de projet, conformité RGPD, documentation technique, KPIs métier | [à venir](bc06_gestion_projet/README.md) |

## Démarrage rapide (BC01)

```bash
# 1. Copier la config d'environnement
cp .env.example .env

# 2. Démarrer l'infrastructure (Postgres + Redis + Adminer + Kafka + Kafka UI)
docker compose up -d

# 3. Installer les dépendances Python
pip install -r requirements.txt

# 4. Générer et charger les données synthétiques (staging -> dwh, voie batch)
python bc01_socle_donnees/data/seed.py --clients 5000 --transactions 400000 --fraud-rate 0.015

# 5. Vérifier le socle (10 contrôles qualité)
python bc01_socle_donnees/scripts/quality_checks.py

# 6. Simuler le flux temps réel (2 terminaux séparés)
python bc01_socle_donnees/streaming/consumer.py
python bc01_socle_donnees/streaming/producer.py --rate 5
```

| Interface | URL |
|---|---|
| Adminer (PostgreSQL) | http://localhost:8080 |
| Kafka UI | http://localhost:8090 |

Détails de l'architecture, du schéma en étoile et des choix de conception : [bc01_socle_donnees/docs/BC01.md](bc01_socle_donnees/docs/BC01.md).
