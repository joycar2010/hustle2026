"""策略总览 + 明细。数据真源：引擎快照(Redis) + dcm_main 仓位表 + income 归因。"""
from fastapi import APIRouter, Depends
from ..enums import StrategyCode
from ..deps import require_operator, require_viewer, not_wired
from .. import adapters

router = APIRouter(prefix="/strategies", tags=["strategies"])


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
