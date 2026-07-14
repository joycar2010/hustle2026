-- 0018: 批次1 事实闭环+去噪骨架(V5 §17/ADR-008)。
-- ①venue_incident 有状态 Incident:同 (venue,account,rule) 聚合一行,只在 发生/升级/恢复/超时 通知;
--   CLOSED 后复发=新行(历史不覆盖)。②withdrawal_baseline 滚动基线(Redis 快照重启即失,PG 保基线)。
-- ③venue_mode_transition 模式历史(before/after/reason/版本,恢复审计的地基)。
CREATE TABLE IF NOT EXISTS venue_incident (
    id            BIGSERIAL PRIMARY KEY,
    incident_key  TEXT NOT NULL,               -- venue:account:rule
    venue         TEXT NOT NULL,
    account_key   TEXT NOT NULL DEFAULT '',
    rule          TEXT NOT NULL,
    state         TEXT NOT NULL DEFAULT 'OPEN'
                  CHECK (state IN ('OPEN', 'ESCALATED', 'RECOVERING', 'CLOSED')),
    severity      TEXT NOT NULL DEFAULT 'warn',
    title         TEXT NOT NULL DEFAULT '',
    detail        TEXT NOT NULL DEFAULT '',
    hit_count     INT NOT NULL DEFAULT 1,
    first_seen    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen     TIMESTAMPTZ NOT NULL DEFAULT now(),
    escalated_at  TIMESTAMPTZ,
    recovering_at TIMESTAMPTZ,
    closed_at     TIMESTAMPTZ,
    last_notified_at TIMESTAMPTZ
);
-- 活跃 incident 每 key 至多一行;CLOSED 不占位
CREATE UNIQUE INDEX IF NOT EXISTS idx_incident_active ON venue_incident(incident_key)
    WHERE state != 'CLOSED';
CREATE INDEX IF NOT EXISTS idx_incident_seen ON venue_incident(last_seen DESC);

CREATE TABLE IF NOT EXISTS withdrawal_baseline (
    id            BIGSERIAL PRIMARY KEY,
    venue         TEXT NOT NULL,
    window_note   TEXT NOT NULL DEFAULT '',    -- 该所历史窗口说明(binance~90d/bitget=30d/gate~7d…)
    p50_sec       NUMERIC,
    p95_sec       NUMERIC,
    sample_n      INT NOT NULL DEFAULT 0,
    pending_count INT NOT NULL DEFAULT 0,
    oldest_pending_age_sec NUMERIC NOT NULL DEFAULT 0,
    recent_failures INT NOT NULL DEFAULT 0,
    computed_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_wd_baseline_venue ON withdrawal_baseline(venue, computed_at DESC);

-- withdrawal_observation(0015 已建)补逐笔幂等索引:venue+流水号 upsert
CREATE UNIQUE INDEX IF NOT EXISTS idx_wd_obs_venue_tx ON withdrawal_observation(venue, venue_tx_id)
    WHERE venue_tx_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS venue_mode_transition (
    id             BIGSERIAL PRIMARY KEY,
    scope_type     TEXT NOT NULL DEFAULT 'VENUE',
    scope_key      TEXT NOT NULL,
    before_mode    TEXT NOT NULL,
    after_mode     TEXT NOT NULL,
    reason         TEXT NOT NULL DEFAULT '',
    policy_epoch   BIGINT NOT NULL DEFAULT 0,
    policy_version BIGINT NOT NULL DEFAULT 0,
    recorded_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_mode_transition ON venue_mode_transition(scope_key, recorded_at DESC);

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mix_ro') THEN
        GRANT SELECT ON venue_incident, withdrawal_baseline, venue_mode_transition TO mix_ro;
    END IF;
END $$;
