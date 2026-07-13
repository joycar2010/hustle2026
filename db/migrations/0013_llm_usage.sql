-- 0013: LLM 逐调用用量账(2026-07-13)——每日消费明细数据源(mix /system/llm/usage-daily)。
-- llm-advisor 每次 chat/completions 调用(含失败)落一行;成本估算在读侧按中转站单价折算。
CREATE TABLE IF NOT EXISTS llm_usage_log (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    relay       TEXT NOT NULL DEFAULT '',
    model       TEXT NOT NULL DEFAULT '',
    tokens_in   INTEGER NOT NULL DEFAULT 0,
    tokens_out  INTEGER NOT NULL DEFAULT 0,
    latency_ms  INTEGER NOT NULL DEFAULT 0,
    ok          BOOLEAN NOT NULL DEFAULT TRUE,
    error       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_llm_usage_ts ON llm_usage_log(ts DESC);
