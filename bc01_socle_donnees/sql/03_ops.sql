-- ============================================================
-- Couche ops — transversale : observe les trois autres couches,
-- jamais sur le chemin critique d'écriture de la donnée.
-- ============================================================

CREATE TABLE ops.log_chargement (
    log_id       BIGSERIAL PRIMARY KEY,
    source       VARCHAR(50) NOT NULL,     -- 'seed.py' | 'consumer.py'
    mode         VARCHAR(10) NOT NULL,     -- 'batch' | 'stream'
    nb_lignes    INTEGER NOT NULL DEFAULT 0,
    duree_ms     INTEGER,
    statut       VARCHAR(10) NOT NULL,     -- 'EN_COURS' | 'OK' | 'ERREUR'
    message      TEXT,
    demarre_at   TIMESTAMP NOT NULL DEFAULT now(),
    termine_at   TIMESTAMP
);

CREATE TABLE ops.controle_qualite (
    controle_id  BIGSERIAL PRIMARY KEY,
    nom_controle VARCHAR(60) NOT NULL,
    categorie    VARCHAR(20) NOT NULL,     -- completude | integrite | unicite | coherence | plausibilite
    statut       VARCHAR(3) NOT NULL,      -- 'OK' | 'KO'
    valeur       NUMERIC,
    seuil        NUMERIC,
    detail       TEXT,
    execute_at   TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX idx_ops_qc_execute_at ON ops.controle_qualite(execute_at DESC);
