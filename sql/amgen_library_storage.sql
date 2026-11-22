-- Development schema for Replit App Storage's integrity manifest and active pointer.
-- Replit Publish promotes the development schema to the managed production database.
CREATE TABLE amgen_library_storage (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton IS TRUE),
    generation BIGINT NOT NULL CHECK (generation > 0),
    objects JSONB NOT NULL,
    active_pointer JSONB,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE amgen_review_decisions (
    id BIGSERIAL PRIMARY KEY,
    scope_hash TEXT NOT NULL,
    block_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    note TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    scope_json TEXT NOT NULL
);
CREATE INDEX amgen_review_scope_idx ON amgen_review_decisions(scope_hash, id);

CREATE TABLE amgen_ingestion_batches (
    run TEXT NOT NULL,
    batch TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    done BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (run, batch)
);

CREATE TABLE amgen_ingestion_job_lock (
    target TEXT PRIMARY KEY,
    pid INTEGER NOT NULL,
    started DOUBLE PRECISION NOT NULL
);
