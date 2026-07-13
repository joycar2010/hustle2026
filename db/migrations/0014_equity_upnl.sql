-- 0014: equity_snapshots 加 upnl_usdt(venue 级未实现盈亏合计)。
-- 用途=pnl-recorder 日度对账断言:Δ权益 − Δ未实现 − 账单全类型合计 = 残差,|残差|>阈值即账单缺记告警
-- (bybit 24h窗/bitget buy-sell/bybit cashFlow 三个账单黑洞的系统性兜底)。
ALTER TABLE equity_snapshots ADD COLUMN IF NOT EXISTS upnl_usdt NUMERIC;
CREATE INDEX IF NOT EXISTS idx_equity_snap_venue_ts ON equity_snapshots(venue, ts DESC);
