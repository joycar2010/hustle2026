-- MIX M6 账本正式化 Schema (2026-07-18)
-- 目标:基于当前749U余额建立Units份额制、FINALIZED NAV、InvestorProjection幂等重建。
-- 铁律:①份额制=Units不可篡改的数字承诺;②NAV快照=时点闭合;③HOUSE账户=系统自有资金(不分配客户)。

-- §1 client_party(客户主体,一户一主体或多户一主体)
CREATE TABLE IF NOT EXISTS client_party (
    client_id BIGSERIAL PRIMARY KEY,
    client_type TEXT NOT NULL CHECK (client_type IN ('INDIVIDUAL','INSTITUTION','HOUSE')),
    display_name TEXT NOT NULL,
    kyc_level TEXT DEFAULT 'NONE' CHECK (kyc_level IN ('NONE','BASIC','FULL')),
    status TEXT DEFAULT 'active' CHECK (status IN ('active','suspended','closed')),
    note TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cp_type ON client_party(client_type);
COMMENT ON TABLE client_party IS 'M6客户主体:一户一主体或多户一主体,与share_account 1:N';

-- §2 share_account(份额账户,Units持有容器)
CREATE TABLE IF NOT EXISTS share_account (
    investor_id BIGSERIAL PRIMARY KEY,
    client_id BIGINT NOT NULL REFERENCES client_party(client_id),
    account_name TEXT NOT NULL UNIQUE,
    account_type TEXT NOT NULL CHECK (account_type IN ('HOUSE','SMA','CORE_POOL','UNALLOCATED')),
    total_units NUMERIC(24,8) NOT NULL DEFAULT 0 CHECK (total_units >= 0),
    total_equity_usdt NUMERIC(18,2),
    last_nav_at TIMESTAMPTZ,
    status TEXT DEFAULT 'active' CHECK (status IN ('active','frozen','closed')),
    note TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sa_client ON share_account(client_id);
CREATE INDEX IF NOT EXISTS idx_sa_type ON share_account(account_type);
COMMENT ON TABLE share_account IS 'M6份额账户:Units持有容器,不直接持有USDT/BTC,只记录份额';

-- §3 nav_snapshot(NAV快照,时点闭合)
CREATE TABLE IF NOT EXISTS nav_snapshot (
    snapshot_id TEXT PRIMARY KEY,
    snapshot_type TEXT NOT NULL CHECK (snapshot_type IN ('FINALIZED','DRAFT','RECONCILING')),
    as_of TIMESTAMPTZ NOT NULL,
    total_equity_usdt NUMERIC(18,2) NOT NULL,
    total_units NUMERIC(24,8) NOT NULL,
    nav_per_unit NUMERIC(18,8) NOT NULL,
    recon_status TEXT DEFAULT 'PENDING' CHECK (recon_status IN ('PENDING','MATCHED','UNMATCHED','ADJUSTED')),
    recon_delta_usdt NUMERIC(18,2),
    venue_equities JSONB, -- {binance:93.37, okx:75.1, ...}
    note TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_nav_type ON nav_snapshot(snapshot_type);
CREATE INDEX IF NOT EXISTS idx_nav_asof ON nav_snapshot(as_of DESC);
COMMENT ON TABLE nav_snapshot IS 'M6 NAV快照:时点闭合,FINALIZED不可变';

-- §4 migration_event(迁移事件,MIGRATION_OPENING等里程碑)
CREATE TABLE IF NOT EXISTS migration_event (
    event_id BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL CHECK (event_type IN ('MIGRATION_OPENING','NAV_FINALIZED','UNITS_ISSUED','UNITS_REDEEMED','RECON_ADJUSTED')),
    event_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    snapshot_id TEXT REFERENCES nav_snapshot(snapshot_id),
    affected_accounts JSONB, -- [investor_id, ...]
    delta_units NUMERIC(24,8),
    delta_equity_usdt NUMERIC(18,2),
    operator TEXT,
    note TEXT,
    audit_hash TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_mig_type ON migration_event(event_type);
CREATE INDEX IF NOT EXISTS idx_mig_at ON migration_event(event_at DESC);
COMMENT ON TABLE migration_event IS 'M6迁移事件:MIGRATION_OPENING等里程碑,不可篡改';

-- §5 portfolio_access_grant(授权:auth_subject → client → share_account)
CREATE TABLE IF NOT EXISTS portfolio_access_grant (
    grant_id BIGSERIAL PRIMARY KEY,
    auth_subject TEXT NOT NULL, -- uid from JWT
    client_id BIGINT NOT NULL REFERENCES client_party(client_id),
    role TEXT DEFAULT 'viewer' CHECK (role IN ('viewer','trader','admin')),
    granted_by TEXT,
    granted_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    status TEXT DEFAULT 'active' CHECK (status IN ('active','revoked'))
);
CREATE INDEX IF NOT EXISTS idx_pag_subject ON portfolio_access_grant(auth_subject);
CREATE INDEX IF NOT EXISTS idx_pag_client ON portfolio_access_grant(client_id);
COMMENT ON TABLE portfolio_access_grant IS 'M6授权:auth_subject(JWT uid) → client → share_account路径';
