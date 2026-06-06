-- =============================================================================
-- seed.sql
-- Real seed data for development & evaluation.
--
-- All authentication uses real bcrypt hashes generated via the pgcrypto
-- `crypt()` function (cost 12, blowfish). No plaintext passwords are stored.
--
-- Default credentials (for local dev only):
--     alice@example.com / alice-pass-2026
--     bob@example.com   / bob-pass-2026
--     carol@example.com / carol-pass-2026
--
-- This file is intended to run AFTER migrations 001, 002, and 003.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Users (with bcrypt password hashes)
-- -----------------------------------------------------------------------------
INSERT INTO users (id, email, name, password_hash, role) VALUES
    ('11111111-1111-1111-1111-111111111111', 'alice@example.com', 'Alice Anderson',
        crypt('alice-pass-2026', gen_salt('bf', 12)), 'customer'),
    ('22222222-2222-2222-2222-222222222222', 'bob@example.com',   'Bob Brown',
        crypt('bob-pass-2026',   gen_salt('bf', 12)), 'customer'),
    ('33333333-3333-3333-3333-333333333333', 'carol@example.com', 'Carol Chen',
        crypt('carol-pass-2026', gen_salt('bf', 12)), 'customer'),
    ('44444444-4444-4444-4444-444444444444', 'support@example.com', 'Support Bot',
        crypt('support-pass-2026', gen_salt('bf', 12)), 'support')
ON CONFLICT (email) DO UPDATE
    SET password_hash = EXCLUDED.password_hash,
        role          = EXCLUDED.role,
        name          = EXCLUDED.name;

-- -----------------------------------------------------------------------------
-- Inventory (real per-SKU stock — the mock Shopify service queries this
-- table for exchange availability)
-- -----------------------------------------------------------------------------
INSERT INTO inventory (sku, name, stock_quantity, unit_price) VALUES
    -- SKUs sold in seed orders
    ('TSHIRT-BLU-M',       'Blue T-Shirt (M)',          150, 21.00),
    ('TSHIRT-BLU-L',       'Blue T-Shirt (L)',          120, 21.00),
    ('TSHIRT-RED-M',       'Red T-Shirt (M)',            80, 21.00),
    ('HEADPHONES-X1',      'Wireless Headphones (Black)', 40, 129.99),
    ('HEADPHONES-X1-SLV',  'Wireless Headphones (Silver)', 25, 129.99),
    ('SNEAKER-RED-10',     'Red Sneakers (size 10)',     30, 89.50),
    ('SNEAKER-RED-11',     'Red Sneakers (size 11)',     12, 89.50),
    ('JACKET-BLK-L',       'Black Jacket (L)',           20, 215.75),
    ('JACKET-BLK-XL',      'Black Jacket (XL)',           8, 215.75),
    ('MUG-CER-WHT',        'Ceramic Mug (White)',       200,  9.00),
    ('MUG-CER-BLK',        'Ceramic Mug (Black)',       180,  9.00),
    ('TABLET-PRO-10',      'Pro Tablet 10" (Space Grey)', 15, 499.00),
    ('TABLET-PRO-10-SLV',  'Pro Tablet 10" (Silver)',     10, 499.00),
    ('BACKPACK-GRY',       'Grey Backpack',              50, 75.00),
    ('BACKPACK-BLU',       'Blue Backpack',              40, 75.00),
    ('WATER-BOTTLE',       'Steel Water Bottle',        300, 16.00),
    ('WATER-BOTTLE-STL',   'Stainless Water Bottle',    250, 18.00),
    ('JEANS-BLU-32',       'Blue Jeans (32)',            45, 65.00),
    ('JEANS-BLU-33',       'Blue Jeans (33)',            38, 65.00),
    ('JEANS-BLU-34',       'Blue Jeans (34)',             0, 65.00),  -- intentionally OOS
    ('BOOK-COOK-01',       'Cookbook Vol 1',             60, 24.00),
    ('BOOK-COOK-02',       'Cookbook Vol 2',             55, 24.00)
ON CONFLICT (sku) DO UPDATE
    SET name           = EXCLUDED.name,
        stock_quantity = EXCLUDED.stock_quantity,
        unit_price     = EXCLUDED.unit_price,
        updated_at     = NOW();

-- -----------------------------------------------------------------------------
-- Orders
-- -----------------------------------------------------------------------------
INSERT INTO orders (id, user_id, status, total_amount, items, tracking_number, carrier,
                    placed_at, shipped_at, delivered_at, estimated_delivery)
VALUES
    -- Delivered recently (within return window)
    ('ORD-1001', '11111111-1111-1111-1111-111111111111', 'delivered', 42.00,
     '[{"sku":"TSHIRT-BLU-M","name":"Blue T-Shirt (M)","quantity":2,"unit_price":21.00}]'::JSONB,
     'TRK10001', 'UPS', NOW() - INTERVAL '12 days', NOW() - INTERVAL '10 days',
     NOW() - INTERVAL '7 days', NOW() - INTERVAL '8 days'),

    ('ORD-1002', '11111111-1111-1111-1111-111111111111', 'delivered', 129.99,
     '[{"sku":"HEADPHONES-X1","name":"Wireless Headphones","quantity":1,"unit_price":129.99}]'::JSONB,
     'TRK10002', 'FedEx', NOW() - INTERVAL '20 days', NOW() - INTERVAL '18 days',
     NOW() - INTERVAL '15 days', NOW() - INTERVAL '16 days'),

    -- Delivered outside the return window (>30 days)
    ('ORD-1003', '22222222-2222-2222-2222-222222222222', 'delivered', 89.50,
     '[{"sku":"SNEAKER-RED-10","name":"Red Sneakers (10)","quantity":1,"unit_price":89.50}]'::JSONB,
     'TRK10003', 'USPS', NOW() - INTERVAL '60 days', NOW() - INTERVAL '58 days',
     NOW() - INTERVAL '55 days', NOW() - INTERVAL '56 days'),

    -- Shipped, not yet delivered (WISMO target)
    ('ORD-1004', '22222222-2222-2222-2222-222222222222', 'shipped', 215.75,
     '[{"sku":"JACKET-BLK-L","name":"Black Jacket (L)","quantity":1,"unit_price":215.75}]'::JSONB,
     'TRK10004', 'UPS', NOW() - INTERVAL '4 days', NOW() - INTERVAL '2 days',
     NULL, NOW() + INTERVAL '1 day'),

    -- Pending order
    ('ORD-1005', '33333333-3333-3333-3333-333333333333', 'pending', 18.00,
     '[{"sku":"MUG-CER-WHT","name":"Ceramic Mug","quantity":2,"unit_price":9.00}]'::JSONB,
     NULL, NULL, NOW() - INTERVAL '6 hours', NULL, NULL, NOW() + INTERVAL '5 days'),

    -- High-value delivered (requires manager review for refund)
    ('ORD-1006', '33333333-3333-3333-3333-333333333333', 'delivered', 499.00,
     '[{"sku":"TABLET-PRO-10","name":"Pro Tablet 10\"","quantity":1,"unit_price":499.00}]'::JSONB,
     'TRK10006', 'FedEx', NOW() - INTERVAL '10 days', NOW() - INTERVAL '8 days',
     NOW() - INTERVAL '5 days', NOW() - INTERVAL '6 days'),

    -- Delayed shipment
    ('ORD-1007', '11111111-1111-1111-1111-111111111111', 'shipped', 75.00,
     '[{"sku":"BACKPACK-GRY","name":"Grey Backpack","quantity":1,"unit_price":75.00}]'::JSONB,
     'TRK10007', 'USPS', NOW() - INTERVAL '14 days', NOW() - INTERVAL '12 days',
     NULL, NOW() - INTERVAL '5 days'),  -- estimated past = delayed

    -- Cancelled order
    ('ORD-1008', '22222222-2222-2222-2222-222222222222', 'cancelled', 32.00,
     '[{"sku":"WATER-BOTTLE","name":"Steel Water Bottle","quantity":2,"unit_price":16.00}]'::JSONB,
     NULL, NULL, NOW() - INTERVAL '3 days', NULL, NULL, NULL),

    -- Exchange candidate (size issue)
    ('ORD-1009', '33333333-3333-3333-3333-333333333333', 'delivered', 65.00,
     '[{"sku":"JEANS-BLU-32","name":"Blue Jeans (32)","quantity":1,"unit_price":65.00}]'::JSONB,
     'TRK10009', 'UPS', NOW() - INTERVAL '8 days', NOW() - INTERVAL '6 days',
     NOW() - INTERVAL '3 days', NOW() - INTERVAL '4 days'),

    -- Low-value damaged delivery
    ('ORD-1010', '11111111-1111-1111-1111-111111111111', 'delivered', 24.00,
     '[{"sku":"BOOK-COOK-01","name":"Cookbook Vol 1","quantity":1,"unit_price":24.00}]'::JSONB,
     'TRK10010', 'USPS', NOW() - INTERVAL '5 days', NOW() - INTERVAL '4 days',
     NOW() - INTERVAL '1 day', NOW() - INTERVAL '2 days')
ON CONFLICT (id) DO NOTHING;

-- -----------------------------------------------------------------------------
-- A prior refunded return for history
-- -----------------------------------------------------------------------------
INSERT INTO returns (order_id, reason, item_skus, refund_amount, status, rma_id, refund_id)
VALUES (
    'ORD-1010', 'damaged in transit',
    '["BOOK-COOK-01"]'::JSONB, 24.00, 'refunded',
    'RMA-SEED-001', 'REF-SEED-001'
)
ON CONFLICT DO NOTHING;
