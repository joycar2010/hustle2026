-- MIX-V6.2-PATCH-02 §8/§14:点差扩大主动保护(shadow)+分位采样。
-- 运行时由 app/risk_guard.py CREATE TABLE IF NOT EXISTS 保障;本文件为迁移记录。
-- 新表只存 策略/快照/事件/样本——财务事实仍在既有权威表,不建第二本账。
-- forward-fix:snapshot/event 为证据账不做破坏性回滚;policy 弃用置 is_default=false。

CREATE TABLE IF NOT EXISTS risk_spread_sample (
    symbol TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    gap_pct DOUBLE PRECISION,
    min_spread_bps DOUBLE PRECISION);
CREATE INDEX IF NOT EXISTS idx_rss_sym_ts ON risk_spread_sample (symbol, ts DESC);

CREATE TABLE IF NOT EXISTS risk_exit_policy (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    version INT NOT NULL DEFAULT 1,
    product_scope TEXT NOT NULL DEFAULT 'C2.P,C2.H,C3.S',
    hard_loss_budget_abs DOUBLE PRECISION NOT NULL,
    hard_loss_budget_pct_nav DOUBLE PRECISION NOT NULL,
    min_margin_level DOUBLE PRECISION NOT NULL DEFAULT 1.10,
    max_liq_pct DOUBLE PRECISION NOT NULL DEFAULT 80,
    max_recovery_windows DOUBLE PRECISION NOT NULL,
    spread_watch_q DOUBLE PRECISION NOT NULL DEFAULT 0.90,
    spread_reduce_q DOUBLE PRECISION NOT NULL DEFAULT 0.967,
    hysteresis DOUBLE PRECISION NOT NULL DEFAULT 0.7,
    min_state_duration_sec INT NOT NULL DEFAULT 600,
    reduction_steps INT NOT NULL DEFAULT 3,
    emergency_exit_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now());

CREATE TABLE IF NOT EXISTS risk_exit_snapshot (
    id BIGSERIAL PRIMARY KEY,
    work_key TEXT NOT NULL,
    symbol TEXT NOT NULL,
    product TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL,
    closeout_pnl_net DOUBLE PRECISION,
    l_now DOUBLE PRECISION,
    hard_budget DOUBLE PRECISION,
    budget_remaining DOUBLE PRECISION,
    recovery_windows DOUBLE PRECISION,
    margin_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    policy_name TEXT NOT NULL DEFAULT '',
    policy_version INT,
    as_of TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS idx_res_key_ts ON risk_exit_snapshot (work_key, id DESC);

CREATE TABLE IF NOT EXISTS risk_exit_event (
    id BIGSERIAL PRIMARY KEY,
    work_key TEXT NOT NULL,
    symbol TEXT NOT NULL,
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    ts TIMESTAMPTZ NOT NULL DEFAULT now());

GRANT SELECT, INSERT, UPDATE, DELETE ON risk_spread_sample, risk_exit_policy,
    risk_exit_snapshot, risk_exit_event TO mix_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO mix_app;
