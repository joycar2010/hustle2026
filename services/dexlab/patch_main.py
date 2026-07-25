"""LP0 前向接线:把 plan→manifest 主脊接入 dexlab main.py 的命令处理器。
锚点唯一断言 + 备份 + ast 校验;任一锚点不唯一即中止不写。全部改动 additive/try-except 包裹,
主脊失败绝不影响既有研究命令(scan_start/scan_stop/verdict 原行为保留)。
"""
import ast
import sys
import time

MAIN = "/home/ec2-user/dexlab/main.py"

REPLACEMENTS = [
    # 1) import lab_spine
    ("import sqlite3\nimport logging\n",
     "import sqlite3\nimport logging\nimport lab_spine as _spine\n"),

    # 2) scan_start:登记不可变 plan,plan_id 藏进 run.params 供 scan_stop 取
    ('            cur = c.execute("INSERT INTO lab_run(project_id,kind,params,state,started_at) VALUES(?,?,?,?,?)",\n'
     '                            (pid, kind, json.dumps(body.get("params") or {}), "RUNNING", now))\n',
     '            run_params = dict(body.get("params") or {})\n'
     '            try:\n'
     '                run_params["_plan_id"] = _spine.register_run_plan(c, pid, kind, run_params, now)\n'
     '            except Exception as _e:  # noqa: BLE001  # 主脊 plan 登记失败绝不挡研究主命令\n'
     '                log.warning("spine plan register failed pid=%s: %r", pid, _e)\n'
     '            cur = c.execute("INSERT INTO lab_run(project_id,kind,params,state,started_at) VALUES(?,?,?,?,?)",\n'
     '                            (pid, kind, json.dumps(run_params, ensure_ascii=False), "RUNNING", now))\n'),

    # 3) scan_stop:停轮后为每个刚 DONE 的 run 出覆盖率 manifest
    ('        elif cmd in ("scan_stop", "shadow_stop"):\n'
     '            c.execute("UPDATE lab_run SET state=\'DONE\', ended_at=? WHERE project_id=? AND state=\'RUNNING\'",\n'
     '                      (now, pid))\n',
     '        elif cmd in ("scan_stop", "shadow_stop"):\n'
     '            _stopping = [dict(_rr) for _rr in c.execute(\n'
     '                "SELECT run_id,project_id,kind,params,started_at FROM lab_run "\n'
     '                "WHERE project_id=? AND state=\'RUNNING\'", (pid,)).fetchall()]\n'
     '            c.execute("UPDATE lab_run SET state=\'DONE\', ended_at=? WHERE project_id=? AND state=\'RUNNING\'",\n'
     '                      (now, pid))\n'
     '            _mans = []\n'
     '            for _r in _stopping:\n'
     '                try:\n'
     '                    _r["state"] = "DONE"; _r["ended_at"] = now\n'
     '                    _pl = (json.loads(_r.get("params") or "{}") or {}).get("_plan_id")\n'
     '                    c.execute("DELETE FROM lab_run_manifests WHERE run_id=?", (_r["run_id"],))\n'
     '                    _mans.append(_spine.insert_manifest(c, _r, plan_id=_pl, min_ratio=0.80))\n'
     '                except Exception as _e:  # noqa: BLE001  # manifest 失败不挡停轮\n'
     '                    log.warning("spine manifest failed run=%s: %r", _r.get("run_id"), _e)\n'
     '            out["manifests"] = _mans\n'),

    # 4) verdict:发布后附覆盖率顾问(shadow,不拦,只落 outbox)
    ('            c.execute("INSERT INTO lab_verdict(project_id,verdict,reason,actor,created_at,status,"\n'
     '                      "evidence_snapshot) VALUES(?,?,?,?,?,\'ACTIVE\',?)",\n'
     '                      (pid, v, str(body.get("reason") or "")[:500], actor, now, _ev_snapshot(c, pid)))\n',
     '            c.execute("INSERT INTO lab_verdict(project_id,verdict,reason,actor,created_at,status,"\n'
     '                      "evidence_snapshot) VALUES(?,?,?,?,?,\'ACTIVE\',?)",\n'
     '                      (pid, v, str(body.get("reason") or "")[:500], actor, now, _ev_snapshot(c, pid)))\n'
     '            try:\n'
     '                _adv = _spine.coverage_advisory(c, pid)\n'
     '                if _adv:\n'
     '                    out["coverage_advisory"] = _adv\n'
     '                    c.execute("INSERT INTO research_outbox(project_id,title,summary,severity,created_at,"\n'
     '                              "artifact_type,schema_version) VALUES(?,?,?,?,?,\'LAB_COVERAGE_ADVISORY\',2)",\n'
     '                              (pid, f"{pid} 覆盖率顾问(shadow)", json.dumps(_adv, ensure_ascii=False), "warn", now))\n'
     '            except Exception as _e:  # noqa: BLE001\n'
     '                log.warning("spine coverage advisory failed pid=%s: %r", pid, _e)\n'),
]


def main():
    src = open(MAIN, encoding="utf-8").read()
    for i, (old, new) in enumerate(REPLACEMENTS, 1):
        n = src.count(old)
        if n != 1:
            print(f"ABORT: replacement #{i} anchor count={n} (expected 1). No write.")
            sys.exit(1)
        src = src.replace(old, new)
    # 校验新源可解析
    ast.parse(src)
    if "--apply" in sys.argv:
        bak = f"{MAIN}.pre_spine_{time.strftime('%Y%m%d_%H%M%S')}"
        import shutil
        shutil.copy2(MAIN, bak)
        open(MAIN, "w", encoding="utf-8").write(src)
        print(f"APPLIED. backup={bak}")
    else:
        print("DRY OK: all 4 anchors unique, patched source parses. Re-run with --apply to write.")


if __name__ == "__main__":
    main()
