-- S4 借贷利率套利真金仓位账(engine-lending armed)。
-- 结构=借币(全仓杠杆)→杠杆卖出→永续多头对冲;收益=(-资金费,负费率时为正)-借币成本。
-- 状态机与 dualperp/basis 同族:OPENING 预占(组合闸并发竞态课)/非终态部分索引。
CREATE TABLE lending_positions (
    id            BIGSERIAL PRIMARY KEY,
    coin          TEXT NOT NULL,                 -- base 资产(如 T)
    symbol        TEXT NOT NULL,                 -- 交易符号(TUSDT)
    qty_base      NUMERIC NOT NULL DEFAULT 0,    -- 实际成交 base 量(两腿对称目标)
    borrow_qty    NUMERIC NOT NULL DEFAULT 0,    -- 实际借币量
    notional_usdt NUMERIC NOT NULL DEFAULT 0,
    net_daily_pct NUMERIC,                       -- 开仓时点带符号净差(-funding-borrow)
    state         TEXT NOT NULL DEFAULT 'OPENING'
                  CHECK (state IN ('OPENING','OPEN','CLOSING','CLOSED','FAILED','ROLLBACK')),
    error_message TEXT NOT NULL DEFAULT '',
    opened_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at     TIMESTAMPTZ,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_lending_pos_active ON lending_positions (coin)
    WHERE state NOT IN ('CLOSED','FAILED');
CREATE INDEX idx_lending_pos_ts ON lending_positions (opened_at DESC);
