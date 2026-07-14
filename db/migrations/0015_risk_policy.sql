-- 0015: G0 风险策略权威(V5 补充说明 ADR-001)——15万U 入金前置保命闸。
-- risk-ledger 是唯一计算/发布者(risk plane 权威归属 C 控制面);发布 dcm:risk:policy 供 opener/manager 消费。
-- G0 用版本号(policy_version 单调自增),G1 再升 outbox + policy_epoch/sequence fencing。

-- 逐 venue/account 硬敞口上限种子(操作员配置的 Tier 上限)。scope_key='venue:binance' 或 'account:joycar0014'。
CREATE TABLE IF NOT EXISTS risk_venue_cap (
    scope_key        TEXT PRIMARY KEY,           -- venue:<name> | account:<key>
    tier             TEXT NOT NULL DEFAULT 'B',  -- A/B/C/Restricted(仅记录,上限以下列为准)
    max_notional_usdt NUMERIC NOT NULL,          -- 该 scope 允许的最大在场名义(硬上限)
    warn_ratio       NUMERIC NOT NULL DEFAULT 0.85, -- 达上限×此比例 → WATCH
    enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    note             TEXT,
    updated_by       TEXT,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 操作员手动风险模式覆盖(append-only,仿 admin_audit;最新一条 per scope 生效)。
-- risk-ledger 合并:有效模式 = max_strictness(自动敞口判定, 最新未过期 override)。
CREATE TABLE IF NOT EXISTS risk_policy_override (
    id           BIGSERIAL PRIMARY KEY,
    scope_type   TEXT NOT NULL,     -- VENUE | ACCOUNT | GLOBAL | SYMBOL
    scope_key    TEXT NOT NULL,     -- venue名 / 账户key / 'GLOBAL' / symbol
    mode         TEXT NOT NULL,     -- NORMAL | WATCH | NO_NEW_RISK | REDUCE_ONLY | EXIT_ONLY
    reason       TEXT,
    expires_at   TIMESTAMPTZ,       -- NULL=不过期(须显式 NORMAL 解除)
    created_by   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_risk_override_scope ON risk_policy_override(scope_type, scope_key, id DESC);

-- 原始账户限制/错误事实(V5 §6.3;G0 落原始码,判定在 risk-ledger)。
CREATE TABLE IF NOT EXISTS restriction_event (
    id           BIGSERIAL PRIMARY KEY,
    venue        TEXT NOT NULL,
    account_key  TEXT,
    scope        TEXT NOT NULL DEFAULT 'ACCOUNT',  -- VENUE|ACCOUNT|CREDENTIAL|ASSET_NETWORK
    signal_type  TEXT NOT NULL,                    -- AUTH_ERROR|PERMISSION_DENIED|RISK_CONTROL|KYC|ORDER_REJECT|WITHDRAWAL_DELAY|...
    source_type  TEXT NOT NULL DEFAULT 'PRIVATE_API', -- OFFICIAL|PRIVATE_API|ACCOUNT_FACT|SUPPORT|COMMUNITY
    severity     TEXT NOT NULL DEFAULT 'MEDIUM',   -- HARD|MEDIUM|SOFT|TRANSPORT
    raw_code     TEXT,
    http_status  INT,
    endpoint     TEXT,
    raw_payload  TEXT,
    dedupe_key   TEXT,
    first_seen   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen    TIMESTAMPTZ NOT NULL DEFAULT now(),
    hit_count    INT NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_restriction_dedupe ON restriction_event(dedupe_key) WHERE dedupe_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_restriction_venue_seen ON restriction_event(venue, last_seen DESC);

-- 提现事实与基线(V5 §6.4;G0 占位,采集在 transfer-monitor)。
CREATE TABLE IF NOT EXISTS withdrawal_observation (
    id           BIGSERIAL PRIMARY KEY,
    venue        TEXT NOT NULL,
    account_key  TEXT,
    asset        TEXT,
    network      TEXT,
    amount       NUMERIC,
    initiated_at TIMESTAMPTZ,
    confirmed_at TIMESTAMPTZ,
    duration_sec NUMERIC,
    status       TEXT,             -- PENDING|CONFIRMED|FAILED
    venue_tx_id  TEXT,
    chain_tx     TEXT,
    recorded_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_withdrawal_venue ON withdrawal_observation(venue, recorded_at DESC);

-- 策略版本单调计数(G0 fencing 雏形;消费者只接受更高版本,防旧快照复活)。
CREATE TABLE IF NOT EXISTS risk_policy_version (
    id            INT PRIMARY KEY DEFAULT 1,
    policy_version BIGINT NOT NULL DEFAULT 0,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT risk_policy_version_singleton CHECK (id = 1)
);
INSERT INTO risk_policy_version(id, policy_version) VALUES (1, 0) ON CONFLICT (id) DO NOTHING;

-- mix_ro(mix-backend 读聚合角色)追加写面:仅 override/restriction/withdrawal 三表 INSERT + cap 表读写
-- (DB 强制边界,仿 admin_audit;mix 不获得引擎表写权限)。
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mix_ro') THEN
        GRANT SELECT ON risk_venue_cap, risk_policy_override, restriction_event,
              withdrawal_observation, risk_policy_version TO mix_ro;
        GRANT INSERT ON risk_policy_override, restriction_event, withdrawal_observation TO mix_ro;
        GRANT UPDATE, INSERT ON risk_venue_cap TO mix_ro;
        GRANT USAGE, SELECT ON SEQUENCE risk_policy_override_id_seq, restriction_event_id_seq,
              withdrawal_observation_id_seq TO mix_ro;
    END IF;
END $$;
