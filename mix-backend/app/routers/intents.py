"""C2.P Intent 创建端点 (P0 紧急)
POST /api/v6/operator/intents - 为 C2.P 双永续创建工作项+DRY_RUN 预演。
"""
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
    side: str  # LONG / SHORT
    target_notional: float

class IntentCreate(BaseModel):
    product_code: str  # C2_PERP_PAIR / C1 / C3
    symbol: str  # BTCUSDT
    side_a: IntentSide
    side_b: Optional[IntentSide] = None  # C1 单边无 side_b
    dry_run: bool = False
    research_note: Optional[str] = None
    hard_loss_budget: Optional[float] = 30.0  # 默认硬亏预算 30U

@router.post("/operator/intents")
async def create_intent(body: IntentCreate, op=Depends(require_operator)):
    """创建 Intent 工作项:C2.P 双永续/C1 现货永续/C3 借币点差。
    DRY_RUN 模式:计算成本/深度/风险但不实际开仓,生成预演报告供审批。"""
    # 验证 product_code
    if body.product_code not in ["C2_PERP_PAIR", "C1", "C3"]:
        raise HTTPException(400, f"product_code 必须为 C2_PERP_PAIR/C1/C3")
    # C2.P 必须双边
    if body.product_code == "C2_PERP_PAIR" and not body.side_b:
        raise HTTPException(400, "C2_PERP_PAIR 必须提供 side_b")
    # 生成 work_item_id
    work_item_id = f"wi-{int(time.time())}-{body.product_code.lower()}"
    # 构造工作项
    pool = await ds.pg()
    if not pool:
        raise HTTPException(503, "数据库不可达")
    # 插入 strategy_workitem 表（假设已存在，若无需创建）
    # 当前简化版：返回模拟工作项
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
    # 保存到 Redis（临时存储，生产应写入 PG strategy_workitem 表）
    await ds.rds().setex(f"dcm:workitem:{work_item_id}", 86400, json.dumps(work_item))
    # DRY_RUN 预演
    if body.dry_run:
        # 计算目标金额可执行报价、成本、风险
        dry_run_result = {
            "executable_spread": "待实现:从 account-snapshot 取 bid/ask",
            "estimated_cost": "待实现:交易费+滑点+保证金",
            "max_loss_scenario": f"硬亏预算 {body.hard_loss_budget}U",
            "recommendation": "人工审批后可开仓",
        }
        work_item["dry_run_result"] = dry_run_result
    return work_item
