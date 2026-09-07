-- ============================================================
-- BC01 — Socle de données : découpage en couches (à la Kimball)
--
--   staging  : copie brute, telle que reçue (batch ou stream), aucune règle métier
--   dwh      : schéma en étoile — dimensions + faits, alimenté par une seule
--              fonction de transformation partagée entre les deux voies d'ingestion
--   mart     : vues de restitution — contrat d'interface pour BC02 → BC06
--   ops      : journal des chargements + contrôles qualité, transversal,
--              jamais sur le chemin critique de la donnée
-- ============================================================
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS dwh;
CREATE SCHEMA IF NOT EXISTS mart;
CREATE SCHEMA IF NOT EXISTS ops;
