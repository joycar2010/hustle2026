"""
QH系统对账Worker - P0.3
用于对账UNKNOWN/RECONCILING状态的订单
"""
import asyncio
import inspect
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
import httpx

from connector import _EXPLICIT_NOT_FILLED_RETCODES

from qh_command_tracer import (
    get_tracer,
    CommandStatus,
    CommandType,
    TraceTimestamp
)


logger = logging.getLogger(__name__)


AGENT_SENDING_GRACE_SECONDS = 2.0
RECONCILIATION_SCAN_LIMIT = 100
RECONCILIATION_SCAN_COUNT = 1000


def _decode_redis_hash(raw):
    if not isinstance(raw, dict):
        return {}
    return {
        key.decode() if isinstance(key, bytes) else key:
        value.decode() if isinstance(value, bytes) else value
        for key, value in raw.items()
    }


class ReconciliationWorker:
    """对账Worker - 每5秒扫描一次UNKNOWN状态的订单"""

    def __init__(self,
                 redis_client,
                 db_session,
                 bridge_main_url: str,
                 bridge_hedge_url: str,
                 bridge_api_key: str,
                 connection_factory=None,
                 close_confirmed_callback=None,
                 open_confirmed_callback=None,
                 open_saga_callback=None,
                 command_active_callback=None):
        self.redis = redis_client
        self.db = db_session
        self.tracer = get_tracer()
        self.bridge_main_url = bridge_main_url
        self.bridge_hedge_url = bridge_hedge_url
        self.bridge_api_key = bridge_api_key
        self.connection_factory = connection_factory
        self.close_confirmed_callback = close_confirmed_callback
        self.open_confirmed_callback = open_confirmed_callback
        self.open_saga_callback = open_saga_callback
        self.command_active_callback = command_active_callback
        self.running = False

        # HTTP客户端(复用连接)
        self.http_client = httpx.AsyncClient(
            headers={"x-api-key": bridge_api_key},
            timeout=httpx.Timeout(10.0)
        )

    async def start(self):
        """启动对账Worker"""
        self.running = True
        logger.info("ReconciliationWorker started")

        while self.running:
            try:
                await self._reconcile_cycle()
            except Exception as e:
                logger.error(f"对账循环异常: {e}", exc_info=True)

            await asyncio.sleep(5)

    async def stop(self):
        """停止Worker"""
        self.running = False
        await self.http_client.aclose()
        logger.info("ReconciliationWorker stopped")

    async def _command_is_active(self, command_id, command):
        """Fail closed when the local dispatcher still owns this command."""
        callback = self.command_active_callback
        if callback is None:
            return False
        try:
            active = callback(command_id, command)
            if inspect.isawaitable(active):
                active = await active
            return bool(active)
        except Exception as exc:
            logger.warning(
                "Active command guard unavailable for %s; reconciliation deferred: %s",
                command_id, exc,
            )
            return True

    async def _reconcile_cycle(self):
        """一轮对账循环"""
        # redis-py is synchronous. The old four-pass SCAN/HGETALL loop could
        # stop every trade finalizer on this event loop for several seconds.
        commands, counts = await asyncio.to_thread(
            self._discover_reconciliation_commands)

        if not commands:
            return

        logger.info(
            "Reconciliation cycle: %s commands "
            "(SUBMITTED:%s, UNKNOWN:%s, RECONCILING:%s, MANUAL_OPEN:%s)",
            len(commands), counts[CommandStatus.SUBMITTED.value],
            counts[CommandStatus.UNKNOWN.value],
            counts[CommandStatus.RECONCILING.value], counts["MANUAL_OPEN"],
        )

        # 并发对账
        tasks = [
            self._reconcile_one(command_id, command)
            for command_id, command in commands
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    def _discover_reconciliation_commands(self):
        """Classify recoverable commands with one Redis read pass."""
        keys = []
        cursor = 0
        while True:
            cursor, page = self.redis.scan(
                cursor=cursor,
                match=f"{self.tracer.key_prefix}*",
                count=RECONCILIATION_SCAN_COUNT,
            )
            keys.extend(page or [])
            if cursor == 0:
                break

        # SCAN may repeat keys while the keyspace changes.
        keys = list(dict.fromkeys(keys))
        wanted = (
            CommandStatus.SUBMITTED.value,
            CommandStatus.UNKNOWN.value,
            CommandStatus.RECONCILING.value,
        )
        buckets = {status: [] for status in wanted}
        manual = []
        if keys:
            pipe = self.redis.pipeline(transaction=False)
            for key in keys:
                pipe.hgetall(key)
            rows = pipe.execute()
            for key, raw in zip(keys, rows):
                command = _decode_redis_hash(raw)
                if not command:
                    continue
                status = str(command.get("status") or "")
                key_text = key.decode() if isinstance(key, bytes) else str(key)
                command_id = key_text.removeprefix(self.tracer.key_prefix)
                if status in buckets:
                    if len(buckets[status]) < RECONCILIATION_SCAN_LIMIT:
                        buckets[status].append((command_id, command))
                    continue
                if (status == CommandStatus.MANUAL_REVIEW.value and
                        command.get("type") == CommandType.OPEN_PAIR.value and
                        command.get("main_request_id") and
                        command.get("hedge_request_id") and
                        len(manual) < RECONCILIATION_SCAN_LIMIT):
                    manual.append((command_id, command))

        ordered = []
        seen = set()
        for status in wanted:
            for item in buckets[status]:
                if item[0] not in seen:
                    seen.add(item[0])
                    ordered.append(item)
        for item in manual:
            if item[0] not in seen:
                seen.add(item[0])
                ordered.append(item)
        counts = {status: len(buckets[status]) for status in wanted}
        counts["MANUAL_OPEN"] = len(manual)
        return ordered, counts

    async def _reconcile_one(self, command_id: str,
                             command: Optional[Dict[str, str]] = None):
        """对账单笔订单"""
        try:
            if command is not None:
                # Discovery runs in a worker thread and returns a point-in-time
                # snapshot. Re-read before acting so a command that completed
                # meanwhile can never be rewritten or sent through truth reads.
                cmd = await asyncio.to_thread(
                    self.tracer.get_command, command_id)
            else:
                cmd = self.tracer.get_command(command_id)
            if not cmd:
                logger.warning(f"命令不存在: {command_id}")
                return

            status = str(cmd.get("status") or "")
            recoverable = status in {
                CommandStatus.SUBMITTED.value,
                CommandStatus.UNKNOWN.value,
                CommandStatus.RECONCILING.value,
            }
            recoverable_manual_open = (
                status == CommandStatus.MANUAL_REVIEW.value and
                cmd.get("type") == CommandType.OPEN_PAIR.value and
                cmd.get("main_request_id") and cmd.get("hedge_request_id")
            )
            if not recoverable and not recoverable_manual_open:
                return

            if await self._command_is_active(command_id, cmd):
                logger.debug("Reconciliation deferred for active command %s", command_id)
                return

            # 更新状态为对账中
            cmd_type = cmd.get("type")
            if (cmd_type == CommandType.OPEN_PAIR.value and
                    self.open_saga_callback is not None):
                handled = self.open_saga_callback(command_id, cmd)
                if inspect.isawaitable(handled):
                    handled = await handled
                if handled:
                    return
            # Let the live durable-saga owner defer an exact job before the
            # worker rewrites SUBMITTED underneath the dispatcher.
            if cmd.get("status") in (CommandStatus.SUBMITTED.value, CommandStatus.UNKNOWN.value):
                self.tracer.update_status(command_id, CommandStatus.RECONCILING)
                self.tracer.record_timestamp(command_id, TraceTimestamp.RECONCILE_START)
            # Close truth must be scoped to the command's user and exact
            # ticket. The legacy fixed bridge URLs are not ownership proof.
            if cmd_type == CommandType.CLOSE_PAIR.value:
                await self._reconcile_close(command_id, cmd)
                return
            if cmd_type == CommandType.CLOSE_LEG.value:
                await self._reconcile_close_leg(command_id, cmd)
                return

            # Durable Agent request ids remain the first source for opens.
            if await self._reconcile_agent_status(command_id, cmd):
                return

            if cmd_type == CommandType.OPEN_PAIR.value:
                await self._reconcile_open(command_id, cmd)

        except Exception as e:
            logger.error(f"对账失败 {command_id}: {e}", exc_info=True)

    async def _reconcile_agent_status(self, command_id: str, cmd: Dict[str, str]) -> bool:
        main_rid = cmd.get("main_request_id")
        hedge_rid = cmd.get("hedge_request_id")
        if not main_rid or not hedge_rid:
            return False

        main, hedge = await self._query_agent_status_pair(cmd)
        if main is None or hedge is None:
            return False

        states = tuple(str(status.get("state") or "UNKNOWN").upper()
                       for status in (main, hedge))
        for leg, status in (("main", main), ("hedge", hedge)):
            raw_result = status.get("result")
            result = raw_result if isinstance(raw_result, dict) else {}
            ticket = result.get("order") or result.get("deal") or result.get("ticket")
            if ticket:
                cmd[f"{leg}_ticket"] = str(ticket)
                self.tracer.update_field(command_id, f"{leg}_ticket", ticket)
            if result:
                self.tracer.update_field(command_id, f"{leg}_result", result)
        if states == ("DONE", "DONE"):
            evidence = {
                "main_ok": True,
                "hedge_ok": True,
                "agent_states": {"main": states[0], "hedge": states[1]},
            }
            for leg, status in (("main", main), ("hedge", hedge)):
                raw_result = status.get("result")
                result = raw_result if isinstance(raw_result, dict) else {}
                evidence[leg] = result
                ticket = result.get("order") or result.get("deal") or result.get("ticket")
                if ticket:
                    cmd[f"{leg}_ticket"] = str(ticket)
                    self.tracer.update_field(command_id, f"{leg}_ticket", ticket)
                self.tracer.update_field(command_id, f"{leg}_result", result)
            if not await self._apply_confirmed_open(
                    command_id, cmd, evidence, "COMPLETED"):
                await self._mark_manual_review(
                    command_id,
                    "Agent confirmed both fills but durable open cleanup failed",
                )
                return True
            self.tracer.update_status(command_id, CommandStatus.COMPLETED)
            self.tracer.record_timestamp(command_id, TraceTimestamp.RECONCILE_DONE)
            self.tracer.update_field(command_id, "reconcile_result", "agent_both_done")
            return True

        terminal = {"DONE", "FAILED"}
        if all(state in terminal for state in states):
            evidence = {
                "main": (main.get("result")
                         if isinstance(main.get("result"), dict) else {}),
                "hedge": (hedge.get("result")
                          if isinstance(hedge.get("result"), dict) else {}),
                "main_ok": states[0] == "DONE",
                "hedge_ok": states[1] == "DONE",
                "agent_states": {"main": states[0], "hedge": states[1]},
            }
            explicit_no_fill = {
                leg: self._agent_result_explicit_not_filled(evidence[leg])
                for leg in ("main", "hedge")
            }
            evidence["agent_no_fill"] = explicit_no_fill
            for leg in ("main", "hedge"):
                result = evidence[leg]
                ticket = result.get("order") or result.get("deal") or result.get("ticket")
                if ticket:
                    cmd[f"{leg}_ticket"] = str(ticket)
                    self.tracer.update_field(command_id, f"{leg}_ticket", ticket)
            if states[0] == states[1] == "FAILED":
                if not all(explicit_no_fill.values()):
                    evidence["reason"] = "Agent terminal failure lacks explicit no-fill proof"
                    if not await self._apply_confirmed_open(
                            command_id, cmd, evidence, "MANUAL_REVIEW"):
                        logger.error("Open manual-review hold failed %s", command_id)
                    await self._mark_manual_review(
                        command_id, evidence["reason"])
                    return True
                evidence["confirmed_no_fill"] = True
                if not await self._apply_confirmed_open(
                        command_id, cmd, evidence, "FAILED"):
                    await self._mark_manual_review(
                        command_id,
                        "Agent confirmed both failures but durable open cleanup failed",
                    )
                    return True
                await self._mark_failed(command_id, "Agent确认双腿失败")
            else:
                failed_leg = next(
                    (index for index, state in enumerate(states)
                     if state == "FAILED"), None)
                if failed_leg is not None and not explicit_no_fill[
                        ("main", "hedge")[failed_leg]]:
                    evidence["reason"] = "Agent terminal failure lacks explicit no-fill proof"
                    if not await self._apply_confirmed_open(
                            command_id, cmd, evidence, "MANUAL_REVIEW"):
                        logger.error("Open manual-review hold failed %s", command_id)
                    await self._mark_manual_review(
                        command_id, evidence["reason"])
                    return True
                if not await self._apply_confirmed_open(
                        command_id, cmd, evidence, "SINGLE_LEG_EXPOSED"):
                    await self._mark_manual_review(
                        command_id,
                        "Agent confirmed a single-leg fill but durable risk hold failed",
                    )
                    return True
                await self._handle_single_leg_exposed(command_id, "agent_terminal_mismatch", cmd)
            return True

        self.tracer.update_field(
            command_id, "reconcile_agent_states",
            {"main": states[0], "hedge": states[1]},
        )
        if "UNKNOWN" in states:
            # UNKNOWN must not hide authoritative broker truth.
            return False
        if "SENDING" in states:
            # Give the Agent a short result-file grace period, then fall back
            # to the same user's broker positions/history.
            return self._get_command_age_seconds(cmd) < AGENT_SENDING_GRACE_SECONDS
        return False

    async def _query_agent_status_pair(self, cmd: Dict[str, str]):
        """Read both legs without converting a 404 into a broker failure."""
        try:
            connection = await self._user_connection(cmd.get("username"))
        except Exception as exc:
            logger.warning("User Agent connector unavailable %s: %s",
                           cmd.get("command_id") or "", exc)
            connection = None

        async def one(leg_name, request_id):
            leg_connection = (getattr(connection, leg_name, None)
                              if connection is not None else None)
            if leg_connection is None:
                return None
            try:
                order_status = getattr(leg_connection, "order_status", None)
                if callable(order_status):
                    payload = order_status(request_id)
                else:
                    getter = getattr(leg_connection, "_get", None)
                    if not callable(getter):
                        return None
                    payload = getter(f"/mt5/order-status/{request_id}")
                if inspect.isawaitable(payload):
                    payload = await payload
                return payload if isinstance(payload, dict) else None
            except httpx.HTTPStatusError as exc:
                response = getattr(exc, "response", None)
                status_code = getattr(response, "status_code", None)
                if status_code == 404:
                    return {
                        "state": "NOT_FOUND",
                        "http_status": 404,
                        "request_id": request_id,
                        "error": str(exc),
                    }
                logger.warning("User Agent status query failed %s %s: %s",
                               cmd.get("username"), request_id, exc)
            except Exception as exc:
                logger.warning("User Agent status query failed %s %s: %s",
                               cmd.get("username"), request_id, exc)
            return None

        main_rid = cmd.get("main_request_id")
        hedge_rid = cmd.get("hedge_request_id")
        return await asyncio.gather(
            one("main", main_rid), one("hedge", hedge_rid))

    @staticmethod
    def _agent_result_explicit_not_filled(result):
        """Accept only a structured no-fill result or MT5 INVALID (10013)."""
        if not isinstance(result, dict):
            return False
        if result.get("success") or result.get("ok"):
            return False
        for key in ("order", "deal", "ticket", "position"):
            try:
                if int(result.get(key) or 0) > 0:
                    return False
            except (TypeError, ValueError):
                return False
        if result.get("not_sent") and result.get("dispatch_durable") is False:
            return True
        raw = result.get("final_retcode", result.get("retcode"))
        try:
            retcode = int(raw)
        except (TypeError, ValueError):
            retcode = None
        return bool(
            result.get("not_filled") is True and
            str(result.get("certainty") or "").upper() == "NOT_FILLED" and
            (retcode in _EXPLICIT_NOT_FILLED_RETCODES or
             result.get("dispatch_durable") is False)
        ) or retcode in _EXPLICIT_NOT_FILLED_RETCODES

    async def _reconcile_open(self, command_id: str, cmd: Dict[str, str]):
        """对账开仓订单"""
        main_ticket = cmd.get("main_ticket")
        hedge_ticket = cmd.get("hedge_ticket")

        if not main_ticket or not hedge_ticket:
            # Old ordered opens can have a terminal main rejection while the
            # second leg was never dispatched.  Query both request ids before
            # the age-based manual-review fallback so a proven no-fill frees
            # its slot/capacity immediately.
            if cmd.get("main_request_id") and cmd.get("hedge_request_id"):
                main_status, hedge_status = await self._query_agent_status_pair(cmd)
                recovered = await self._reconcile_missing_pair_failure(
                    command_id, cmd, main_status, hedge_status)
                if recovered:
                    return
            if self._get_command_age_seconds(cmd) > 120:
                evidence = {
                    "main_ok": False,
                    "hedge_ok": False,
                    "reason": "missing_pair_tickets",
                }
                if not await self._apply_confirmed_open(
                        command_id, cmd, evidence, "MANUAL_REVIEW"):
                    logger.error("Open manual-review hold failed %s", command_id)
                await self._mark_manual_review(command_id, "开仓120秒后仍缺少可证明的双腿ticket")
            return

        # 查询三个来源确认状态
        # 1. Bridge history API
        try:
            connection = await self._user_connection(cmd.get("username"))
        except Exception as exc:
            logger.warning("User open connector unavailable %s: %s", command_id, exc)
            connection = None
        main_leg = getattr(connection, "main", None) if connection is not None else None
        hedge_leg = getattr(connection, "hedge", None) if connection is not None else None

        # Query all broker evidence concurrently through this command's user.
        (main_deal_result, hedge_deal_result,
         main_pos_result, hedge_pos_result) = await asyncio.gather(
            self._check_deal_in_leg(main_leg, main_ticket),
            self._check_deal_in_leg(hedge_leg, hedge_ticket),
            self._check_position_in_leg(main_leg, main_ticket),
            self._check_position_in_leg(hedge_leg, hedge_ticket),
        )
        main_deal_state, main_deal = main_deal_result
        hedge_deal_state, hedge_deal = hedge_deal_result

        # 2. 数据库hedge_positions表
        db_position = await self._check_position_in_db(cmd.get("username"), cmd.get("symbol"), main_ticket, hedge_ticket)

        # 3. Broker的positions (通过Bridge查询)
        main_pos_state, main_pos = main_pos_result
        hedge_pos_state, hedge_pos = hedge_pos_result

        def leg_truth(deal_state, deal, position_state, position):
            if "FILLED" in (deal_state, position_state):
                return "FILLED", position or deal
            if deal_state == position_state == "NOT_FOUND":
                return "NOT_FOUND", None
            return "UNAVAILABLE", None

        main_truth, main_payload = leg_truth(
            main_deal_state, main_deal, main_pos_state, main_pos)
        hedge_truth, hedge_payload = leg_truth(
            hedge_deal_state, hedge_deal, hedge_pos_state, hedge_pos)
        main_filled = main_truth == "FILLED"
        hedge_filled = hedge_truth == "FILLED"
        evidence = {
            "main": main_payload or {"ticket": main_ticket},
            "hedge": hedge_payload or {"ticket": hedge_ticket},
            "main_ok": main_filled,
            "hedge_ok": hedge_filled,
            "broker_truth": {"main": main_truth, "hedge": hedge_truth},
        }

        if main_filled and hedge_filled:
            # 双腿都成交
            if not await self._apply_confirmed_open(
                    command_id, cmd, evidence, "COMPLETED"):
                await self._mark_manual_review(
                    command_id,
                    "Broker confirmed both fills but durable open cleanup failed",
                )
                return
            self.tracer.update_status(command_id, CommandStatus.COMPLETED)
            self.tracer.record_timestamp(command_id, TraceTimestamp.RECONCILE_DONE)
            self.tracer.update_field(command_id, "reconcile_result", "both_filled")

            # 更新deal信息
            if main_deal:
                self.tracer.update_field(command_id, "main_deal", main_deal.get("deal"))
                self.tracer.update_field(command_id, "main_filled_price", main_deal.get("price"))
            if hedge_deal:
                self.tracer.update_field(command_id, "hedge_deal", hedge_deal.get("deal"))
                self.tracer.update_field(command_id, "hedge_filled_price", hedge_deal.get("price"))

            logger.info(f"✓ 对账成功 {command_id}: 双腿已成交")

        elif main_filled and hedge_truth == "NOT_FOUND":
            # 单腿暴露 - 主腿成交,对冲腿未成交
            if not await self._apply_confirmed_open(
                    command_id, cmd, evidence, "SINGLE_LEG_EXPOSED"):
                await self._mark_manual_review(
                    command_id,
                    "Broker confirmed a main-leg-only fill but durable risk hold failed",
                )
                return
            await self._handle_single_leg_exposed(command_id, "main_filled_hedge_missing", cmd)

        elif main_truth == "NOT_FOUND" and hedge_filled:
            # 单腿暴露 - 对冲腿成交,主腿未成交
            if not await self._apply_confirmed_open(
                    command_id, cmd, evidence, "SINGLE_LEG_EXPOSED"):
                await self._mark_manual_review(
                    command_id,
                    "Broker confirmed a hedge-leg-only fill but durable risk hold failed",
                )
                return
            await self._handle_single_leg_exposed(command_id, "hedge_filled_main_missing", cmd)

        elif "UNAVAILABLE" in (main_truth, hedge_truth):
            reason = "Open truth unavailable: main=%s hedge=%s" % (
                main_truth, hedge_truth)
            if main_filled or hedge_filled or self._get_command_age_seconds(cmd) > 120:
                evidence["reason"] = reason
                await self._apply_confirmed_open(
                    command_id, cmd, evidence, "MANUAL_REVIEW")
                await self._mark_manual_review(command_id, reason)
            else:
                logger.debug("Open reconciliation pending %s: %s", command_id, reason)

        else:
            # Only two authoritative NOT_FOUND results can prove no fill.
            age_sec = self._get_command_age_seconds(cmd)
            if age_sec > 30:
                # 超过30秒仍未成交,判定为失败
                evidence["confirmed_no_fill"] = True
                if not await self._apply_confirmed_open(
                        command_id, cmd, evidence, "FAILED"):
                    await self._mark_manual_review(
                        command_id,
                        "Broker confirmed no fills but durable open cleanup failed",
                    )
                    return
                await self._mark_failed(command_id, "双腿均未成交,超过30秒")
            else:
                # 继续等待
                logger.debug(f"对账中 {command_id}: 双腿均未成交,等待中 ({age_sec:.1f}s)")

    async def _reconcile_missing_pair_failure(self, command_id, cmd,
                                               main_status, hedge_status):
        """Auto-fail only an ordered pair with independently proven no-fill."""
        main_result = (main_status.get("result")
                       if isinstance(main_status, dict) and
                       isinstance(main_status.get("result"), dict) else {})
        # Some MT5 bridges keep the outer request state at PENDING while the
        # result already contains a terminal retcode (notably 10013,
        # INVALID).  The structured result is the stronger evidence here:
        # once it proves no order/deal/ticket was created, do not wait for the
        # stale outer state to become FAILED and later expose a review latch.
        main_state = (str(main_status.get("state") or "").upper()
                      if isinstance(main_status, dict) else "")
        main_no_fill = (
            main_state not in ("DONE", "SUCCESS") and
            self._agent_result_explicit_not_filled(main_result))
        hedge_not_dispatched = (
            isinstance(hedge_status, dict) and
            str(hedge_status.get("state") or "").upper() == "NOT_FOUND" and
            int(hedge_status.get("http_status") or 0) == 404 and
            self._leg_dispatch_started(cmd, "hedge") is False)
        if not (main_no_fill and hedge_not_dispatched):
            return await self._reconcile_missing_pair_snapshot_failure(
                command_id, cmd, main_status, hedge_status)

        try:
            connection = await self._user_connection(cmd.get("username"))
        except Exception:
            connection = None
        main_leg = getattr(connection, "main", None) if connection else None
        hedge_leg = getattr(connection, "hedge", None) if connection else None
        # The explicit MT5 INVALID result and an undispatched hedge already
        # prove this command created no broker ticket.  Position snapshots
        # only need to be registered and fresh; another slot may legitimately
        # have an open position and must not block this slot's auto-failure.
        main_snapshot_ok, hedge_snapshot_ok = await asyncio.gather(
            self._position_snapshot_available(main_leg),
            self._position_snapshot_available(hedge_leg),
        )
        if not (main_snapshot_ok and hedge_snapshot_ok):
            return False
        if not self._slot_ownership_empty(cmd):
            return False

        evidence = {
            "main": dict(main_result),
            "hedge": {"request_id": cmd.get("hedge_request_id"),
                      "not_sent": True, "http_status": 404},
            "main_ok": False,
            "hedge_ok": False,
            "agent_states": {
                "main": str(main_status.get("state") or "").upper(),
                "hedge": "NOT_FOUND",
            },
            "agent_no_fill": {"main": True, "hedge": True},
            "confirmed_no_fill": True,
            "broker_truth": {"main": "NOT_FOUND", "hedge": "NOT_FOUND"},
            "reason": "main_invalid_request_hedge_not_dispatched",
        }
        if not await self._apply_confirmed_open(
                command_id, cmd, evidence, "FAILED"):
            await self._mark_manual_review(
                command_id, "Confirmed pair no-fill cleanup failed")
            return True
        await self._mark_failed(command_id, "双腿均未成交（MT5请求无效/对冲腿未派发）")
        return True

    async def _reconcile_missing_pair_snapshot_failure(
            self, command_id, cmd, main_status, hedge_status):
        """Close a lost-open review only with complete broker no-fill proof."""
        if self._get_command_age_seconds(cmd) <= 120:
            return False
        if (self._leg_dispatch_started(cmd, "main") is not True or
                self._leg_dispatch_started(cmd, "hedge") is not False):
            return False

        def status_can_have_no_ticket(status):
            if status is None:
                return True
            if not isinstance(status, dict):
                return False
            state = str(status.get("state") or "").upper()
            if state in ("DONE", "SUCCESS"):
                return False
            result = status.get("result")
            if isinstance(result, dict):
                for key in ("order", "deal", "ticket", "position"):
                    try:
                        if int(result.get(key) or 0) > 0:
                            return False
                    except (TypeError, ValueError):
                        return False
            return True

        if (not status_can_have_no_ticket(main_status) or
                not status_can_have_no_ticket(hedge_status)):
            return False

        try:
            connection = await self._user_connection(cmd.get("username"))
        except Exception:
            connection = None
        main_leg = getattr(connection, "main", None) if connection else None
        hedge_leg = getattr(connection, "hedge", None) if connection else None
        if main_leg is None or hedge_leg is None:
            return False

        markers = {
            "main": self._pair_history_markers(cmd, "main"),
            "hedge": self._pair_history_markers(cmd, "hedge"),
        }
        # A no-fill decision must be tied to the durable request/comment
        # identity.  Without it, an empty history can only mean that the
        # query was incomplete or that an older bridge omitted correlation.
        if not markers["main"] or not markers["hedge"]:
            return False

        main_snapshot, hedge_snapshot = await asyncio.gather(
            self._read_position_snapshot(main_leg),
            self._read_position_snapshot(hedge_leg),
        )
        if (not self._snapshot_is_authoritative(main_snapshot) or
                not self._snapshot_is_authoritative(hedge_snapshot)):
            return False

        # Positions from other configured slots are expected and must not
        # block this slot's independent no-fill resolution.  Only a position
        # carrying this request's correlation marker is evidence of a fill.
        if (self._snapshot_pair_match(main_snapshot, markers["main"]) is not None or
                self._snapshot_pair_match(hedge_snapshot, markers["hedge"]) is not None):
            return False

        main_history, hedge_history = await asyncio.gather(
            self._read_pair_history(main_leg, cmd.get("symbol")),
            self._read_pair_history(hedge_leg, cmd.get("symbol")),
        )
        if main_history is None or hedge_history is None:
            return False
        if (self._history_pair_match(main_history, markers["main"]) is not None or
                self._history_pair_match(hedge_history, markers["hedge"]) is not None):
            return False
        if not self._slot_ownership_empty(cmd):
            return False

        evidence = {
            "main": {"request_id": cmd.get("main_request_id"),
                     "snapshot": main_snapshot},
            "hedge": {"request_id": cmd.get("hedge_request_id"),
                      "snapshot": hedge_snapshot, "not_sent": True},
            "main_ok": False,
            "hedge_ok": False,
            "agent_states": {
                "main": str((main_status or {}).get("state") or "UNKNOWN").upper(),
                "hedge": str((hedge_status or {}).get("state") or "NOT_FOUND").upper(),
            },
            "agent_no_fill": {"main": True, "hedge": True},
            "broker_truth": {"main": "NOT_FOUND", "hedge": "NOT_FOUND"},
            "history_complete": {"main": True, "hedge": True},
            "confirmed_no_fill": True,
            "reason": "agent_state_missing_fresh_empty_pair_history",
        }
        if not await self._apply_confirmed_open(
                command_id, cmd, evidence, "FAILED"):
            await self._mark_manual_review(
                command_id, "Confirmed pair no-fill cleanup failed")
            return True
        await self._mark_failed(
            command_id, "Pair broker snapshots empty and history has no matching fill")
        return True

    async def _read_pair_history(self, leg_connection, symbol):
        """Read complete deal/order windows; unavailable means no proof."""
        getter = getattr(leg_connection, "_get", None)
        if not callable(getter):
            return None
        snapshots = {}
        for path, key in (("/mt5/history/deals", "deals"),
                          ("/mt5/history/orders", "orders")):
            try:
                params = {"days": 1}
                if symbol:
                    params["symbol"] = symbol
                payload = getter(path, **params)
                if inspect.isawaitable(payload):
                    payload = await payload
                if not isinstance(payload, dict):
                    return None
                if (payload.get("registered") is False or
                        payload.get("snapshot_stale") is True or
                        payload.get("truncated") is True or
                        payload.get("complete") is False):
                    return None
                rows = payload.get(key)
                if not isinstance(rows, list) or any(
                        not isinstance(row, dict) for row in rows):
                    return None
                snapshots[key] = rows
            except Exception as exc:
                logger.debug("Pair history unavailable path=%s: %s", path, exc)
                return None
        return snapshots

    @staticmethod
    def _snapshot_is_authoritative(snapshot):
        """Accept only a registered/fresh broker position snapshot.

        Older test doubles and MT4 connectors expose ``registered=True``
        without version fields.  The MT5 bridge instead exposes broker
        snapshot sequence/timestamp metadata.  An unmarked empty dictionary
        is deliberately rejected because it is indistinguishable from a
        failed or partial read.
        """
        if not isinstance(snapshot, dict):
            return False
        if snapshot.get("registered") is False:
            return False
        stale = snapshot.get("snapshot_stale", False)
        if isinstance(stale, str):
            stale = stale.strip().lower() in ("1", "true", "yes", "stale")
        if stale:
            return False
        positions = snapshot.get("positions")
        if not isinstance(positions, list) or any(
                not isinstance(row, dict) for row in positions):
            return False

        if snapshot.get("registered") is True:
            return True
        source = str(snapshot.get("snapshot_source") or "").lower()
        try:
            sequence = int(snapshot.get("snapshot_seq") or 0)
            timestamp = int(snapshot.get("snapshot_ts_ms") or 0)
        except (TypeError, ValueError):
            return False
        if source != "broker" or sequence <= 0 or timestamp <= 0:
            return False
        try:
            age_ms = float(snapshot.get("snapshot_age_ms"))
        except (TypeError, ValueError):
            age_ms = 0.0
        return age_ms >= 0.0 and age_ms <= 15000.0

    @staticmethod
    def _snapshot_pair_match(snapshot, markers):
        if not isinstance(snapshot, dict) or not markers:
            return None
        rows = snapshot.get("positions")
        if not isinstance(rows, list):
            return None
        for row in rows:
            if not isinstance(row, dict):
                continue
            haystack = json.dumps(row, ensure_ascii=True,
                                  sort_keys=True).lower()
            if any(marker in haystack for marker in markers):
                return row
        return None

    @classmethod
    def _pair_history_markers(cls, cmd, leg):
        result = cls._decode_command_mapping(cmd.get("final_result"))
        contexts = result.get("leg_contexts")
        context = contexts.get(leg) if isinstance(contexts, dict) else {}
        leg_result = result.get(leg)
        markers = [cmd.get("pair_request_id"), cmd.get("%s_request_id" % leg)]
        for source in (context, leg_result):
            if isinstance(source, dict):
                markers.extend((source.get("dispatch_comment"),
                                source.get("comment"),
                                source.get("dispatch_request_id"),
                                source.get("request_id")))
        return tuple(dict.fromkeys(str(marker).strip().lower()
                                   for marker in markers if marker))

    @staticmethod
    def _history_pair_match(history, markers):
        if not markers:
            return None
        for rows in history.values():
            for row in rows:
                haystack = json.dumps(row, ensure_ascii=True,
                                      sort_keys=True).lower()
                if any(marker in haystack for marker in markers):
                    return row
        return None

    @staticmethod
    def _decode_command_mapping(value):
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
                return decoded if isinstance(decoded, dict) else {}
            except (TypeError, ValueError):
                return {}
        return {}

    @classmethod
    def _leg_dispatch_started(cls, cmd, leg):
        result = cls._decode_command_mapping(cmd.get("final_result"))
        contexts = result.get("leg_contexts")
        context = contexts.get(leg) if isinstance(contexts, dict) else None
        if isinstance(context, dict) and "dispatch_started" in context:
            return bool(context.get("dispatch_started"))
        leg_result = result.get(leg)
        if isinstance(leg_result, dict) and "dispatch_started" in leg_result:
            return bool(leg_result.get("dispatch_started"))
        return None

    async def _empty_position_snapshot(self, leg_connection):
        payload = await self._read_position_snapshot(leg_connection)
        if payload is None:
            return False
        positions = payload.get("positions")
        return isinstance(positions, list) and not positions

    async def _position_snapshot_available(self, leg_connection):
        """Return true for a registered, non-stale account snapshot."""
        payload = await self._read_position_snapshot(leg_connection)
        return payload is not None and isinstance(payload.get("positions"), list)

    async def _read_position_snapshot(self, leg_connection):
        if leg_connection is None:
            return None
        try:
            positions_call = getattr(leg_connection, "positions", None)
            if not callable(positions_call):
                return None
            payload = positions_call()
            if inspect.isawaitable(payload):
                payload = await payload
            if not isinstance(payload, dict):
                return None
            stale = payload.get("snapshot_stale", False)
            if isinstance(stale, str):
                stale = stale.strip().lower() in ("1", "true", "yes", "stale")
            if payload.get("registered") is False or stale:
                return None
            return payload
        except Exception:
            return None

    def _slot_ownership_empty(self, cmd):
        if self.redis is None:
            return False
        username = str(cmd.get("username") or "").strip()
        symbol = str(cmd.get("symbol") or "XAUUSD").strip()
        try:
            slot = int(cmd.get("slot") or 0)
        except (TypeError, ValueError):
            slot = 0
        if not username or not symbol or slot < 1:
            return False
        try:
            # No-fill proof is scoped to the command's target slot.  Other
            # slots may be legitimately occupied and must not keep this slot
            # in MANUAL_REVIEW.  slotpending is ticket-scoped and has no slot
            # field, so owner/map rows are the only safe slot-level evidence.
            for leg in ("main", "hedge"):
                for prefix in ("qh:slotowner:", "qh:slotmap:"):
                    key = f"{prefix}{username}:{leg}:{symbol}"
                    rows = self.redis.hgetall(key) or {}
                    for raw_slot in rows.values():
                        try:
                            if int(raw_slot) == slot:
                                return False
                        except (TypeError, ValueError):
                            return False
            return True
        except Exception:
            return False

    async def _reconcile_close(self, command_id: str, cmd: Dict[str, str]):
        """Reconcile a pair close from the command user's exact-ticket truth."""
        tickets = {"main": cmd.get("main_ticket"), "hedge": cmd.get("hedge_ticket")}
        if not all(tickets.values()):
            if self._get_command_age_seconds(cmd) > 120:
                await self._mark_manual_review(command_id, "平仓120秒后仍缺少exact ticket证据")
            return
        await self._reconcile_close_tickets(command_id, cmd, tickets)

    async def _reconcile_close_leg(self, command_id: str, cmd: Dict[str, str]):
        """Reconcile one exact ticket without requiring the peer account."""
        cmd = self._recover_close_leg_identity(command_id, cmd)
        leg = cmd.get("leg")
        ticket = cmd.get("ticket")
        if leg not in ("main", "hedge") or not ticket:
            if self._get_command_age_seconds(cmd) > 120:
                await self._mark_manual_review(command_id, "单腿平仓缺少leg/exact ticket证据")
            return
        await self._reconcile_close_tickets(command_id, cmd, {leg: ticket})

    @staticmethod
    def _mapping(value):
        if isinstance(value,dict):
            return dict(value)
        if isinstance(value,bytes):
            value=value.decode("utf-8","replace")
        if isinstance(value,str):
            try:
                decoded=json.loads(value)
            except (TypeError,ValueError):
                return {}
            return dict(decoded) if isinstance(decoded,dict) else {}
        return {}

    @staticmethod
    def _text(value):
        return value.decode("utf-8","replace") if isinstance(value,bytes) else value

    def _job_record(self, job_id):
        if not job_id:
            return {}
        raw=self.redis.hgetall("qh:tradeq:job:%s"%job_id) or {}
        job={str(self._text(key)):self._text(value) for key,value in raw.items()}
        for field in ("payload","context","result","error"):
            if field in job:
                decoded=self._mapping(job[field])
                if decoded:
                    job[field]=decoded
        return job

    def _recover_close_leg_identity(self, command_id, cmd):
        """Recover legacy close-leg metadata only from one fully-bound queue intent."""
        cmd=dict(cmd or {})
        if cmd.get("leg") in ("main","hedge") and cmd.get("ticket"):
            return cmd
        def _positive_int(value):
            if value is None or isinstance(value,bool):
                return None
            text=str(value).strip()
            return int(text) if text.isdigit() and int(text)>0 else None
        pending=self._mapping(cmd.get("pending_context"))
        job_id=str(cmd.get("queue_job_id") or pending.get("queue_job_id") or "")
        job=self._job_record(job_id)
        payload=self._mapping(job.get("payload"))
        durable_context=self._mapping(job.get("context"))
        leg=str(pending.get("leg") or durable_context.get("leg") or payload.get("leg") or "")
        candidates=[cmd.get("ticket"),pending.get("ticket"),durable_context.get("ticket"),
                    payload.get("ticket")]
        tickets={str(value) for value in candidates if value not in (None,"")}
        slot=_positive_int(cmd.get("slot") or pending.get("slot") or job.get("slot"))
        pending_slot=_positive_int(pending.get("slot"))
        job_slot=_positive_int(job.get("slot"))
        durable_slot=_positive_int(durable_context.get("slot")) if durable_context else slot
        ticket=next(iter(tickets)) if len(tickets)==1 else ""
        identity_ok=(
            bool(job_id) and bool(job) and leg in ("main","hedge") and len(tickets)==1 and
            _positive_int(ticket) is not None and
            str(cmd.get("type") or "").lower()==CommandType.CLOSE_LEG.value and
            str(cmd.get("username") or "")==str(pending.get("username") or "") and
            str(cmd.get("username") or "")==str(job.get("username") or "") and
            str(cmd.get("symbol") or "XAUUSD")==str(pending.get("symbol") or "XAUUSD") and
            str(cmd.get("symbol") or "XAUUSD")==str(job.get("symbol") or "XAUUSD") and
            str(job.get("command_id") or "")==str(command_id) and
            str(job.get("op") or "")==CommandType.CLOSE_LEG.value and
            str(payload.get("op") or "")==CommandType.CLOSE_LEG.value and
            str(payload.get("leg") or "")==leg and
            (not durable_context or (
                str(durable_context.get("username") or "")==str(cmd.get("username") or "") and
                str(durable_context.get("symbol") or "XAUUSD")==str(cmd.get("symbol") or "XAUUSD") and
                str(durable_context.get("leg") or "")==leg and
                str(durable_context.get("queue_job_id") or "")==job_id)) and
            str(pending.get("queue_job_id") or "")==job_id and
            job_slot==slot and pending_slot==slot and durable_slot==slot and slot is not None
        )
        if not identity_ok:
            return cmd
        repaired=dict(cmd); repaired.update({"leg":leg,"ticket":ticket,"slot":str(slot),
                                              "queue_job_id":job_id})
        for name in (
                "single_leg_review_authorized","source_review_state",
                "source_review_command_id","source_review_job_id","source_review_slot",
                "source_review_leg","source_review_ticket"):
            candidate=pending.get(name)
            if candidate in (None,""):
                candidate=payload.get(name)
            if candidate not in (None,""):
                repaired[name]=candidate
        self.tracer.update_field(command_id,"leg",leg)
        self.tracer.update_field(command_id,"ticket",ticket)
        self.tracer.update_field(command_id,"slot",slot)
        self.tracer.update_field(command_id,"metadata_repair_reason",
                                 "legacy_close_leg_identity_recovered_from_bound_queue_intent")
        return repaired

    async def _user_connection(self, username: str):
        if self.connection_factory is None:
            return None
        connection = self.connection_factory(username)
        return await connection if inspect.isawaitable(connection) else connection

    async def _close_ticket_truth(self, connection, leg: str, ticket: str):
        """Return CLOSED/OPEN/UNKNOWN; read failures are never absence proof."""
        leg_connection = getattr(connection, leg, None) if connection is not None else None
        if leg_connection is None:
            return "UNKNOWN"
        saw_open = False
        consecutive_absent = 0
        for attempt in range(2):
            try:
                raw = await leg_connection.positions()
                if isinstance(raw, dict):
                    if raw.get("registered") is False or not isinstance(raw.get("positions"), list):
                        raise ValueError("unregistered or invalid positions payload")
                    rows = raw["positions"]
                elif isinstance(raw, list):
                    rows = raw
                else:
                    raise ValueError("invalid positions payload")
                if any(not isinstance(row, dict) for row in rows):
                    raise ValueError("invalid position row")
                present = any(str(row.get("ticket") or row.get("order")) == str(ticket)
                              for row in rows)
                if present:
                    saw_open = True
                    consecutive_absent = 0
                else:
                    consecutive_absent += 1
            except Exception:
                consecutive_absent = 0
            if attempt == 0:
                await asyncio.sleep(0.1)
        if consecutive_absent >= 2:
            return "CLOSED"
        return "OPEN" if saw_open else "UNKNOWN"

    async def _apply_confirmed_open(self, command_id, cmd, evidence, resolution_state):
        """Commit local queue/capacity truth before exposing an open terminal state."""
        if self.open_confirmed_callback is None:
            logger.error("No open cleanup callback for %s; retaining manual review", command_id)
            return False
        try:
            result = self.open_confirmed_callback(
                command_id, cmd, dict(evidence or {}), resolution_state
            )
            if inspect.isawaitable(result):
                result = await result
            return result is not False
        except Exception as exc:
            logger.error("Open cleanup failed %s: %s", command_id, exc, exc_info=True)
            return False

    async def _apply_confirmed_close(self, command_id, cmd, closed, resolution_state):
        if not closed:
            return True
        if self.close_confirmed_callback is None:
            logger.error("No close cleanup callback for %s; retaining manual review", command_id)
            return False
        try:
            result = self.close_confirmed_callback(
                command_id, cmd, dict(closed), resolution_state
            )
            if inspect.isawaitable(result):
                result = await result
            return result is not False
        except Exception as exc:
            logger.error("Close cleanup failed %s: %s", command_id, exc, exc_info=True)
            return False

    async def _reconcile_close_tickets(self, command_id, cmd, tickets):
        try:
            connection = await self._user_connection(cmd.get("username"))
        except Exception as exc:
            logger.warning("User connector unavailable %s: %s", command_id, exc)
            connection = None
        legs = list(tickets)
        outcomes = await asyncio.gather(*(
            self._close_ticket_truth(connection, leg, tickets[leg]) for leg in legs
        ))
        truth = dict(zip(legs, outcomes))
        closed = {leg: tickets[leg] for leg in legs if truth[leg] == "CLOSED"}
        if len(closed) == len(tickets):
            resolution_state = "COMPLETED"
        elif len(tickets) == 2 and len(closed) == 1:
            other = next(leg for leg in legs if leg not in closed)
            resolution_state = ("SINGLE_LEG_EXPOSED" if truth[other] == "OPEN"
                                else "MANUAL_REVIEW")
        else:
            resolution_state = "MANUAL_REVIEW"
        if closed and not await self._apply_confirmed_close(
                command_id, cmd, closed, resolution_state):
            await self._mark_manual_review(command_id, "精确ticket已消失但本地owner清理失败")
            return

        if len(closed) == len(tickets):
            self.tracer.update_field(command_id, "reconcile_truth", truth)
            self.tracer.update_field(command_id, "reconcile_result",
                                     "single_closed" if len(tickets) == 1 else "both_closed")
            self.tracer.update_status(command_id, CommandStatus.COMPLETED)
            self.tracer.record_timestamp(command_id, TraceTimestamp.RECONCILE_DONE)
            logger.info("Reconciled exact close %s: %s", command_id, truth)
            return

        if len(tickets) == 2 and len(closed) == 1:
            other = next(leg for leg in legs if leg not in closed)
            if truth[other] == "OPEN":
                await self._handle_single_leg_exposed(
                    command_id, "%s_closed_%s_open" % (next(iter(closed)), other), cmd
                )
            else:
                await self._mark_manual_review(
                    command_id, "%s已平但%s腿真相不可读" % (next(iter(closed)), other)
                )
            return

        age_sec = self._get_command_age_seconds(cmd)
        if age_sec > 120:
            await self._mark_manual_review(
                command_id, "平仓终态未获权威证明: %s" % truth
            )
        else:
            self.tracer.update_field(command_id, "reconcile_truth", truth)
            logger.debug("Close reconciliation pending %s: %s", command_id, truth)

    async def _handle_single_leg_exposed(self, command_id: str, reason: str, cmd: Dict[str, str]):
        """处理单腿暴露情况"""
        try:
            current = self.tracer.get_command(command_id) or {}
            if str(current.get("status") or "").upper() == "COMPLETED":
                logger.info("Single-leg snapshot already auto-converged %s", command_id)
                return
        except Exception:
            pass
        self.tracer.update_status(command_id, CommandStatus.SINGLE_LEG_EXPOSED)
        self.tracer.update_field(command_id, "exposure_reason", reason)
        self.tracer.record_timestamp(command_id, TraceTimestamp.RECONCILE_DONE)

        # 触发告警
        await self._trigger_alert(command_id, reason, cmd)

        logger.error(f"⚠ 单腿暴露 {command_id}: {reason}")

    async def _mark_failed(self, command_id: str, reason: str):
        """标记为失败"""
        self.tracer.update_status(command_id, CommandStatus.FAILED)
        self.tracer.update_field(command_id, "failure_reason", reason)
        self.tracer.record_timestamp(command_id, TraceTimestamp.RECONCILE_DONE)
        logger.info(f"✗ 对账完成 {command_id}: 失败 - {reason}")

    async def _mark_manual_review(self, command_id: str, reason: str):
        self.tracer.update_status(command_id, CommandStatus.MANUAL_REVIEW)
        self.tracer.update_field(command_id, "failure_reason", reason)
        self.tracer.record_timestamp(command_id, TraceTimestamp.RECONCILE_DONE)
        logger.error("Manual review required %s: %s", command_id, reason)

    @staticmethod
    def _matches_fields(row: Dict[str, Any], ticket: str, fields) -> bool:
        target = str(ticket).strip()
        if not target:
            return False
        return any(
            row.get(field) is not None and str(row.get(field)).strip() == target
            for field in fields
        )

    @classmethod
    def _row_matches_order(cls, row: Dict[str, Any], ticket: str) -> bool:
        if row.get("order") is not None:
            return cls._matches_fields(row, ticket, ("order",))
        # Legacy MT4-compatible history may expose a single ticket identity.
        return cls._matches_fields(row, ticket, ("ticket", "deal"))

    @classmethod
    def _row_matches_position(cls, row: Dict[str, Any], ticket: str) -> bool:
        explicit = tuple(field for field in ("position", "position_id")
                         if row.get(field) is not None)
        if explicit:
            return cls._matches_fields(row, ticket, explicit)
        return cls._matches_fields(row, ticket, ("ticket", "order"))

    async def _check_deal_in_leg(
            self, leg_connection, ticket: str) -> Tuple[str, Optional[Dict]]:
        """Return exact-ticket FILLED/NOT_FOUND/UNAVAILABLE for one user leg."""
        if leg_connection is None:
            return "UNAVAILABLE", None
        try:
            getter = getattr(leg_connection, "_get", None)
            if callable(getter):
                payload = getter("/mt5/history/deals", days=1, order=ticket)
            else:
                history_deals = getattr(leg_connection, "history_deals", None)
                if not callable(history_deals):
                    return "UNAVAILABLE", None
                payload = history_deals(1)
            if inspect.isawaitable(payload):
                payload = await payload
            if isinstance(payload, dict):
                if payload.get("registered") is False:
                    return "UNAVAILABLE", None
                deals = payload.get("deals")
            else:
                deals = payload
            if not isinstance(deals, list) or any(
                    not isinstance(deal, dict) for deal in deals):
                return "UNAVAILABLE", None
            match = next((deal for deal in deals
                          if self._row_matches_order(deal, ticket)), None)
            if match is not None:
                return "FILLED", match
            if (isinstance(payload, dict) and payload.get("complete") is True and
                    payload.get("truncated") is not True):
                return "NOT_FOUND", None
            return "UNAVAILABLE", None
        except Exception as exc:
            logger.warning("Deal truth unavailable ticket=%s: %s", ticket, exc)
            return "UNAVAILABLE", None

    async def _check_position_in_db(self, username: str, symbol: str, main_ticket: str, hedge_ticket: str) -> Optional[Any]:
        """查询数据库持仓表"""
        try:
            # 这里需要实际的DB查询逻辑
            # from models import HedgePosition
            # position = self.db.query(HedgePosition).filter(
            #     HedgePosition.user_id == get_user_id(username),
            #     HedgePosition.symbol == symbol,
            #     HedgePosition.main_order == main_ticket,
            #     HedgePosition.hedge_order == hedge_ticket
            # ).first()
            # return position
            return None  # 占位
        except Exception as e:
            logger.warning(f"查询DB持仓失败: {e}")
        return None

    async def _check_position_in_leg(
            self, leg_connection, ticket: str) -> Tuple[str, Optional[Dict]]:
        """Return exact-ticket FILLED/NOT_FOUND/UNAVAILABLE for one user leg."""
        if leg_connection is None:
            return "UNAVAILABLE", None
        try:
            positions_call = getattr(leg_connection, "positions", None)
            if not callable(positions_call):
                return "UNAVAILABLE", None
            payload = positions_call()
            if inspect.isawaitable(payload):
                payload = await payload
            if isinstance(payload, dict):
                if payload.get("registered") is False:
                    return "UNAVAILABLE", None
                positions = payload.get("positions")
            else:
                positions = payload
            if not isinstance(positions, list) or any(
                    not isinstance(position, dict) for position in positions):
                return "UNAVAILABLE", None
            match = next((position for position in positions
                          if self._row_matches_position(position, ticket)), None)
            return ("FILLED", match) if match is not None else ("NOT_FOUND", None)
        except Exception as exc:
            logger.warning("Position truth unavailable ticket=%s: %s", ticket, exc)
            return "UNAVAILABLE", None

    async def _check_close_in_history(self, bridge_url: str, ticket: str) -> Optional[Dict]:
        """查询平仓历史"""
        try:
            # 查询最近的deals,寻找该ticket的平仓记录
            resp = await self.http_client.get(
                f"{bridge_url}/mt5/history/deals",
                params={"position": ticket, "limit": 10}
            )
            if resp.status_code == 200:
                deals = resp.json().get("deals", [])
                for deal in deals:
                    if (isinstance(deal, dict) and
                            self._row_matches_position(deal, ticket) and
                            deal.get("entry") == 1):  # entry=1表示平仓
                        return deal
        except Exception as e:
            logger.warning(f"查询平仓历史失败 {bridge_url}: {e}")
        return None

    async def _trigger_alert(self, command_id: str, reason: str, cmd: Dict[str, str]):
        """触发单腿暴露告警"""
        # 这里应该调用飞书/邮件/短信等告警接口
        alert_msg = f"""
⚠️ QH单腿暴露告警

命令ID: {command_id}
用户: {cmd.get('username')}
币种: {cmd.get('symbol')}
方向: {cmd.get('direction')}
原因: {reason}
时间: {datetime.utcnow().isoformat()}

主腿ticket: {cmd.get('main_ticket')}
对冲腿ticket: {cmd.get('hedge_ticket')}

请立即处理!
        """.strip()

        logger.critical(alert_msg)

        # TODO: 调用实际告警接口
        # await send_feishu_alert(alert_msg)

    def _get_command_age_seconds(self, cmd: Dict[str, str]) -> float:
        """获取命令年龄(秒)"""
        api_received = cmd.get(TraceTimestamp.API_RECEIVED)
        if not api_received:
            return 0

        try:
            received_time = datetime.fromisoformat(api_received.replace('Z', '+00:00'))
            return (datetime.utcnow() - received_time.replace(tzinfo=None)).total_seconds()
        except:
            return 0
