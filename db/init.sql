-- ============================================================
-- Multi-Agent Financial Complaint Governance Engine
-- PostgreSQL Schema Initialization
-- ============================================================

-- Extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─── complaints ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS complaints (
    complaint_id    TEXT PRIMARY KEY,
    product         TEXT NOT NULL,
    sub_product     TEXT,
    issue           TEXT,
    sub_issue       TEXT,
    narrative       TEXT NOT NULL,
    company         TEXT,
    state           TEXT,
    zip_code        TEXT,
    company_response        TEXT,
    timely_response         TEXT,
    consumer_disputed       TEXT,
    disputed_flag           BOOLEAN DEFAULT FALSE,
    date_received           DATE,
    date_sent_to_company    DATE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_complaints_product ON complaints(product);
CREATE INDEX IF NOT EXISTS idx_complaints_issue   ON complaints(issue);
CREATE INDEX IF NOT EXISTS idx_complaints_date    ON complaints(date_received);

-- ─── document_pages ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS document_pages (
    page_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    complaint_id    TEXT NOT NULL REFERENCES complaints(complaint_id) ON DELETE CASCADE,
    page_num        INTEGER NOT NULL DEFAULT 1,
    section_type    TEXT NOT NULL,   -- 'header' | 'narrative' | 'tags'
    text_content    TEXT NOT NULL,
    token_count     INTEGER,
    metadata_json   JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pages_complaint_id ON document_pages(complaint_id);
CREATE INDEX IF NOT EXISTS idx_pages_section      ON document_pages(section_type);

-- ─── embeddings (pointer table; vectors live in Qdrant) ──────
CREATE TABLE IF NOT EXISTS embeddings (
    page_id         UUID PRIMARY KEY REFERENCES document_pages(page_id) ON DELETE CASCADE,
    qdrant_point_id TEXT UNIQUE,
    model_name      TEXT NOT NULL,
    vector_dim      INTEGER,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ─── agent_votes ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_votes (
    vote_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    complaint_id    TEXT NOT NULL REFERENCES complaints(complaint_id) ON DELETE CASCADE,
    agent_name      TEXT NOT NULL,
    round_num       INTEGER NOT NULL DEFAULT 1,
    score           NUMERIC(4,2) NOT NULL,
    confidence      NUMERIC(4,3) NOT NULL,
    risk_flags      JSONB DEFAULT '[]',
    reasoning       TEXT,
    raw_response    JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_votes_complaint ON agent_votes(complaint_id);
CREATE INDEX IF NOT EXISTS idx_votes_agent     ON agent_votes(agent_name);

-- ─── decisions ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS decisions (
    decision_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    complaint_id        TEXT UNIQUE NOT NULL REFERENCES complaints(complaint_id) ON DELETE CASCADE,
    final_score         NUMERIC(4,2),
    ai_decision         TEXT,         -- 'Monetary Relief' | 'Explanation Only' | 'Escalate'
    ai_confidence       NUMERIC(4,3),
    debate_rounds       INTEGER DEFAULT 0,
    guardrail_applied   TEXT,
    actual_outcome      TEXT,         -- from CFPB data (company_response)
    agreement_flag      BOOLEAN,
    evaluation_notes    TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_decisions_flag ON decisions(agreement_flag);

-- ─── config ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS config (
    config_id           SERIAL PRIMARY KEY,
    version             INTEGER NOT NULL DEFAULT 1,
    weight_compliance   NUMERIC(4,3) DEFAULT 0.30,
    weight_fairness     NUMERIC(4,3) DEFAULT 0.20,
    weight_financial    NUMERIC(4,3) DEFAULT 0.20,
    weight_fraud        NUMERIC(4,3) DEFAULT 0.20,
    weight_reputation   NUMERIC(4,3) DEFAULT 0.10,
    debate_threshold    NUMERIC(4,2) DEFAULT 2.00,
    cold_start_penalty  NUMERIC(4,3) DEFAULT 0.15,
    min_similar_cases   INTEGER DEFAULT 5,
    notes               TEXT,
    is_active           BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Seed default config
INSERT INTO config (version, notes, is_active) VALUES (1, 'Initial default weights', TRUE)
ON CONFLICT DO NOTHING;

-- ─── metrics (evaluation aggregates) ─────────────────────────
CREATE TABLE IF NOT EXISTS metrics (
    metric_id       SERIAL PRIMARY KEY,
    run_date        DATE NOT NULL DEFAULT CURRENT_DATE,
    total_evaluated INTEGER,
    accuracy        NUMERIC(5,4),
    precision_score NUMERIC(5,4),
    recall_score    NUMERIC(5,4),
    dispute_pred_accuracy NUMERIC(5,4),
    per_agent_json  JSONB DEFAULT '{}',
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
