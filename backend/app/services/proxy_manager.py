"""
代理管理服务
支持ipipgo代理和本地服务器IP代理
"""
import asyncio
import logging
import time
from collections import deque, defaultdict
from typing import List, Dict, Any, Optional, Deque
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

        # ── 滚动失败率窗口 + 告警 ─────────────────────────────────────────
        # 按 proxy_id 保存最近一个窗口内的 (timestamp, is_success) 样本
        self._rolling_samples: Dict[int, Deque] = defaultdict(lambda: deque(maxlen=200))
        # 按 proxy_id 保存上次告警时间，用于冷却
        self._last_alert_at: Dict[int, datetime] = {}
        self.rolling_window_sec = 300       # 5 分钟滑窗
        self.min_samples_for_alert = 5      # 窗口内至少 5 次样本才评估
        self.failure_rate_threshold = 0.5   # 失败率 ≥ 50% 触发告警
        self.alert_cooldown_sec = 600       # 10 分钟告警冷却,同代理不再轰炸

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
        更新代理健康状态 + 维护滚动失败率窗口 + 必要时触发告警

        Args:
            db: 数据库会话
            proxy: 代理对象
            health_result: 健康检查结果
        """
        is_success = bool(health_result['is_success'])
        now = datetime.utcnow()

        # 记录健康检查日志
        log = ProxyHealthLog(
            proxy_id=proxy.id,
            check_time=now,
            is_success=is_success,
            latency_ms=health_result['latency_ms'],
            error_message=health_result['error_message'],
            check_type='auto',
            target_url="https://api.binance.com/api/v3/ping",
            response_code=health_result['response_code']
        )
        db.add(log)

        # ── 滚动失败率窗口维护 ────────────────────────────────────────
        # 推入新样本；按 window 秒过期旧样本
        samples = self._rolling_samples[proxy.id]
        samples.append((now, is_success))
        cutoff = now - timedelta(seconds=self.rolling_window_sec)
        while samples and samples[0][0] < cutoff:
            samples.popleft()

        total = len(samples)
        fails = sum(1 for _, ok in samples if not ok)
        failure_rate = (fails / total) if total > 0 else 0.0

        # 更新代理健康分数 + 累计计数（累计字段保持以兼容历史 UI）
        if is_success:
            proxy.health_score = min(100, proxy.health_score + 5)
            proxy.failed_requests = max(0, proxy.failed_requests - 1)
        else:
            proxy.health_score = max(0, proxy.health_score - 10)
            proxy.failed_requests += 1

        # ── 滚动窗口阈值判断:替代"连续失败 3 次"的脆弱判定 ─────────────
        prev_status = proxy.status
        if total >= self.min_samples_for_alert and failure_rate >= self.failure_rate_threshold:
            proxy.status = 'failed'
        elif is_success and proxy.status == 'failed' and failure_rate < self.failure_rate_threshold:
            # 窗口内恢复,状态回滚
            proxy.status = 'active'

        # 更新延迟
        if health_result['latency_ms']:
            if proxy.avg_latency_ms:
                proxy.avg_latency_ms = (proxy.avg_latency_ms * 0.7 + health_result['latency_ms'] * 0.3)
            else:
                proxy.avg_latency_ms = health_result['latency_ms']

        proxy.last_check_time = now
        proxy.total_requests += 1

        await db.commit()

        # ── 告警触发:状态跨入 failed 或滚动失败率持续超标 ────────────
        if prev_status != 'failed' and proxy.status == 'failed':
            await self._maybe_alert_proxy_failure(
                proxy=proxy,
                failure_rate=failure_rate,
                window_samples=total,
                window_fails=fails,
                reason="status_transition_to_failed",
            )
        elif (proxy.status == 'failed' and failure_rate >= self.failure_rate_threshold
              and total >= self.min_samples_for_alert):
            await self._maybe_alert_proxy_failure(
                proxy=proxy,
                failure_rate=failure_rate,
                window_samples=total,
                window_fails=fails,
                reason="sustained_high_failure_rate",
            )

    async def _maybe_alert_proxy_failure(
        self,
        proxy: ProxyPool,
        failure_rate: float,
        window_samples: int,
        window_fails: int,
        reason: str,
    ):
        """触发代理失败告警(飞书 + 日志),带冷却保护。"""
        now = datetime.utcnow()
        last = self._last_alert_at.get(proxy.id)
        if last and (now - last).total_seconds() < self.alert_cooldown_sec:
            logger.debug(
                f"[PROXY_ALERT] cooldown active for proxy={proxy.id}, skipping alert ({reason})"
            )
            return
        self._last_alert_at[proxy.id] = now

        title = "⚠️ 代理健康告警"
        color = "red"
        body = (
            f"代理: {proxy.host}:{proxy.port} (provider={proxy.provider}, id={proxy.id})\n"
            f"窗口: 最近 {self.rolling_window_sec // 60} 分钟 共 {window_samples} 次检查\n"
            f"失败次数: {window_fails} / {window_samples}  (失败率 {failure_rate * 100:.1f}%)\n"
            f"健康分: {proxy.health_score}  状态: {proxy.status}\n"
            f"触发原因: {reason}\n"
            f"请排查网络/订阅状态,必要时切换到备用 IP。"
        )
        logger.warning(
            f"[PROXY_ALERT] proxy_id={proxy.id} host={proxy.host}:{proxy.port} "
            f"rate={failure_rate*100:.1f}% samples={window_samples} reason={reason}"
        )

        # 推送飞书告警给所有管理员(与 ProxyExpiryChecker._notify 一致的路径)
        try:
            from app.core.database import AsyncSessionLocal
            from app.models.user import User
            from app.services.feishu_service import get_feishu_service

            feishu = get_feishu_service()
            if not feishu:
                logger.warning("[PROXY_ALERT] feishu service not ready, alert not pushed")
                return

            async with AsyncSessionLocal() as db:
                res = await db.execute(
                    select(User).where(
                        User.is_active == True,
                        User.role.in_(["超级管理员", "系统管理员", "管理员"]),
                    )
                )
                admins = res.scalars().all()

            for admin in admins:
                if not getattr(admin, "feishu_open_id", None):
                    continue
                try:
                    await feishu.send_card_message(
                        receive_id=admin.feishu_open_id,
                        title=title,
                        content=body,
                        color=color,
                    )
                except Exception as _e:
                    logger.error(f"[PROXY_ALERT] send to {admin.username} failed: {_e}")
        except Exception as e:
            logger.error(f"[PROXY_ALERT] dispatch failed: {e}")

    async def _run_rolling_health_check(self):
        """后台调度循环:定时对所有 active/failed 代理跑一次健康检查,驱动滚动窗口。"""
        from app.core.database import AsyncSessionLocal
        logger.info(
            f"[PROXY_HEALTH_SCHEDULER] started, interval={self.health_check_interval}s, "
            f"window={self.rolling_window_sec}s, rate_threshold={self.failure_rate_threshold}"
        )
        self.health_check_running = True
        # 启动后延迟 30 秒避免与 app 启动抢 I/O
        await asyncio.sleep(30)
        while self.health_check_running:
            try:
                async with AsyncSessionLocal() as db:
                    proxies = await self.get_proxies(db, status=None, min_health_score=0)
                    # 仅对 active / failed 的做检查,expired 跳过
                    targets = [p for p in proxies if p.status in ('active', 'failed')]
                for proxy in targets:
                    try:
                        result = await self.check_proxy_health(proxy, timeout=self.health_check_timeout)
                    except Exception as e:
                        logger.error(f"[PROXY_HEALTH_SCHEDULER] check error proxy={proxy.id}: {e}")
                        continue
                    try:
                        async with AsyncSessionLocal() as db2:
                            db2.add(proxy)  # attach
                            await self.update_proxy_health(db2, proxy, result)
                    except Exception as e:
                        logger.error(f"[PROXY_HEALTH_SCHEDULER] update error proxy={proxy.id}: {e}")
            except Exception as e:
                logger.error(f"[PROXY_HEALTH_SCHEDULER] loop iteration failed: {e}")
            await asyncio.sleep(self.health_check_interval)

    async def start_health_scheduler(self):
        """幂等启动后台健康检查调度器。"""
        if self.health_check_running:
            return
        asyncio.create_task(self._run_rolling_health_check())

    async def stop_health_scheduler(self):
        self.health_check_running = False

    async def auto_assign_proxy(
        self,
        db: AsyncSession,
        account_id: str,
        platform_id: int,
        created_by: Optional[str] = None
    ) -> ProxyPool:
        """
        自动为账户分配代理（ipipgo 静态订阅池）

        流程:
          1. 优先挑选 provider='ipipgo'、状态 active、未被其他账户占用、健康分 >= 60 的代理
          2. 次选任意 active、未占用、健康分 >= 60 的代理（兼容历史本地代理等）
          3. 池内无可用代理时抛出明确错误 —— ipipgo 为预分配订阅制，需管理员在后台补充 IP

        Args:
            db: 数据库会话
            account_id: 账户ID
            platform_id: 平台ID
            created_by: 创建人ID (保留签名用于向后兼容)

        Returns:
            分配的代理对象

        Raises:
            RuntimeError: 池内没有可用 ipipgo 代理时抛出
        """
        # 已绑定的代理 id 集合
        bound_result = await db.execute(
            select(AccountProxyBinding.proxy_id)
            .where(
                and_(
                    AccountProxyBinding.platform_id == platform_id,
                    AccountProxyBinding.is_active == True,
                )
            )
        )
        bound_proxy_ids = {row[0] for row in bound_result.all()}

        # 1) 优先 ipipgo
        ipipgo_proxies = await self.get_proxies(
            db,
            status='active',
            provider='ipipgo',
            min_health_score=60,
        )
        ipipgo_proxies = [p for p in ipipgo_proxies if p.id not in bound_proxy_ids]

        if ipipgo_proxies:
            proxy = ipipgo_proxies[0]
            logger.info(f"auto_assign: 使用 ipipgo 代理 proxy_id={proxy.id} for account={account_id}")
        else:
            # 2) 次选任意可用
            fallback = await self.get_proxies(db, status='active', min_health_score=60)
            fallback = [p for p in fallback if p.id not in bound_proxy_ids]
            if not fallback:
                msg = (
                    f"ipipgo 代理池无可用代理 (account={account_id}, platform={platform_id}). "
                    "请管理员到 ipipgo 后台购买/同步新 IP 后再试。"
                )
                logger.error(msg)
                raise RuntimeError(msg)
            proxy = fallback[0]
            logger.info(
                f"auto_assign: ipipgo 池空，退化到 provider={proxy.provider} proxy_id={proxy.id}"
            )

        # 3) 绑定
        await self.bind_proxy_to_account(db, account_id, proxy.id, platform_id)
        return proxy


# 全局单例
proxy_manager = ProxyManager()
