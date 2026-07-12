-- S4 借贷利率套利 shadow 战绩账(engine-lending shadow 版执行器)
-- 纪律同 dualperp/basis shadow:先攒 would_enter/would_exit 战绩与 E 分布,armed 另行专场
CREATE TABLE IF NOT EXISTS lending_shadow_log (
  id bigserial PRIMARY KEY,
  ts timestamptz NOT NULL DEFAULT now(),
  coin text NOT NULL,
  net_daily_pct numeric(12,6),       -- 三率净差(|资金费|+理财-借币,%/d)
  funding_abs numeric(12,6),
  earn_pct numeric(12,6),
  borrow_pct numeric(12,6),
  decision text NOT NULL,            -- would_enter | hold | would_exit | idle
  target_usdt numeric(18,2) NOT NULL DEFAULT 0,
  note text NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_lend_shadow_ts ON lending_shadow_log(ts DESC);
CREATE INDEX IF NOT EXISTS idx_lend_shadow_coin ON lending_shadow_log(coin, ts DESC);
