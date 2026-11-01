"""One-shot in-place patcher: add the slow-loop overlay to a dashboard.py.

Refuses to touch the file unless every anchor occurs exactly once, so it is
safe against drifted copies.  Idempotent: a file already containing the
overlay is left unchanged.  Usage:  python3 patch_dashboard.py <path>
"""
from __future__ import annotations

import sys

OVERLAY = '''AGENTS_STATUS_PATH = ROOT / "agents" / "out" / "agent_status.json"
_SLOW_LOOP_ALIAS = {"review": "desk"}  # review work surfaces under the desk card
_SLOW_LOOP_MAX_AGE_SEC = 1200          # timer cadence 10min + margin


def _slow_loop_overlay(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Overlay REAL per-role slow-loop status (agents/run.py) onto the base
    snapshot.  Read-only and failure-silent: missing/stale file changes
    nothing."""
    try:
        if not AGENTS_STATUS_PATH.exists():
            return snapshot
        if time.time() - AGENTS_STATUS_PATH.stat().st_mtime > _SLOW_LOOP_MAX_AGE_SEC:
            return snapshot
        payload = json.loads(AGENTS_STATUS_PATH.read_text(encoding="utf-8"))
        for role, info in (payload.get("roles") or {}).items():
            if not isinstance(info, dict) or info.get("kind") != "agent":
                continue
            target = _SLOW_LOOP_ALIAS.get(role, role)
            entry = snapshot.get(target)
            if entry is None:
                continue
            slow = entry.setdefault("slow_loop", {})
            slow[role] = {k: info.get(k) for k in (
                "status", "workflow_stage", "duration_ms", "heartbeat_ts",
                "n_reviews", "n_degraded", "whale_trades", "detail") if k in info}
            stage = info.get("workflow_stage")
            if stage and stage != "-" and role == target:
                entry["workflow_stage"] = f"slow-loop:{stage}"
            if info.get("status") == "error" and role == target:
                entry["status"] = "error"
                entry["detail"] = info.get("detail") or entry.get("detail")
    except (OSError, ValueError, TypeError):
        pass
    return snapshot


'''

DEF_ANCHOR = "def _agent_status_snapshot() -> dict[str, Any]:"
RET_NORM = ("                        normalized[role] = item\n"
            "                    return normalized")
RET_NORM_NEW = ("                        normalized[role] = item\n"
                "                    return _slow_loop_overlay(normalized)")
RET_RESULT = ('"model_calls": {"primary": "waiting", "secondary": "waiting"}})\n'
              "    return result")
RET_RESULT_NEW = ('"model_calls": {"primary": "waiting", "secondary": "waiting"}})\n'
                  "    return _slow_loop_overlay(result)")


def main() -> int:
    path = sys.argv[1]
    src = open(path, encoding="utf-8").read()
    if "_slow_loop_overlay" in src:
        print("already patched; nothing to do")
        return 0
    for name, anchor in (("def", DEF_ANCHOR), ("ret_norm", RET_NORM), ("ret_result", RET_RESULT)):
        if src.count(anchor) != 1:
            print(f"ABORT: anchor {name} count={src.count(anchor)} (need exactly 1)")
            return 2
    src = src.replace(DEF_ANCHOR, OVERLAY + DEF_ANCHOR, 1)
    src = src.replace(RET_NORM, RET_NORM_NEW, 1)
    src = src.replace(RET_RESULT, RET_RESULT_NEW, 1)
    open(path, "w", encoding="utf-8").write(src)
    print("patched OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
