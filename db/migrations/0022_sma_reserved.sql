-- 0022: 批次5——SMA P2 预留(补充说明 §3.3:只建 schema+flag,不生产化)。
-- 生产启动门槛(§3.4 六条:真实 mandate/托管就绪/客户要求/收入3×成本/演练预算/P0稳定30天)
-- 全满足前 SMA_EXECUTION_ENABLED 保持 false;Client Guard 不维护生产实例。
CREATE TABLE IF NOT EXISTS managed_account (
    client_id    TEXT PRIMARY KEY,
    display_name TEXT NOT NULL DEFAULT '',
    custody_mode TEXT NOT NULL DEFAULT 'CLIENT_OWNED_GUARD'
                 CHECK (custody_mode IN ('CLIENT_OWNED_GUARD', 'B_TRADE_ONLY_KMS', 'THIRD_PARTY_MPC')),
    status       TEXT NOT NULL DEFAULT 'RESERVED'
                 CHECK (status IN ('RESERVED', 'ONBOARDING', 'ACTIVE', 'PAUSED', 'CLOSED')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS strategy_mandate (
    id               BIGSERIAL PRIMARY KEY,
    client_id        TEXT NOT NULL REFERENCES managed_account(client_id),
    mandate_version  INT NOT NULL DEFAULT 1,
    allowed_products TEXT NOT NULL DEFAULT '',
    max_equity_usdt  NUMERIC NOT NULL DEFAULT 0,
    max_notional_usdt NUMERIC NOT NULL DEFAULT 0,
    signed_artifact  TEXT NOT NULL DEFAULT '',    -- 客户签署件引用(不可变存储)
    signed_at        TIMESTAMPTZ,
    expires_at       TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (client_id, mandate_version)
);

CREATE TABLE IF NOT EXISTS client_venue_approval (
    id                BIGSERIAL PRIMARY KEY,
    client_id         TEXT NOT NULL REFERENCES managed_account(client_id),
    venue             TEXT NOT NULL,
    account_key       TEXT NOT NULL DEFAULT '',
    custody_eligible  BOOLEAN NOT NULL DEFAULT FALSE,
    allowed_products  TEXT NOT NULL DEFAULT '',
    maximum_equity    NUMERIC NOT NULL DEFAULT 0,
    maximum_notional  NUMERIC NOT NULL DEFAULT 0,
    risk_tier         TEXT NOT NULL DEFAULT 'C',
    mandate_version   INT NOT NULL DEFAULT 1,
    approved_at       TIMESTAMPTZ,
    expires_at        TIMESTAMPTZ,
    UNIQUE (client_id, venue, account_key)
);

CREATE TABLE IF NOT EXISTS account_intent (
    id              BIGSERIAL PRIMARY KEY,
    intent_id       TEXT NOT NULL UNIQUE,
    client_id       TEXT NOT NULL,
    venue           TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL DEFAULT '',
    qty             NUMERIC NOT NULL DEFAULT 0,
    limit_px        NUMERIC,
    intent_type     TEXT NOT NULL DEFAULT 'OPEN',
    policy_epoch    BIGINT NOT NULL DEFAULT 0,
    policy_version  BIGINT NOT NULL DEFAULT 0,
    mandate_version INT NOT NULL DEFAULT 0,
    state           TEXT NOT NULL DEFAULT 'DRAFT',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ
);

-- 硬 flag:SMA 执行默认关(engine_config 热配置,开启须走 §3.4 门槛+审计)
INSERT INTO engine_config(engine, ckey, cval, updated_by)
VALUES ('sma', 'execution_enabled', 'false', 'v5-migration-0022')
ON CONFLICT (engine, ckey) DO NOTHING;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mix_ro') THEN
        GRANT SELECT ON managed_account, strategy_mandate, client_venue_approval, account_intent TO mix_ro;
    END IF;
END $$;
