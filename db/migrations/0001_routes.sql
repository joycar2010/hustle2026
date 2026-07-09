-- 路由权威表:决策面输出「币 × 引擎 × 目标仓位」三元组的唯一真源。
-- 设计纪律(coin id=1/NULL魔法行教训):显式列全 NOT NULL(缺省空串而非 NULL)、
-- UNIQUE(symbol)=DB 层路由互斥(一币一行一引擎)、CHECK 白名单、乐观锁 version、全量审计。

CREATE TABLE route_assignments (
    id                   BIGSERIAL PRIMARY KEY,
    symbol               TEXT        NOT NULL,             -- 统一符号(BTCUSDT)
    engine               TEXT        NOT NULL,             -- 路由到哪个执行引擎
    venue_long           TEXT        NOT NULL DEFAULT '',  -- dualperp: 多腿所
    market_long          TEXT        NOT NULL DEFAULT '',
    venue_short          TEXT        NOT NULL DEFAULT '',  -- dualperp: 空腿所
    market_short         TEXT        NOT NULL DEFAULT '',
    target_notional_usdt NUMERIC(18,2) NOT NULL DEFAULT 0, -- 目标仓位(USDT 名义)
    state                TEXT        NOT NULL DEFAULT 'proposed',
    reason               TEXT        NOT NULL DEFAULT '',  -- 顾问/人工给出的依据(审计用)
    version              INTEGER     NOT NULL DEFAULT 1,   -- 乐观锁
    updated_by           TEXT        NOT NULL DEFAULT 'manual',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_route_symbol UNIQUE (symbol),
    CONSTRAINT ck_route_engine CHECK (engine IN ('coin', 'dualperp', 'basis', 'none')),
    CONSTRAINT ck_route_state  CHECK (state  IN ('proposed', 'active', 'draining', 'off'))
);

-- 字段级审计:每次写入留 old/new 全量快照(rules_save 审计 diff 模式)
CREATE TABLE route_audit (
    id         BIGSERIAL PRIMARY KEY,
    symbol     TEXT        NOT NULL,
    actor      TEXT        NOT NULL,
    old_row    JSONB,
    new_row    JSONB,
    note       TEXT        NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_route_audit_symbol ON route_audit (symbol, created_at DESC);
