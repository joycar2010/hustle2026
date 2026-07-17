"""V6 DEX/Onchain LAB API(§8)——挂载前缀 /api/v6。

架构:D-lab(crossarb-testbox,独立 VPC/PG/Redis/钱包)跑 dexlab-api;
mix-backend 只做**单向只读拉取代理**(C 拉 LAB,LAB 永远进不来):
- D-lab 无权访问 B/cred-agent/生产密钥/客户 PII(网络层隔离:不同 VPC,无生产凭证);
- LAB 信号只经 research_outbox 单向发布为研究摘要;
- 生产 API 拒绝 environment=DEX_LAB 的 PositionIntent(v6ops.operator_commands 已强制);
- 允许的 LAB 命令只有:开始/停止扫描、回放、shadow、标注、生成报告、受控 canary 提案。
  **不存在生产下单命令**——白名单在此处与 D-lab 两端双重强制。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException

from ..deps import require_viewer, require_operator
from .. import config

log = logging.getLogger("mix.lab")
router = APIRouter(tags=["v6-lab"])

_ALLOWED_CMDS = {"scan_start", "scan_stop", "replay", "shadow_start", "shadow_stop",
                 "annotate", "report", "canary_proposal", "verdict"}


def _base() -> str:
    import os
    return (os.getenv("DEX_LAB_BASE") or getattr(config, "DEX_LAB_BASE", "") or
            "http://13.230.29.158/lab-api").rstrip("/")


def _token() -> str:
    import os
    return os.getenv("DEX_LAB_TOKEN") or getattr(config, "DEX_LAB_TOKEN", "") or ""


async def _proxy(method: str, path: str, payload: dict | None = None):
    import httpx
    url = f"{_base()}{path}"
    try:
        async with httpx.AsyncClient(timeout=10) as cli:
            hdr = {"X-Lab-Token": _token()}
            r = (await cli.get(url, headers=hdr)) if method == "GET" \
                else (await cli.post(url, headers=hdr, json=payload or {}))
        if r.status_code >= 500:
            return {"lab_reachable": False, "error": f"LAB 端 {r.status_code}", "data": None}
        return {"lab_reachable": True, "status": r.status_code, "data": r.json()}
    except Exception as e:  # noqa: BLE001
        # LAB 不可达=如实降级,绝不影响生产(D-lab 不在生产故障域)
        return {"lab_reachable": False, "error": str(e)[:200], "data": None}


@router.get("/lab/projects")
async def lab_projects(_who=Depends(require_viewer)):
    return await _proxy("GET", "/projects")


@router.get("/lab/projects/{pid}/lifecycle")
async def lab_lifecycle(pid: str, _who=Depends(require_viewer)):
    """V6.2 §4.2 阶段导航(只读):六阶段真状态+锁定原因+完成条件+下一步。"""
    return await _proxy("GET", f"/projects/{pid}/lifecycle")


@router.get("/lab/runs")
async def lab_runs(project: str = "", _who=Depends(require_viewer)):
    return await _proxy("GET", f"/runs?project={project}")


@router.get("/lab/evidence")
async def lab_evidence(run_id: str = "", project: str = "", _who=Depends(require_viewer)):
    return await _proxy("GET", f"/evidence?run_id={run_id}&project={project}")


@router.get("/lab/verdicts")
async def lab_verdicts(_who=Depends(require_viewer)):
    return await _proxy("GET", "/verdicts")


@router.get("/lab/signals")
async def lab_signals(project: str = "", limit: int = 50, _who=Depends(require_viewer)):
    return await _proxy("GET", f"/signals?project={project}&limit={limit}")


@router.get("/lab/outbox")
async def lab_outbox(_who=Depends(require_viewer)):
    """research_outbox 研究摘要(单向,只读)。机会墙只显示一条「LAB 有新结果」提醒,
    实验信号不入 CEX 可执行列表(§8.1)。"""
    return await _proxy("GET", "/outbox")


@router.get("/lab/health")
async def lab_health(_who=Depends(require_viewer)):
    return await _proxy("GET", "/health")


@router.post("/lab/commands")
async def lab_commands(body: dict, op=Depends(require_operator)):
    """受控 LAB 命令(白名单双端强制)。不存在生产下单命令。"""
    cmd = str(body.get("command") or "")
    if cmd not in _ALLOWED_CMDS:
        raise HTTPException(400, f"LAB 只允许:{sorted(_ALLOWED_CMDS)};不存在生产下单命令")
    if str(body.get("environment") or "DEX_LAB") != "DEX_LAB":
        raise HTTPException(400, "LAB 命令 environment 只能是 DEX_LAB")
    out = await _proxy("POST", "/commands", {**body, "actor": op["operator"]})
    if not out.get("lab_reachable"):
        raise HTTPException(502, f"D-lab 不可达:{out.get('error')}(生产不受影响)")
    # V6.2:D-lab 的 4xx(证据闸 409/重测闸 409/枚举 400)必须原样透传——
    # 此前包在 200 里返回,前端会把被拒的判决显示成"已登记"
    st = int(out.get("status") or 200)
    if st >= 400:
        data = out.get("data") or {}
        raise HTTPException(st, data.get("detail") if isinstance(data, dict) and "detail" in data else data)
    return out
