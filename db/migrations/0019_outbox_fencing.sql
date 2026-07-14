-- 0019: 批次2 版本复活防线(ADR-005)。
-- ①effective_risk_policy:PG 权威全量快照(Redis 清空/C 重启窗口的耐久读路)。
-- ②risk_policy_outbox:同事务写 outbox,发布器投 Redis 后标 dispatched(耐久发布)。
-- ③credential_epoch:凭证代次——key 指纹变化=凭证轮换,自动 bump+Incident。
-- ④exec_saga.saga_version:状态变更单调递增(与 policy_epoch/owner gen 分离的第三类版本)。
CREATE TABLE IF NOT EXISTS effective_risk_policy (
    id             INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    policy_epoch   BIGINT NOT NULL,
    policy_version BIGINT NOT NULL,
    snapshot       JSONB NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS risk_policy_outbox (
    id             BIGSERIAL PRIMARY KEY,
    policy_epoch   BIGINT NOT NULL,
    policy_version BIGINT NOT NULL,
    snapshot       JSONB NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    dispatched_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_policy_outbox_undispatched ON risk_policy_outbox(id)
    WHERE dispatched_at IS NULL;

CREATE TABLE IF NOT EXISTS credential_epoch (
    venue           TEXT PRIMARY KEY,
    epoch           BIGINT NOT NULL DEFAULT 1,
    key_fingerprint TEXT NOT NULL DEFAULT '',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    note            TEXT NOT NULL DEFAULT ''
);

ALTER TABLE exec_saga ADD COLUMN IF NOT EXISTS saga_version BIGINT NOT NULL DEFAULT 0;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mix_ro') THEN
        GRANT SELECT ON effective_risk_policy, risk_policy_outbox, credential_epoch TO mix_ro;
    END IF;
END $$;
