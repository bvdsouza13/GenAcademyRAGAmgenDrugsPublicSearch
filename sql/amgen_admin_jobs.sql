-- Apply once to the managed development database before enabling hosted Admin builds.
CREATE TABLE IF NOT EXISTS amgen_admin_jobs (
    job_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('build_library')),
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    payload JSONB NOT NULL,
    progress JSONB NOT NULL DEFAULT '{}'::jsonb,
    result JSONB,
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    worker_id TEXT,
    heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS amgen_admin_jobs_recent_idx
    ON amgen_admin_jobs (created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS amgen_admin_jobs_one_active_idx
    ON amgen_admin_jobs ((true)) WHERE status IN ('queued', 'running');
