-- 期现底仓引擎(basis)配对仓位账本:币安现货多 + 永续空(单所双腿)。
-- 与 dualperp_positions 同纪律:显式状态机 CHECK/非终态部分索引/审计字段齐全。

CREATE TABLE basis_positions (
    id             BIGSERIAL PRIMARY KEY,
    symbol         TEXT NOT NULL,                      -- 统一符号(现货与永续同名,如 SKLUSDT)
    base_asset     TEXT NOT NULL DEFAULT '',           -- 现货对账用(free 余额资产名)
    qty_base       NUMERIC(28,10) NOT NULL DEFAULT 0,
    notional_usdt  NUMERIC(18,2)  NOT NULL DEFAULT 0,
    state          TEXT NOT NULL DEFAULT 'OPENING',
    spot_order_id  TEXT NOT NULL DEFAULT '',
    perp_order_id  TEXT NOT NULL DEFAULT '',
    open_e_bps     NUMERIC(12,4),                      -- 开仓时净期望
    funding_daily  NUMERIC(12,6),                      -- 开仓时资金费日化%
    error_message  TEXT NOT NULL DEFAULT '',
    opened_at      TIMESTAMPTZ,
    closed_at      TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_basis_state CHECK (state IN
        ('OPENING', 'OPEN', 'CLOSING', 'CLOSED', 'FAILED', 'ROLLBACK'))
);

CREATE INDEX idx_basis_pos_active ON basis_positions (symbol)
    WHERE state NOT IN ('CLOSED', 'FAILED');
