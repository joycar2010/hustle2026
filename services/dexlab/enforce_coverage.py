#!/usr/bin/env python3
"""LP0 follow-up ①:coverage_advisory shadow→enforce。
GRADUATE_PROPOSAL 判决时,若 coverage_advisory 返回 DEGRADED/INCOMPLETE runs,拒绝判决。
其他 verdict 不拦(只 GRADUATION 要求完整覆盖率证明)。"""
import sys, os

MAIN = os.path.expanduser("~/dexlab/main.py")
src = open(MAIN, encoding="utf-8").read()

# 找到 GRADUATE_PROPOSAL 闸的 blocking.append 段落,在其后、raise HTTPException 之前插入覆盖率闸
anchor = """                if v == "GRADUATE_PROPOSAL":
                    stg = c.execute("SELECT stage FROM lab_project WHERE project_id=?", (pid,)).fetchone()
                    if not stg or stg["stage"] not in ("SHADOW", "CANARY"):
                        blocking.append("GRADUATE_PROPOSAL 只能来自 SHADOW/CANARY 完成态(§4.1 不变量)")
                if blocking:"""

if anchor not in src:
    print("ABORT: anchor not found", file=sys.stderr); sys.exit(1)
if src.count(anchor) != 1:
    print("ABORT: anchor non-unique", file=sys.stderr); sys.exit(1)
if "LP0 coverage enforce" in src:
    print("already enforced: marker found", file=sys.stderr); sys.exit(0)

replacement = """                if v == "GRADUATE_PROPOSAL":
                    stg = c.execute("SELECT stage FROM lab_project WHERE project_id=?", (pid,)).fetchone()
                    if not stg or stg["stage"] not in ("SHADOW", "CANARY"):
                        blocking.append("GRADUATE_PROPOSAL 只能来自 SHADOW/CANARY 完成态(§4.1 不变量)")
                    # LP0 coverage enforce:GRADUATION 要求完整覆盖率证明(DEGRADED/INCOMPLETE 拦)
                    try:
                        _cov_adv = _spine.coverage_advisory(c, pid)
                        if _cov_adv:
                            for _m in _cov_adv:
                                rid = _m.get("run_id", "?")
                                integ = _m.get("integrity", "?")
                                cov = _m.get("coverage", 0)
                                blocking.append(f"覆盖率不足:run#{rid} {integ} ({cov*100:.1f}%<95%)")
                    except Exception as _e:
                        log.warning("coverage advisory failed in GRADUATION gate pid=%s: %r", pid, _e)
                if blocking:"""

src = src.replace(anchor, replacement, 1)
open(MAIN, "w", encoding="utf-8").write(src)
print("enforced: coverage gate inserted into GRADUATE_PROPOSAL block")
