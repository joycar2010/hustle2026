"""LAB 研究主脊(V6.2 §7):plan(预登记·不可变) → run → manifest(覆盖率/完整性证明)。
把"实验先登记、跑完出覆盖率证明"的严谨性落到最小可用。纯函数 + 无 import 期副作用。
字段语义按 dexlab.db 盘上 DDL 自洽推导;采样节奏取 scanner.py INTERVAL=300s(权威分母)。
只在 ~/dexlab/dexlab.db 上操作,零生产凭证、零下单——与 D-lab 隔离铁律一致。
"""
import json
import hashlib

SAMPLING_INTERVAL = 300   # 与 scanner.py INTERVAL 对齐:每 5min 每 project 落一条 lab_signal
_COMPLETE_MIN = 0.95      # 完整性阈值(自洽默认;plan 各自的 min_coverage_ratio 可上浮)
_DEGRADED_MIN = 0.80


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


_PLAN_HASH_KEYS = (
    "product_code", "strategy_version", "window_start", "window_end", "sampling_interval",
    "expected_slots", "min_valid_slots", "min_coverage_ratio", "instrument_scope_hash",
    "size_ladder_json", "episode_policy_json", "cost_model_version", "risk_model_version",
    "pricing_model_version", "primary_metric", "decision_policy_json",
)


def canonical_plan_hash(fields: dict) -> str:
    """plan_hash = 不可变字段集合的 sha256(排除 registered_at / 审计列 / status)。
    同一组不可变承诺 → 同一 hash,天然防重复登记与事后篡改。"""
    return _sha({k: fields.get(k) for k in _PLAN_HASH_KEYS})


def payload_root_hash(conn, project_id, window_start, window_end) -> str:
    """窗口内 (ts,payload) 有序摘要:manifest 的内容完整性锚。改一条历史信号 → hash 变,verdict 可发现。"""
    h = hashlib.sha256()
    for ts, payload in conn.execute(
            "SELECT ts,payload FROM lab_signal WHERE project_id=? AND ts>=? AND ts<=? ORDER BY ts,id",
            (project_id, window_start, window_end)):
        h.update(str(ts).encode()); h.update(b"\x00")
        h.update((payload or "").encode()); h.update(b"\x01")
    return h.hexdigest()


def compute_coverage(conn, project_id, window_start, window_end, interval=SAMPLING_INTERVAL):
    """按 interval 分桶,统计 [window_start,window_end] 内有信号的桶=observed_slots。
    分母 expected 用 scanner 预期节奏(非信号自身间隔),诚实暴露持久化稀疏。
    返回 (expected, observed, coverage_ratio, missing_ranges[[start_ts,end_ts]...])。"""
    if window_end <= window_start:
        return 0, 0, 0.0, []
    expected = max(1, round((window_end - window_start) / interval))
    filled = set()
    for (ts,) in conn.execute(
            "SELECT ts FROM lab_signal WHERE project_id=? AND ts>=? AND ts<=?",
            (project_id, window_start, window_end)):
        b = int((ts - window_start) // interval)
        if 0 <= b < expected:
            filled.add(b)
    observed = len(filled)
    coverage = round(observed / expected, 4) if expected else 0.0
    missing_buckets = sorted(set(range(expected)) - filled)
    missing = []
    if missing_buckets:
        s = p = missing_buckets[0]
        for b in missing_buckets[1:]:
            if b == p + 1:
                p = b; continue
            missing.append([window_start + s * interval, window_start + (p + 1) * interval])
            s = p = b
        missing.append([window_start + s * interval, window_start + (p + 1) * interval])
    return expected, observed, coverage, missing


def integrity_from_coverage(coverage, min_ratio) -> str:
    if coverage >= max(min_ratio, _COMPLETE_MIN):
        return "COMPLETE"
    if coverage >= _DEGRADED_MIN:
        return "DEGRADED"
    return "INCOMPLETE"


def window_end_for(conn, run_row):
    """run 的窗口终点:DONE 用 ended_at;RUNNING 用该 project 最后一条信号 ts(as-of 快照)。"""
    if run_row["ended_at"]:
        return run_row["ended_at"]
    row = conn.execute("SELECT max(ts) FROM lab_signal WHERE project_id=?",
                       (run_row["project_id"],)).fetchone()
    return (row[0] if row else None) or run_row["started_at"]


def insert_manifest(conn, run_row, plan_id=None, min_ratio=_DEGRADED_MIN):
    """为一个 lab_run 计算并 INSERT 一条 manifest(调用方负责先 DELETE 旧行保证幂等——
    不依赖新版 SQLite 的 ON CONFLICT,兼容老 sqlite)。返回 manifest 摘要 dict。"""
    run_id = run_row["run_id"]; pid = run_row["project_id"]
    ws = run_row["started_at"]; we = window_end_for(conn, run_row)
    expected, observed, coverage, missing = compute_coverage(conn, pid, ws, we)
    valid = observed   # 回填保守:不宣称超过 observed 的 valid
    integ = integrity_from_coverage(coverage, min_ratio)
    ep = conn.execute("SELECT count(*) FROM lab_episodes WHERE run_id=?", (run_id,)).fetchone()[0]
    root = payload_root_hash(conn, pid, ws, we)
    as_of = "" if run_row["state"] == "DONE" else "as_of_running:"
    conn.execute(
        "INSERT INTO lab_run_manifests"
        "(run_id,plan_id,expected_slots,observed_slots,valid_slots,coverage_ratio,"
        " missing_ranges_json,source_gap_json,episode_count,payload_root_hash,"
        " integrity_status,completion_reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (run_id, plan_id, expected, observed, valid, coverage,
         json.dumps(missing), None, ep, root, integ, f"{as_of}cov={coverage}:{integ}"))
    return {"run_id": run_id, "project_id": pid, "plan_id": plan_id, "window": [ws, we],
            "expected_slots": expected, "observed_slots": observed, "valid_slots": valid,
            "coverage_ratio": coverage, "integrity_status": integ,
            "episode_count": ep, "missing_ranges": len(missing)}


def manifest_for_run(conn, run_id):
    """读一个 run 的 manifest(供 verdict 覆盖率顾问用)。无则 None。"""
    row = conn.execute(
        "SELECT run_id,plan_id,coverage_ratio,integrity_status,expected_slots,observed_slots "
        "FROM lab_run_manifests WHERE run_id=?", (run_id,)).fetchone()
    return dict(row) if row else None


def register_run_plan(conn, pid, kind, params, now, interval=SAMPLING_INTERVAL):
    """scan_start 前向登记:从 params.horizon_days(默认30)承诺窗口+expected_slots,写不可变 plan。
    这是反 p-hacking 的核心——开跑前就锁死"我将在窗口 W 内采 N 槽、min_coverage=X"。返回 plan_id。"""
    horizon_days = float(params.get("horizon_days") or 30)
    ws = int(now); we = int(now + horizon_days * 86400)
    expected = max(1, round((we - ws) / interval))
    min_cov = float(params.get("min_coverage_ratio") or 0.90)
    fields = {
        "product_code": pid, "strategy_version": f"{kind.lower()}-v1",
        "window_start": ws, "window_end": we, "sampling_interval": interval,
        "expected_slots": expected, "min_valid_slots": int(expected * min_cov),
        "min_coverage_ratio": min_cov,
        "instrument_scope_hash": _sha({"project": pid, "scope": params.get("scope", "scanner-default")}),
        "size_ladder_json": json.dumps(params.get("size_ladder") or []),
        "episode_policy_json": json.dumps(params.get("episode_policy") or {}, ensure_ascii=False),
        "cost_model_version": str(params.get("cost_model_version") or "v1"),
        "risk_model_version": None, "pricing_model_version": None,
        "primary_metric": params.get("primary_metric") or "conservative_net_bps",
        "decision_policy_json": json.dumps(
            params.get("decision_policy") or {"pre_registered": True}, ensure_ascii=False),
    }
    ph = canonical_plan_hash(fields)
    plan_id = f"{pid}-{kind.lower()}-{now}"
    conn.execute(
        "INSERT OR IGNORE INTO lab_run_plans"
        "(plan_id,product_code,strategy_version,window_start,window_end,sampling_interval,expected_slots,"
        " min_valid_slots,min_coverage_ratio,instrument_scope_hash,size_ladder_json,episode_policy_json,"
        " cost_model_version,risk_model_version,pricing_model_version,primary_metric,decision_policy_json,"
        " registered_at,registered_by,plan_hash,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'ACTIVE')",
        (plan_id, fields["product_code"], fields["strategy_version"], ws, we, interval, expected,
         fields["min_valid_slots"], fields["min_coverage_ratio"], fields["instrument_scope_hash"],
         fields["size_ladder_json"], fields["episode_policy_json"], fields["cost_model_version"],
         None, None, fields["primary_metric"], fields["decision_policy_json"], now, "scan_start", ph))
    return plan_id


def coverage_advisory(conn, pid):
    """verdict 时的覆盖率顾问(shadow,不拦):列出该 project 非 COMPLETE 的 run manifest。无则 None。"""
    rows = conn.execute(
        "SELECT m.run_id,m.coverage_ratio,m.integrity_status,m.expected_slots,m.observed_slots "
        "FROM lab_run_manifests m JOIN lab_run r ON r.run_id=m.run_id "
        "WHERE r.project_id=? AND m.integrity_status IS NOT NULL AND m.integrity_status<>'COMPLETE'",
        (pid,)).fetchall()
    if not rows:
        return None
    return [{"run_id": r[0], "coverage_ratio": r[1], "integrity_status": r[2],
             "expected_slots": r[3], "observed_slots": r[4]} for r in rows]
