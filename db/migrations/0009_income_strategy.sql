-- strategy_code 逐回路归因根治(第一步:账本行在写入时打标,消费端不再查询期猜测)
-- 口径:S1=basis 引擎在管过的币 / S2=dualperp / ''=未归因(写入时两侧都查不到)
-- 打标发生在 pnl-recorder 写入时(时间局部:当时谁在管谁认领);历史行由回填脚本一次性补
ALTER TABLE income_records ADD COLUMN IF NOT EXISTS strategy_code text NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_income_strategy ON income_records(strategy_code, ts DESC);
