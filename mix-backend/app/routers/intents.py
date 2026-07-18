"""C2.P Intent 状态流转端点 (Phase 3 简化版)
PATCH /api/v6/operator/intents/{work_item_id} - 状态流转: DRY_RUN → PROPOSED → OPENING → HOLDING
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.routers.ops import require_operator
from app import datasources as ds
import time
import json

router = APIRouter()

class IntentUpdate(BaseModel):
    action: str  # APPROVE / START_OPENING / MARK_HOLDING / CANCEL
    note: Optional[str] = None

@router.patch("/operator/intents/{work_item_id}")
async def update_intent(work_item_id: str, body: IntentUpdate, op=Depends(require_operator)):
    """更新 Intent 状态:
    - APPROVE: DRY_RUN → PROPOSED (人工审批通过)
    - START_OPENING: PROPOSED → OPENING (开始执行开仓)
    - MARK_HOLDING: OPENING → HOLDING (两腿成交完成)
    - CANCEL: 任意阶段 → CANCELLED"""
    r = ds.rds()
    key = f"dcm:workitem:{work_item_id}"
    wi_raw = await r.get(key)
    if not wi_raw:
        raise HTTPException(404, f"Intent {work_item_id} 不存在")
    wi = json.loads(wi_raw)

    # 状态机
    current_stage = wi.get("workflow_stage")
    if body.action == "APPROVE":
        if current_stage != "DRY_RUN":
            raise HTTPException(400, f"只有 DRY_RUN 状态可审批,当前 {current_stage}")
        wi["workflow_stage"] = "PROPOSED"
        wi["approved_by"] = op["operator"]
        wi["approved_at"] = time.time()
    elif body.action == "START_OPENING":
        if current_stage != "PROPOSED":
            raise HTTPException(400, f"只有 PROPOSED 可开仓,当前 {current_stage}")
        wi["workflow_stage"] = "OPENING"
        wi["opening_started_at"] = time.time()
        wi["opening_note"] = body.note or "手动开仓:操作员在交易所执行"
    elif body.action == "MARK_HOLDING":
        if current_stage != "OPENING":
            raise HTTPException(400, f"只有 OPENING 可标记 HOLDING,当前 {current_stage}")
        wi["workflow_stage"] = "HOLDING"
        wi["holding_started_at"] = time.time()
        # TODO: 记录实际成交价、数量、时间差
        wi["legs_executed"] = body.note or "待补充:实际成交详情"
    elif body.action == "CANCEL":
        wi["workflow_stage"] = "CANCELLED"
        wi["cancelled_by"] = op["operator"]
        wi["cancelled_at"] = time.time()
        wi["cancel_reason"] = body.note
    else:
        raise HTTPException(400, f"未知 action: {body.action}")

    wi["updated_at"] = time.time()
    await r.setex(key, 86400, json.dumps(wi))
    return wi
