-- 0012: 逐仓 carry 归因对账(P1,2026-07-13)
-- 每个已平 dualperp 仓,把 income_records 按 [开仓-5min, min(平仓+35min, 同币下一仓开仓)] 窗口
-- 归因到本仓,拆 funding/pnl/fee → net。complete=账单结算判定(bybit walker 有滞后,
-- 平仓 3h 内的行每轮重算直至定案)。advisor 降权只采信 complete 行。
CREATE TABLE IF NOT EXISTS dualperp_carry_recon (
    position_id   INTEGER PRIMARY KEY REFERENCES dualperp_positions(id) ON DELETE CASCADE,
    symbol        TEXT NOT NULL,
    venue_long    TEXT NOT NULL,
    venue_short   TEXT NOT NULL,
    notional_usdt NUMERIC NOT NULL DEFAULT 0,
    opened_at     TIMESTAMPTZ NOT NULL,
    closed_at     TIMESTAMPTZ NOT NULL,
    hold_hours    NUMERIC NOT NULL DEFAULT 0,
    open_gap_bps  NUMERIC,
    funding_usdt  NUMERIC NOT NULL DEFAULT 0,
    pnl_usdt      NUMERIC NOT NULL DEFAULT 0,
    fee_usdt      NUMERIC NOT NULL DEFAULT 0,
    net_usdt      NUMERIC NOT NULL DEFAULT 0,
    bills_n       INTEGER NOT NULL DEFAULT 0,
    complete      BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_carry_recon_symbol ON dualperp_carry_recon(symbol, closed_at DESC);
