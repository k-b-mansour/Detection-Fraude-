-- ============================================================
-- Couche mart — contrat d'interface pour BC02 → BC06.
-- Vues uniquement : aucune donnée stockée, toujours à jour.
-- ============================================================

CREATE VIEW mart.v_kpis_globaux AS
SELECT
    COUNT(*)                                              AS nb_transactions,
    COUNT(*) FILTER (WHERE is_fraud)                      AS nb_fraudes,
    ROUND(100.0 * COUNT(*) FILTER (WHERE is_fraud)
          / NULLIF(COUNT(*) FILTER (WHERE is_fraud IS NOT NULL), 0), 3) AS taux_fraude_pct,
    ROUND(SUM(montant) FILTER (WHERE is_fraud), 2)         AS montant_fraude_total,
    COUNT(*) FILTER (WHERE is_fraud IS NULL)               AS nb_en_attente_labellisation
FROM dwh.fact_transactions;

CREATE VIEW mart.v_kpis_ingestion AS
SELECT
    mode_ingestion,
    COUNT(*)                                    AS nb_transactions,
    COUNT(*) FILTER (WHERE is_fraud)            AS nb_fraudes,
    MIN(created_at)                              AS premiere_ecriture,
    MAX(created_at)                              AS derniere_ecriture
FROM dwh.fact_transactions
GROUP BY mode_ingestion;

CREATE VIEW mart.v_profil_horaire AS
SELECT
    t.heure,
    COUNT(*)                                          AS nb_transactions,
    COUNT(*) FILTER (WHERE f.is_fraud)                AS nb_fraudes,
    ROUND(100.0 * COUNT(*) FILTER (WHERE f.is_fraud)
          / NULLIF(COUNT(*) FILTER (WHERE f.is_fraud IS NOT NULL), 0), 3) AS taux_fraude_pct
FROM dwh.fact_transactions f
JOIN dwh.dim_temps t ON t.temps_key = f.temps_key
GROUP BY t.heure
ORDER BY t.heure;

CREATE VIEW mart.v_top_fraude_type AS
SELECT
    fraud_type,
    COUNT(*)                 AS nb_fraudes,
    ROUND(SUM(montant), 2)   AS montant_total,
    ROUND(AVG(montant), 2)   AS montant_moyen
FROM dwh.fact_transactions
WHERE is_fraud
GROUP BY fraud_type
ORDER BY nb_fraudes DESC;
