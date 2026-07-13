"""策略总览 + 明细。数据真源：引擎快照(Redis) + dcm_main 仓位表 + income 归因。"""
from fastapi import APIRouter, Depends, Header, HTTPException
from ..enums import StrategyCode
from ..deps import require_operator, require_viewer, not_wired
from .. import adapters
from .. import proxy

router = APIRouter(prefix="/strategies", tags=["strategies"])

# 引擎级模式热切换能力:S2(dualperp)经 gateway engine_config 热切(联锁+审计在 gateway);
# S1(basis)/S4(lending) 模式在引擎 env,须 SSH 重启,不做网页热切(诚实标注);S3=coin 独立门闸;S5/S6 未建。
MODE_ENGINE = {"S2": "dualperp"}
MODES = ("shadow", "armed")


@router.get("")
async def strategies(_who=Depends(require_viewer)):
    """六策略卡。S1/S2/S3 真数据；S4 仅数据无回路、S5/S6 未启用 —— 如实标注，不用演示数冒充。"""
    return await adapters.strategies_overview()


@router.get("/{code}")
async def strategy_detail(code: StrategyCode, _who=Depends(require_viewer)):
    overview = await adapters.strategies_overview()
    me = next((s for s in overview if s["code"] == code.value), {})
    rows = await adapters.position_rows(code.value)
    return {**me, "rows": rows}


@router.post("/{code}/toggle", status_code=202)
async def strategy_toggle(code: StrategyCode, op=Depends(require_operator)):
    """启停 = 高危写。P2 代理 dcm gateway engine_config（confirm=ARM 联锁在那边）。"""
    not_wired(f"strategies/{code.value}/toggle")


@router.post("/{code}/mode")
async def strategy_mode(code: StrategyCode, body: dict, op=Depends(require_operator),
                        x_op_token: str | None = Header(default=None)):
    """引擎模式热切换（shadow/armed）。仅 S2 支持网页热切（gateway 权威:武装联锁+confirm=ARM+审计）。
    armed 是全项目最不可逆动作——切 armed 必须带 confirm=ARM（前端二次确认透传）。"""
    engine = MODE_ENGINE.get(code.value)
    if not engine:
        raise HTTPException(501, f"{code.value} 模式在引擎 env（须 SSH 重启），不支持网页热切；"
                                 f"S3=coin 独立门闸，S5/S6 策略未建")
    mode = str(body.get("mode") or "")
    if mode not in MODES:
        raise HTTPException(400, "mode 必须是 shadow / armed")
    confirm = body.get("confirm") if mode == "armed" else None
    if mode == "armed" and confirm != "ARM":
        raise HTTPException(428, "切 armed 需二次确认（confirm=ARM）——真金下单联锁")
    status, data = await proxy.gateway_engine_config(x_op_token, "mode", mode, confirm)
    await proxy.audit(op["operator"], op["role"], "strategy.mode", f"{code.value}:{engine}",
                      {"mode": mode}, f"{status}:{str(data)[:120]}")
    if status >= 400:
        raise HTTPException(status if status < 500 else 502,
                            data.get("error") or f"gateway 拒绝：{str(data)[:120]}")
    return {"ok": True, "code": code.value, "mode": mode, "gateway": data,
            "note": "引擎 3s 回读生效；armed 联锁要求风控全绿"}
