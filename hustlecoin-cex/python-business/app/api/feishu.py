import hashlib
import hmac
import base64
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
import httpx

from app.db.models import FeishuConfig
from app.db.models_auth import User
from app.db.schemas.feishu import FeishuConfigUpdate, FeishuConfigResponse
from app.db.schemas.common import MessageResponse
from app.db.session import get_db
from app.middleware.permissions import get_current_user_id
from app.services.feishu_bot import send_bot_text

router = APIRouter(prefix="/api/feishu", tags=["feishu"])


def _get_or_create(db: Session) -> FeishuConfig:
    # 告警配置是全局行(user_id IS NULL),与引擎 FeishuSender/notifier.fire_template 读取口径一致
    # (多行表 .first() 无序,会让 /rules 绿框读到非引擎所用行 —— 显示=保存=引擎统一到 NULL 行)
    cfg = db.query(FeishuConfig).filter(FeishuConfig.user_id.is_(None)).first()
    if not cfg:
        cfg = FeishuConfig(user_id=None)
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


def _mask_secret(secret: str | None) -> str | None:
    if not secret:
        return None
    if len(secret) <= 4:
        return "****"
    return "****" + secret[-4:]


def _to_response(cfg: FeishuConfig) -> dict:
    return {
        "id": cfg.id,
        "webhook_url": cfg.webhook_url,
        "secret_key_masked": _mask_secret(cfg.secret_key),
        "alert_interval_sec": cfg.alert_interval_sec,
        "alert_count": cfg.alert_count,
        "margin_rate_alert": cfg.margin_rate_alert,
        "leverage_risk_alert": cfg.leverage_risk_alert,
        "enable_transfer_fail_alert": cfg.enable_transfer_fail_alert,
        "enable_new_borrow_alert": cfg.enable_new_borrow_alert,
        "enable_borrow_success_alert": getattr(cfg, "enable_borrow_success_alert", True),
        "enable_repay_success_alert": getattr(cfg, "enable_repay_success_alert", True),
        "updated_at": cfg.updated_at,
    }


@router.get("/", response_model=FeishuConfigResponse)
def get_feishu_config(db: Session = Depends(get_db)):
    return _to_response(_get_or_create(db))


@router.put("/", response_model=FeishuConfigResponse)
def update_feishu_config(data: FeishuConfigUpdate, db: Session = Depends(get_db)):
    cfg = _get_or_create(db)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(cfg, field, value)
    db.commit()
    db.refresh(cfg)
    return _to_response(cfg)


@router.post("/test", response_model=MessageResponse)
async def test_feishu(request: Request, db: Session = Depends(get_db)):
    cfg = _get_or_create(db)
    app_id = getattr(cfg, "app_id", None)
    app_secret = getattr(cfg, "app_secret", None)

    # 优先自建应用机器人:发给当前登录用户的 feishu_open_id(与引擎告警同口径)
    if app_id and app_secret:
        uid = get_current_user_id(request)
        u = db.query(User).filter(User.id == uid).first()
        open_id = getattr(u, "feishu_open_id", None) if u else None
        if not open_id:
            raise HTTPException(status_code=400, detail="当前用户未绑定飞书(feishu_open_id 为空),无法机器人推送")
        import asyncio
        ok, detail = await asyncio.to_thread(
            send_bot_text, app_id, app_secret, open_id, "测试消息", "HustleCoin 飞书通知测试 ✓")
        if not ok:
            raise HTTPException(status_code=502, detail=f"飞书机器人发送失败: {detail}")
        return {"message": "测试消息已通过飞书机器人发送"}

    # 回退:群机器人 webhook
    if not cfg.webhook_url:
        raise HTTPException(status_code=400, detail="飞书未配置(app_id 自建应用 或 webhook 均为空)")
    payload: dict = {
        "msg_type": "text",
        "content": {"text": "HustleCoin CEX-CEX 飞书通知测试 ✓"},
    }
    if cfg.secret_key:
        timestamp = str(int(time.time()))
        string_to_sign = f"{timestamp}\n{cfg.secret_key}"
        hmac_code = hmac.new(string_to_sign.encode("utf-8"), b"", digestmod=hashlib.sha256).digest()
        sign = base64.b64encode(hmac_code).decode("utf-8")
        payload["timestamp"] = timestamp
        payload["sign"] = sign
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(cfg.webhook_url, json=payload)
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Feishu API error: {resp.text}")
        result = resp.json()
        if result.get("code") != 0:
            raise HTTPException(status_code=502, detail=f"Feishu error: {result.get('msg')}")
    return {"message": "Test message sent successfully"}
