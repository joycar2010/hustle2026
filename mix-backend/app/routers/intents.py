"""Intent创建+状态流转+手动开仓记录端点"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.routers.ops import require_operator
from app import datasources as ds
import time
import json

router = APIRouter()

class IntentSide(BaseModel):
    venue: str
    side: str
    target_notional: float

class IntentCreate(BaseModel):
    product_code: str
    symbol: str
    side_a: IntentSide
    side_b: Optional[IntentSide] = None
    dry_run: bool = False
    research_note: Optional[str] = None
    hard_loss_budget: Optional[float] = 30.0

@router.post("/operator/intents")
async def create_intent(body: IntentCreate, op=Depends(require_operator)):
    """创建Intent工作项"""
    if body.product_code not in ["C2_PERP_PAIR", "C1", "C3"]:
        raise HTTPException(400, f"Invalid product_code")
    if body.product_code == "C2_PERP_PAIR" and not body.side_b:
        raise HTTPException(400, "C2_PERP_PAIR requires side_b")

    work_item_id = f"wi-{int(time.time())}-{body.product_code.lower().replace('_','-')}"
    work_item = {
        "work_item_id": work_item_id,
        "product_code": body.product_code,
        "symbol": body.symbol,
        "workflow_stage": "DRY_RUN" if body.dry_run else "PROPOSED",
        "side_a": body.side_a.dict(),
        "side_b": body.side_b.dict() if body.side_b else None,
        "research_note": body.research_note,
        "hard_loss_budget": body.hard_loss_budget,
        "created_by": op["operator"],
        "created_at": time.time(),
    }

    r = ds.rds()
    await r.setex(f"dcm:workitem:{work_item_id}", 86400, json.dumps(work_item))
    return work_item

class IntentUpdate(BaseModel):
    action: str
    note: Optional[str] = None

@router.patch("/operator/intents/{work_item_id}")
async def update_intent(work_item_id: str, body: IntentUpdate, op=Depends(require_operator)):
    """更新Intent状态"""
    r = ds.rds()
    key = f"dcm:workitem:{work_item_id}"
    wi_raw = await r.get(key)
    if not wi_raw:
        raise HTTPException(404, f"Intent not found")
    wi = json.loads(wi_raw)

    current_stage = wi.get("workflow_stage")
    if body.action == "APPROVE":
        if current_stage != "DRY_RUN":
            raise HTTPException(400, f"Only DRY_RUN can be approved")
        wi["workflow_stage"] = "PROPOSED"
        wi["approved_by"] = op["operator"]
        wi["approved_at"] = time.time()
    elif body.action == "START_OPENING":
        wi["workflow_stage"] = "OPENING"
        wi["opening_started_at"] = time.time()
    elif body.action == "MARK_HOLDING":
        wi["workflow_stage"] = "HOLDING"
        wi["holding_started_at"] = time.time()
    elif body.action == "CANCEL":
        wi["workflow_stage"] = "CANCELLED"
        wi["cancelled_by"] = op["operator"]
        wi["cancelled_at"] = time.time()
    else:
        raise HTTPException(400, f"Unknown action")

    wi["updated_at"] = time.time()
    await r.setex(key, 86400, json.dumps(wi))
    return wi

class ManualExecution(BaseModel):
    leg: str
    order_id: str
    filled_price: float
    filled_qty: float
    filled_notional: float
    exchange_timestamp: Optional[float] = None
    note: Optional[str] = None

@router.post("/operator/intents/{work_item_id}/record_execution")
async def record_manual_execution(work_item_id: str, body: ManualExecution, op=Depends(require_operator)):
    """记录手动开仓成交数据"""
    r = ds.rds()
    key = f"dcm:workitem:{work_item_id}"
    wi_raw = await r.get(key)
    if not wi_raw:
        raise HTTPException(404, f"Intent not found")
    wi = json.loads(wi_raw)

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

    leg_a_done = "leg_a_execution" in wi
    leg_b_done = "leg_b_execution" in wi

    if leg_a_done and leg_b_done:
        wi["workflow_stage"] = "HOLDING"
        wi["holding_started_at"] = time.time()
        entry_spread = wi["leg_a_execution"]["filled_price"] - wi["leg_b_execution"]["filled_price"]
        wi["entry_spread"] = entry_spread
        status_msg = f"Both legs filled, auto HOLDING. Entry spread: {entry_spread}"
    elif leg_b_done and not leg_a_done:
        temp_delta = -wi["side_b"]["target_notional"]
        wi["temp_delta_usd"] = temp_delta
        status_msg = f"Short leg filled, long pending. Temp Delta: {temp_delta} USD"
    elif leg_a_done and not leg_b_done:
        temp_delta = wi["side_a"]["target_notional"]
        wi["temp_delta_usd"] = temp_delta
        status_msg = f"Long leg filled, short pending. Temp Delta: {temp_delta} USD"
    else:
        status_msg = "Waiting for first leg"

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
