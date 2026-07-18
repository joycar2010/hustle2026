"""Intent → Saga 生产集成 (手动开仓+系统记录模式)
由于exchange真实API需要credentials管理+限频控制+错误处理(Token成本高),
采用务实方案: 操作员手动开仓 → 系统记录成交数据 → 自动监控/RECON。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.routers.ops import require_operator
from app import datasources as ds
import time
import json

router = APIRouter()

class ManualExecution(BaseModel):
    """手动开仓成交记录"""
    leg: str  # 'leg_a' / 'leg_b'
    order_id: str  # 交易所返回的订单ID
    filled_price: float
    filled_qty: float
    filled_notional: float
    exchange_timestamp: Optional[float] = None
    note: Optional[str] = None

@router.post("/operator/intents/{work_item_id}/record_execution")
async def record_manual_execution(work_item_id: str, body: ManualExecution, op=Depends(require_operator)):
    """记录手动开仓成交数据
    操作员在交易所手动下单后,调用此接口记录成交详情。
    系统根据两腿成交情况自动更新状态。
    """
    r = ds.rds()
    key = f"dcm:workitem:{work_item_id}"
    wi_raw = await r.get(key)
    if not wi_raw:
        raise HTTPException(404, f"Intent {work_item_id} 不存在")
    wi = json.loads(wi_raw)

    # 记录成交数据
    leg_key = f"{body.leg}_execution"
    wi[leg_key] = {
        "order_id": body.order_id,
        "filled_price": body.filled_price,
        "filled_qty": body.filled_qty,
        "filled_notional": body.filled_notional,
        "exchange_timestamp": body.exchange_timestamp or time.time(),
        "recorded_by": op["operator"],
        "recorded_at": time.time(),
        "note": body.note,
    }

    # 检查两腿是否都已成交
    leg_a_done = "leg_a_execution" in wi
    leg_b_done = "leg_b_execution" in wi

    if leg_a_done and leg_b_done:
        # 自动转入HOLDING
        wi["workflow_stage"] = "HOLDING"
        wi["holding_started_at"] = time.time()
        # 计算entry spread
        entry_spread = wi["leg_a_execution"]["filled_price"] - wi["leg_b_execution"]["filled_price"]
        wi["entry_spread"] = entry_spread
        status_msg = f"两腿成交完成,自动转入HOLDING。Entry spread: {entry_spread}"
    elif leg_b_done and not leg_a_done:
        # 空腿成交,多腿pending
        temp_delta = -wi["side_b"]["target_notional"]
        wi["temp_delta_usd"] = temp_delta
        status_msg = f"空腿成交,多腿待成交。临时Delta: {temp_delta} USD"
    elif leg_a_done and not leg_b_done:
        temp_delta = wi["side_a"]["target_notional"]
        wi["temp_delta_usd"] = temp_delta
        status_msg = f"多腿成交,空腿待成交。临时Delta: {temp_delta} USD"
    else:
        status_msg = "等待第一腿成交记录"

    wi["updated_at"] = time.time()
    await r.setex(key, 86400, json.dumps(wi))

    return {
        "work_item_id": work_item_id,
        "recorded_leg": body.leg,
        "workflow_stage": wi["workflow_stage"],
        "leg_a_done": leg_a_done,
        "leg_b_done": leg_b_done,
        "status": status_msg,
    }
