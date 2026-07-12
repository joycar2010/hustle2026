"""
写代理层（P2）—— mix-backend 绝不直写引擎库，一切写操作代理到权威 API：
  - S3(coin)：dcm:coin:cmd 命令队列（coin-bridge 消费→本机铸 JWT→coin FastAPI，coin 逻辑权威）
  - S2(dualperp)：dcm gateway /api/admin/engine_config（RBAC+武装联锁+审计全在 gateway）
本层唯一的 DB 写 = admin_audit 留痕（mix_ro 仅有该表 INSERT 权限，边界由 DB 强制）。
"""
import json
import time
import asyncio
import logging
import uuid
from typing import Optional

from . import datasources as ds

log = logging.getLogger("mix.proxy")

GATEWAY_BASE = "http://127.0.0.1:8000"
CMD_QUEUE = "dcm:coin:cmd"


async def audit(operator: str, role: str, action: str, target: str, payload: dict, result: str):
    """写审计（失败只记日志，不阻断主流程）。"""
    pool = await ds.pg()
    if pool is None:
        return
    try:
        await pool.execute(
            "INSERT INTO admin_audit(operator, role, action, target, payload, result) "
            "VALUES($1,$2,$3,$4,$5,$6)",
            operator, role, action, target, json.dumps(payload, ensure_ascii=False, default=str), result)
    except Exception as e:  # noqa: BLE001
        log.warning("audit insert failed: %s", e)


async def coin_cmd(action: str, params: dict, operator: str, timeout_sec: float = 8.0) -> dict:
    """入队 coin 命令并等回执（bridge 白名单校验 + coin FastAPI 权威执行）。"""
    r = ds.rds()
    if r is None:
        return {"ok": False, "err": "总线未配置"}
    cid = uuid.uuid4().hex
    msg = {"id": cid, "action": action, "params": params,
           "operator": operator, "src": "mix-backend", "ts": int(time.time())}
    await r.rpush(CMD_QUEUE, json.dumps(msg, ensure_ascii=False))
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        await asyncio.sleep(0.5)
        raw = await r.get(f"dcm:coin:cmd:result:{cid}")
        if raw:
            try:
                return json.loads(raw)
            except Exception:  # noqa: BLE001
                return {"ok": False, "err": "回执解析失败"}
    return {"ok": False, "err": f"coin 桥回执超时({timeout_sec:.0f}s)——命令可能仍在排队执行，勿盲目重试"}


async def gateway_engine_config(op_token: str, key: str, val: str,
                                confirm: Optional[str] = None) -> tuple[int, dict]:
    """代理 gateway engine_config 写（令牌透传保留操作者身份；联锁/审计在 gateway）。"""
    import httpx
    body = {"engine": "dualperp", "key": key, "val": val}
    if confirm:
        body["confirm"] = confirm
    async with httpx.AsyncClient(timeout=10) as c:
        resp = await c.post(f"{GATEWAY_BASE}/api/admin/engine_config",
                            json=body, headers={"X-Op-Token": op_token})
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001
            data = {"error": resp.text[:200]}
        return resp.status_code, data
