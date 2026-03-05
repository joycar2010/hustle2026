"""Notification service API endpoints"""
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel
import uuid

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.notification_config import (
    NotificationConfig,
    NotificationTemplate,
    NotificationLog
)
from app.services.feishu_service import get_feishu_service, init_feishu_service
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


# Pydantic models
class NotificationConfigUpdate(BaseModel):
    is_enabled: bool
    config_data: dict


class NotificationTemplateUpdate(BaseModel):
    template_name: Optional[str] = None
    title_template: Optional[str] = None
    content_template: Optional[str] = None
    enable_email: Optional[bool] = None
    enable_sms: Optional[bool] = None
    enable_feishu: Optional[bool] = None
    priority: Optional[int] = None
    cooldown_seconds: Optional[int] = None


class SendNotificationRequest(BaseModel):
    template_key: str
    user_ids: List[str]
    variables: dict


# ============================================================================
# Configuration Management
# ============================================================================

@router.get("/config")
async def get_notification_configs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all notification service configurations"""
    # Check admin permission
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")

    result = await db.execute(select(NotificationConfig))
    configs = result.scalars().all()

    return {
        "success": True,
        "configs": [
            {
                "service_type": c.service_type,
                "is_enabled": c.is_enabled,
                "config_data": c.config_data,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None
            }
            for c in configs
        ]
    }


@router.put("/config/{service_type}")
async def update_notification_config(
    service_type: str,
    config_update: NotificationConfigUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update notification service configuration"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")

    # Validate service type
    if service_type not in ["email", "sms", "feishu"]:
        raise HTTPException(status_code=400, detail="不支持的服务类型")

    # Find or create config
    result = await db.execute(
        select(NotificationConfig).filter(
            NotificationConfig.service_type == service_type
        )
    )
    config = result.scalar_one_or_none()

    if not config:
        config = NotificationConfig(
            service_type=service_type,
            is_enabled=config_update.is_enabled,
            config_data=config_update.config_data
        )
        db.add(config)
    else:
        config.is_enabled = config_update.is_enabled
        config.config_data = config_update.config_data
        config.updated_at = datetime.utcnow()

    await db.commit()

    # If Feishu config, reinitialize service
    if service_type == "feishu" and config_update.is_enabled:
        try:
            init_feishu_service(
                config_update.config_data.get("app_id"),
                config_update.config_data.get("app_secret")
            )
            logger.info("飞书服务已重新初始化")
        except Exception as e:
            logger.error(f"飞书服务初始化失败: {e}")
            raise HTTPException(status_code=500, detail=f"飞书服务初始化失败: {str(e)}")

    return {"success": True, "message": "配置已更新"}


@router.post("/test/{service_type}")
async def test_notification_service(
    service_type: str,
    recipient: str = Query(..., description="接收者ID（飞书open_id/邮箱/手机号）"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Test notification service"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")

    if service_type == "feishu":
        feishu = get_feishu_service()
        if not feishu:
            raise HTTPException(status_code=400, detail="飞书服务未初始化，请先配置并启用")

        try:
            result = await feishu.send_card_message(
                receive_id=recipient,
                title="🧪 测试消息",
                content="**这是一条测试消息**\n\n如果您收到此消息，说明飞书通知服务配置成功！\n\n测试时间：" +
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                color="blue"
            )

            if result.get("success"):
                return {"success": True, "message": "测试消息发送成功", "message_id": result.get("message_id")}
            else:
                return {"success": False, "error": result.get("error")}

        except Exception as e:
            logger.error(f"飞书测试消息发送失败: {e}")
            raise HTTPException(status_code=500, detail=f"发送失败: {str(e)}")

    elif service_type == "email":
        # TODO: Implement email test
        raise HTTPException(status_code=501, detail="邮件服务暂未实现")

    elif service_type == "sms":
        # TODO: Implement SMS test
        raise HTTPException(status_code=501, detail="短信服务暂未实现")

    else:
        raise HTTPException(status_code=400, detail="不支持的服务类型")


# ============================================================================
# Template Management
# ============================================================================

@router.get("/templates")
async def get_notification_templates(
    category: Optional[str] = Query(None, description="模板分类：trading, risk, system"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get notification templates"""
    query = select(NotificationTemplate).filter(
        NotificationTemplate.is_active == True
    )

    if category:
        query = query.filter(NotificationTemplate.category == category)

    result = await db.execute(query.order_by(NotificationTemplate.category, NotificationTemplate.priority.desc()))
    templates = result.scalars().all()

    return {
        "success": True,
        "templates": [
            {
                "template_id": str(t.template_id),
                "template_key": t.template_key,
                "template_name": t.template_name,
                "category": t.category,
                "title_template": t.title_template,
                "content_template": t.content_template,
                "enable_email": t.enable_email,
                "enable_sms": t.enable_sms,
                "enable_feishu": t.enable_feishu,
                "priority": t.priority,
                "cooldown_seconds": t.cooldown_seconds,
                "updated_at": t.updated_at.isoformat() if t.updated_at else None
            }
            for t in templates
        ]
    }


@router.get("/templates/{template_id}")
async def get_notification_template(
    template_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get single notification template"""
    result = await db.execute(
        select(NotificationTemplate).filter(
            NotificationTemplate.template_id == uuid.UUID(template_id)
        )
    )
    template = result.scalar_one_or_none()

    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    return {
        "success": True,
        "template": {
            "template_id": str(template.template_id),
            "template_key": template.template_key,
            "template_name": template.template_name,
            "category": template.category,
            "title_template": template.title_template,
            "content_template": template.content_template,
            "enable_email": template.enable_email,
            "enable_sms": template.enable_sms,
            "enable_feishu": template.enable_feishu,
            "priority": template.priority,
            "cooldown_seconds": template.cooldown_seconds
        }
    }


@router.put("/templates/{template_id}")
async def update_notification_template(
    template_id: str,
    template_update: NotificationTemplateUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update notification template"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")

    result = await db.execute(
        select(NotificationTemplate).filter(
            NotificationTemplate.template_id == uuid.UUID(template_id)
        )
    )
    template = result.scalar_one_or_none()

    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    # Update fields
    update_data = template_update.dict(exclude_unset=True)
    for key, value in update_data.items():
        if hasattr(template, key):
            setattr(template, key, value)

    template.updated_at = datetime.utcnow()
    await db.commit()

    return {"success": True, "message": "模板已更新"}


# ============================================================================
# Send Notifications
# ============================================================================

@router.post("/send")
async def send_notification(
    request: SendNotificationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send notification to users"""
    # Get template
    result = await db.execute(
        select(NotificationTemplate).filter(
            and_(
                NotificationTemplate.template_key == request.template_key,
                NotificationTemplate.is_active == True
            )
        )
    )
    template = result.scalar_one_or_none()

    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    # Render template
    try:
        title = template.title_template.format(**request.variables)
        content = template.content_template.format(**request.variables)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"模板变量缺失: {str(e)}")

    # Send notifications
    results = []
    feishu = get_feishu_service()

    for user_id_str in request.user_ids:
        try:
            user_id = uuid.UUID(user_id_str)

            # Get user
            user_result = await db.execute(
                select(User).filter(User.user_id == user_id)
            )
            user = user_result.scalar_one_or_none()

            if not user:
                logger.warning(f"用户不存在: {user_id_str}")
                continue

            # Send Feishu notification
            if template.enable_feishu and feishu:
                # For now, use email as feishu_user_id (should be configured separately)
                feishu_user_id = user.email  # TODO: Add feishu_user_id to user settings

                try:
                    # Determine color based on priority
                    color_map = {1: "blue", 2: "blue", 3: "orange", 4: "red"}
                    color = color_map.get(template.priority, "blue")

                    result = await feishu.send_card_message(
                        receive_id=feishu_user_id,
                        title=title,
                        content=content,
                        receive_id_type="email",  # Use email as receive_id_type
                        color=color
                    )

                    # Log notification
                    log = NotificationLog(
                        user_id=user_id,
                        template_key=request.template_key,
                        service_type="feishu",
                        recipient=feishu_user_id,
                        title=title,
                        content=content,
                        status="sent" if result.get("success") else "failed",
                        error_message=result.get("error"),
                        sent_at=datetime.utcnow() if result.get("success") else None
                    )
                    db.add(log)

                    results.append({
                        "user_id": user_id_str,
                        "service": "feishu",
                        "success": result.get("success"),
                        "error": result.get("error")
                    })

                except Exception as e:
                    logger.error(f"发送飞书通知失败 (用户 {user_id_str}): {e}")
                    results.append({
                        "user_id": user_id_str,
                        "service": "feishu",
                        "success": False,
                        "error": str(e)
                    })

        except Exception as e:
            logger.error(f"处理用户通知失败 ({user_id_str}): {e}")
            results.append({
                "user_id": user_id_str,
                "success": False,
                "error": str(e)
            })

    await db.commit()

    success_count = sum(1 for r in results if r.get("success"))
    failed_count = len(results) - success_count

    return {
        "success": success_count > 0,
        "total": len(request.user_ids),
        "sent_count": success_count,
        "failed_count": failed_count,
        "results": results
    }


# ============================================================================
# Notification Logs
# ============================================================================

@router.get("/logs")
async def get_notification_logs(
    user_id: Optional[str] = Query(None, description="用户ID"),
    service_type: Optional[str] = Query(None, description="服务类型"),
    status: Optional[str] = Query(None, description="状态"),
    limit: int = Query(50, le=200, description="返回数量"),
    offset: int = Query(0, description="偏移量"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get notification logs"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")

    query = select(NotificationLog)

    if user_id:
        query = query.filter(NotificationLog.user_id == uuid.UUID(user_id))
    if service_type:
        query = query.filter(NotificationLog.service_type == service_type)
    if status:
        query = query.filter(NotificationLog.status == status)

    query = query.order_by(NotificationLog.created_at.desc()).limit(limit).offset(offset)

    result = await db.execute(query)
    logs = result.scalars().all()

    return {
        "success": True,
        "logs": [
            {
                "log_id": str(log.log_id),
                "user_id": str(log.user_id) if log.user_id else None,
                "template_key": log.template_key,
                "service_type": log.service_type,
                "recipient": log.recipient,
                "title": log.title,
                "status": log.status,
                "error_message": log.error_message,
                "sent_at": log.sent_at.isoformat() if log.sent_at else None,
                "created_at": log.created_at.isoformat()
            }
            for log in logs
        ],
        "total": len(logs),
        "limit": limit,
        "offset": offset
    }
