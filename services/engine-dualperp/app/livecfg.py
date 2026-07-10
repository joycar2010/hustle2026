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

    @staticmethod
    def _syms(s: str) -> set[str]:
        return {x.strip().upper() for x in (s or "").split(",") if x.strip()}

    async def load(self, pool):
        try:
            rows = await pool.fetch("SELECT ckey,cval FROM engine_config WHERE engine='dualperp'")
        except Exception as e:
            logger.warning("engine_config load failed (用现值): %r", e)
            return
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
        logger.info("CFG loaded: mode=%s arm=%s hard=%s portfolio=%s converge=%s",
                    self.mode, sorted(self.arm_symbols), self.max_notional_hard,
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


CFG = LiveConfig()
