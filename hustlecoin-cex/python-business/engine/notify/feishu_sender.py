import asyncio
import hashlib
import hmac
import base64
import json
import time
import logging
from decimal import Decimal

import httpx
import redis as redis_sync

from app.config import settings
from app.db.models import FeishuConfig
from app.db.models_notify import NotificationLog
from app.db.session import SessionLocal
from app.services.notifier import throttle_ok

logger = logging.getLogger(__name__)


class FeishuSender:
    """引擎告警统一出口。绿框(FeishuConfig)6 个字段在此真生效:
      · alert_interval_sec / alert_count → 全局节流令牌桶(与 fire_template 共用 throttle_ok,跨 worker)
      · enable_transfer_fail_alert / enable_new_borrow_alert → 对应告警开关
      · leverage_risk_alert → 爆仓风险临界保证金水平(risk_monitor 读用,替代硬编码 1.3)
      · margin_rate_alert → 爆仓率(%)告警阈值(暴露给消费方)
    关键告警(风险/划转失败/卡仓/心跳)同时镜像到 coinadmin 跑马灯(NotificationLog channel=marquee
    + notification:broadcast),与模板系统落同一展示面 —— 消除"引擎直发 vs 模板"双轨的展示割裂。
    可靠性优先:飞书直发始终保留;Redis/跑马灯任一异常都不阻断直发,绝不因附加渠道吞掉告警。"""

    def __init__(self):
        self._webhook_url: str | None = None
        self._secret_key: str | None = None
        self._last_reload = 0
        self._redis = None
        # 自建应用机器人(优先):app_id/secret 取全局 FeishuConfig,收件人=本 worker user 的 feishu_open_id
        self.user_id: int | None = None
        self._app_id: str | None = None
        self._app_secret: str | None = None
        self._recipient_open_id: str | None = None
        # 绿框配置(安全默认;_ensure_config 从 DB 覆盖)
        self._alert_interval_sec = 5
        self._alert_count = 1
        self.leverage_risk_alert = Decimal("1.3")
        self.margin_rate_alert = Decimal("30")
        self.enable_transfer_fail_alert = True
        self.enable_new_borrow_alert = True
        self.enable_borrow_success_alert = True
        self.enable_repay_success_alert = True

    def _ensure_config(self):
        now = time.time()
        if now - self._last_reload < 300 and self._last_reload > 0:
            return
        db = SessionLocal()
        try:
            # 与 fire_template 一致:优先全局配置(user_id 为空)
            cfg = (db.query(FeishuConfig).filter(FeishuConfig.user_id.is_(None)).first()
                   or db.query(FeishuConfig).first())
            if cfg:
                self._webhook_url = cfg.webhook_url
                self._secret_key = cfg.secret_key
                self._app_id = getattr(cfg, "app_id", None)
                self._app_secret = getattr(cfg, "app_secret", None)
                try:
                    self._alert_interval_sec = int(getattr(cfg, "alert_interval_sec", 5) or 0)
                    self._alert_count = max(1, int(getattr(cfg, "alert_count", 1) or 1))
                    if getattr(cfg, "leverage_risk_alert", None) is not None:
                        self.leverage_risk_alert = Decimal(str(cfg.leverage_risk_alert))
                    if getattr(cfg, "margin_rate_alert", None) is not None:
                        self.margin_rate_alert = Decimal(str(cfg.margin_rate_alert))
                    self.enable_transfer_fail_alert = bool(getattr(cfg, "enable_transfer_fail_alert", True))
                    self.enable_new_borrow_alert = bool(getattr(cfg, "enable_new_borrow_alert", True))
                    self.enable_borrow_success_alert = bool(getattr(cfg, "enable_borrow_success_alert", True))
                    self.enable_repay_success_alert = bool(getattr(cfg, "enable_repay_success_alert", True))
                except Exception as e:
                    logger.debug(f"feishu green-box cfg parse: {e}")
            # 收件人 open_id:本 worker user 的 feishu_open_id;无则回退最低 id 有绑定的用户(运营)
            try:
                from app.db.models_auth import User
                u = db.query(User).filter(User.id == self.user_id).first() if self.user_id is not None else None
                if u and getattr(u, "feishu_open_id", None):
                    self._recipient_open_id = u.feishu_open_id
                else:
                    fb = (db.query(User).filter(User.feishu_open_id.isnot(None))
                          .order_by(User.id).first())
                    self._recipient_open_id = fb.feishu_open_id if fb else None
            except Exception as e:
                logger.debug(f"feishu recipient resolve: {e}")
            self._last_reload = now
        finally:
            db.close()

    def _get_redis(self):
        if self._redis is None:
            try:
                self._redis = redis_sync.from_url(settings.redis_url, decode_responses=True)
            except Exception:
                self._redis = None
        return self._redis

    def _mirror_marquee(self, title: str, content: str, priority: int, color: str, blink: bool):
        """关键告警镜像到 coinadmin 跑马灯:实时广播 + 落 NotificationLog(供 /recent-marquee 轮询)。
        同步函数,调用方用 asyncio.to_thread 包;任何异常静默(不阻断飞书直发)。"""
        text = f"{title}：{content}" if content else title
        try:
            r = self._get_redis()
            if r is not None:
                r.publish("notification:broadcast", json.dumps({
                    "title": title, "content": text, "priority": priority,
                    "color": color, "blink": blink, "sound": "alert" if blink else "none",
                }))
        except Exception:
            self._redis = None
        try:
            db = SessionLocal()
            try:
                db.add(NotificationLog(template_name=title, channel="marquee",
                                       status="sent", content=text[:500]))
                db.commit()
            finally:
                db.close()
        except Exception:
            pass

    async def _emit(self, title: str, content: str, *, marquee: bool,
                    priority: int, color: str, blink: bool):
        """实际发一条:关键告警镜像跑马灯 + 飞书直发。不含节流/重复逻辑。"""
        if marquee:
            try:
                await asyncio.to_thread(self._mirror_marquee, title, content, priority, color, blink)
            except Exception:
                pass

        # 优先自建应用机器人(app_id/secret + 收件人 open_id);发给本 worker user 的飞书
        if self._app_id and self._app_secret and self._recipient_open_id:
            try:
                from app.services.feishu_bot import send_bot_text
                ok, detail = await asyncio.to_thread(
                    send_bot_text, self._app_id, self._app_secret, self._recipient_open_id, title, content)
                if not ok:
                    logger.warning(f"Feishu bot send failed: {detail}")
                return
            except Exception as e:
                logger.warning(f"Feishu bot send error: {e}")
                return

        # 回退:群机器人 webhook
        if not self._webhook_url:
            return
        payload: dict = {
            "msg_type": "text",
            "content": {"text": f"[{title}]\n{content}"},
        }
        if self._secret_key:
            ts = str(int(time.time()))
            string_to_sign = f"{ts}\n{self._secret_key}"
            sign = base64.b64encode(
                hmac.new(string_to_sign.encode(), b"", hashlib.sha256).digest()
            ).decode()
            payload["timestamp"] = ts
            payload["sign"] = sign
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(self._webhook_url, json=payload)
                if resp.status_code != 200:
                    logger.warning(f"Feishu send failed: HTTP {resp.status_code}")
        except Exception as e:
            logger.warning(f"Feishu send error: {e}")

    async def _repeat(self, n: int, interval: int, title: str, content: str, priority: int, color: str):
        """提醒次数:后台补发 n 次(每隔 interval 秒),不阻塞调用方;不重复刷跑马灯。"""
        for _ in range(n):
            await asyncio.sleep(max(1, interval))
            try:
                await self._emit(title, content, marquee=False, priority=priority, color=color, blink=False)
            except Exception:
                pass

    async def send(self, title: str, content: str, *, marquee: bool = False,
                   priority: int = 3, color: str = "#3b82f6", blink: bool = False,
                   throttle_key: str | None = None):
        self._ensure_config()
        # 防刷屏:同一告警在「整段重复序列(alert_interval_sec × alert_count)」内只放行一次触发
        # (Redis 令牌桶,跨 worker;异常 fail-open)
        key = f"engine:{throttle_key or title}"
        iv = max(1, self._alert_interval_sec)
        n = max(1, self._alert_count)
        if not await asyncio.to_thread(throttle_ok, key, iv * n, 1):
            return
        # 先发第一条;再按「提醒次数」alert_count 补发 (n-1) 次,每隔 alert_interval_sec(后台,不阻塞)
        await self._emit(title, content, marquee=marquee, priority=priority, color=color, blink=blink)
        if n > 1:
            asyncio.create_task(self._repeat(n - 1, self._alert_interval_sec, title, content, priority, color))

    async def notify_position_opened(self, account_note: str, symbol: str, spread: Decimal, qty: Decimal, usdt: Decimal):
        """借币成功(开仓/对冲完成)提醒,绿框开关 enable_borrow_success_alert 控制。"""
        self._ensure_config()
        if not self.enable_borrow_success_alert:
            return
        await self.send(
            "借币成功",
            f"账户: {account_note}\n"
            f"币种: {symbol}\n"
            f"方向: 杠杆借币做空 + 合约做多\n"
            f"数量: {qty}\n"
            f"金额: {usdt} USDT\n"
            f"点差: {spread}%",
            throttle_key=f"opened:{account_note}:{symbol}",
        )

    async def notify_position_closed(self, account_note: str, symbol: str, pnl: Decimal, spread: Decimal):
        """还币成功(平仓/还币完成)提醒,绿框开关 enable_repay_success_alert 控制。"""
        self._ensure_config()
        if not self.enable_repay_success_alert:
            return
        emoji = "+" if pnl >= 0 else ""
        await self.send(
            "还币成功",
            f"账户: {account_note}\n"
            f"币种: {symbol}\n"
            f"盈亏: {emoji}{pnl} USDT\n"
            f"平仓点差: {spread}%",
            throttle_key=f"closed:{account_note}:{symbol}",
        )

    async def notify_new_borrow(self, account_note: str, symbol: str, qty: Decimal, usdt: Decimal):
        """新增借币提醒(绿框开关 enable_new_borrow_alert 控制)。"""
        self._ensure_config()
        if not self.enable_new_borrow_alert:
            return
        await self.send(
            "新增借币",
            f"账户: {account_note}\n"
            f"币种: {symbol}\n"
            f"借入数量: {qty}\n"
            f"名义金额: {usdt} USDT",
            throttle_key=f"borrow:{account_note}:{symbol}",
        )

    async def notify_error(self, account_note: str, action: str, error: str):
        await self.send(
            "错误告警",
            f"账户: {account_note}\n"
            f"操作: {action}\n"
            f"错误: {error}",
            marquee=True, priority=2, color="#f59e0b",
            throttle_key=f"error:{account_note}:{action}",
        )

    async def notify_risk(self, account_note: str, margin_level: Decimal):
        await self.send(
            "风险告警",
            f"账户: {account_note}\n"
            f"保证金水平: {margin_level}\n"
            f"请立即检查!",
            marquee=True, priority=1, color="#ef4444", blink=True,
            throttle_key=f"risk:{account_note}",
        )

    async def notify_futures_margin(self, account_note: str, buffer_pct: Decimal, threshold: Decimal):
        """合约爆仓预警(绿框 margin_rate_alert):距爆仓安全垫低于阈值。关键告警,镜像跑马灯。"""
        await self.send(
            "合约爆仓预警",
            f"账户: {account_note}\n"
            f"合约距爆仓安全垫: {buffer_pct:.1f}% (< {threshold}%)\n"
            f"合约账户接近强平,请立即检查/补保证金!",
            marquee=True, priority=1, color="#ef4444", blink=True,
            throttle_key=f"futmargin:{account_note}",
        )

    async def notify_stuck_positions(self, positions: list[dict]):
        lines = [f"  {p['symbol']}(#{p['id']}) 状态={p['status']} 已卡{p['stuck_minutes']}分钟" for p in positions]
        await self.send(
            "持仓异常告警",
            f"发现 {len(positions)} 个卡住的持仓:\n" + "\n".join(lines),
            marquee=True, priority=1, color="#ef4444", blink=True,
            throttle_key="stuck",
        )

    async def notify_heartbeat_stale(self, workers: list[dict]):
        lines = [f"  {w['scope']} 上次心跳={w['last_heartbeat']}" for w in workers]
        await self.send(
            "Worker心跳告警",
            f"{len(workers)} 个Worker心跳超时:\n" + "\n".join(lines),
            marquee=True, priority=1, color="#ef4444", blink=True,
            throttle_key="heartbeat",
        )

    async def notify_transfer_failed(self, account_note: str, amount: Decimal, skipped_futures: bool = False):
        """划转失败告警(绿框开关 enable_transfer_fail_alert 控制)。"""
        self._ensure_config()
        if not self.enable_transfer_fail_alert:
            return
        reason = "（已跳过合约划转，爆仓率低于阈值）" if skipped_futures else ""
        await self.send(
            "划转失败告警",
            f"账户: {account_note}\n"
            f"所需金额: {amount} USDT\n"
            f"所有资金来源均划转失败{reason}\n"
            f"请立即检查账户余额!",
            marquee=True, priority=1, color="#ef4444", blink=True,
            throttle_key=f"transfer_fail:{account_note}",
        )
