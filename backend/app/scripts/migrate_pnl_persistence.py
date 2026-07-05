"""持久化 PnL 取数: binance_income / mt5_deals / pnl_sync_watermark 三表。
幂等(CREATE TABLE IF NOT EXISTS)。仿 migrate_hedging_pairs.py 范式。
背景: income/deals 原为实时拉取+内存缓存(重启即丢、易打爆币安REST限频)。
持久化后历史只拉一次, 只增量重拉近端7天。见 [[coin-pnl-income-persistence]]。
运行: cd /data/hustle2026/backend && python -m app.scripts.migrate_pnl_persistence
"""
import asyncio
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

DDL = [
# 表1: 币安逐笔 income
"""
CREATE TABLE IF NOT EXISTS binance_income (
    id              BIGSERIAL PRIMARY KEY,
    account_id      UUID NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    tran_id         BIGINT,
    trade_id        BIGINT,
    income_type     VARCHAR(32) NOT NULL,
    income          NUMERIC(30,12) NOT NULL,
    asset           VARCHAR(16),
    symbol          VARCHAR(32),
    income_time_ms  BIGINT NOT NULL,
    info            VARCHAR(64),
    raw             JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    dedup_key       TEXT GENERATED ALWAYS AS (
        COALESCE(tran_id::text,
            income_time_ms::text || '|' || income_type || '|' || income::text
            || '|' || COALESCE(symbol,'') || '|' || COALESCE(trade_id::text,''))
    ) STORED
)
""",
"CREATE UNIQUE INDEX IF NOT EXISTS uix_binance_income_dedup     ON binance_income(account_id, dedup_key)",
"CREATE INDEX        IF NOT EXISTS idx_binance_income_acct_time ON binance_income(account_id, income_time_ms)",
"CREATE INDEX        IF NOT EXISTS idx_binance_income_type_time ON binance_income(account_id, income_type, income_time_ms)",
# 表2: MT5 全量 deal
"""
CREATE TABLE IF NOT EXISTS mt5_deals (
    id              BIGSERIAL PRIMARY KEY,
    account_id      UUID NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    ticket          BIGINT NOT NULL,
    order_id        BIGINT,
    symbol          VARCHAR(32),
    deal_type       SMALLINT,
    entry           SMALLINT,
    volume          NUMERIC(20,8),
    price           NUMERIC(20,8),
    profit          NUMERIC(20,8),
    swap            NUMERIC(20,8),
    commission      NUMERIC(20,8),
    comment         VARCHAR(128),
    deal_time_raw   BIGINT NOT NULL,
    deal_time_utc   TIMESTAMPTZ NOT NULL,
    bridge_port     INT,
    raw             JSONB,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uix_mt5_deals_acct_ticket UNIQUE (account_id, ticket)
)
""",
"CREATE INDEX IF NOT EXISTS idx_mt5_deals_acct_time       ON mt5_deals(account_id, deal_time_utc)",
"CREATE INDEX IF NOT EXISTS idx_mt5_deals_acct_entry_time ON mt5_deals(account_id, entry, deal_time_utc)",
# 表3: 同步水位
"""
CREATE TABLE IF NOT EXISTS pnl_sync_watermark (
    account_id      UUID NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    source          VARCHAR(32) NOT NULL,
    covered_from_ms BIGINT,
    covered_to_ms   BIGINT,
    last_sync_at    TIMESTAMPTZ,
    last_error      TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, source)
)
""",
]

async def main():
    async with AsyncSessionLocal() as db:
        for i, stmt in enumerate(DDL):
            await db.execute(text(stmt))
            print(f"  [{i+1}/{len(DDL)}] OK: {stmt.strip().splitlines()[0][:60]}")
        await db.commit()
    print("migrate_pnl_persistence: done")

if __name__ == "__main__":
    asyncio.run(main())
