-- V4.0 Phase 0:投资份额账本(CORE_POOL 只读份额,append-only)
-- 方案 §12.1:不存可编辑 share_percent;份额比例 = investor units / total units 计算。
-- 部署: sudo -u postgres psql -d mix_main -f 0003_share_ledger.sql
-- 铁律:share_event 只增不改(修正走 reversal/adjustment);pool_nav_snapshot 日度 FINALIZED 不覆盖。

-- ① 份额账户:一个投资人一行,关联登录用户
CREATE TABLE IF NOT EXISTS share_account (
    investor_id   BIGSERIAL PRIMARY KEY,
    login_user_id BIGINT REFERENCES mix_users(id) ON DELETE SET NULL,  -- 门户登录身份
    display_name  TEXT NOT NULL DEFAULT '',
    is_house      BOOLEAN NOT NULL DEFAULT FALSE,   -- HOUSE 资金也在池内则建普通份额账户,不藏系统外(§12.2)
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','frozen','closed')),
    note          TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ② 份额流水:append-only,任何份额变化都在这里留痕(§12.3)
--    Units 正=发行/转入,负=赎回/转出;每条关联外部资金流 + 定价所用的 FINALIZED NAV
CREATE TABLE IF NOT EXISTS share_event (
    id               BIGSERIAL PRIMARY KEY,
    investor_id      BIGINT NOT NULL REFERENCES share_account(investor_id),
    event_type       TEXT NOT NULL CHECK (event_type IN ('ISSUE','REDEEM','TRANSFER','ADJUST')),
    units            NUMERIC(30,10) NOT NULL,           -- 带符号:发行+ / 赎回-
    effective_nav_id BIGINT,                            -- 定价用的 pool_nav_snapshot.id(FINALIZED)
    external_flow_id TEXT NOT NULL DEFAULT '',          -- 关联入金/出金真实流水(venue_tx_id 等)
    idempotency_key  TEXT UNIQUE,                        -- 防重放:同一资金流只发一次份额
    reverses_id      BIGINT REFERENCES share_event(id), -- 修正=指向被冲销的原事件(不删不改)
    approved_by      TEXT NOT NULL DEFAULT '',
    approved_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    note             TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_share_event_investor ON share_event(investor_id, approved_at DESC);

-- ③ 组合净值快照:池级 NAV + 总 Units,日度 FINALIZED 不覆盖(§11.2 NAV 状态机)
CREATE TABLE IF NOT EXISTS pool_nav_snapshot (
    id           BIGSERIAL PRIMARY KEY,
    nav_status   TEXT NOT NULL CHECK (nav_status IN ('ESTIMATED','CALCULATED','RECONCILED','FINALIZED','PUBLISHED')),
    pool_nav     NUMERIC(30,8) NOT NULL,     -- CORE_POOL 组合净值(USDT)
    total_units  NUMERIC(30,10) NOT NULL,    -- 当时总发行 Units
    nav_per_unit NUMERIC(30,10) NOT NULL,    -- = pool_nav / total_units(total=0 时首日种 1.0)
    net_flow     NUMERIC(30,8) NOT NULL DEFAULT 0,  -- 该区间净外部资金流(算 Pool Return 用)
    as_of        TIMESTAMPTZ NOT NULL,
    source       TEXT NOT NULL DEFAULT '',   -- 来源说明(ledger/recon 版本)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pool_nav_asof ON pool_nav_snapshot(as_of DESC);
CREATE INDEX IF NOT EXISTS idx_pool_nav_final ON pool_nav_snapshot(nav_status, as_of DESC);

-- ④ 投资者投影:由 FINALIZED NAV + 份额派生的展示层(只读,可重算,不是权威)
CREATE TABLE IF NOT EXISTS investor_projection (
    id              BIGSERIAL PRIMARY KEY,
    investor_id     BIGINT NOT NULL REFERENCES share_account(investor_id),
    nav_id          BIGINT NOT NULL REFERENCES pool_nav_snapshot(id),
    units           NUMERIC(30,10) NOT NULL,
    nav_per_unit    NUMERIC(30,10) NOT NULL,
    investor_equity NUMERIC(30,8) NOT NULL,      -- = units × nav_per_unit
    pool_return_pct NUMERIC(18,8),               -- 全员相同的组合收益率
    as_of           TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (investor_id, nav_id)
);
CREATE INDEX IF NOT EXISTS idx_investor_proj ON investor_projection(investor_id, as_of DESC);

-- ⑤ 投资者审计事件(登录/查看/导出留痕,§12.4 MFA 要求)
CREATE TABLE IF NOT EXISTS investor_audit_event (
    id          BIGSERIAL PRIMARY KEY,
    investor_id BIGINT REFERENCES share_account(investor_id),
    action      TEXT NOT NULL,               -- login | view | export | mfa_challenge
    detail      TEXT NOT NULL DEFAULT '',
    ip          TEXT NOT NULL DEFAULT '',
    ts          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_investor_audit ON investor_audit_event(investor_id, ts DESC);

GRANT SELECT, INSERT, UPDATE ON share_account TO mix_app;
GRANT SELECT, INSERT ON share_event TO mix_app;             -- append-only:不给 UPDATE/DELETE
GRANT SELECT, INSERT ON pool_nav_snapshot TO mix_app;       -- 快照不改
GRANT SELECT, INSERT, DELETE ON investor_projection TO mix_app;  -- 投影可重算(删旧重生)
GRANT SELECT, INSERT ON investor_audit_event TO mix_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO mix_app;
