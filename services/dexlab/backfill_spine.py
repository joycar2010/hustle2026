"""LP0 一次性回填:为既有 lab_run 补 retro plan + 覆盖率 manifest,并落 budget/wallet 诚实零值。
INSERT-only 进空表(lab_run_plans/lab_run_manifests/lab_budget/lab_wallet_snapshot),幂等,可 DELETE 回滚。
不触碰运行中的 dexlab-api/scanner 代码路径。
lab_redemption_models **故意不填**——G1 需要真验证过的赎回模型,伪造 VERIFIED 会假解锁 D2 真经济闸,
留空=诚实(确无已验证模型),单列后续做真链上建模。
用法:python backfill_spine.py [--dry]   (--dry 只算不写)
"""
import sqlite3
import json
import time
import sys

sys.path.insert(0, "/home/ec2-user/dexlab")
import lab_spine as S

DB = "/home/ec2-user/dexlab/dexlab.db"
DRY = "--dry" in sys.argv


def build_retro_plan(conn, run):
    pid = run["project_id"]; run_id = run["run_id"]
    ws = run["started_at"]; we = S.window_end_for(conn, run)
    expected, observed, coverage, _missing = S.compute_coverage(conn, pid, ws, we)
    cm = conn.execute("SELECT updated_at FROM lab_cost_model WHERE project_id=?", (pid,)).fetchone()
    cost_ver = f"v{cm[0]}" if cm and cm[0] else "v0"
    fields = {
        "product_code": pid, "strategy_version": f"retro-{run['kind'].lower()}-v0",
        "window_start": ws, "window_end": we, "sampling_interval": S.SAMPLING_INTERVAL,
        "expected_slots": expected, "min_valid_slots": int(expected * 0.80),
        "min_coverage_ratio": 0.80,
        "instrument_scope_hash": S._sha({"project": pid, "scope": "scanner-default"}),
        "size_ladder_json": "[]",
        "episode_policy_json": json.dumps({"source": "replay", "note": "retro"}, ensure_ascii=False),
        "cost_model_version": cost_ver, "risk_model_version": None, "pricing_model_version": None,
        "primary_metric": "conservative_net_bps",
        "decision_policy_json": json.dumps({
            "retro": True, "derived_from_run": run_id,
            "note": "回填追认计划:窗口/expected 由实际信号跨度反推,非事前预登记",
            "min_coverage_ratio": 0.80}, ensure_ascii=False),
    }
    ph = S.canonical_plan_hash(fields)
    plan_id = f"retro-{pid}-run{run_id}"
    status = "COMPLETED" if run["state"] == "DONE" else "ACTIVE"
    if not DRY:
        conn.execute(
            "INSERT OR IGNORE INTO lab_run_plans"
            "(plan_id,product_code,strategy_version,window_start,window_end,sampling_interval,expected_slots,"
            " min_valid_slots,min_coverage_ratio,instrument_scope_hash,size_ladder_json,episode_policy_json,"
            " cost_model_version,risk_model_version,pricing_model_version,primary_metric,decision_policy_json,"
            " registered_at,registered_by,plan_hash,status) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (plan_id, fields["product_code"], fields["strategy_version"], ws, we, S.SAMPLING_INTERVAL,
             expected, fields["min_valid_slots"], fields["min_coverage_ratio"], fields["instrument_scope_hash"],
             fields["size_ladder_json"], fields["episode_policy_json"], fields["cost_model_version"],
             None, None, fields["primary_metric"], fields["decision_policy_json"],
             ws, "backfill-retro", ph, status))
    return plan_id, status


def main():
    conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row
    runs = list(conn.execute(
        "SELECT run_id,project_id,kind,state,started_at,ended_at FROM lab_run ORDER BY run_id"))
    out = []
    for run in runs:
        plan_id, status = build_retro_plan(conn, run)
        if not DRY:
            conn.execute("DELETE FROM lab_run_manifests WHERE run_id=?", (run["run_id"],))
        m = S.insert_manifest(conn, run, plan_id=plan_id, min_ratio=0.80) if not DRY else \
            {"run_id": run["run_id"], "project_id": run["project_id"], "plan_id": plan_id, "dry": True}
        out.append({**m, "plan_status": status, "run_state": run["state"], "kind": run["kind"]})
    now = int(time.time())
    if not DRY:
        for (pid,) in conn.execute("SELECT DISTINCT project_id FROM lab_run"):
            conn.execute("INSERT OR IGNORE INTO lab_budget(project_id,granted_usdt,used_usdt,wallet,updated_at) "
                         "VALUES(?,0,0,'',?)", (pid, now))
        # LAB 域无生产钱包;§16.1 只读探针实测旁路钱包为空 → 诚实 equity=0
        conn.execute("INSERT INTO lab_wallet_snapshot(wallet,equity_usdt,ts) VALUES('LAB_NO_WALLET',0,?)", (now,))
        conn.commit()
    print("=== manifests ===")
    for o in out:
        print(json.dumps(o, ensure_ascii=False))
    print("=== table counts ===")
    for t in ("lab_run_plans", "lab_run_manifests", "lab_budget", "lab_wallet_snapshot", "lab_redemption_models"):
        n = conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"{t}: {n}")
    conn.close()


if __name__ == "__main__":
    main()
