"""Intent创建+状态流转+手动开仓记录端点"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.routers.ops import require_operator
from app import datasources as ds
import time
import json

router = APIRouter()

# 持有期3-7天,TTL须覆盖全生命周期;每次写操作续期
_WI_TTL = 30 * 86400

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
    await r.setex(f"dcm:workitem:{work_item_id}", _WI_TTL, json.dumps(work_item))
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
    await r.setex(key, _WI_TTL, json.dumps(wi))
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
    await r.setex(key, _WI_TTL, json.dumps(wi))

    return {
        "work_item_id": work_item_id,
        "recorded_leg": body.leg,
        "workflow_stage": wi["workflow_stage"],
        "leg_a_done": leg_a_done,
        "leg_b_done": leg_b_done,
        "status": status_msg,
    }


def _leg_pnl(side: str, entry_price: float, exit_price: float, qty: float) -> float:
    # 线性USDT合约: 多腿=(卖出-买入)×qty, 空腿=(开空-买回)×qty
    if (side or "").lower() in ("long", "buy"):
        return (exit_price - entry_price) * qty
    return (entry_price - exit_price) * qty


@router.post("/operator/intents/{work_item_id}/record_close")
async def record_manual_close(work_item_id: str, body: ManualExecution, op=Depends(require_operator)):
    """记录手动平仓成交数据;两腿平完自动CLOSED+按逐腿真实成交价算realized_pnl"""
    r = ds.rds()
    key = f"dcm:workitem:{work_item_id}"
    wi_raw = await r.get(key)
    if not wi_raw:
        raise HTTPException(404, "Intent not found")
    wi = json.loads(wi_raw)
    if wi.get("workflow_stage") not in ("HOLDING", "CLOSING"):
        raise HTTPException(400, f"stage={wi.get('workflow_stage')},只有HOLDING/CLOSING可记录平仓")
    open_exec = wi.get(f"{body.leg}_execution")
    if not open_exec:
        raise HTTPException(400, f"{body.leg}无开仓成交记录,无法平仓对账")

    wi[f"{body.leg}_close"] = {
        "order_id": body.order_id,
        "filled_price": body.filled_price,
        "filled_qty": body.filled_qty,
        "filled_notional": body.filled_notional,
        "exchange_timestamp": body.exchange_timestamp or time.time(),
        "recorded_by": op["operator"],
        "recorded_at": time.time(),
        "note": body.note,
    }
    wi["workflow_stage"] = "CLOSING"

    a_closed, b_closed = "leg_a_close" in wi, "leg_b_close" in wi
    two_legs = bool(wi.get("side_b"))
    if a_closed and (b_closed or not two_legs):
        pnl = _leg_pnl(wi["side_a"].get("side"), wi["leg_a_execution"]["filled_price"],
                       wi["leg_a_close"]["filled_price"], wi["leg_a_close"]["filled_qty"])
        recon = {"leg_a_price_pnl": pnl}
        if two_legs:
            pb = _leg_pnl(wi["side_b"].get("side"), wi["leg_b_execution"]["filled_price"],
                          wi["leg_b_close"]["filled_price"], wi["leg_b_close"]["filled_qty"])
            recon["leg_b_price_pnl"] = pb
            pnl += pb
        wi["realized_price_pnl"] = pnl  # 价格腿PnL;资金费/手续费以交易所账单为权威,RECON待账单
        recon["note"] = "价格腿PnL(逐腿真实成交价);净PnL须叠加交易所账单funding/fee"
        wi["recon"] = recon
        wi["workflow_stage"] = "CLOSED"
        wi["closed_at"] = time.time()
        status_msg = f"All legs closed. Realized price PnL: {round(pnl, 6)}"
    else:
        status_msg = "leg closed, waiting for remaining leg"

    wi["updated_at"] = time.time()
    await r.setex(key, _WI_TTL, json.dumps(wi))
    return {
        "work_item_id": work_item_id,
        "recorded_leg": body.leg,
        "workflow_stage": wi["workflow_stage"],
        "realized_price_pnl": wi.get("realized_price_pnl"),
        "status": status_msg,
    }


@router.get("/operator/intents")
async def list_intents(op=Depends(require_operator)):
    """列出全部Intent工作项(Redis dcm:workitem:*)"""
    r = ds.rds()
    out = []
    async for k in r.scan_iter(match="dcm:workitem:wi-*", count=200):
        raw = await r.get(k)
        if raw:
            try:
                out.append(json.loads(raw))
            except Exception:
                continue
    out.sort(key=lambda w: w.get("created_at") or 0, reverse=True)
    return {"rows": out, "total": len(out)}


@router.get("/operator/intents/{work_item_id}")
async def get_intent(work_item_id: str, op=Depends(require_operator)):
    r = ds.rds()
    raw = await r.get(f"dcm:workitem:{work_item_id}")
    if not raw:
        raise HTTPException(404, "Intent not found")
    return json.loads(raw)
