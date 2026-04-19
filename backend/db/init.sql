-- =========================================================
-- CIE PostgreSQL Schema v1.0
-- Run by docker-entrypoint-initdb.d at first container start.
-- Full schema is managed by Alembic migrations in production.
-- =========================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── Users ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       VARCHAR NOT NULL UNIQUE,
    name        VARCHAR NOT NULL,
    google_id   VARCHAR NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ── Workflows ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workflows (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        VARCHAR NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ── Workflow Nodes ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workflow_nodes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id     UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    type            VARCHAR NOT NULL CHECK (type IN ('INPUT','CLEAN','ANALYZE','VISUALIZE','OUTPUT')),
    skill_id        VARCHAR,
    parameters      JSONB NOT NULL DEFAULT '{}',
    position_order  INTEGER NOT NULL
);

-- ── Template Mappings ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS template_mappings (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    template_name        VARCHAR NOT NULL,
    google_drive_file_id VARCHAR NOT NULL,
    file_type            VARCHAR NOT NULL CHECK (file_type IN ('SLIDES','DOCS')),
    tags                 JSONB NOT NULL DEFAULT '[]'
);

-- ── Audit Logs ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_logs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(id),
    action        VARCHAR NOT NULL,
    resource_type VARCHAR NOT NULL,
    resource_id   UUID,
    timestamp     TIMESTAMPTZ DEFAULT NOW(),
    ip_address    INET
);

-- ── Indexes ────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_workflows_user_id       ON workflows(user_id);
CREATE INDEX IF NOT EXISTS idx_workflow_nodes_workflow  ON workflow_nodes(workflow_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id      ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp    ON audit_logs(timestamp DESC);
