"""Notification service API endpoints"""
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import Optional, List
from datetime import datetime, timedelta
from pydantic import BaseModel
import uuid
import logging

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except ImportError:
    from backports.zoneinfo import ZoneInfo  # Python 3.8 fallback

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.notification_config import (
    NotificationConfig,
    NotificationTemplate,
    NotificationLog
)
from app.services.feishu_service import get_feishu_service, init_feishu_service
from app.services.audio_manager import get_audio_file_key

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/test-version")
async def test_version():
    """测试端点 - 验证代码版本"""
    return {"version": "2024-03-06-v2", "message": "新版本代码已加载"}


def get_beijing_time():
    """
    获取当前北京时间（UTC+8），返回不带时区的 naive datetime 对象
    解决数据库 TIMESTAMP WITHOUT TIME ZONE 存储报错问题
    """
    beijing_tz = ZoneInfo("Asia/Shanghai")  # 使用标准时区标识
    beijing_time = datetime.now(beijing_tz)  # 获取带时区的北京时间
    # 移除时区信息，转为 naive datetime（数据库兼容）
    return beijing_time.replace(tzinfo=None)


class SafeFormatter(dict):
    """A dict subclass that returns a placeholder for missing keys"""
    def __missing__(self, key):
        return f'{{{key}}}'


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
    auto_check_enabled: Optional[bool] = None
    # 旧字段（保留兼容）
    alert_sound: Optional[str] = None
    repeat_count: Optional[int] = None
    # 新字段
    alert_sound_file: Optional[str] = None
    alert_sound_repeat: Optional[int] = None
    popup_title_template: Optional[str] = None
    popup_content_template: Optional[str] = None
    is_enabled: Optional[bool] = None


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
    if current_user.role not in ['超级管理员', '系统管理员', '安全管理员', '管理员', 'admin', 'super_admin']:
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
    if current_user.role not in ['超级管理员', '系统管理员', '安全管理员', '管理员', 'admin', 'super_admin']:
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



@router.post("/email/broadcast")
async def send_email_broadcast(
    request: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send a broadcast email to multiple recipients via configured SMTP."""
    if current_user.role not in ['超级管理员', '系统管理员', '安全管理员', '管理员', 'admin', 'super_admin']:
        raise HTTPException(status_code=403, detail="需要管理员权限")

    recipients = request.get('recipients', [])
    subject = request.get('subject', '系统通知')
    body = request.get('body', '')

    if not recipients:
        raise HTTPException(status_code=422, detail="至少需要一个收件人")
    if not subject or not body:
        raise HTTPException(status_code=422, detail="主题和内容不能为空")

    try:
        from app.services.email_service import email_service
        html_body = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;background:#f5f5f5;padding:20px;">
  <div style="background:#fff;border-radius:8px;max-width:600px;margin:0 auto;padding:24px;">
    <pre style="white-space:pre-wrap;font-family:inherit;font-size:14px;line-height:1.7;">{body}</pre>
  </div>
</body></html>"""
        success = await email_service.send_email(db, recipients, subject, html_body, body)
        if success:
            return {"success": True, "message": f"已发送给 {len(recipients)} 个收件人"}
        else:
            raise HTTPException(status_code=503, detail="SMTP 发送失败，请检查邮件配置")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test/{service_type}")
async def test_notification_service(
    service_type: str,
    recipient: str = Query(..., description="接收者ID（飞书open_id/邮箱/手机号）"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Test notification service"""
    if current_user.role not in ['超级管理员', '系统管理员', '安全管理员', '管理员', 'admin', 'super_admin']:
        raise HTTPException(status_code=403, detail="需要管理员权限")

    if service_type == "feishu":
        feishu = get_feishu_service()
        if not feishu:
            raise HTTPException(status_code=400, detail="飞书服务未初始化，请先配置并启用")

        try:
            # Detect recipient type
            # Phone numbers: start with + or digits only (with optional country code)
            # Open ID: starts with "ou_"
            # Email: contains @
            if recipient.startswith("ou_"):
                receive_id_type = "open_id"
            elif "@" in recipient:
                receive_id_type = "email"
            elif recipient.startswith("+") or recipient.isdigit():
                receive_id_type = "mobile"
                # Ensure phone number has country code
                if not recipient.startswith("+"):
                    recipient = "+86" + recipient  # Default to China country code
            else:
                # Default to open_id for unknown formats
                receive_id_type = "open_id"

            logger.info(f"发送飞书测试消息: recipient={recipient}, type={receive_id_type}")

            beijing_time = get_beijing_time()
            result = await feishu.send_card_message(
                receive_id=recipient,
                title="🧪 测试消息",
                content="**这是一条测试消息**\n\n如果您收到此消息，说明飞书通知服务配置成功！\n\n测试时间：" +
                        beijing_time.strftime("%Y-%m-%d %H:%M:%S") + " (北京时间)",
                receive_id_type=receive_id_type,
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


@router.get("/feishu/status")
async def get_feishu_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get Feishu service status"""
    if current_user.role not in ['超级管理员', '系统管理员', '安全管理员', '管理员', 'admin', 'super_admin']:
        raise HTTPException(status_code=403, detail="需要管理员权限")

    feishu = get_feishu_service()
    if not feishu:
        return {
            "connected": False,
            "error": "飞书服务未初始化",
            "token_expires_at": None
        }

    try:
        # Try to get token to verify connection
        token = await feishu.get_tenant_access_token()
        if token:
            return {
                "connected": True,
                "token_expires_at": feishu.token_expires_at.isoformat() if feishu.token_expires_at else None,
                "error": None
            }
        else:
            return {
                "connected": False,
                "error": "无法获取访问令牌",
                "token_expires_at": None
            }
    except Exception as e:
        logger.error(f"检查飞书服务状态失败: {e}")
        return {
            "connected": False,
            "error": str(e),
            "token_expires_at": None
        }


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
    logger.info("=== 获取通知模板列表 - 新版本代码 ===")
    query = select(NotificationTemplate).filter(
        NotificationTemplate.is_active == True
    )

    if category:
        query = query.filter(NotificationTemplate.category == category)

    result = await db.execute(query.order_by(NotificationTemplate.category, NotificationTemplate.priority.desc()))
    templates = result.scalars().all()

    response_data = {
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
                # 旧字段（保留兼容）
                "alert_sound": t.alert_sound,
                "repeat_count": t.repeat_count,
                # 新字段
                "alert_sound_file": t.alert_sound_file,
                "alert_sound_repeat": t.alert_sound_repeat,
                "popup_title_template": t.popup_title_template,
                "popup_content_template": t.popup_content_template,
                "is_enabled": t.is_active,
                "updated_at": t.updated_at.isoformat() if t.updated_at else None
            }
            for t in templates
        ]
    }

    # 调试日志：打印第一个模板的关键字段
    if response_data["templates"]:
        first = response_data["templates"][0]
        logger.info(f"API返回第一个模板: {first['template_name']}")
        logger.info(f"  - alert_sound: {first.get('alert_sound')}")
        logger.info(f"  - repeat_count: {first.get('repeat_count')}")
        logger.info(f"  - is_enabled: {first.get('is_enabled')}")

    return response_data


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
            "cooldown_seconds": template.cooldown_seconds,
            # 旧字段（保留兼容）
            "alert_sound": template.alert_sound,
            "repeat_count": template.repeat_count,
            # 新字段
            "alert_sound_file": template.alert_sound_file,
            "alert_sound_repeat": template.alert_sound_repeat,
            "popup_title_template": template.popup_title_template,
            "popup_content_template": template.popup_content_template
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
    if current_user.role not in ['超级管理员', '系统管理员', '安全管理员', '管理员', 'admin', 'super_admin']:
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
    logger.info(f"更新模板 {template.template_name}, 数据: {update_data}")

    for key, value in update_data.items():
        # Map is_enabled to is_active
        if key == 'is_enabled':
            logger.info(f"设置 is_active = {value}")
            setattr(template, 'is_active', value)
        elif hasattr(template, key):
            setattr(template, key, value)

    template.updated_at = datetime.utcnow()
    await db.commit()

    logger.info(f"模板更新成功: {template.template_name}, is_active={template.is_active}")

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
    """Send notification to users (admin only)"""
    ADMIN_ROLES = {'超级管理员', '系统管理员', '安全管理员', '管理员', 'admin', 'super_admin'}
    if current_user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="需要管理员权限")

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

    # Render template with safe formatting (missing variables will be shown as {variable_name})
    try:
        safe_vars = SafeFormatter(request.variables)
        title = template.title_template.format_map(safe_vars)
        content = template.content_template.format_map(safe_vars)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"模板渲染失败: {str(e)}")

    # Send notifications
    results = []
    feishu = get_feishu_service()

    logger.info(f"Feishu service status: {'initialized' if feishu else 'not initialized'}")
    logger.info(f"Template enable_feishu: {template.enable_feishu}")

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
                # Use feishu_open_id if available, fallback to feishu_mobile, then email
                feishu_user_id = user.feishu_open_id or user.feishu_mobile or user.email
                receive_id_type = "open_id" if user.feishu_open_id else ("mobile" if user.feishu_mobile else "email")

                try:
                    # Determine color based on priority
                    color_map = {1: "blue", 2: "blue", 3: "orange", 4: "red"}
                    color = color_map.get(template.priority, "blue")

                    # Check if template has alert sound
                    if template.alert_sound and template.alert_sound.strip():
                        # Get audio file_key
                        audio_file_key = await get_audio_file_key(feishu, template.alert_sound)

                        if audio_file_key:
                            # Send card with audio
                            logger.info(f"发送带音频的卡片消息: {template.alert_sound}")
                            result = await feishu.send_card_with_audio(
                                receive_id=feishu_user_id,
                                title=title,
                                content=content,
                                audio_file_key=audio_file_key,
                                audio_title=f"{template.template_name}提醒",
                                receive_id_type=receive_id_type,
                                color=color,
                                loop=True,  # 循环播放
                                auto_play=True  # 自动播放
                            )
                        else:
                            # Fallback to normal card if audio upload failed
                            logger.warning(f"音频文件上传失败，发送普通卡片: {template.alert_sound}")
                            result = await feishu.send_card_message(
                                receive_id=feishu_user_id,
                                title=title,
                                content=content,
                                receive_id_type=receive_id_type,
                                color=color
                            )
                    else:
                        # Send normal card without audio
                        result = await feishu.send_card_message(
                            receive_id=feishu_user_id,
                            title=title,
                            content=content,
                            receive_id_type=receive_id_type,
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
                        sent_at=get_beijing_time() if result.get("success") else None
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
    if current_user.role not in ['超级管理员', '系统管理员', '安全管理员', '管理员', 'admin', 'super_admin']:
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
