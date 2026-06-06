-- 003_inventory_auth_mocks.sql — production-grade additions:
--   * bcrypt password_hash + role on users
--   * real per-SKU inventory (replaces hardcoded out-of-stock sets in mocks)
--   * persistent state for the Shopify/Stripe mock services

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS password_hash TEXT,
    ADD COLUMN IF NOT EXISTS role          TEXT NOT NULL DEFAULT 'customer'
        CHECK (role IN ('customer','support','admin'));

CREATE TABLE IF NOT EXISTS inventory (
    sku             TEXT        PRIMARY KEY,
    name            TEXT        NOT NULL,
    stock_quantity  INTEGER     NOT NULL CHECK (stock_quantity >= 0),
    unit_price      NUMERIC(10,2) NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_inventory_stock ON inventory(stock_quantity);

CREATE TABLE IF NOT EXISTS mock_returns (
    rma_id              TEXT        PRIMARY KEY,
    order_id            TEXT        NOT NULL,
    item_skus           JSONB       NOT NULL,
    reason              TEXT        NOT NULL,
    status              TEXT        NOT NULL DEFAULT 'created'
        CHECK (status IN ('created','received','rejected','refunded')),
    shipping_label_url  TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mock_returns_order_id ON mock_returns(order_id);

CREATE TABLE IF NOT EXISTS mock_exchanges (
    exchange_id         TEXT        PRIMARY KEY,
    order_id            TEXT        NOT NULL,
    original_sku        TEXT        NOT NULL,
    new_sku             TEXT        NOT NULL,
    reason              TEXT        NOT NULL,
    status              TEXT        NOT NULL DEFAULT 'created'
        CHECK (status IN ('created','shipped','delivered','cancelled')),
    estimated_ship_at   TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mock_exchanges_order_id ON mock_exchanges(order_id);

CREATE TABLE IF NOT EXISTS mock_refunds (
    refund_id           TEXT        PRIMARY KEY,
    order_id            TEXT        NOT NULL,
    amount              NUMERIC(10,2) NOT NULL CHECK (amount > 0),
    currency            TEXT        NOT NULL DEFAULT 'USD',
    status              TEXT        NOT NULL
        CHECK (status IN ('succeeded','pending_review','failed','reversed')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mock_refunds_order_id ON mock_refunds(order_id);

CREATE TABLE IF NOT EXISTS mock_idempotency_keys (
    key                 TEXT        PRIMARY KEY,
    endpoint            TEXT        NOT NULL,
    request_hash        TEXT        NOT NULL,
    response            JSONB       NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
