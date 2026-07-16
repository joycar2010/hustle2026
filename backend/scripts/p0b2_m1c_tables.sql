-- P0-0716批次2 + M1c 表 (2026-07-16)
CREATE TABLE IF NOT EXISTS account_symbol_fee_rates (
  account_id uuid NOT NULL,
  platform_symbol_id int NOT NULL,
  maker_fee_rate numeric(12,8),
  taker_fee_rate numeric(12,8),
  source varchar(32),
  first_observed_at timestamptz NOT NULL DEFAULT now(),
  last_verified_at timestamptz NOT NULL DEFAULT now(),
  valid_to timestamptz,
  raw jsonb,
  status varchar(16) DEFAULT 'FRESH',
  PRIMARY KEY (account_id, platform_symbol_id)
);

-- M1c: markout采样(A腿fill后的行情漂移, 度量maker逆向选择成本)
CREATE TABLE IF NOT EXISTS fill_markouts (
  id bigserial PRIMARY KEY,
  execution_id uuid,
  venue_order_id varchar(64),
  symbol varchar(32),
  side varchar(8),
  fill_price numeric(20,8),
  fill_qty numeric(20,8),
  horizon_ms int,                -- 250/1000/5000/30000
  mid_at_horizon numeric(20,8),
  markout_bps numeric(14,6),     -- 有符号: 正=成交后价格向不利方向移动(逆向选择成本)
  spread_at_horizon numeric(14,6),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_markout_exec ON fill_markouts (execution_id);
CREATE INDEX IF NOT EXISTS idx_markout_time ON fill_markouts (created_at);

-- M1c: trade_cycle归属(execution级FIFO配对由投影任务做, 先建表)
ALTER TABLE executions ADD COLUMN IF NOT EXISTS trade_cycle_id uuid;
CREATE INDEX IF NOT EXISTS idx_exec_cycle ON executions (trade_cycle_id);
