"""
QH系统全链路追踪模块 - P0.1
用于追踪每笔订单从API接收到最终完成的完整生命周期
"""
import uuid
import json
import contextvars
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum


_API_RECEIVED_CONTEXT = contextvars.ContextVar("qh_api_received_at", default=None)


def set_api_received(value=None):
    """Bind the real HTTP ingress timestamp to the current request context."""
    return _API_RECEIVED_CONTEXT.set(value or datetime.utcnow().isoformat())


def reset_api_received(token):
    _API_RECEIVED_CONTEXT.reset(token)


def current_api_received():
    return _API_RECEIVED_CONTEXT.get()


class CommandStatus(str, Enum):
    """订单命令状态枚举"""
    RECEIVED = "RECEIVED"              # API已接收
    PREFLIGHT = "PREFLIGHT"            # 前置检查中
    SUBMITTED = "SUBMITTED"            # 已提交到Bridge
    UNKNOWN = "UNKNOWN"                # 超时,状态未知
    RECONCILING = "RECONCILING"        # 对账中
    COMPLETED = "COMPLETED"            # 成功完成
    FAILED = "FAILED"                  # 明确失败
    MANUAL_REVIEW = "MANUAL_REVIEW"    # 证据不足,冻结并等待人工核对
    SINGLE_LEG_EXPOSED = "SINGLE_LEG_EXPOSED"  # 单腿暴露


class CommandType(str, Enum):
    """命令类型"""
    OPEN_PAIR = "open_pair"
    CLOSE_PAIR = "close_pair"
    CLOSE_LEG = "close_leg"


class TraceTimestamp:
    """时间戳字段名"""
    API_RECEIVED = "api_received"
    PREFLIGHT_START = "preflight_start"
    PREFLIGHT_DONE = "preflight_done"
    BRIDGE_SENT_MAIN = "bridge_sent_main"
    BRIDGE_SENT_HEDGE = "bridge_sent_hedge"
    BRIDGE_RECEIVED_MAIN = "bridge_received_main"
    BRIDGE_RECEIVED_HEDGE = "bridge_received_hedge"
    ORDER_SEND_START_MAIN = "order_send_start_main"
    ORDER_SEND_END_MAIN = "order_send_end_main"
    ORDER_SEND_START_HEDGE = "order_send_start_hedge"
    ORDER_SEND_END_HEDGE = "order_send_end_hedge"
    FIRST_POSITION_SEEN = "first_position_seen"
    RECONCILE_START = "reconcile_start"
    RECONCILE_DONE = "reconcile_done"
    HTTP_SENT = "http_sent"
    # Q-series (open_pair 分段 - P0-A 延迟止血)
    AUTH_GATE_DONE      = "q01_auth_gate_done"
    PREFLIGHT_COMPLETE  = "q02_preflight_complete"
    DISPATCH_PREPARED   = "q03_dispatch_prepared"
    LEG_TASKS_CREATED   = "q04_leg_tasks_created"
    PAIR_JOIN_DONE      = "q11_pair_join_done"
    LEDGER_COMMITTED    = "q12_ledger_committed"
    UNKNOWN_COMMITTED   = "q09_unknown_committed"
    QUEUE_ADMITTED = "queue_admitted"
    QUEUE_DISPATCH_STARTED = "queue_dispatch_started"
    BRIDGE_ACK_MAIN = "bridge_ack_main"
    BRIDGE_ACK_HEDGE = "bridge_ack_hedge"
    BROKER_TERMINAL_MAIN = "broker_terminal_main"
    BROKER_TERMINAL_HEDGE = "broker_terminal_hedge"
    BROKER_TERMINAL_CONFIRMED = "broker_terminal_confirmed"
    FRONTEND_CLIENT_STARTED_RECEIVED = "frontend_client_started_received"
    FRONTEND_QUEUE_STATE_RECEIVED = "frontend_queue_state_received"
    FRONTEND_POSITION_REFRESH_DONE = "frontend_position_refresh_done"


class CommandTracer:
    """订单命令追踪器"""

    def __init__(self, redis_client):
        self.redis = redis_client
        self.key_prefix = "qh:command:"

    def generate_command_id(self, cmd_type: CommandType, username: str, symbol: str) -> str:
        """生成唯一的command_id"""
        unique_suffix = uuid.uuid4().hex[:12]
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        return f"{cmd_type.value}_{username}_{symbol}_{timestamp}_{unique_suffix}"

    def create_command(self,
                       cmd_type: CommandType,
                       username: str,
                       symbol: str,
                       direction: Optional[str] = None,
                       metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        创建新命令追踪记录

        Returns:
            command_id: 命令唯一标识
        """
        command_id = self.generate_command_id(cmd_type, username, symbol)

        record = {
            "command_id": command_id,
            "type": cmd_type.value,
            "username": username,
            "symbol": symbol,
            "status": CommandStatus.RECEIVED.value,
            TraceTimestamp.API_RECEIVED: current_api_received() or datetime.utcnow().isoformat(),
        }

        if direction:
            record["direction"] = direction

        if metadata:
            # Redis不支持bool,转换为字符串
            for k, v in metadata.items():
                if isinstance(v, bool):
                    record[k] = str(v)
                elif v is not None:
                    record[k] = v

        # 写入Redis,24小时过期
        key = f"{self.key_prefix}{command_id}"
        self.redis.hset(key, mapping=record)
        self.redis.expire(key, 86400)

        return command_id

    def update_status(self, command_id: str, status: CommandStatus):
        """更新命令状态"""
        key = f"{self.key_prefix}{command_id}"
        self.redis.hset(key, mapping={
            "status": status.value,
            f"status_{status.value}_at": datetime.utcnow().isoformat(),
        })

    def update_fields(self, command_id: str, fields: Dict[str, Any]):
        """Update related trace fields with one atomic Redis hash write."""
        if not fields:
            return
        mapping = {}
        for field, value in fields.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            mapping[field] = value
        self.redis.hset(f"{self.key_prefix}{command_id}", mapping=mapping)

    def record_timestamp(self, command_id: str, timestamp_name: str, value: Optional[str] = None):
        """记录时间戳"""
        key = f"{self.key_prefix}{command_id}"
        if value is None:
            value = datetime.utcnow().isoformat()
        self.redis.hset(key, timestamp_name, value)

    def update_field(self, command_id: str, field: str, value: Any):
        """更新任意字段"""
        self.update_fields(command_id, {field: value})

    def get_command(self, command_id: str) -> Optional[Dict[str, str]]:
        """获取命令详情"""
        key = f"{self.key_prefix}{command_id}"
        data = self.redis.hgetall(key)
        if not data:
            return None

        # 字节转字符串
        return {k.decode() if isinstance(k, bytes) else k:
                v.decode() if isinstance(v, bytes) else v
                for k, v in data.items()}

    def calculate_latencies(self, command_id: str) -> Dict[str, float]:
        """
        计算各阶段延迟(毫秒)

        Returns:
            {
                "preflight_ms": 前置检查耗时,
                "main_bridge_ms": 主腿Bridge往返,
                "hedge_bridge_ms": 对冲腿Bridge往返,
                "main_order_send_ms": 主腿order_send耗时,
                "hedge_order_send_ms": 对冲腿order_send耗时,
                "total_ms": 总耗时
            }
        """
        cmd = self.get_command(command_id)
        if not cmd:
            return {}

        def parse_time(ts_str):
            if not ts_str:
                return None
            try:
                return datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            except:
                return None

        def calc_ms(start_key, end_key):
            start = parse_time(cmd.get(start_key))
            end = parse_time(cmd.get(end_key))
            if start and end:
                elapsed = (end - start).total_seconds() * 1000
                return elapsed if elapsed >= 0 else None
            return None

        latencies = {}

        # 前置检查
        preflight = calc_ms(TraceTimestamp.PREFLIGHT_START, TraceTimestamp.PREFLIGHT_DONE)
        if preflight is not None:
            latencies["preflight_ms"] = preflight

        # 主腿Bridge
        main_bridge = calc_ms(TraceTimestamp.BRIDGE_SENT_MAIN, TraceTimestamp.BRIDGE_RECEIVED_MAIN)
        if main_bridge is not None:
            latencies["main_bridge_ms"] = main_bridge

        # 对冲腿Bridge
        hedge_bridge = calc_ms(TraceTimestamp.BRIDGE_SENT_HEDGE, TraceTimestamp.BRIDGE_RECEIVED_HEDGE)
        if hedge_bridge is not None:
            latencies["hedge_bridge_ms"] = hedge_bridge

        # 主腿order_send
        main_order = calc_ms(TraceTimestamp.ORDER_SEND_START_MAIN, TraceTimestamp.ORDER_SEND_END_MAIN)
        if main_order is not None:
            latencies["main_order_send_ms"] = main_order

        # 对冲腿order_send
        hedge_order = calc_ms(TraceTimestamp.ORDER_SEND_START_HEDGE, TraceTimestamp.ORDER_SEND_END_HEDGE)
        if hedge_order is not None:
            latencies["hedge_order_send_ms"] = hedge_order

        # 总耗时
        total = calc_ms(TraceTimestamp.API_RECEIVED, TraceTimestamp.HTTP_SENT)
        if total is not None:
            latencies["total_ms"] = total

        # Q-series 分段
        auth_gate = calc_ms(TraceTimestamp.API_RECEIVED, TraceTimestamp.AUTH_GATE_DONE)
        if auth_gate is not None:
            latencies["q01_auth_gate_ms"] = auth_gate

        preflight = calc_ms(TraceTimestamp.AUTH_GATE_DONE, TraceTimestamp.PREFLIGHT_COMPLETE)
        if preflight is not None:
            latencies["q02_preflight_ms"] = preflight

        dispatch_wait = calc_ms(TraceTimestamp.PREFLIGHT_COMPLETE, TraceTimestamp.DISPATCH_PREPARED)
        if dispatch_wait is not None:
            latencies["q03_dispatch_wait_ms"] = dispatch_wait

        pair_join = calc_ms(TraceTimestamp.DISPATCH_PREPARED, TraceTimestamp.PAIR_JOIN_DONE)
        if pair_join is not None:
            latencies["q11_pair_join_ms"] = pair_join

        ledger_commit = calc_ms(TraceTimestamp.PAIR_JOIN_DONE, TraceTimestamp.LEDGER_COMMITTED)
        if ledger_commit is not None:
            latencies["q12_ledger_ms"] = ledger_commit

        queue_admission = calc_ms(TraceTimestamp.API_RECEIVED, TraceTimestamp.QUEUE_ADMITTED)
        if queue_admission is not None:
            latencies["request_to_queue_ms"] = queue_admission

        queue_wait = calc_ms(TraceTimestamp.QUEUE_ADMITTED, TraceTimestamp.QUEUE_DISPATCH_STARTED)
        if queue_wait is not None:
            latencies["queue_wait_ms"] = queue_wait

        for leg in ("main", "hedge"):
            ack = calc_ms(
                TraceTimestamp.QUEUE_DISPATCH_STARTED,
                TraceTimestamp.BRIDGE_ACK_MAIN if leg == "main" else TraceTimestamp.BRIDGE_ACK_HEDGE,
            )
            if ack is not None:
                latencies["%s_bridge_ack_ms" % leg] = ack
            broker = calc_ms(
                TraceTimestamp.BRIDGE_ACK_MAIN if leg == "main" else TraceTimestamp.BRIDGE_ACK_HEDGE,
                TraceTimestamp.BROKER_TERMINAL_MAIN if leg == "main" else TraceTimestamp.BROKER_TERMINAL_HEDGE,
            )
            if broker is not None:
                latencies["%s_broker_terminal_ms" % leg] = broker

        broker_pair = calc_ms(
            TraceTimestamp.QUEUE_DISPATCH_STARTED,
            TraceTimestamp.BROKER_TERMINAL_CONFIRMED,
        )
        if broker_pair is not None:
            latencies["broker_pair_terminal_ms"] = broker_pair

        frontend_queue = calc_ms(
            TraceTimestamp.API_RECEIVED,
            TraceTimestamp.FRONTEND_QUEUE_STATE_RECEIVED,
        )
        if frontend_queue is not None:
            latencies["request_to_frontend_queue_ms"] = frontend_queue

        frontend_refresh = calc_ms(
            TraceTimestamp.API_RECEIVED,
            TraceTimestamp.FRONTEND_POSITION_REFRESH_DONE,
        )
        if frontend_refresh is not None:
            latencies["request_to_frontend_refresh_ms"] = frontend_refresh

        queue_to_refresh = calc_ms(
            TraceTimestamp.FRONTEND_QUEUE_STATE_RECEIVED,
            TraceTimestamp.FRONTEND_POSITION_REFRESH_DONE,
        )
        if queue_to_refresh is not None:
            latencies["frontend_queue_to_refresh_ms"] = queue_to_refresh

        broker_to_frontend = calc_ms(
            TraceTimestamp.BROKER_TERMINAL_CONFIRMED,
            TraceTimestamp.FRONTEND_POSITION_REFRESH_DONE,
        )
        if broker_to_frontend is not None:
            latencies["broker_to_frontend_refresh_ms"] = broker_to_frontend

        for field, latency_name in (
            ("frontend_queue_elapsed_ms", "client_to_frontend_queue_ms"),
            ("frontend_position_refresh_elapsed_ms", "client_to_frontend_refresh_ms"),
        ):
            try:
                value = float(cmd.get(field))
            except (TypeError, ValueError):
                continue
            if value >= 0:
                latencies[latency_name] = value

        # dispatch_skew: 两腿发出时刻差
        t_sent_m = cmd.get("bridge_sent_main")
        t_sent_h = cmd.get("bridge_sent_hedge")
        if t_sent_m and t_sent_h:
            try:
                def _p(s): return datetime.fromisoformat(s.replace('Z','+00:00'))
                skew = abs((_p(t_sent_m) - _p(t_sent_h)).total_seconds() * 1000)
                latencies["pair_dispatch_skew_ms"] = skew
            except Exception:
                pass

        return latencies

    def list_commands_by_status(self, statuses, limit: int = 100) -> list:
        wanted = {s.value if isinstance(s, CommandStatus) else str(s) for s in statuses}
        cursor = 0
        found = []

        while True:
            cursor, keys = self.redis.scan(
                cursor=cursor,
                match=f"{self.key_prefix}*",
                count=100
            )

            for key in keys:
                cmd = self.redis.hgetall(key)
                status = cmd.get("status") if isinstance(cmd, dict) else None
                if status is None and isinstance(cmd, dict):
                    status = cmd.get(b"status")
                if isinstance(status, bytes):
                    status = status.decode()
                if cmd and status in wanted:
                    key_text = key.decode() if isinstance(key, bytes) else key
                    cmd_id = key_text.replace(self.key_prefix, "")
                    found.append(cmd_id)

                    if len(found) >= limit:
                        return found

            if cursor == 0:
                break

        return found

    def list_unknown_commands(self, limit: int = 100) -> list:
        """列出所有UNKNOWN状态的命令"""
        return self.list_commands_by_status((CommandStatus.UNKNOWN,), limit)

    def list_submitted_commands(self, limit: int = 100) -> list:
        return self.list_commands_by_status((CommandStatus.SUBMITTED,), limit)

    def list_reconciling_commands(self, limit: int = 100) -> list:
        """列出所有RECONCILING状态的命令"""
        return self.list_commands_by_status((CommandStatus.RECONCILING,), limit)


# 全局单例
_tracer_instance: Optional[CommandTracer] = None


def init_tracer(redis_client):
    """初始化全局tracer"""
    global _tracer_instance
    _tracer_instance = CommandTracer(redis_client)


def get_tracer() -> CommandTracer:
    """获取全局tracer实例"""
    if _tracer_instance is None:
        raise RuntimeError("CommandTracer未初始化,请先调用init_tracer()")
    return _tracer_instance
