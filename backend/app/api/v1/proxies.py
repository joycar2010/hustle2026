"""
代理管理API路由
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.schemas.proxy import (
    ProxyPoolCreate,
    ProxyPoolUpdate,
    ProxyPoolResponse,
    AccountProxyBindingResponse,
    ProxyHealthCheckRequest,
    QingguoProxyRequest,
    AccountProxyConfigRequest,
    ProxyHealthLogResponse
)
from app.services.proxy_manager import proxy_manager
from app.services.qingguo_proxy_service import qingguo_proxy_service

router = APIRouter()


@router.get("/proxies", response_model=List[ProxyPoolResponse])
async def get_proxies(
    status: Optional[str] = Query(None, description="状态过滤: active, inactive, expired, failed"),
    provider: Optional[str] = Query(None, description="提供商过滤: qingguo, local, custom"),
    min_health_score: int = Query(0, ge=0, le=100, description="最低健康分数"),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """获取代理列表"""
    proxies = await proxy_manager.get_proxies(
        db,
        status=status,
        provider=provider,
        min_health_score=min_health_score
    )
    return proxies


@router.get("/proxies/{proxy_id}", response_model=ProxyPoolResponse)
async def get_proxy(
    proxy_id: int,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """获取单个代理详情"""
    proxy = await proxy_manager.get_proxy_by_id(db, proxy_id)
    if not proxy:
        raise HTTPException(status_code=404, detail="代理不存在")
    return proxy


@router.post("/proxies", response_model=ProxyPoolResponse)
async def create_proxy(
    proxy_data: ProxyPoolCreate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """
    创建自定义代理
    支持手动添加代理IP
    """
    proxy = await proxy_manager.create_proxy(
        db,
        proxy_data.dict(),
        created_by=user_id
    )
    return proxy


@router.post("/proxies/local", response_model=ProxyPoolResponse)
async def create_local_proxy(
    name: str = Query(default="本地服务器", description="代理名称"),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """
    创建本地服务器代理
    使用本机IP，不经过代理服务器
    """
    proxy = await proxy_manager.create_local_proxy(
        db,
        name=name,
        created_by=user_id
    )
    return proxy


@router.put("/proxies/{proxy_id}", response_model=ProxyPoolResponse)
async def update_proxy(
    proxy_id: int,
    update_data: ProxyPoolUpdate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """更新代理"""
    proxy = await proxy_manager.update_proxy(
        db,
        proxy_id,
        update_data.dict(exclude_unset=True)
    )
    if not proxy:
        raise HTTPException(status_code=404, detail="代理不存在")
    return proxy


@router.delete("/proxies/{proxy_id}")
async def delete_proxy(
    proxy_id: int,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """删除代理"""
    success = await proxy_manager.delete_proxy(db, proxy_id)
    if not success:
        raise HTTPException(status_code=404, detail="代理不存在")
    return {"message": "删除成功"}


@router.post("/proxies/fetch-from-qingguo", response_model=List[ProxyPoolResponse])
async def fetch_proxies_from_qingguo(
    request: QingguoProxyRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """
    从青果网络获取代理
    """
    try:
        proxies = await proxy_manager.fetch_proxies_from_qingguo(
            db,
            num=request.num,
            region=request.region,
            protocol=request.protocol,
            expire_time=request.expire_time,
            created_by=user_id
        )
        return proxies
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取代理失败: {str(e)}")


@router.post("/proxies/health-check")
async def check_proxy_health(
    request: ProxyHealthCheckRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """
    执行代理健康检查
    """
    # 获取要检查的代理列表
    if request.proxy_ids:
        proxies = []
        for proxy_id in request.proxy_ids:
            proxy = await proxy_manager.get_proxy_by_id(db, proxy_id)
            if proxy:
                proxies.append(proxy)
    else:
        # 检查所有活跃代理
        proxies = await proxy_manager.get_proxies(db, status='active')

    # 执行健康检查
    results = []
    for proxy in proxies:
        health_result = await proxy_manager.check_proxy_health(proxy)
        await proxy_manager.update_proxy_health(db, proxy, health_result)
        results.append({
            'proxy_id': proxy.id,
            'host': proxy.host,
            'port': proxy.port,
            **health_result
        })

    return {
        'total': len(results),
        'success': sum(1 for r in results if r['is_success']),
        'failed': sum(1 for r in results if not r['is_success']),
        'results': results
    }


@router.post("/accounts/proxy/config")
async def configure_account_proxy(
    request: AccountProxyConfigRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """
    配置账户代理
    支持绑定、解绑、自动分配代理
    """
    if request.proxy_id is None:
        # 解绑代理
        success = await proxy_manager.unbind_proxy_from_account(
            db,
            request.account_id,
            request.platform_id
        )
        if not success:
            raise HTTPException(status_code=404, detail="没有找到绑定的代理")
        return {"message": "解绑成功", "proxy_id": None}

    elif request.proxy_id == 0 and request.auto_create:
        # 自动分配代理
        proxy = await proxy_manager.auto_assign_proxy(
            db,
            request.account_id,
            request.platform_id,
            created_by=user_id
        )
        return {
            "message": "自动分配代理成功",
            "proxy_id": proxy.id,
            "proxy": ProxyPoolResponse.from_orm(proxy)
        }

    else:
        # 绑定指定代理
        proxy = await proxy_manager.get_proxy_by_id(db, request.proxy_id)
        if not proxy:
            raise HTTPException(status_code=404, detail="代理不存在")

        binding = await proxy_manager.bind_proxy_to_account(
            db,
            request.account_id,
            request.proxy_id,
            request.platform_id
        )

        return {
            "message": "绑定成功",
            "proxy_id": proxy.id,
            "proxy": ProxyPoolResponse.from_orm(proxy)
        }


@router.get("/accounts/{account_id}/proxy/{platform_id}", response_model=Optional[ProxyPoolResponse])
async def get_account_proxy(
    account_id: str,
    platform_id: int,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """
    获取账户绑定的代理
    """
    proxy = await proxy_manager.get_account_proxy(db, account_id, platform_id)
    return proxy


@router.get("/qingguo/balance")
async def get_qingguo_balance(
    user_id: str = Depends(get_current_user_id)
):
    """
    查询青果网络账户余额
    """
    try:
        balance = await qingguo_proxy_service.check_balance()
        return balance
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询余额失败: {str(e)}")


@router.get("/proxies/{proxy_id}/health-logs", response_model=List[ProxyHealthLogResponse])
async def get_proxy_health_logs(
    proxy_id: int,
    limit: int = Query(100, ge=1, le=1000, description="返回记录数"),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """
    获取代理健康检查日志
    """
    from sqlalchemy import select
    from app.models.proxy import ProxyHealthLog

    result = await db.execute(
        select(ProxyHealthLog)
        .where(ProxyHealthLog.proxy_id == proxy_id)
        .order_by(ProxyHealthLog.check_time.desc())
        .limit(limit)
    )
    logs = result.scalars().all()
    return logs
