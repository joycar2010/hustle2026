"""
代理管理服务
支持手动代理和本地服务器IP代理
"""
import asyncio
import logging
import time
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, update
from sqlalchemy.orm import selectinload

from app.models.proxy import ProxyPool, AccountProxyBinding, ProxyHealthLog
import aiohttp

logger = logging.getLogger(__name__)


class ProxyManager:
    """代理管理器"""

    def __init__(self):
        self.health_check_interval = 300  # 健康检查间隔(秒)
        self.health_check_timeout = 10  # 健康检查超时(秒)
        self.health_check_running = False

    async def create_proxy(
        self,
        db: AsyncSession,
        proxy_data: Dict[str, Any],
        created_by: Optional[str] = None
    ) -> ProxyPool:
        """
        创建代理

        Args:
            db: 数据库会话
            proxy_data: 代理数据
            created_by: 创建人ID

        Returns:
            创建的代理对象
        """
        proxy = ProxyPool(
            proxy_type=proxy_data.get('proxy_type', 'http'),
            host=proxy_data['host'],
            port=proxy_data['port'],
            username=proxy_data.get('username'),
            password=proxy_data.get('password'),
            provider=proxy_data.get('provider', 'custom'),
            region=proxy_data.get('region'),
            ip_address=proxy_data.get('ip_address'),
            expire_time=proxy_data.get('expire_time'),
            status='active',
            created_by=created_by
        )

        db.add(proxy)
        await db.commit()
        await db.refresh(proxy)

        logger.info(f"创建代理成功: {proxy.host}:{proxy.port}")
        return proxy

    async def create_local_proxy(
        self,
        db: AsyncSession,
        name: str = "本地服务器",
        created_by: Optional[str] = None
    ) -> ProxyPool:
        """
        创建本地服务器代理（使用本机IP，不经过代理）

        Args:
            db: 数据库会话
            name: 代理名称
            created_by: 创建人ID

        Returns:
            创建的代理对象
        """
        proxy = ProxyPool(
            proxy_type='direct',  # 直连模式
            host='localhost',
            port=0,  # 端口0表示直连
            provider='local',
            region='local',
            ip_address='127.0.0.1',
            status='active',
            health_score=100,
            metadata={'name': name, 'type': 'local'},
            created_by=created_by
        )

        db.add(proxy)
        await db.commit()
        await db.refresh(proxy)

        logger.info(f"创建本地代理成功: {name}")
        return proxy

    async def get_proxies(
        self,
        db: AsyncSession,
        status: Optional[str] = None,
        provider: Optional[str] = None,
        min_health_score: int = 0
    ) -> List[ProxyPool]:
        """
        获取代理列表

        Args:
            db: 数据库会话
            status: 状态过滤
            provider: 提供商过滤
            min_health_score: 最低健康分数

        Returns:
            代理列表
        """
        query = select(ProxyPool)

        conditions = []
        if status:
            conditions.append(ProxyPool.status == status)
        if provider:
            conditions.append(ProxyPool.provider == provider)
        if min_health_score > 0:
            conditions.append(ProxyPool.health_score >= min_health_score)

        if conditions:
            query = query.where(and_(*conditions))

        query = query.order_by(ProxyPool.health_score.desc(), ProxyPool.created_at.desc())

        result = await db.execute(query)
        return result.scalars().all()

    async def get_proxy_by_id(self, db: AsyncSession, proxy_id: int) -> Optional[ProxyPool]:
        """获取单个代理"""
        result = await db.execute(
            select(ProxyPool).where(ProxyPool.id == proxy_id)
        )
        return result.scalar_one_or_none()

    async def update_proxy(
        self,
        db: AsyncSession,
        proxy_id: int,
        update_data: Dict[str, Any]
    ) -> Optional[ProxyPool]:
        """更新代理"""
        proxy = await self.get_proxy_by_id(db, proxy_id)
        if not proxy:
            return None

        for key, value in update_data.items():
            if hasattr(proxy, key) and value is not None:
                setattr(proxy, key, value)

        proxy.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(proxy)

        logger.info(f"更新代理成功: {proxy.id}")
        return proxy

    async def delete_proxy(self, db: AsyncSession, proxy_id: int) -> bool:
        """删除代理"""
        proxy = await self.get_proxy_by_id(db, proxy_id)
        if not proxy:
            return False

        await db.delete(proxy)
        await db.commit()

        logger.info(f"删除代理成功: {proxy_id}")
        return True

    async def bind_proxy_to_account(
        self,
        db: AsyncSession,
        account_id: str,
        proxy_id: int,
        platform_id: int,
        priority: int = 0
    ) -> AccountProxyBinding:
        """
        绑定代理到账户

        Args:
            db: 数据库会话
            account_id: 账户ID
            proxy_id: 代理ID
            platform_id: 平台ID (1=Binance, 2=Bybit)
            priority: 优先级

        Returns:
            绑定对象
        """
        # 先解绑该账户在该平台的其他代理
        await db.execute(
            update(AccountProxyBinding)
            .where(
                and_(
                    AccountProxyBinding.account_id == account_id,
                    AccountProxyBinding.platform_id == platform_id,
                    AccountProxyBinding.is_active == True
                )
            )
            .values(is_active=False, unbind_time=datetime.utcnow())
        )

        # 创建新绑定
        binding = AccountProxyBinding(
            account_id=account_id,
            proxy_id=proxy_id,
            platform_id=platform_id,
            is_active=True,
            priority=priority
        )

        db.add(binding)
        await db.commit()
        await db.refresh(binding)

        logger.info(f"绑定代理成功: account={account_id}, proxy={proxy_id}, platform={platform_id}")
        return binding

    async def unbind_proxy_from_account(
        self,
        db: AsyncSession,
        account_id: str,
        platform_id: int
    ) -> bool:
        """
        解绑账户的代理

        Args:
            db: 数据库会话
            account_id: 账户ID
            platform_id: 平台ID

        Returns:
            是否成功
        """
        result = await db.execute(
            update(AccountProxyBinding)
            .where(
                and_(
                    AccountProxyBinding.account_id == account_id,
                    AccountProxyBinding.platform_id == platform_id,
                    AccountProxyBinding.is_active == True
                )
            )
            .values(is_active=False, unbind_time=datetime.utcnow())
        )

        await db.commit()

        logger.info(f"解绑代理成功: account={account_id}, platform={platform_id}")
        return result.rowcount > 0

    async def get_account_proxy(
        self,
        db: AsyncSession,
        account_id: str,
        platform_id: int
    ) -> Optional[ProxyPool]:
        """
        获取账户绑定的代理

        Args:
            db: 数据库会话
            account_id: 账户ID
            platform_id: 平台ID

        Returns:
            代理对象，如果没有绑定则返回None
        """
        result = await db.execute(
            select(ProxyPool)
            .join(AccountProxyBinding)
            .where(
                and_(
                    AccountProxyBinding.account_id == account_id,
                    AccountProxyBinding.platform_id == platform_id,
                    AccountProxyBinding.is_active == True
                )
            )
        )
        return result.scalar_one_or_none()

    async def check_proxy_health(
        self,
        proxy: ProxyPool,
        target_url: str = "https://api.binance.com/api/v3/ping",
        timeout: int = 10
    ) -> Dict[str, Any]:
        """
        检查代理健康状态

        Args:
            proxy: 代理对象
            target_url: 测试目标URL
            timeout: 超时时间(秒)

        Returns:
            健康检查结果: {is_success, latency_ms, error_message, response_code}
        """
        # 本地代理直接返回成功
        if proxy.provider == 'local':
            return {
                'is_success': True,
                'latency_ms': 0,
                'error_message': None,
                'response_code': 200
            }

        start_time = time.time()
        result = {
            'is_success': False,
            'latency_ms': None,
            'error_message': None,
            'response_code': None
        }

        try:
            # 构建代理URL
            proxy_url = proxy.proxy_url

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    target_url,
                    proxy=proxy_url,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                    ssl=False  # 跳过SSL验证以提高速度
                ) as resp:
                    latency = (time.time() - start_time) * 1000
                    result['latency_ms'] = round(latency, 2)
                    result['response_code'] = resp.status
                    result['is_success'] = resp.status == 200

                    if resp.status != 200:
                        result['error_message'] = f"HTTP {resp.status}"

        except asyncio.TimeoutError:
            result['error_message'] = "连接超时"
        except aiohttp.ClientError as e:
            result['error_message'] = f"网络错误: {str(e)}"
        except Exception as e:
            result['error_message'] = f"未知错误: {str(e)}"

        return result

    async def update_proxy_health(
        self,
        db: AsyncSession,
        proxy: ProxyPool,
        health_result: Dict[str, Any]
    ):
        """
        更新代理健康状态

        Args:
            db: 数据库会话
            proxy: 代理对象
            health_result: 健康检查结果
        """
        # 记录健康检查日志
        log = ProxyHealthLog(
            proxy_id=proxy.id,
            check_time=datetime.utcnow(),
            is_success=health_result['is_success'],
            latency_ms=health_result['latency_ms'],
            error_message=health_result['error_message'],
            check_type='auto',
            target_url="https://api.binance.com/api/v3/ping",
            response_code=health_result['response_code']
        )
        db.add(log)

        # 更新代理健康分数
        if health_result['is_success']:
            # 成功：健康分数+5，最高100
            proxy.health_score = min(100, proxy.health_score + 5)
            proxy.failed_requests = max(0, proxy.failed_requests - 1)
        else:
            # 失败：健康分数-10，最低0
            proxy.health_score = max(0, proxy.health_score - 10)
            proxy.failed_requests += 1

            # 连续失败3次，标记为失败状态
            if proxy.failed_requests >= 3:
                proxy.status = 'failed'

        # 更新延迟
        if health_result['latency_ms']:
            if proxy.avg_latency_ms:
                # 移动平均
                proxy.avg_latency_ms = (proxy.avg_latency_ms * 0.7 + health_result['latency_ms'] * 0.3)
            else:
                proxy.avg_latency_ms = health_result['latency_ms']

        proxy.last_check_time = datetime.utcnow()
        proxy.total_requests += 1

        await db.commit()

    async def auto_assign_proxy(
        self,
        db: AsyncSession,
        account_id: str,
        platform_id: int,
        created_by: Optional[str] = None
    ) -> ProxyPool:
        """
        自动为账户分配健康分数最高的可用代理

        Args:
            db: 数据库会话
            account_id: 账户ID
            platform_id: 平台ID
            created_by: 创建人ID

        Returns:
            分配的代理对象
        """
        available_proxies = await self.get_proxies(
            db,
            status='active',
            min_health_score=60
        )

        result = await db.execute(
            select(AccountProxyBinding.proxy_id)
            .where(
                and_(
                    AccountProxyBinding.platform_id == platform_id,
                    AccountProxyBinding.is_active == True
                )
            )
        )
        bound_proxy_ids = {row[0] for row in result.all()}

        available_proxies = [p for p in available_proxies if p.id not in bound_proxy_ids]

        if not available_proxies:
            raise ValueError("没有可用的代理，请先手动添加代理")

        proxy = available_proxies[0]
        await self.bind_proxy_to_account(db, account_id, proxy.id, platform_id)
        return proxy


# 全局单例
proxy_manager = ProxyManager()
