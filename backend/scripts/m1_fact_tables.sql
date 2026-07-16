-- M1 执行事实层(V1.1 §8.2 首版, 2026-07-16)。纯加法, 无消费者依赖, shadow双写。
CREATE TABLE IF NOT EXISTS executions (
  execution_id uuid PRIMARY KEY,
  strategy_id varchar(120),
  user_id uuid,
  pair_code varchar(30),
  strategy_type varchar(30),
  ladder_idx int,
  planned_qty numeric(20,8),
  status varchar(30),               -- RUNNING/FILLED/NO_FILL/BUDGET_GATED/HALTED/CRASHED
  binance_filled numeric(20,8),
  hedge_filled_lot numeric(20,8),
  error text,
  release_sha varchar(40),
  created_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz
);
CREATE INDEX IF NOT EXISTS idx_exec_user_time ON executions (user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_exec_open ON executions (status) WHERE status IN ('RUNNING','CRASHED');

CREATE TABLE IF NOT EXISTS execution_orders (
  id bigserial PRIMARY KEY,
  execution_id uuid,
  venue varchar(16),
  account_id uuid,
  symbol varchar(32),
  side varchar(8),
  requested_qty numeric(20,8),
  venue_order_id varchar(64),
  client_order_id varchar(64),
  status varchar(24) DEFAULT 'NEW',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_exord_exec ON execution_orders (execution_id);
CREATE INDEX IF NOT EXISTS idx_exord_venue ON execution_orders (venue, venue_order_id);

CREATE TABLE IF NOT EXISTS execution_fills (
  id bigserial PRIMARY KEY,
  execution_id uuid,
  venue varchar(16),
  venue_order_id varchar(64),
  fill_qty numeric(20,8),
  avg_price numeric(20,8),
  qty_unit varchar(8),              -- A(基础单位) / lot
  source varchar(24),               -- monitor/bridge/repair/rest
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_exfill_exec ON execution_fills (execution_id);

CREATE TABLE IF NOT EXISTS execution_events (
  id bigserial PRIMARY KEY,
  execution_id uuid,
  event varchar(40),
  detail jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_exevt_exec ON execution_events (execution_id);
