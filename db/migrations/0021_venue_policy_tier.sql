-- 0021: 批次5——VenuePolicyRegistry(V5 §6.1)+ Tier 分级播种(§8.3)。
-- 条款登记为人工盘点承载体:PROHIBITED→FROZEN 硬闸;UNCLEAR→WATCH(当前资金≈HOUSE_RND,
-- 按补充说明 §3.1 只提示不掐;进 CORE_POOL/SMA 前须复核为 ALLOWED)。复核到期计入未复核数。
CREATE TABLE IF NOT EXISTS venue_policy (
    venue                TEXT PRIMARY KEY,
    policy_version       TEXT NOT NULL DEFAULT '',
    automation_status    TEXT NOT NULL DEFAULT 'UNCLEAR',
    arbitrage_status     TEXT NOT NULL DEFAULT 'UNCLEAR'
                         CHECK (arbitrage_status IN ('ALLOWED', 'UNCLEAR', 'PROHIBITED')),
    subaccount_status    TEXT NOT NULL DEFAULT 'UNCLEAR',
    withdrawal_rules     TEXT NOT NULL DEFAULT '',
    api_permission_model TEXT NOT NULL DEFAULT '',
    restricted_products  TEXT NOT NULL DEFAULT '',
    review_owner         TEXT NOT NULL DEFAULT '',
    reviewed_at          TIMESTAMPTZ,
    next_review_at       TIMESTAMPTZ,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS venue_policy_artifact (
    id             BIGSERIAL PRIMARY KEY,
    venue          TEXT NOT NULL,
    kind           TEXT NOT NULL DEFAULT 'TERMS',   -- TERMS|AM_CONFIRMATION|SUPPORT_TICKET|ANNOUNCEMENT
    title          TEXT NOT NULL DEFAULT '',
    url_or_ref     TEXT NOT NULL DEFAULT '',
    content_sha256 TEXT NOT NULL DEFAULT '',
    note           TEXT NOT NULL DEFAULT '',
    recorded_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_policy_artifact_venue ON venue_policy_artifact(venue, recorded_at DESC);

-- 六所播种:全部 UNCLEAR + 14 天复核期(人工盘点起点;客户经理口头说明不算 artifact)
INSERT INTO venue_policy(venue, next_review_at) VALUES
    ('binance', now() + interval '14 days'),
    ('bybit',   now() + interval '14 days'),
    ('okx',     now() + interval '14 days'),
    ('gate',    now() + interval '14 days'),
    ('bitget',  now() + interval '14 days'),
    ('hyperliquid', now() + interval '14 days')
ON CONFLICT (venue) DO NOTHING;

-- Tier 分级初始上限落 risk_venue_cap(V5 §8.3;金额=初始工程门槛,当前敞口≈5U 零行为变化)
INSERT INTO risk_venue_cap(scope_key, tier, max_notional_usdt, warn_ratio, note) VALUES
    ('venue:binance', 'B', 200, 0.85, 'V5§8.3 TierB 初始(主流所,提现已验证)'),
    ('venue:bybit',   'B', 200, 0.85, 'V5§8.3 TierB 初始'),
    ('venue:okx',     'B', 200, 0.85, 'V5§8.3 TierB 初始'),
    ('venue:gate',    'B', 150, 0.85, 'V5§8.3 TierB 初始(中型所保守)'),
    ('venue:bitget',  'B', 150, 0.85, 'V5§8.3 TierB 初始(中型所保守)'),
    ('venue:hyperliquid', 'C', 100, 0.85, 'V5§8.3 TierC 初始(新接入历史不足)')
ON CONFLICT (scope_key) DO NOTHING;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mix_ro') THEN
        GRANT SELECT ON venue_policy, venue_policy_artifact TO mix_ro;
        GRANT INSERT, UPDATE ON venue_policy, venue_policy_artifact TO mix_ro;
        GRANT USAGE, SELECT ON SEQUENCE venue_policy_artifact_id_seq TO mix_ro;
    END IF;
END $$;
