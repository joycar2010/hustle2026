"""exec-kernel 侧风险策略消费者(V5 补充说明 ADR-004 fail-closed / ADR-005 版本单调)。

读 risk-ledger 发布的 dcm:risk:policy,给 opener/manager 提供逐 venue 的开仓许可判定。
铁律:
  - 快照缺失/超龄(>STALE_SEC,"刷新龄"非"策略变更龄")→ fail-closed:CAN_OPEN 一律 False,
    但减险(reduce/cancel/repay/rescue)不受影响(调用方各自判断,本模块只答"能否新增")。
  - 版本单调:只接受更高 policy_version,防旧快照复活(进程内记 last_version)。
"""
import json
import os
import time

POLICY_KEY = "dcm:risk:policy"
STALE_SEC = int(os.environ.get("DCM_POLICY_STALE_SEC", "90"))   # 快照刷新龄阈值(fail-closed)

_last_version = {"v": -1}   # 进程内单调门闩


async def read_policy(r):
    """返回 (policy_dict|None, fresh_bool)。None=缺失;fresh=False 表示超龄或缺失,须 fail-closed。"""
    try:
        raw = await r.get(POLICY_KEY)
    except Exception:  # noqa: BLE001
        return None, False
    if not raw:
        return None, False
    try:
        pol = json.loads(raw)
    except Exception:  # noqa: BLE001
        return None, False
    age = time.time() - float(pol.get("ts") or 0)
    if age > STALE_SEC:
        return pol, False   # 有内容但超龄:调用方按 fail-closed 处理
    ver = int(pol.get("policy_version") or -1)
    if ver < _last_version["v"]:
        return pol, False   # 版本回退(旧快照复活)→ 拒绝当新鲜
    _last_version["v"] = max(_last_version["v"], ver)
    return pol, True


async def can_open(r, venue: str):
    """该 venue 是否允许新增风险(开仓/加仓/增债)。
    返回 (allowed: bool, reason: str)。fail-closed:策略不可用/超龄一律不允许新增。"""
    pol, fresh = await read_policy(r)
    if pol is None:
        return False, "策略快照缺失(fail-closed 拒新增)"
    if not fresh:
        return False, f"策略快照超龄>{STALE_SEC}s 或版本回退(fail-closed 拒新增)"
    vd = (pol.get("venues") or {}).get(venue)
    if vd is None:
        return False, f"{venue} 无策略记录(fail-closed)"
    caps = vd.get("capabilities") or {}
    if caps.get("CAN_OPEN"):
        return True, vd.get("mode", "NORMAL")
    return False, f"{venue} 模式={vd.get('mode')}({vd.get('reason')})"
