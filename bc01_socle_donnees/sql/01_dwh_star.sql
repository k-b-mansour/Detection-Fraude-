-- ============================================================
-- Couche dwh — schéma en étoile
--
-- Fait central : dwh.fact_transactions, alimenté UNIQUEMENT par
-- dwh.charger_faits_transactions() (04_transform.sql), jamais par
-- une écriture directe — batch et streaming empruntent la même porte.
-- ============================================================

-- ------------------------------------------------------------
-- DIM_AGENCES
-- ------------------------------------------------------------
CREATE TABLE dwh.dim_agences (
    agence_key   SERIAL PRIMARY KEY,
    code_agence  VARCHAR(10) UNIQUE NOT NULL,
    nom          VARCHAR(100) NOT NULL,
    region       VARCHAR(50) NOT NULL,
    ville        VARCHAR(50) NOT NULL
);

-- ------------------------------------------------------------
-- DIM_CLIENTS
-- L'agence est un attribut du client (agence gestionnaire du
-- compte), pas de la transaction : une transaction carte ne
-- transite pas par une agence physique.
-- ------------------------------------------------------------
CREATE TABLE dwh.dim_clients (
    client_key           SERIAL PRIMARY KEY,
    client_id             UUID UNIQUE NOT NULL,       -- clé naturelle, pseudonymisée RGPD
    agence_key             INT NOT NULL REFERENCES dwh.dim_agences(agence_key),
    date_naissance         DATE NOT NULL,
    code_postal            VARCHAR(5) NOT NULL,
    departement            VARCHAR(3) NOT NULL,
    segment                VARCHAR(20) NOT NULL,        -- particulier / premium / professionnel
    revenu_mensuel_net     NUMERIC(10,2) NOT NULL,
    statut                 VARCHAR(20) NOT NULL DEFAULT 'actif',
    date_entree_relation   DATE NOT NULL,
    created_at             TIMESTAMP NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------
-- DIM_TEMPS
-- Une ligne par heure sur la période simulée — dimension
-- conforme, réutilisée par tous les blocs suivants.
-- ------------------------------------------------------------
CREATE TABLE dwh.dim_temps (
    temps_key    SERIAL PRIMARY KEY,
    horodatage   TIMESTAMP UNIQUE NOT NULL,
    date_jour    DATE NOT NULL,
    annee        SMALLINT NOT NULL,
    mois         SMALLINT NOT NULL,
    jour         SMALLINT NOT NULL,
    heure        SMALLINT NOT NULL,
    jour_semaine SMALLINT NOT NULL,   -- 1 = lundi ... 7 = dimanche
    is_weekend   BOOLEAN NOT NULL,
    is_nuit      BOOLEAN NOT NULL     -- 00h-6h, plage horaire à risque
);

-- Membre "Inconnu" : clé technique 0, réservée. Une transaction streaming
-- dont l'horodatage tombe hors de la fenêtre simulée (2025) s'y rattache
-- plutôt que d'être perdue silencieusement — cf. dwh.charger_faits_transactions.
INSERT INTO dwh.dim_temps (temps_key, horodatage, date_jour, annee, mois, jour, heure, jour_semaine, is_weekend, is_nuit)
VALUES (0, '1900-01-01 00:00:00', '1900-01-01', 1900, 1, 1, 0, 1, FALSE, FALSE);
-- Pas de setval ici : la clé 0 est posée hors séquence, la SERIAL démarre bien à 1 au prochain INSERT.

-- ------------------------------------------------------------
-- DIM_CANAL
-- ------------------------------------------------------------
CREATE TABLE dwh.dim_canal (
    canal_key       SERIAL PRIMARY KEY,
    canal           VARCHAR(20) NOT NULL,   -- en_ligne / sans_contact / puce / distributeur
    mcc_code        VARCHAR(4) NOT NULL,
    mcc_libelle     VARCHAR(100) NOT NULL,
    is_online       BOOLEAN NOT NULL,
    is_contactless  BOOLEAN NOT NULL,
    UNIQUE (canal, mcc_code)
);

-- Membre "Inconnu" : mêmes garanties que dim_temps ci-dessus.
INSERT INTO dwh.dim_canal (canal_key, canal, mcc_code, mcc_libelle, is_online, is_contactless)
VALUES (0, 'inconnu', '0000', 'Canal non résolu', FALSE, FALSE);

-- ------------------------------------------------------------
-- FACT_TRANSACTIONS
-- Grain : une ligne = une transaction carte.
--
-- is_fraud / fraud_type sont NULLables : une transaction issue du
-- flux streaming entre dans le fait dès son horodatage résolu,
-- mais son statut de fraude n'est connu qu'après investigation
-- (BC02/BC03 viendront le compléter). Les transactions batch
-- (historique simulé) arrivent déjà labellisées.
-- ------------------------------------------------------------
CREATE TABLE dwh.fact_transactions (
    transaction_key       BIGSERIAL PRIMARY KEY,
    transaction_bk         VARCHAR(50) UNIQUE NOT NULL,  -- clé métier déterministe, garantit l'idempotence

    client_key             INT NOT NULL REFERENCES dwh.dim_clients(client_key),
    temps_key               INT NOT NULL REFERENCES dwh.dim_temps(temps_key),
    canal_key               INT NOT NULL REFERENCES dwh.dim_canal(canal_key),

    montant                 NUMERIC(12,2) NOT NULL,
    devise                  CHAR(3) NOT NULL DEFAULT 'EUR',
    pays_transaction        VARCHAR(2) NOT NULL,
    pays_residence          VARCHAR(2) NOT NULL,
    distance_domicile_km    NUMERIC(8,2) NOT NULL,
    authentification        VARCHAR(20) NOT NULL,      -- 3ds / puce_pin / none

    is_fraud                 BOOLEAN,                    -- NULL = pas encore statué
    fraud_type               VARCHAR(30),

    mode_ingestion           VARCHAR(10) NOT NULL,        -- 'batch' | 'stream'
    created_at               TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX idx_fact_tx_client ON dwh.fact_transactions(client_key);
CREATE INDEX idx_fact_tx_temps  ON dwh.fact_transactions(temps_key);
CREATE INDEX idx_fact_tx_fraud  ON dwh.fact_transactions(is_fraud);

-- ------------------------------------------------------------
-- FACT_CARD_BLOCKS — feature comportementale (BC02)
-- ------------------------------------------------------------
CREATE TABLE dwh.fact_card_blocks (
    block_key       SERIAL PRIMARY KEY,
    client_key      INT NOT NULL REFERENCES dwh.dim_clients(client_key),
    temps_key       INT NOT NULL REFERENCES dwh.dim_temps(temps_key),
    motif           VARCHAR(50) NOT NULL,   -- perte / vol / fraude_suspectee / autre
    date_deblocage  TIMESTAMP,
    created_at      TIMESTAMP NOT NULL DEFAULT now()
);
