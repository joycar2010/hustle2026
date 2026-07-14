-- 0017: G2 RiskRepair 修复意图(shadow 骨架)——受限 venue 的仓位撤离作为持久化意图管理。
-- 生产者=exec-repair(B 机,shadow 只提案绝不下单);执行路径(armed 后)=把 plan.patch 并入
-- dcm:exec:manager:config → manager close_pair → exec_core.SagaExecutor → MultiVenue(复用六所 place)。
-- 生命周期:PROPOSED →(策略恢复)CANCELLED /(TTL 到期)EXPIRED /(armed 采纳)EXECUTED。
CREATE TABLE IF NOT EXISTS risk_repair_intent (
    id             BIGSERIAL PRIMARY KEY,
    intent_id      TEXT NOT NULL UNIQUE,
    kind           TEXT NOT NULL DEFAULT 'EVACUATE_PAIR'
                   CHECK (kind IN ('EVACUATE_PAIR', 'REDUCE_VENUE')),
    venue          TEXT NOT NULL,                -- 触发撤离的受限 venue
    pair_id        TEXT NOT NULL DEFAULT '',
    symbol         TEXT NOT NULL DEFAULT '',
    state          TEXT NOT NULL DEFAULT 'PROPOSED'
                   CHECK (state IN ('PROPOSED', 'CANCELLED', 'EXPIRED', 'EXECUTED')),
    mode           TEXT NOT NULL DEFAULT 'shadow' CHECK (mode IN ('shadow', 'armed')),
    feasible       BOOLEAN,                      -- 预检结论(NULL=未评估)
    plan           JSONB NOT NULL DEFAULT '{}'::jsonb,      -- manager config patch + 腿描述
    feasibility    JSONB NOT NULL DEFAULT '{}'::jsonb,      -- 逐项预检明细
    reason         TEXT NOT NULL DEFAULT '',     -- 触发原因(策略模式+reason)
    close_reason   TEXT NOT NULL DEFAULT '',     -- 终态原因(policy_recovered/ttl/…)
    policy_epoch   BIGINT NOT NULL DEFAULT 0,
    policy_version BIGINT NOT NULL DEFAULT 0,
    est_notional_usdt NUMERIC NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_repair_intent_active ON risk_repair_intent(venue, pair_id)
    WHERE state = 'PROPOSED';
CREATE INDEX IF NOT EXISTS idx_repair_intent_seen ON risk_repair_intent(updated_at DESC);

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mix_ro') THEN
        GRANT SELECT ON risk_repair_intent TO mix_ro;
    END IF;
END $$;
