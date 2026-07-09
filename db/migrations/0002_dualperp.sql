-- 双合约配对引擎:配对仓位账本 + shadow 决策日志。
-- 组合键纪律:所有腿字段显式 (venue, market, account),不做任何单对/单所假设(testgo 三次爆雷)。

CREATE TABLE dualperp_positions (
    id             BIGSERIAL PRIMARY KEY,
    symbol         TEXT NOT NULL,                      -- 统一符号
    venue_long     TEXT NOT NULL,
    market_long    TEXT NOT NULL,
    venue_short    TEXT NOT NULL,
    market_short   TEXT NOT NULL,
    account_long   TEXT NOT NULL DEFAULT '',           -- 子账户标识(限频/资金预算归属)
    account_short  TEXT NOT NULL DEFAULT '',
    qty_base       NUMERIC(28,10) NOT NULL DEFAULT 0,
    notional_usdt  NUMERIC(18,2)  NOT NULL DEFAULT 0,
    state          TEXT NOT NULL DEFAULT 'OPENING',
    long_order_id  TEXT NOT NULL DEFAULT '',
    short_order_id TEXT NOT NULL DEFAULT '',
    open_gap_bps   NUMERIC(12,4),
    close_gap_bps  NUMERIC(12,4),
    error_message  TEXT NOT NULL DEFAULT '',
    opened_at      TIMESTAMPTZ,
    closed_at      TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_dp_state CHECK (state IN
        ('OPENING', 'OPEN', 'CLOSING', 'CLOSED', 'FAILED', 'ROLLBACK'))
);

-- 非终态部分索引:体外对账(GOLD_RECON 模式)按此扫
CREATE INDEX idx_dp_pos_active ON dualperp_positions (symbol)
    WHERE state NOT IN ('CLOSED', 'FAILED');

-- shadow 决策日志:真金前的战绩账(捕获率/入场分布评估的原始数据)
CREATE TABLE dualperp_shadow_log (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    symbol      TEXT NOT NULL,
    venue_long  TEXT NOT NULL DEFAULT '',
    venue_short TEXT NOT NULL DEFAULT '',
    gap_bps     NUMERIC(12,4),
    long_ask    NUMERIC(28,10),
    short_bid   NUMERIC(28,10),
    decision    TEXT NOT NULL,          -- would_open|would_hold|would_close|skip_stale|idle
    detail      JSONB
);

CREATE INDEX idx_dp_shadow_sym_ts ON dualperp_shadow_log (symbol, ts DESC);
