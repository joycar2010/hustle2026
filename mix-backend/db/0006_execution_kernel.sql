-- V4.0 Phase1 统一执行内核数据模型(方案 §6)—— 契约与事实先行,SHADOW,不发真单。
-- 铁律(§5.3):Intent/风险预留/Saga/成交/账单/审计一律 PostgreSQL 持久化;Redis 清空后可从此恢复。
-- 武装执行(B adapter 真下单)在此契约稳定 + 过混沌测试后另行门控,本迁移不含执行器。
-- 部署: sudo -u postgres psql -d mix_main -f 0006_execution_kernel.sql

-- ① 资源所有权:owner_key = portfolio:book:canonical_underlying:settlement_bucket
--    leg_lock = venue:account:canonical_instrument:position_mode(每腿一把锁)
--    取代 decision UNIQUE(symbol) 的弱锁:不同结算币/到期/账户共享 symbol 由 owner/leg 精确表达
CREATE TABLE IF NOT EXISTS resource_ownership (
    owner_key    TEXT PRIMARY KEY,           -- portfolio:book:underlying:settlement_bucket
    portfolio    TEXT NOT NULL,              -- CORE_POOL | HOUSE_RND | SMA:<id>
    book         TEXT NOT NULL,              -- CORE_POOL | HOUSE_RND
    canonical_underlying TEXT NOT NULL,
    settlement_bucket TEXT NOT NULL DEFAULT '',  -- perp | 2026Q3 | 2026Q4 ...(结算桶)
    product_id   TEXT NOT NULL DEFAULT '',   -- 关联 product_catalog
    generation   INT NOT NULL DEFAULT 1,     -- 所有权切换 +1;B 下单前校验 generation
    status       TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','releasing','released')),
    leg_locks    JSONB NOT NULL DEFAULT '[]',  -- [{venue,account,canonical_instrument,position_mode}]
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ② 风险预留:开仓前锁定风险预算(集中度/压力资本/venue 水位),可否决可减险
CREATE TABLE IF NOT EXISTS risk_reservation (
    id           BIGSERIAL PRIMARY KEY,
    owner_key    TEXT NOT NULL,
    reserved_notional_usdt NUMERIC(20,4) NOT NULL DEFAULT 0,
    stress_capital_usdt    NUMERIC(20,4) NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'held' CHECK (status IN ('held','consumed','released')),
    detail       JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_riskres_owner ON risk_reservation(owner_key, status);

-- ③ 目标状态意图:决策面输出「币×引擎×目标仓位」+ owner + TTL + generation
CREATE TABLE IF NOT EXISTS position_intent (
    intent_id    BIGSERIAL PRIMARY KEY,
    owner_key    TEXT NOT NULL,
    product_id   TEXT NOT NULL DEFAULT '',
    generation   INT NOT NULL DEFAULT 1,
    template     TEXT NOT NULL,             -- SPOT_LONG_DERIVATIVE_SHORT | DERIVATIVE_LONG_DERIVATIVE_SHORT | BORROW_SPOT_SHORT_DERIVATIVE_LONG
    legs         JSONB NOT NULL,            -- [{venue,instrument_id,side,target_notional_usdt}]
    target_state TEXT NOT NULL,            -- open | close | flat
    mode         TEXT NOT NULL DEFAULT 'shadow' CHECK (mode IN ('shadow','armed')),
    risk_reservation_id BIGINT REFERENCES risk_reservation(id),
    ttl_at       TIMESTAMPTZ NOT NULL,      -- 超时作废(行情/报价过旧不执行)
    status       TEXT NOT NULL DEFAULT 'proposed'
                 CHECK (status IN ('proposed','reserved','dispatched','acked','done','expired','rejected')),
    created_by   TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_intent_owner ON position_intent(owner_key, status);
CREATE INDEX IF NOT EXISTS idx_intent_status ON position_intent(status, ttl_at);

-- ④ 决策出箱 / 执行入箱(PG outbox 模式:决策面写 outbox,执行面消费;事实经 inbox 回流)
CREATE TABLE IF NOT EXISTS decision_outbox (
    id           BIGSERIAL PRIMARY KEY,
    intent_id    BIGINT NOT NULL REFERENCES position_intent(intent_id),
    payload      JSONB NOT NULL,
    dispatched   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_outbox_pending ON decision_outbox(dispatched, id) WHERE dispatched = FALSE;

CREATE TABLE IF NOT EXISTS execution_inbox (
    id           BIGSERIAL PRIMARY KEY,
    event_id     TEXT UNIQUE,               -- 交易所事件去重键
    intent_id    BIGINT,
    payload      JSONB NOT NULL,
    processed    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ⑤ 配对 Saga:双腿状态机(§6.4)。异常态首要——单腿/ADL/venue 停摆/结算待定/隔离
CREATE TABLE IF NOT EXISTS pair_saga (
    saga_id      BIGSERIAL PRIMARY KEY,
    intent_id    BIGINT NOT NULL REFERENCES position_intent(intent_id),
    owner_key    TEXT NOT NULL,
    state        TEXT NOT NULL DEFAULT 'PROPOSED'
                 CHECK (state IN ('PROPOSED','RESERVED','OPENING','HEDGING','OPEN','CLOSING','CLOSED',
                                  'ORDER_UNKNOWN','LEG_IMBALANCE','ADL_RECOVERY','VENUE_DEGRADED',
                                  'SETTLEMENT_PENDING','QUARANTINED')),
    leg_states   JSONB NOT NULL DEFAULT '{}',  -- {leg_idx: SENT|ACK|PARTIAL|CANCEL_PENDING|FILLED|UNKNOWN}
    mode         TEXT NOT NULL DEFAULT 'shadow',
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_saga_state ON pair_saga(state, updated_at);

-- ⑥ 订单事件(每腿):确定性 clientOrderId,ACK 丢失先查询再重试
CREATE TABLE IF NOT EXISTS order_event (
    id             BIGSERIAL PRIMARY KEY,
    saga_id        BIGINT REFERENCES pair_saga(saga_id),
    leg_idx        INT NOT NULL,
    venue          TEXT NOT NULL,
    instrument_id  TEXT NOT NULL,
    client_order_id TEXT NOT NULL,          -- 确定性,重试幂等
    venue_order_id TEXT NOT NULL DEFAULT '',
    leg_state      TEXT NOT NULL,           -- SENT|ACK|PARTIAL|CANCEL_PENDING|FILLED|UNKNOWN
    filled_qty     NUMERIC(30,10) NOT NULL DEFAULT 0,
    detail         JSONB,
    ts             TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_orderevent_saga ON order_event(saga_id, leg_idx);
CREATE UNIQUE INDEX IF NOT EXISTS uq_orderevent_coid ON order_event(client_order_id);

GRANT SELECT, INSERT, UPDATE ON resource_ownership TO mix_app;
GRANT SELECT, INSERT, UPDATE ON risk_reservation TO mix_app;
GRANT SELECT, INSERT, UPDATE ON position_intent TO mix_app;
GRANT SELECT, INSERT, UPDATE ON decision_outbox TO mix_app;
GRANT SELECT, INSERT, UPDATE ON execution_inbox TO mix_app;
GRANT SELECT, INSERT, UPDATE ON pair_saga TO mix_app;
GRANT SELECT, INSERT, UPDATE ON order_event TO mix_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO mix_app;
