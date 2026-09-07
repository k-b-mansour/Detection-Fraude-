-- ============================================================
-- dwh.charger_faits_transactions — UNIQUE porte d'écriture vers
-- dwh.fact_transactions. Batch (seed.py) et streaming (consumer.py)
-- appellent exactement la même fonction : le chemin ne peut pas
-- diverger entre les deux voies d'ingestion.
--
-- Deux façons de traiter une dimension qui ne matche pas :
--   - client_id : JOIN strict. Un client inconnu est une anomalie
--     (le producer ne pioche que des client_id réels) — la ligne de
--     staging reste `traite = FALSE` et sera signalée par le contrôle
--     qualité `staging_transforme` si elle stagne plus de 10 minutes.
--   - horodatage / canal : LEFT JOIN + repli sur le membre "Inconnu"
--     (clé 0). Une transaction streaming dont l'horodatage tombe hors
--     de la fenêtre simulée (2025) atterrit quand même dans le fait,
--     rattachée à dim_temps.temps_key = 0 — comportement volontaire et
--     documenté, jamais une perte silencieuse.
--
-- Idempotence : ON CONFLICT (transaction_bk) DO NOTHING — rejouer un
-- fichier ou réingérer un micro-lot Kafka déjà traité n'insère aucun
-- doublon.
--
-- Paramètre p_mode : NULL = traite tout le staging non traité,
-- 'batch' ou 'stream' = ne traite que les lignes de ce mode.
-- ============================================================
CREATE OR REPLACE FUNCTION dwh.charger_faits_transactions(p_mode VARCHAR DEFAULT NULL)
RETURNS INTEGER AS $$
DECLARE
    v_resolved_ids BIGINT[];
    v_inserted     INTEGER;
BEGIN
    WITH source AS (
        SELECT s.*
        FROM staging.raw_transactions s
        WHERE s.traite = FALSE
          AND (p_mode IS NULL OR s.mode_ingestion = p_mode)
    ),
    resolved AS (
        SELECT
            s.id AS staging_id,
            s.transaction_bk,
            c.client_key,
            COALESCE(t.temps_key, 0) AS temps_key,
            COALESCE(ca.canal_key, 0) AS canal_key,
            s.montant, s.pays_transaction, s.distance_domicile_km, s.authentification,
            s.is_fraud, s.fraud_type, s.mode_ingestion
        FROM source s
        JOIN dwh.dim_clients c     ON c.client_id = s.client_id
        LEFT JOIN dwh.dim_temps t  ON t.horodatage = date_trunc('hour', s.horodatage)
        LEFT JOIN dwh.dim_canal ca ON ca.canal = s.canal AND ca.mcc_code = s.mcc_code
    ),
    ins AS (
        INSERT INTO dwh.fact_transactions (
            transaction_bk, client_key, temps_key, canal_key, montant, devise,
            pays_transaction, pays_residence, distance_domicile_km, authentification,
            is_fraud, fraud_type, mode_ingestion
        )
        SELECT
            transaction_bk, client_key, temps_key, canal_key, montant, 'EUR',
            pays_transaction, 'FR', distance_domicile_km, authentification,
            is_fraud, fraud_type, mode_ingestion
        FROM resolved
        ON CONFLICT (transaction_bk) DO NOTHING
        RETURNING 1
    )
    SELECT
        (SELECT COUNT(*) FROM ins),
        (SELECT array_agg(staging_id) FROM resolved)
    INTO v_inserted, v_resolved_ids;

    IF v_resolved_ids IS NOT NULL THEN
        UPDATE staging.raw_transactions
        SET traite = TRUE
        WHERE id = ANY(v_resolved_ids);
    END IF;

    RETURN COALESCE(v_inserted, 0);
END;
$$ LANGUAGE plpgsql;
