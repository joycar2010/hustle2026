"""引擎热配置:armed 开关/白名单/上限从 engine_config 表读,dcm:config:updates 热重载。

DB 优先、env 兜底:DB 有该键用 DB,否则用 env 默认。取代 systemd Environment——
armed 从"改环境变量+重启"变成"管理台写表+0秒热切换",且可审计。
mode 切 armed 时执行器已常驻(启动即构造+reconcile),仅按 CFG.mode 门控动作,切换即时安全。
"""
import asyncio
import logging
import os
from decimal import Decimal

logger = logging.getLogger("engine-dualperp.cfg")


class LiveConfig:
    def __init__(self):
        self.mode = os.environ.get("DCM_DP_MODE", "shadow")
        self.arm_symbols = self._syms(os.environ.get("DCM_DP_ARM_SYMBOLS", ""))
        self.max_notional_hard = Decimal(os.environ.get("DCM_DP_MAX_NOTIONAL_HARD", "25"))
        self.max_portfolio_notional = Decimal(os.environ.get("DCM_DP_MAX_PORTFOLIO_NOTIONAL", "80"))
        self.auto_converge = os.environ.get("DCM_DP_AUTO_CONVERGE", "false").lower() == "true"
        # list=只认显式白名单;advisor=另外自动信任 advisor 名下 active 路由(人工路由仍须列名)
        self.arm_mode = os.environ.get("DCM_DP_ARM_MODE", "list")

    @staticmethod
    def _syms(s: str) -> set[str]:
        return {x.strip().upper() for x in (s or "").split(",") if x.strip()}

    def _snapshot(self):
        return (self.mode, tuple(sorted(self.arm_symbols)), str(self.max_notional_hard),
                str(self.max_portfolio_notional), self.auto_converge, self.arm_mode)

    async def load(self, pool):
        try:
            rows = await pool.fetch("SELECT ckey,cval FROM engine_config WHERE engine='dualperp'")
        except Exception as e:
            logger.warning("engine_config load failed (用现值): %r", e)
            return
        before = self._snapshot()
        m = {r["ckey"]: r["cval"] for r in rows}
        if "mode" in m and m["mode"] in ("shadow", "armed"):
            self.mode = m["mode"]
        if "arm_symbols" in m:
            self.arm_symbols = self._syms(m["arm_symbols"])
        for k, attr, cast in (("max_notional_hard", "max_notional_hard", Decimal),
                              ("max_portfolio_notional", "max_portfolio_notional", Decimal)):
            if k in m:
                try:
                    setattr(self, attr, cast(m[k]))
                except Exception:
                    pass
        if "auto_converge" in m:
            self.auto_converge = str(m["auto_converge"]).lower() == "true"
        if "arm_mode" in m and m["arm_mode"] in ("list", "advisor"):
            self.arm_mode = m["arm_mode"]
        if self._snapshot() != before:   # 轮询兜底下只在变更时出声,避免 30s 刷屏
            logger.info("CFG loaded: mode=%s arm_mode=%s arm=%s hard=%s portfolio=%s converge=%s",
                        self.mode, self.arm_mode, sorted(self.arm_symbols), self.max_notional_hard,
                        self.max_portfolio_notional, self.auto_converge)

    async def watch(self, redis, pool):
        while True:
            try:
                ps = redis.pubsub()
                await ps.subscribe("dcm:config:updates")
                async for msg in ps.listen():
                    if msg.get("type") == "message" and msg.get("data") == "dualperp":
                        await self.load(pool)
            except Exception as e:
                logger.warning("config watch reconnect: %r", e)
                await asyncio.sleep(2)

    async def poll(self, pool, interval: int = 30):
        """轮询兜底:pubsub 半开假死(网络黑洞「握手 OK 零帧」课)时,armed/Kill
        开关仍须最迟 interval 秒到达引擎——武装开关的送达不能依赖单一通道。"""
        while True:
            await asyncio.sleep(interval)
            try:
                await self.load(pool)
            except Exception as e:
                logger.warning("config poll failed: %r", e)


CFG = LiveConfig()
