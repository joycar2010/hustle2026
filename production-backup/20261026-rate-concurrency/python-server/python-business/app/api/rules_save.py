"""统一规则保存 —— 单事务原子写 feishu + global + fund,带乐观锁与字段级审计 diff。

修回原桌面版「单 config.yaml 原子落盘」的一致性:三块配置要么一起成功,要么一起回滚,
不再出现「global 成功 / fund 失败」的半保存脏态。并发编辑用 version 乐观锁挡 last-write-wins。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ValidationError
from typing import Any, Optional
from sqlalchemy.orm import Session

from app.db.models import GlobalRules, FundRules, FeishuConfig
from app.db.schemas.global_rules import GlobalRulesUpdate
from app.db.schemas.fund_rules import FundRulesUpdate
from app.db.schemas.feishu import FeishuConfigUpdate
from app.db.session import get_db
from app.middleware.permissions import get_current_user_id
from app.services.rule_hysteresis import remove_hierarchy_has_conflict
from app.services.rule_reload import publish_rules_reload
from engine.config_loader import DEFAULT_GLOBAL
from engine.thresholds import push_remove_conflict

router = APIRouter(prefix="/api/rules", tags=["rules"])


class RulesSaveAll(BaseModel):
    feishu: Optional[dict[str, Any]] = None
    global_rules: Optional[dict[str, Any]] = None
    fund_rules: Optional[dict[str, Any]] = None
    expected_global_version: Optional[int] = None
    expected_fund_version: Optional[int] = None


def _apply(obj, validated: dict, prefix: str, diffs: dict) -> None:
    """逐字段 setattr,记录 before/after(仅变化项)到 diffs。version 字段不接受外部写入。"""
    for k, v in validated.items():
        if k == "version":
            continue
        old = getattr(obj, k, None)
        if str(old) != str(v):
            diffs[f"{prefix}.{k}"] = [None if old is None else str(old), None if v is None else str(v)]
        setattr(obj, k, v)


@router.put("/save-all")
def save_all(payload: RulesSaveAll, request: Request, db: Session = Depends(get_db)):
    # ── 字段级校验前置:非法值直接 422,不进事务、不写库 ──
    try:
        gd = (GlobalRulesUpdate(**payload.global_rules).model_dump(exclude_unset=True)
              if payload.global_rules is not None else None)
        fd = (FundRulesUpdate(**payload.fund_rules).model_dump(exclude_unset=True)
              if payload.fund_rules is not None else None)
        cd = (FeishuConfigUpdate(**payload.feishu).model_dump(exclude_unset=True)
              if payload.feishu is not None else None)
    except ValidationError as ve:
        msg = "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in ve.errors())
        raise HTTPException(status_code=422, detail=f"参数校验失败: {msg}")

    # GlobalRules + FundRules 均按登录用户作用域(用户隔离)
    uid = get_current_user_id(request)
    g = db.query(GlobalRules).filter(GlobalRules.user_id == uid).first()
    f = db.query(FundRules).filter(FundRules.user_id == uid).first()

    if gd is not None and ({"auto_push_spread", "remove_spread"} & gd.keys()):
        auto_push = gd.get(
            "auto_push_spread",
            getattr(g, "auto_push_spread", DEFAULT_GLOBAL.auto_push_spread),
        )
        remove_spread = gd.get(
            "remove_spread",
            getattr(g, "remove_spread", DEFAULT_GLOBAL.remove_spread),
        )
        if push_remove_conflict(auto_push, remove_spread) or remove_hierarchy_has_conflict(
            db,
            uid,
            auto_push_spread=auto_push,
            global_remove_spread=remove_spread,
        ):
            raise HTTPException(
                status_code=422,
                detail="点差不足移除必须低于自动推送点差，才能形成稳定迟滞区间",
            )

    # ── 乐观锁:版本不一致 = 期间被他人改过,拒绝覆盖 ──
    if gd is not None and g is not None and payload.expected_global_version is not None:
        if (g.version or 0) != payload.expected_global_version:
            raise HTTPException(status_code=409, detail="交易规则已被他人修改,请刷新后重试")
    if fd is not None and f is not None and payload.expected_fund_version is not None:
        if (f.version or 0) != payload.expected_fund_version:
            raise HTTPException(status_code=409, detail="资金规则已被他人修改,请刷新后重试")

    diffs: dict = {}
    try:
        if gd is not None:
            if g is None:
                g = GlobalRules(user_id=uid)
                db.add(g)
            _apply(g, gd, "global", diffs)
            g.version = (g.version or 0) + 1

        if fd is not None:
            if f is None:
                f = FundRules(user_id=uid)
                db.add(f)
            _apply(f, fd, "fund", diffs)
            f.version = (f.version or 0) + 1

        if cd is not None:
            # Alert settings follow the same tenant boundary as global/fund
            # rules.  A new tenant row inherits the global defaults, then the
            # atomic save applies only this request's fields.
            cfg = db.query(FeishuConfig).filter(FeishuConfig.user_id == uid).first()
            if cfg is None:
                global_cfg = db.query(FeishuConfig).filter(FeishuConfig.user_id.is_(None)).first()
                cfg = FeishuConfig(user_id=uid)
                if global_cfg is not None:
                    for field in (
                        "webhook_url", "secret_key", "app_id", "app_secret",
                        "alert_interval_sec", "alert_count", "risk_alert_cooldown_sec",
                        "margin_rate_alert", "leverage_risk_alert",
                        "enable_transfer_fail_alert", "enable_new_borrow_alert",
                        "enable_borrow_success_alert", "enable_repay_success_alert",
                        "alert_overrides",
                    ):
                        setattr(cfg, field, getattr(global_cfg, field, None))
                db.add(cfg)
            _apply(cfg, cd, "feishu", diffs)

        db.commit()
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"保存失败: {e}")

    # 字段级审计 diff —— 交给审计中间件落入 audit_logs.details(同一请求一行,不重复)
    if diffs:
        try:
            request.state.audit_details = json.dumps(diffs, ensure_ascii=False)[:3900]
        except Exception:
            pass

    if gd is not None or fd is not None:
        publish_rules_reload(uid, "rules-save-all")

    return {
        "global_version": (g.version if g is not None else 0),
        "fund_version": (f.version if f is not None else 0),
        "changed": len(diffs),
    }
