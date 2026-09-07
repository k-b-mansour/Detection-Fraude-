-- ============================================================
-- Couche staging — porte d'entrée UNIQUE des transactions,
-- que la source soit un chargement batch ou un flux Kafka.
--
-- Aucune règle métier ici, aucune clé étrangère : c'est le rôle
-- de dwh.charger_faits_transactions() (04_transform.sql) de
-- résoudre les dimensions et d'écrire dans dwh.fact_transactions.
-- ============================================================
CREATE TABLE staging.raw_transactions (
    id                     BIGSERIAL PRIMARY KEY,
    transaction_bk         VARCHAR(50) UNIQUE NOT NULL,  -- généré à la source (seed.py / producer.py), jamais recalculé en aval

    client_id              UUID NOT NULL,                -- clé naturelle, cf dwh.dim_clients.client_id
    horodatage             TIMESTAMP NOT NULL,
    montant                NUMERIC(12,2) NOT NULL,
    canal                  VARCHAR(20) NOT NULL,
    mcc_code                VARCHAR(4) NOT NULL,
    pays_transaction        VARCHAR(2) NOT NULL,
    distance_domicile_km    NUMERIC(8,2) NOT NULL,
    authentification        VARCHAR(20) NOT NULL,

    is_fraud                BOOLEAN,                      -- connu pour le batch (historique), NULL pour le stream
    fraud_type               VARCHAR(30),

    mode_ingestion            VARCHAR(10) NOT NULL,        -- 'batch' | 'stream'
    traite                     BOOLEAN NOT NULL DEFAULT FALSE,  -- watermark : déjà transformé vers dwh ?

    ingested_at                 TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX idx_stg_client ON staging.raw_transactions(client_id);
CREATE INDEX idx_stg_traite ON staging.raw_transactions(traite) WHERE traite = FALSE;
