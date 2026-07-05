"""System health monitor — single backend-side watcher that evaluates the
same signals the frontend status bar shows, and emits a *cooldown-gated*
Feishu alert via the unified AlertBus when the system turns unhealthy or
recovers.

Why backend-side: the frontend status bar is polled by EVERY browser every
10s. Sending Feishu from the client would multiply by the number of open
tabs. This single task is the one source of truth for system-health Feishu.

Signals evaluated (mirrors api/v1/system.py get_system_status + the extra
probes the MarketCards bar used to fetch separately):
  - backend reachable (always True here — we run inside it)
  - DB pool usage  < 80%
  - Redis healthy
  - Binance WS connected
  - MT5 bridge online (HTTP bridge /health, the real truth source)

Edge-triggered: only emits on healthy→unhealthy and unhealthy→healthy
transitions; cooldown on AlertBus is a second backstop against flapping.
"""
import asyncio
import logging

logger = logging.getLogger(__name__)


class SystemHealthMonitor:
    def __init__(self):
        self.running = False
        self.task = None
        self.proc_pub_task = None
        self.check_interval = 30          # seconds between probes
        self.is_healthy = True            # last known verdict (start optimistic)
        self._consecutive_bad = 0         # require N bad probes before alerting
        self._bad_threshold = 2           # ~60s sustained before we cry wolf
        self._cooldown_s = 1800           # AlertBus dedup window (30 min)

    async def start(self):
        if self.running:
            return
        self.running = True
        self.task = asyncio.create_task(self._loop())
        # P2/admin-WS: dedicated publisher loop pushes the process snapshot to the
        # `strategy.processes` stream channel (admin panel subscribes → real-time).
        # Adaptive cadence: 3s when processes/positions exist, 15s when idle.
        self.proc_pub_task = asyncio.create_task(self._proc_publish_loop())
        logger.info("[system-health] monitor started")

    async def stop(self):
        self.running = False
        for _t in (self.task, getattr(self, "proc_pub_task", None)):
            if _t:
                _t.cancel()
                try:
                    await _t
                except asyncio.CancelledError:
                    pass
        logger.info("[system-health] monitor stopped")

    async def _proc_publish_loop(self):
        """Publish the strategy-process snapshot to stream channel `strategy.processes`
        via stream_hub → Redis ws:stream → Rust hub.broadcast → admin clients.
        Read-only, reuses compute_process_snapshot (same source as polling endpoint)."""
        await asyncio.sleep(20)  # let services init
        while self.running:
            interval = 15.0
            try:
                from app.core.database import AsyncSessionLocal
                from app.api.v1.strategy_processes import compute_process_snapshot
                from app.websocket.stream_hub import stream_hub
                async with AsyncSessionLocal() as _db:
                    snap = await compute_process_snapshot(_db)
                await stream_hub.publish("strategy.processes", snap)
                # faster cadence while anything is active (running procs or held inventory)
                s = snap.get("summary", {})
                if (s.get("total_processes", 0) or s.get("inventory_users", 0)):
                    interval = 3.0
            except asyncio.CancelledError:
                raise
            except Exception as _pe:
                logger.debug(f"[system-health] proc publish skipped: {_pe}")
            await asyncio.sleep(interval)

    async def _probe(self) -> dict:
        """Return {healthy: bool, failures: [str]} from the same signals
        the status bar evaluates. Each probe is defensive — a probe error
        counts as that component being down, never crashes the loop."""
        failures = []

        # DB pool usage
        try:
            from app.core.database import engine
            pool = engine.pool
            size = pool.size()
            max_overflow = getattr(pool, "_max_overflow", 0) or 0
            max_cap = (size + max_overflow) or 1
            active = pool.checkedout()
            if active / max_cap >= 0.8:
                failures.append(f"DB连接池高负载 {active}/{max_cap}")
        except Exception as e:
            failures.append("DB连接池探测失败")
            logger.debug(f"[system-health] db probe error: {e}")

        # Redis
        try:
            from app.core.redis_client import redis_client
            rc = redis_client.client
            ok = False
            if rc is not None:
                await rc.set("_health_probe", "1", ex=10)
                ok = (await rc.get("_health_probe")) is not None
            if not ok:
                failures.append("Redis异常")
        except Exception as e:
            failures.append("Redis异常")
            logger.debug(f"[system-health] redis probe error: {e}")

        # Binance WS
        ws_ok = False
        try:
            from app.services.binance_ws_client import binance_ws
            ws_ok = bool(binance_ws.connected)
        except Exception as e:
            logger.debug(f"[system-health] ws probe error: {e}")
        if not ws_ok:
            failures.append("Binance行情WS未连接")

        # MT5 bridge (real truth = HTTP bridge /health)
        try:
            from app.api.v1.system_monitor import mt5_overall_online
            if not await mt5_overall_online():
                failures.append("MT5桥离线")
        except Exception as e:
            failures.append("MT5桥探测失败")
            logger.debug(f"[system-health] mt5 probe error: {e}")

        return {"healthy": len(failures) == 0, "failures": failures}

    async def _emit(self, healthy: bool, failures: list):
        """Fan out a cooldown-gated Feishu (+WS+DB) alert via AlertBus."""
        from app.core.database import AsyncSessionLocal
        from app.services.agent.feishu_broadcast import broadcast
        try:
            async with AsyncSessionLocal() as db:
                if healthy:
                    await broadcast(
                        db,
                        level="info",
                        category="system_health_recovered",
                        message="✅ testgo 系统已恢复正常（核心服务全部健康）",
                        cooldown_s=self._cooldown_s,
                    )
                else:
                    body = "🚨 testgo 系统异常\n**故障组件**:\n" + "\n".join(
                        f"- {f}" for f in failures
                    )
                    await broadcast(
                        db,
                        level="danger",
                        category="system_health_degraded",
                        message=body,
                        payload={"failures": failures},
                        cooldown_s=self._cooldown_s,
                    )
        except Exception as e:
            logger.warning(f"[system-health] feishu emit failed: {e}")

    async def _loop(self):
        logger.info("[system-health] loop started")
        # Grace period so startup transients (WS/MT5 still connecting) don't alert
        await asyncio.sleep(60)
        while self.running:
            try:
                res = await self._probe()
                healthy = res["healthy"]

                if not healthy:
                    self._consecutive_bad += 1
                else:
                    self._consecutive_bad = 0

                # healthy → unhealthy (sustained)
                if self.is_healthy and self._consecutive_bad >= self._bad_threshold:
                    self.is_healthy = False
                    logger.warning(f"[system-health] DEGRADED: {res['failures']}")
                    await self._emit(False, res["failures"])
                # unhealthy → healthy
                elif (not self.is_healthy) and healthy:
                    self.is_healthy = True
                    logger.info("[system-health] RECOVERED")
                    await self._emit(True, [])

                # P3: strategy reconciliation alert scan (same source as the admin panel's
                # red cells). Cooldown-gated inside AlertBus, so safe to run every cycle.
                try:
                    from app.core.database import AsyncSessionLocal
                    from app.api.v1.strategy_processes import run_reconciliation_alert_scan
                    async with AsyncSessionLocal() as _db:
                        await run_reconciliation_alert_scan(_db)
                except Exception as _re:
                    logger.debug(f"[system-health] reconciliation scan skipped: {_re}")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[system-health] loop error: {e}")

            await asyncio.sleep(self.check_interval)


system_health_monitor = SystemHealthMonitor()
