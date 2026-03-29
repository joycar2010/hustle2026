"""Timing Configuration API Endpoints"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from app.core.database import get_db
from app.core.security import get_current_user_id
from app.schemas.timing_config import (
    TimingConfigCreate,
    TimingConfigUpdate,
    TimingConfigResponse,
    TimingConfigHistoryResponse,
    TimingConfigTemplateCreate,
    TimingConfigTemplateResponse
)
from app.services.timing_config_service import timing_config_service
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/timing-configs", response_model=List[TimingConfigResponse])
async def get_all_timing_configs(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    """Get all timing configurations"""
    configs = await timing_config_service.get_all_configs(db)
    return configs


@router.get("/timing-configs/effective/{strategy_type}")
async def get_effective_timing_config(
    strategy_type: str,
    instance_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    """
    Get effective timing configuration for a strategy type with inheritance.
    Priority: instance > strategy_type > global
    """
    config = await timing_config_service.get_effective_config(
        db,
        strategy_type=strategy_type,
        instance_id=instance_id
    )
    return config


@router.get("/timing-configs/{config_id}", response_model=TimingConfigResponse)
async def get_timing_config(
    config_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    """Get timing configuration by ID"""
    config = await timing_config_service.get_config_by_id(db, config_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Timing configuration not found"
        )
    return config


@router.post("/timing-configs", response_model=TimingConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_timing_config(
    config_data: TimingConfigCreate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    """Create new timing configuration"""
    # Validate config_level
    if config_data.config_level not in ['global', 'strategy_type', 'instance']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="config_level must be 'global', 'strategy_type', or 'instance'"
        )

    # Validate strategy_type for strategy_type level
    if config_data.config_level == 'strategy_type' and not config_data.strategy_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="strategy_type is required for strategy_type level configuration"
        )

    # Validate instance_id for instance level
    if config_data.config_level == 'instance' and not config_data.strategy_instance_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="strategy_instance_id is required for instance level configuration"
        )

    try:
        config = await timing_config_service.create_config(db, config_data, user_id)
        logger.info(f"User {user_id} created timing config {config.id}")
        return config
    except Exception as e:
        logger.error(f"Failed to create timing config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create timing configuration: {str(e)}"
        )


@router.put("/timing-configs/{config_id}", response_model=TimingConfigResponse)
async def update_timing_config(
    config_id: int,
    config_data: TimingConfigUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    """Update timing configuration"""
    # Check if config exists
    existing_config = await timing_config_service.get_config_by_id(db, config_id)
    if not existing_config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Timing configuration not found"
        )

    # Check if config is locked (unless we're just toggling the lock)
    if existing_config.is_locked and config_data.is_locked is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Configuration is locked and cannot be modified. Please unlock it first."
        )

    config = await timing_config_service.update_config(db, config_id, config_data, user_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Timing configuration not found"
        )

    logger.info(f"User {user_id} updated timing config {config_id}")
    return config


@router.delete("/timing-configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_timing_config(
    config_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    """Delete timing configuration"""
    # Check if config exists and is not global
    config = await timing_config_service.get_config_by_id(db, config_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Timing configuration not found"
        )

    # Prevent deletion of global config
    if config.config_level == 'global':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete global configuration"
        )

    success = await timing_config_service.delete_config(db, config_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete timing configuration"
        )

    logger.info(f"User {user_id} deleted timing config {config_id}")
    return None


@router.post("/timing-configs/reload")
async def reload_timing_configs(
    user_id: str = Depends(get_current_user_id)
):
    """Manually trigger timing configuration reload notification"""
    await timing_config_service._clear_cache_and_notify('global', None, None)
    logger.info(f"User {user_id} triggered timing config reload")
    return {"message": "Timing configuration reload triggered"}


@router.get("/timing-configs/history/{strategy_type}", response_model=List[TimingConfigHistoryResponse])
async def get_timing_config_history(
    strategy_type: str,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    """Get timing configuration history for a strategy type"""
    history = await timing_config_service.get_config_history(db, strategy_type, limit)
    return history


@router.get("/timing-configs/templates/{strategy_type}", response_model=List[TimingConfigTemplateResponse])
async def get_custom_templates(
    strategy_type: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    """Get custom templates for a strategy type"""
    templates = await timing_config_service.get_custom_templates(db, strategy_type)
    return templates


@router.post("/timing-configs/templates", response_model=TimingConfigTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_custom_template(
    template_data: TimingConfigTemplateCreate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    """Create a custom template"""
    template = await timing_config_service.create_custom_template(db, template_data, user_id)
    logger.info(f"User {user_id} created custom template {template.id}")
    return template


@router.delete("/timing-configs/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    """Delete a custom template"""
    success = await timing_config_service.delete_custom_template(db, template_id, user_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found or you don't have permission to delete it"
        )

    logger.info(f"User {user_id} deleted custom template {template_id}")
    return None
