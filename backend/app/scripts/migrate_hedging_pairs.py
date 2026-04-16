"""
Database migration: Add platform_symbols and hedging_pairs tables,
extend platforms table with new columns.
Run on server: python -m app.scripts.migrate_hedging_pairs
"""
import asyncio
from sqlalchemy import text
from app.core.database import AsyncSessionLocal


MIGRATION_SQL = """
-- ============================================================
-- 1. Extend platforms table with new columns (safe ADD IF NOT EXISTS)
-- ============================================================
DO $$ BEGIN
  ALTER TABLE platforms ADD COLUMN display_name VARCHAR(50) NOT NULL DEFAULT '';
EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN
  ALTER TABLE platforms ADD COLUMN platform_type VARCHAR(10) NOT NULL DEFAULT 'cex';
EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN
  ALTER TABLE platforms ADD COLUMN auth_type VARCHAR(40) NOT NULL DEFAULT 'hmac_sha256';
EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN
  ALTER TABLE platforms ADD COLUMN position_mode VARCHAR(20) NOT NULL DEFAULT 'hedging';
EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN
  ALTER TABLE platforms ADD COLUMN maker_mechanism VARCHAR(40) NOT NULL DEFAULT 'none';
EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN
  ALTER TABLE platforms ADD COLUMN default_tif VARCHAR(10) NOT NULL DEFAULT 'GTC';
EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN
  ALTER TABLE platforms ADD COLUMN base_currency VARCHAR(10) NOT NULL DEFAULT 'USDT';
EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN
  ALTER TABLE platforms ADD COLUMN requires_proxy BOOLEAN DEFAULT FALSE;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN
  ALTER TABLE platforms ADD COLUMN is_active BOOLEAN DEFAULT TRUE NOT NULL;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

-- Update existing platform rows
UPDATE platforms SET display_name='币安', platform_type='cex', auth_type='hmac_sha256',
  position_mode='hedging', maker_mechanism='price_match_queue', base_currency='USDT',
  requires_proxy=TRUE WHERE platform_id=1 AND display_name='';
UPDATE platforms SET display_name='Bybit MT5', platform_type='mt5', auth_type='bridge_http',
  position_mode='net', maker_mechanism='none', base_currency='USD',
  requires_proxy=FALSE WHERE platform_id=2 AND display_name='';

-- ============================================================
-- 2. Create platform_symbols table
-- ============================================================
CREATE TABLE IF NOT EXISTS platform_symbols (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  platform_id SMALLINT NOT NULL REFERENCES platforms(platform_id),
  symbol VARCHAR(30) NOT NULL,
  base_asset VARCHAR(10) NOT NULL,
  quote_asset VARCHAR(10) NOT NULL DEFAULT 'USDT',
  contract_unit DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  qty_unit VARCHAR(20) NOT NULL DEFAULT 'XAU',
  qty_precision INTEGER NOT NULL DEFAULT 0,
  qty_step DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  min_qty DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  price_precision INTEGER NOT NULL DEFAULT 2,
  price_step DOUBLE PRECISION NOT NULL DEFAULT 0.01,
  maker_fee_rate DOUBLE PRECISION NOT NULL DEFAULT 0.0002,
  taker_fee_rate DOUBLE PRECISION NOT NULL DEFAULT 0.0005,
  fee_type VARCHAR(20) NOT NULL DEFAULT 'percentage',
  fee_per_lot DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  margin_rate_initial DOUBLE PRECISION NOT NULL DEFAULT 0.01,
  margin_rate_maintenance DOUBLE PRECISION NOT NULL DEFAULT 0.005,
  funding_interval VARCHAR(10),
  swap_type VARCHAR(20),
  trading_hours JSONB,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(platform_id, symbol)
);

-- ============================================================
-- 3. Create hedging_pairs table
-- ============================================================
CREATE TABLE IF NOT EXISTS hedging_pairs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  pair_name VARCHAR(60) NOT NULL,
  pair_code VARCHAR(30) NOT NULL UNIQUE,
  account_a_id UUID REFERENCES accounts(account_id),
  symbol_a_id UUID NOT NULL REFERENCES platform_symbols(id),
  account_b_id UUID REFERENCES accounts(account_id),
  symbol_b_id UUID NOT NULL REFERENCES platform_symbols(id),
  conversion_factor DOUBLE PRECISION NOT NULL DEFAULT 100.0,
  usd_usdt_rate DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  usd_usdt_auto_sync BOOLEAN DEFAULT FALSE,
  spread_mode VARCHAR(20) NOT NULL DEFAULT 'absolute',
  spread_precision INTEGER NOT NULL DEFAULT 2,
  default_spread_target DOUBLE PRECISION,
  max_position_value_usd DOUBLE PRECISION,
  min_hedgeable_qty_a DOUBLE PRECISION,
  min_hedgeable_qty_b DOUBLE PRECISION,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  sort_order INTEGER DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_platform_symbols_platform ON platform_symbols(platform_id);
CREATE INDEX IF NOT EXISTS idx_hedging_pairs_active ON hedging_pairs(is_active, sort_order);
"""


SEED_SQL = """
-- ============================================================
-- Seed: Binance symbols (CEX, USDT-margined)
-- ============================================================
INSERT INTO platform_symbols (platform_id, symbol, base_asset, quote_asset, contract_unit, qty_unit, qty_precision, qty_step, min_qty, price_precision, price_step, maker_fee_rate, taker_fee_rate, funding_interval, margin_rate_initial)
VALUES
  (1, 'XAUUSDT',    'XAU', 'USDT', 1,    'XAU',   3, 1,  1,  2, 0.01,   0.0002, 0.0005, '8h', 0.01),
  (1, 'XAGUSDT',    'XAG', 'USDT', 1,    'XAG',   0, 10, 10, 4, 0.0001, 0.0002, 0.0005, '8h', 0.02),
  (1, 'BZUSDT',     'BZ',  'USDT', 1,    'BBL',   0, 1,  1,  3, 0.001,  0.0002, 0.0005, '8h', 0.02),
  (1, 'CLUSDT',     'CL',  'USDT', 1,    'BBL',   0, 1,  1,  3, 0.001,  0.0002, 0.0005, '8h', 0.02),
  (1, 'NATGASUSDT', 'NG',  'USDT', 1,    'mmBtu', 0, 10, 10, 4, 0.0001, 0.0002, 0.0005, '8h', 0.05)
ON CONFLICT (platform_id, symbol) DO NOTHING;

-- ============================================================
-- Seed: Bybit MT5 symbols (MT5 broker, USD)
-- ============================================================
INSERT INTO platform_symbols (platform_id, symbol, base_asset, quote_asset, contract_unit, qty_unit, qty_precision, qty_step, min_qty, price_precision, price_step, fee_type, fee_per_lot, swap_type, margin_rate_initial,
  trading_hours)
VALUES
  (2, 'XAUUSD+', 'XAU', 'USD', 100,   'lot', 2, 0.01, 0.01, 2, 0.01, 'percentage', 0, 'points', 0.01,
    '{"summer_open":"Mon 06:00","summer_close":"Sat 05:00","winter_open":"Mon 07:00","winter_close":"Sat 06:00"}'::jsonb),
  (2, 'XAGUSD',  'XAG', 'USD', 5000,  'lot', 2, 0.01, 0.01, 3, 0.001, 'percentage', 0, 'points', 0.02,
    '{"summer_open":"Mon 06:00","summer_close":"Sat 05:00","winter_open":"Mon 07:00","winter_close":"Sat 06:00"}'::jsonb),
  (2, 'UKOUSD',  'BZ',  'USD', 1000,  'lot', 2, 0.01, 0.01, 2, 0.01, 'percentage', 0, 'points', 0.02,
    '{"summer_open":"Mon 08:00","summer_close":"Sat 05:00","winter_open":"Mon 09:00","winter_close":"Sat 06:00"}'::jsonb),
  (2, 'USOUSD',  'CL',  'USD', 1000,  'lot', 2, 0.01, 0.01, 2, 0.01, 'percentage', 0, 'points', 0.02,
    '{"summer_open":"Mon 08:00","summer_close":"Sat 05:00","winter_open":"Mon 09:00","winter_close":"Sat 06:00"}'::jsonb),
  (2, 'UG-C',    'NG',  'USD', 10000, 'lot', 2, 0.01, 0.01, 3, 0.001, 'percentage', 0, 'points', 0.05,
    '{"summer_open":"Mon 08:00","summer_close":"Sat 05:00","winter_open":"Mon 09:00","winter_close":"Sat 06:00"}'::jsonb)
ON CONFLICT (platform_id, symbol) DO NOTHING;

-- ============================================================
-- Seed: Hedging pairs (product pairs for arbitrage)
-- ============================================================
INSERT INTO hedging_pairs (pair_name, pair_code, symbol_a_id, symbol_b_id, conversion_factor, spread_mode, spread_precision, default_spread_target, sort_order)
SELECT '黄金套利',   'XAU', a.id, b.id, 100,   'absolute', 2, 0.5,   1
FROM platform_symbols a, platform_symbols b
WHERE a.platform_id=1 AND a.symbol='XAUUSDT' AND b.platform_id=2 AND b.symbol='XAUUSD+'
AND NOT EXISTS (SELECT 1 FROM hedging_pairs WHERE pair_code='XAU');

INSERT INTO hedging_pairs (pair_name, pair_code, symbol_a_id, symbol_b_id, conversion_factor, spread_mode, spread_precision, default_spread_target, sort_order)
SELECT '白银套利',   'XAG', a.id, b.id, 500,   'absolute', 4, 0.05,  2
FROM platform_symbols a, platform_symbols b
WHERE a.platform_id=1 AND a.symbol='XAGUSDT' AND b.platform_id=2 AND b.symbol='XAGUSD'
AND NOT EXISTS (SELECT 1 FROM hedging_pairs WHERE pair_code='XAG');

INSERT INTO hedging_pairs (pair_name, pair_code, symbol_a_id, symbol_b_id, conversion_factor, spread_mode, spread_precision, default_spread_target, sort_order)
SELECT '布伦特原油套利', 'BZ', a.id, b.id, 1000, 'absolute', 3, 0.05,  3
FROM platform_symbols a, platform_symbols b
WHERE a.platform_id=1 AND a.symbol='BZUSDT' AND b.platform_id=2 AND b.symbol='UKOUSD'
AND NOT EXISTS (SELECT 1 FROM hedging_pairs WHERE pair_code='BZ');

INSERT INTO hedging_pairs (pair_name, pair_code, symbol_a_id, symbol_b_id, conversion_factor, spread_mode, spread_precision, default_spread_target, sort_order)
SELECT 'WTI原油套利', 'CL', a.id, b.id, 1000,  'absolute', 3, 0.05,  4
FROM platform_symbols a, platform_symbols b
WHERE a.platform_id=1 AND a.symbol='CLUSDT' AND b.platform_id=2 AND b.symbol='USOUSD'
AND NOT EXISTS (SELECT 1 FROM hedging_pairs WHERE pair_code='CL');

INSERT INTO hedging_pairs (pair_name, pair_code, symbol_a_id, symbol_b_id, conversion_factor, spread_mode, spread_precision, default_spread_target, sort_order)
SELECT '天然气套利', 'NG', a.id, b.id, 1000,    'absolute', 4, 0.01,  5
FROM platform_symbols a, platform_symbols b
WHERE a.platform_id=1 AND a.symbol='NATGASUSDT' AND b.platform_id=2 AND b.symbol='UG-C'
AND NOT EXISTS (SELECT 1 FROM hedging_pairs WHERE pair_code='NG');
"""


async def run_migration():
    async with AsyncSessionLocal() as session:
        print("[1/2] Running schema migration...")
        for stmt in MIGRATION_SQL.split(';'):
            stmt = stmt.strip()
            if stmt:
                await session.execute(text(stmt))
        await session.commit()
        print("  Schema migration OK")

        print("[2/2] Seeding platform_symbols and hedging_pairs...")
        for stmt in SEED_SQL.split(';'):
            stmt = stmt.strip()
            if stmt:
                await session.execute(text(stmt))
        await session.commit()
        print("  Seed data OK")

        # Verify
        r = await session.execute(text("SELECT COUNT(*) FROM platform_symbols"))
        sym_count = r.scalar()
        r = await session.execute(text("SELECT COUNT(*) FROM hedging_pairs"))
        pair_count = r.scalar()
        print(f"\n  platform_symbols: {sym_count} rows")
        print(f"  hedging_pairs: {pair_count} rows")


if __name__ == "__main__":
    asyncio.run(run_migration())
