-- 001_init.sql — core relational schema.
-- Idempotent: safe to re-run on existing databases.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS users (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT        NOT NULL UNIQUE,
    name        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS orders (
    id              TEXT        PRIMARY KEY,
    user_id         UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status          TEXT        NOT NULL CHECK (status IN ('pending','shipped','delivered','cancelled')),
    total_amount    NUMERIC(10,2) NOT NULL,
    currency        TEXT        NOT NULL DEFAULT 'USD',
    items           JSONB       NOT NULL DEFAULT '[]'::JSONB,
    tracking_number TEXT,
    carrier         TEXT,
    placed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    shipped_at      TIMESTAMPTZ,
    delivered_at    TIMESTAMPTZ,
    estimated_delivery TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);

CREATE TABLE IF NOT EXISTS returns (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        TEXT        NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    reason          TEXT        NOT NULL,
    item_skus       JSONB       NOT NULL DEFAULT '[]'::JSONB,
    refund_amount   NUMERIC(10,2) NOT NULL DEFAULT 0,
    status          TEXT        NOT NULL CHECK (status IN ('requested','approved','rejected','refunded','manager_review')),
    rma_id          TEXT,
    refund_id       TEXT,
    is_exchange     BOOLEAN     NOT NULL DEFAULT FALSE,
    exchange_sku    TEXT,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_returns_order_id ON returns(order_id);
CREATE INDEX IF NOT EXISTS idx_returns_status ON returns(status);

CREATE TABLE IF NOT EXISTS conversations (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      TEXT        NOT NULL,
    user_id         UUID        REFERENCES users(id) ON DELETE SET NULL,
    intent          TEXT,
    outcome         TEXT,
    messages        JSONB       NOT NULL DEFAULT '[]'::JSONB,
    metadata        JSONB       NOT NULL DEFAULT '{}'::JSONB,
    escalated       BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_session_id ON conversations(session_id);
CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_intent ON conversations(intent);
CREATE INDEX IF NOT EXISTS idx_conversations_created_at ON conversations(created_at DESC);

CREATE TABLE IF NOT EXISTS eval_runs (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_name    TEXT        NOT NULL,
    total_queries   INTEGER     NOT NULL,
    scores          JSONB       NOT NULL DEFAULT '{}'::JSONB,
    failures        JSONB       NOT NULL DEFAULT '[]'::JSONB,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_eval_runs_dataset ON eval_runs(dataset_name);
CREATE INDEX IF NOT EXISTS idx_eval_runs_created_at ON eval_runs(created_at DESC);

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE
    t TEXT;
BEGIN
    FOR t IN SELECT unnest(ARRAY['orders','returns','conversations']) LOOP
        EXECUTE format(
            'DROP TRIGGER IF EXISTS trg_%I_updated_at ON %I; '
            'CREATE TRIGGER trg_%I_updated_at BEFORE UPDATE ON %I '
            'FOR EACH ROW EXECUTE FUNCTION set_updated_at();',
            t, t, t, t
        );
    END LOOP;
END$$;
