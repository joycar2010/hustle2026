-- AI 顾问 shadow 对照账本:逐轮建议全量留痕。
-- 蓝图纪律:AI 输出 schema 强制→硬校验→shadow 对照规则基线跑赢才 enforce——
-- 本表就是"对照"的证据链:建议落库,复盘时与规则引擎实际动作/PnL 归因对表。
CREATE TABLE llm_advice_log (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    model       TEXT NOT NULL DEFAULT '',
    snapshot_ts BIGINT NOT NULL DEFAULT 0,
    latency_ms  INTEGER NOT NULL DEFAULT 0,
    tokens      INTEGER NOT NULL DEFAULT 0,
    symbol      TEXT NOT NULL DEFAULT '',      -- 建议针对的币(空=组合级)
    action      TEXT NOT NULL DEFAULT '',      -- endorse | caution | avoid | watch
    domain      TEXT NOT NULL DEFAULT '',      -- carry | lending | basis | portfolio ...
    reason      TEXT NOT NULL DEFAULT '',
    raw         JSONB
);
CREATE INDEX idx_llm_advice_ts ON llm_advice_log (ts DESC);
CREATE INDEX idx_llm_advice_sym ON llm_advice_log (symbol, ts DESC);
