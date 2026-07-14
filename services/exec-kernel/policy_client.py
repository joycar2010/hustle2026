"""exec-kernel 侧风险策略消费者(V5 补充说明 ADR-004 fail-closed / ADR-005 版本单调)。

读 risk-ledger 发布的 dcm:risk:policy,给 opener/manager 提供逐 venue 的开仓许可判定。
铁律:
  - 快照缺失/超龄(>STALE_SEC,"刷新龄"非"策略变更龄")→ fail-closed:CAN_OPEN 一律 False,
    但减险(reduce/cancel/repay/rescue)不受影响(调用方各自判断,本模块只答"能否新增")。
  - 版本单调:只接受更高 (policy_epoch, sequence),防旧快照复活。
批次2 双防线:
  - PG 回退读:Redis 缺失/被清时从 effective_risk_policy(C 权威快照)读回——耐久发布消费端。
  - 本地 WAL:每次接受新鲜策略即持久化 ~/.risk_policy_wal.json(0600)——进程重启后 fence
    从 WAL 初始化,旧快照即便复活也过不了单调门;Redis+PG 双失联时 WAL 是"最后最严格模式"证据。
"""
import json
import os
import time

POLICY_KEY = "dcm:risk:policy"
STALE_SEC = int(os.environ.get("DCM_POLICY_STALE_SEC", "90"))   # 快照刷新龄阈值(fail-closed)
WAL_PATH = os.environ.get("DCM_POLICY_WAL", os.path.expanduser("~/dexcexmix/.risk_policy_wal.json"))

_last_fence = {"epoch": -1, "seq": -1}   # 进程内 (epoch, sequence) 单调门闩(ADR-005)
_pg_pool = None                          # set_pool() 注入;Redis 失效时的 PG 回退读
_wal_loaded = False
_wal_last_write = 0.0


def set_pool(pool):
    """由服务 main() 注入 dcm_main 连接池,启用 PG 回退读。"""
    global _pg_pool
    _pg_pool = pool


def _wal_load():
    """进程启动首次调用:fence 从 WAL 初始化——重启不清零,旧快照复活防线跨进程生命周期。"""
    global _wal_loaded
    if _wal_loaded:
        return
    _wal_loaded = True
    try:
        with open(WAL_PATH, encoding="utf-8") as f:
            w = json.load(f)
        _last_fence["epoch"] = int(w.get("policy_epoch") or -1)
        _last_fence["seq"] = int(w.get("policy_version") or -1)
    except Exception:  # noqa: BLE001  # 首次运行无 WAL:fence 从 -1 起
        pass


def _wal_store(pol: dict):
    """接受新鲜策略即落 WAL(10s 节流,原子替换,0600)。"""
    global _wal_last_write
    if time.time() - _wal_last_write < 10:
        return
    try:
        tmp = WAL_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(pol, f, ensure_ascii=False)
        os.replace(tmp, WAL_PATH)
        os.chmod(WAL_PATH, 0o600)
        _wal_last_write = time.time()
    except Exception:  # noqa: BLE001  # WAL 写失败不阻塞主链路(防线降级,不 fail)
        pass


async def read_policy(r):
    """返回 (policy_dict|None, fresh_bool)。None=缺失;fresh=False 表示超龄/缺失/fence 回退,须 fail-closed。
    读序:Redis → PG effective_risk_policy(回退)→ 都无则 None。"""
    _wal_load()
    raw = None
    try:
        raw = await r.get(POLICY_KEY)
    except Exception:  # noqa: BLE001
        raw = None
    if not raw and _pg_pool is not None:
        try:
            row = await _pg_pool.fetchrow("SELECT snapshot FROM effective_risk_policy WHERE id=1")
            if row:
                raw = row["snapshot"]
        except Exception:  # noqa: BLE001
            raw = None
    if not raw:
        return None, False
    try:
        pol = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:  # noqa: BLE001
        return None, False
    age = time.time() - float(pol.get("ts") or 0)
    if age > STALE_SEC:
        return pol, False   # 有内容但超龄:调用方按 fail-closed 处理
    # (epoch, sequence) 字典序单调:任一维回退=旧快照复活,拒绝当新鲜(DB 恢复须 bump epoch)
    epoch = int(pol.get("policy_epoch") or 1)
    seq = int(pol.get("policy_version") or -1)
    cur = (epoch, seq)
    last = (_last_fence["epoch"], _last_fence["seq"])
    if cur < last:
        return pol, False
    _last_fence["epoch"], _last_fence["seq"] = epoch, seq
    _wal_store(pol)
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
