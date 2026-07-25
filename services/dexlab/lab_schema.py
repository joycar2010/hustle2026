"""lab_schema.py — 第二代严谨表(plan/manifest/redemption/episode/gate)的代码自有 DDL。
此前它们是孤儿 DDL(某次 pack apply 建表,全库代码零引用)。此模块收编为代码所有,
全部 CREATE ... IF NOT EXISTS:对已存在的 live 库零作用,仅令真库可从代码重建。
DDL 逐字取自盘上 sqlite_master(gen_schema.py 生成),唯一改动=补 IF NOT EXISTS。"""
import time

SCHEMA_VERSION = 2  # 2 = 含第二代严谨表(plan->manifest 主脊)

DDL_V2 = """
CREATE TABLE IF NOT EXISTS lab_run_plans (
    plan_id TEXT PRIMARY KEY,
    product_code TEXT NOT NULL,
    strategy_version TEXT NOT NULL,

    -- 窗口定义（不可变）
    window_start INTEGER NOT NULL,
    window_end INTEGER NOT NULL,
    sampling_interval INTEGER NOT NULL,
    expected_slots INTEGER NOT NULL,

    -- 完成条件（预登记，不可变）
    min_valid_slots INTEGER NOT NULL,
    min_coverage_ratio REAL NOT NULL,

    -- 标的和参数（不可变）
    instrument_scope_hash TEXT NOT NULL,
    size_ladder_json TEXT NOT NULL,
    episode_policy_json TEXT NOT NULL,

    -- 模型版本（不可变）
    cost_model_version TEXT NOT NULL,
    risk_model_version TEXT,
    pricing_model_version TEXT,

    -- 决策策略
    primary_metric TEXT NOT NULL,
    decision_policy_json TEXT NOT NULL,

    -- 元数据
    registered_at INTEGER NOT NULL,
    registered_by TEXT DEFAULT 'system',
    plan_hash TEXT NOT NULL UNIQUE,
    status TEXT DEFAULT 'REGISTERED' CHECK(status IN ('REGISTERED', 'ACTIVE', 'COMPLETED', 'CANCELLED')),

    -- 审计
    created_at INTEGER DEFAULT (strftime('%s', 'now')),
    updated_at INTEGER DEFAULT (strftime('%s', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_run_plans_hash ON lab_run_plans(plan_hash);

CREATE INDEX IF NOT EXISTS idx_run_plans_product ON lab_run_plans(product_code, status);

CREATE TABLE IF NOT EXISTS lab_run_manifests (
    manifest_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES lab_run(run_id),
    plan_id TEXT REFERENCES lab_run_plans(plan_id),

    -- 覆盖率统计
    expected_slots INTEGER NOT NULL,
    observed_slots INTEGER NOT NULL,
    valid_slots INTEGER NOT NULL,
    coverage_ratio REAL NOT NULL,

    -- 缺口记录
    missing_ranges_json TEXT,
    source_gap_json TEXT,

    -- 内容完整性
    episode_count INTEGER DEFAULT 0,
    payload_root_hash TEXT,

    -- 完成状态
    integrity_status TEXT CHECK(integrity_status IN ('COMPLETE', 'INCOMPLETE', 'DEGRADED')),
    completion_reason TEXT,

    -- 审计
    created_at INTEGER DEFAULT (strftime('%s', 'now')),

    UNIQUE(run_id)
);

CREATE INDEX IF NOT EXISTS idx_manifests_plan ON lab_run_manifests(plan_id);

CREATE INDEX IF NOT EXISTS idx_manifests_run ON lab_run_manifests(run_id);

CREATE TABLE IF NOT EXISTS lab_redemption_models (
    model_id TEXT PRIMARY KEY,
    instrument_version TEXT NOT NULL,
    protocol_version TEXT NOT NULL,

    -- 资产转换图
    asset_graph_json TEXT NOT NULL,

    -- 调用路径
    call_graph_json TEXT NOT NULL,

    -- 单位转换
    unit_conversion_json TEXT NOT NULL,

    -- 验证状态
    model_hash TEXT NOT NULL UNIQUE,
    verification_status TEXT CHECK(verification_status IN ('DRAFT', 'VERIFIED', 'DEPRECATED')),
    verified_at INTEGER,
    verified_by TEXT,

    -- 审计
    created_at INTEGER DEFAULT (strftime('%s', 'now')),
    updated_at INTEGER DEFAULT (strftime('%s', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_redemption_instrument ON lab_redemption_models(instrument_version);

CREATE INDEX IF NOT EXISTS idx_redemption_status ON lab_redemption_models(verification_status);

CREATE TABLE IF NOT EXISTS lab_episodes (
    episode_id TEXT PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES lab_run(run_id),
    instrument_version TEXT NOT NULL,

    -- 路由和规模
    route_key TEXT NOT NULL,
    size_bucket TEXT,

    -- 时间窗口
    started_at INTEGER NOT NULL,
    ended_at INTEGER NOT NULL,
    duration INTEGER NOT NULL,
    observation_count INTEGER NOT NULL,

    -- 报价引用
    entry_quote_ids TEXT,
    exit_quote_ids TEXT,

    -- 经济学
    target_notional REAL,
    capacity_at_entry REAL,
    gross_edge_bps REAL,
    full_cost_bps REAL,
    conservative_net_bps REAL,

    -- 风险指标
    mae_bps REAL,
    mfe_bps REAL,
    max_quote_age INTEGER,

    -- 可执行性
    entry_feasible INTEGER DEFAULT 0,
    exit_feasible INTEGER DEFAULT 0,
    hedge_feasible INTEGER DEFAULT 0,

    -- 假阳性分析
    false_positive_reason TEXT,

    -- 市场状态标签
    market_regime TEXT,
    gas_regime TEXT,
    volatility_regime TEXT,

    -- 审计
    created_at INTEGER DEFAULT (strftime('%s', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_episodes_instrument ON lab_episodes(instrument_version);

CREATE INDEX IF NOT EXISTS idx_episodes_run ON lab_episodes(run_id);

CREATE INDEX IF NOT EXISTS idx_episodes_time ON lab_episodes(started_at, ended_at);

CREATE TABLE IF NOT EXISTS lab_validation_gate_results (
    result_id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 评估对象
    subject_type TEXT NOT NULL CHECK(subject_type IN ('INSTRUMENT', 'RUN', 'EPISODE')),
    subject_id TEXT NOT NULL,

    -- 闸门标识
    gate_code TEXT NOT NULL CHECK(gate_code IN ('G1_EVIDENCE', 'G2_ECONOMIC', 'G3_STATISTICAL', 'G4_EXECUTION', 'G5_RISK')),

    -- 晋级目标
    transition_target TEXT,

    -- 结果
    status TEXT NOT NULL CHECK(status IN ('NOT_EVALUATED', 'PASS', 'FAIL', 'BLOCKED', 'STALE')),
    policy_version TEXT NOT NULL,

    -- 原因和指标
    reason_codes TEXT,
    metrics_json TEXT,

    -- 输入快照
    input_snapshot_hash TEXT,

    -- 有效期
    evaluated_at INTEGER NOT NULL,
    expires_at INTEGER,

    -- 审计
    created_at INTEGER DEFAULT (strftime('%s', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_gate_results_eval ON lab_validation_gate_results(evaluated_at);

CREATE INDEX IF NOT EXISTS idx_gate_results_gate ON lab_validation_gate_results(gate_code, status);

CREATE INDEX IF NOT EXISTS idx_gate_results_subject ON lab_validation_gate_results(subject_type, subject_id);
"""


def ensure_v2(conn):
    """幂等:建表(IF NOT EXISTS)+ 盖版本戳。调用点在 main._init() 的 executescript(_DDL) 之后。"""
    conn.executescript(DDL_V2)
    conn.execute("PRAGMA user_version = %d" % SCHEMA_VERSION)
    conn.execute("INSERT OR REPLACE INTO lab_meta(key,value) VALUES('schema_version',?)", (str(SCHEMA_VERSION),))
    conn.execute("INSERT OR IGNORE INTO lab_meta(key,value) VALUES('mig_v62_strict_tables',?)", (str(int(time.time())),))
