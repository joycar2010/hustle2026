import hashlib
import hmac
import base64
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
import httpx

from app.db.models import FeishuConfig
from app.db.schemas.feishu import FeishuConfigUpdate, FeishuConfigResponse
from app.db.schemas.common import MessageResponse
from app.db.session import get_db
from app.middleware.permissions import get_current_user_id

router = APIRouter(prefix="/api/feishu", tags=["feishu"])


def _get_or_create(db: Session, user_id: int) -> FeishuConfig:
    cfg = db.query(FeishuConfig).filter(FeishuConfig.user_id == user_id).first()
    if not cfg:
        cfg = FeishuConfig(user_id=user_id)
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
        "updated_at": cfg.updated_at,
    }


@router.get("/", response_model=FeishuConfigResponse)
def get_feishu_config(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    return _to_response(_get_or_create(db, user_id))


@router.put("/", response_model=FeishuConfigResponse)
def update_feishu_config(data: FeishuConfigUpdate, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    cfg = _get_or_create(db, user_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(cfg, field, value)
    db.commit()
    db.refresh(cfg)
    return _to_response(cfg)


@router.post("/test", response_model=MessageResponse)
async def test_feishu(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    cfg = _get_or_create(db, user_id)
    if not cfg.webhook_url:
        raise HTTPException(status_code=400, detail="Webhook URL not configured")

    payload: dict = {
        "msg_type": "text",
        "content": {"text": "HustleCoin CEX-CEX 飞书通知测试 ✓"},
    }

    if cfg.secret_key:
        timestamp = str(int(time.time()))
        string_to_sign = f"{timestamp}\n{cfg.secret_key}"
        hmac_code = hmac.new(
            string_to_sign.encode("utf-8"),
            b"",
            digestmod=hashlib.sha256,
        ).digest()
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
