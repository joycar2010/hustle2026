-- 0020: 批次3+4——三闸收编 shadow 对比(ADR-002 阶段A)+ RECOVERY_WATCH 恢复阶梯(V5 §7.3)。
-- gate_shadow_diff:旧闸(engine_config armed 阶段/kill/manager pair 武装)vs 新聚合器(policy CAN_OPEN)
-- 的判定差异流水——连续 7 天零"危险放宽"才进阶段C(old AND new)。只记录不影响行为。
CREATE TABLE IF NOT EXISTS gate_shadow_diff (
    id          BIGSERIAL PRIMARY KEY,
    venue       TEXT NOT NULL,
    old_allow   BOOLEAN NOT NULL,
    new_allow   BOOLEAN NOT NULL,
    direction   TEXT NOT NULL CHECK (direction IN ('NEW_LOOSER', 'NEW_STRICTER')),
    inputs      JSONB NOT NULL DEFAULT '{}'::jsonb,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_gate_shadow_recent ON gate_shadow_diff(recorded_at DESC);

-- venue_recovery:REDUCE_ONLY+ 事件出清后的逐级恢复(10%→25%→50%→100% 额度阶梯,
-- 每级至少驻留一个结算周期且无新 Incident;操作员显式 override NORMAL=审计放行提前关闭)。
CREATE TABLE IF NOT EXISTS venue_recovery (
    venue           TEXT PRIMARY KEY,
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    stage           INT NOT NULL DEFAULT 0,      -- 0=10% 1=25% 2=50% 3=100%(完成)
    episode_mode    TEXT NOT NULL DEFAULT '',    -- 触发本次恢复期的最严模式
    entered_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_advance_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at       TIMESTAMPTZ
);

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mix_ro') THEN
        GRANT SELECT ON gate_shadow_diff, venue_recovery TO mix_ro;
    END IF;
END $$;
