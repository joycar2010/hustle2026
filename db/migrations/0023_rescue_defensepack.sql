-- 0023: 批次6——RiskRepair 救援腿 kind + executor fence(ADR-007)+ AccountDefensePack v0(V5 §6.8)。
ALTER TABLE risk_repair_intent DROP CONSTRAINT IF EXISTS risk_repair_intent_kind_check;
ALTER TABLE risk_repair_intent ADD CONSTRAINT risk_repair_intent_kind_check
    CHECK (kind IN ('EVACUATE_PAIR', 'REDUCE_VENUE', 'RESCUE_HEDGE'));
ALTER TABLE risk_repair_intent ADD COLUMN IF NOT EXISTS executor_fence TEXT NOT NULL DEFAULT '';

-- 证据包:venue 限制事件的可验证记录汇总(策略快照/Incident/限制事件/模式历史/提现事实/修复意图)。
-- 只提供可验证记录,不宣称绝对证明;人工修正=新行,不覆盖。
CREATE TABLE IF NOT EXISTS account_defense_pack (
    id           BIGSERIAL PRIMARY KEY,
    venue        TEXT NOT NULL,
    trigger_rule TEXT NOT NULL DEFAULT 'manual',
    content      JSONB NOT NULL DEFAULT '{}'::jsonb,
    note         TEXT NOT NULL DEFAULT '',
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_defense_pack_venue ON account_defense_pack(venue, generated_at DESC);

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mix_ro') THEN
        GRANT SELECT ON account_defense_pack TO mix_ro;
    END IF;
END $$;
