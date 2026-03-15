"""密钥管理API路由"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from pydantic import BaseModel, Field
import logging

from app.core.database import get_db
from app.core.security import get_current_user_id_optional
from app.services.key_management import get_key_management_service

router = APIRouter()
logger = logging.getLogger(__name__)


# ==================== Schemas ====================

class KeyGenerateRequest(BaseModel):
    """生成密钥请求"""
    key_name: str = Field(..., min_length=1, max_length=100, description="密钥名称")
    key_type: str = Field(default="api", description="密钥类型: api, encryption, signing")
    length: int = Field(default=32, ge=16, le=64, description="密钥长度(字节)")


class KeyResponse(BaseModel):
    """密钥响应"""
    key_name: str
    key_type: str
    current_version: int
    versions_count: int
    created_at: str
    is_active: bool


class KeyValueResponse(BaseModel):
    """密钥值响应"""
    key_name: str
    key_value: str
    version: int


class KeyRotateRequest(BaseModel):
    """密钥轮换请求"""
    max_versions: int = Field(default=3, ge=1, le=10, description="保留的最大版本数")


# ==================== API Endpoints ====================

@router.post("/keys/generate", response_model=KeyValueResponse)
async def generate_key(
    request: KeyGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user_id: Optional[str] = Depends(get_current_user_id_optional)
):
    """生成新密钥"""
    try:
        key_service = get_key_management_service(db)

        # 生成密钥
        key_value = key_service.generate_key(
            key_type=request.key_type,
            length=request.length
        )

        # 存储密钥
        await key_service.store_key(
            key_name=request.key_name,
            key_value=key_value,
            key_type=request.key_type
        )

        logger.info(f"Generated key: {request.key_name}, type: {request.key_type}")

        return KeyValueResponse(
            key_name=request.key_name,
            key_value=key_value,
            version=1
        )

    except Exception as e:
        logger.error(f"Failed to generate key: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"生成密钥失败: {str(e)}"
        )


@router.get("/keys", response_model=List[KeyResponse])
async def list_keys(
    db: AsyncSession = Depends(get_db),
    current_user_id: Optional[str] = Depends(get_current_user_id_optional)
):
    """列出所有密钥"""
    try:
        key_service = get_key_management_service(db)
        keys = await key_service.list_keys()

        return [
            KeyResponse(
                key_name=key["key_name"],
                key_type=key["key_type"],
                current_version=key["current_version"],
                versions_count=key["versions_count"],
                created_at=key["created_at"].isoformat(),
                is_active=key["is_active"]
            )
            for key in keys
        ]

    except Exception as e:
        logger.error(f"Failed to list keys: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取密钥列表失败: {str(e)}"
        )


@router.get("/keys/{key_name}", response_model=KeyValueResponse)
async def get_key(
    key_name: str,
    version: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user_id: Optional[str] = Depends(get_current_user_id_optional)
):
    """获取密钥值"""
    try:
        key_service = get_key_management_service(db)
        key_value = await key_service.get_key(key_name, version)

        if key_value is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"密钥不存在: {key_name}"
            )

        # 获取密钥信息
        keys = await key_service.list_keys()
        key_info = next((k for k in keys if k["key_name"] == key_name), None)

        return KeyValueResponse(
            key_name=key_name,
            key_value=key_value,
            version=version or (key_info["current_version"] if key_info else 1)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get key: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取密钥失败: {str(e)}"
        )


@router.post("/keys/{key_name}/rotate", response_model=KeyValueResponse)
async def rotate_key(
    key_name: str,
    request: KeyRotateRequest,
    db: AsyncSession = Depends(get_db),
    current_user_id: Optional[str] = Depends(get_current_user_id_optional)
):
    """轮换密钥"""
    try:
        key_service = get_key_management_service(db)

        # 轮换密钥
        new_key_record = await key_service.rotate_key(
            key_name=key_name,
            max_versions=request.max_versions
        )

        # 获取新密钥值
        new_key_value = await key_service.get_key(
            key_name,
            version=new_key_record["version"]
        )

        logger.info(f"Rotated key: {key_name}, new version: {new_key_record['version']}")

        return KeyValueResponse(
            key_name=key_name,
            key_value=new_key_value,
            version=new_key_record["version"]
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to rotate key: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"轮换密钥失败: {str(e)}"
        )


@router.delete("/keys/{key_name}")
async def delete_key(
    key_name: str,
    db: AsyncSession = Depends(get_db),
    current_user_id: Optional[str] = Depends(get_current_user_id_optional)
):
    """删除密钥"""
    try:
        key_service = get_key_management_service(db)
        success = await key_service.delete_key(key_name)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"密钥不存在: {key_name}"
            )

        logger.info(f"Deleted key: {key_name}")

        return {"message": "密钥已删除", "key_name": key_name}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete key: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除密钥失败: {str(e)}"
        )
