"""
filebridge.py — QHBridge MT4 文件桥 I/O 层(Agent 侧)

EA(QHBridge.mq4)跑在 MT4 终端内,MQL4 只能读写终端沙箱 <terminal>\MQL4\Files\ 下的文件。
本模块是 Agent 侧的对端:读 EA 导出的状态、投递命令、收取结果。

═══ 文件桥协议(权威规约,EA 与 Agent 两侧共同遵守)═══
根目录 = <terminal>\MQL4\Files\qhbridge\

  state/meta.json       EA→Agent  {connected,account,server,company,ts,ea,build}  每 OnTimer 刷
  state/account.json    EA→Agent  账户资金字段(见 read_account)                  每 OnTimer 刷
  state/positions.json  EA→Agent  {positions:[...]}  按 OrderSelect 遍历             每 OnTimer 刷
  state/ticks.json      EA→Agent  {SYM:{bid,ask,last,volume,time}}  watch 内各符号   每 OnTimer 刷
  state/symbols.json    EA→Agent  {SYM:{digits,point,...}}  watch 内各符号           每 OnTimer 刷(低频)
  watch.json            Agent→EA  {symbols:[...]}  QH 查询过的符号,EA 据此导出       Agent 按需更新
  commands/{rid}.json   Agent→EA  下单/平仓命令(Phase D)
  results/{rid}.json    EA→Agent  命令结果 tombstone(Phase D)

原子写:写方一律写 X.tmp 再 rename→X(EA 用 FileMove,Agent 用 os.replace),读方容忍
瞬时解析失败并重试一次。所有 ts 用 TimeLocal()(终端本机时,本机 GMT+0 ≈ UTC),Agent 以
time.time() 比对新鲜度。tick 的 time 是券商服务器时(GMT+3),消费端沿用 MT5 桥 +10800000ms 校正。
"""
import json
import os
import time

# EA 状态文件超过此秒数未刷 = EA 死/终端断,判 not connected
# P0-B: 按数据类型拆分 TTL (替代临时 STATE_STALE_SEC=3600)
STALE_HEARTBEAT_SEC  = 15.0    # EA/agent heartbeat
STALE_QUOTE_SEC      = 0.5     # tick 行情; 与 QH 开仓准入上限一致
STALE_POSITIONS_SEC  = 1.0     # 持仓快照; 与 QH 版本准入上限一致
STALE_ACCOUNT_SEC    = 10.0    # 账户权益/保证金
STALE_SYMBOLS_SEC    = 1800.0  # 合约规格(digits/point)
STATE_STALE_SEC      = STALE_HEARTBEAT_SEC  # 向后兼容
MAX_WATCH_SYMBOLS    = 8        # keep MT4's single event loop bounded
# EA publishes state with a temporary file followed by a Windows rename. A
# reader can observe a short target-file gap or a size/mtime change even when
# the next publication is valid. Keep this retry budget tiny and bounded so a
# real missing snapshot still fails closed without a scheduler-sized delay.
STATE_READ_ATTEMPTS   = 5
STATE_READ_BACKOFF_SEC = 0.0015
STATE_READ_BACKOFF_MAX_SEC = 0.006
STATE_READ_BACKOFF_DECAY = 0.85
# QHBridge publishes a second-resolution TimeLocal value and derives the
# optional millisecond suffix from a monotonic counter.  That suffix is useful
# for ordering, but it is not a wall-clock measurement and may lead the Agent
# clock by almost one second.  File mtime remains the freshness authority.
EA_TIMESTAMP_SKEW_SEC = 1.0


def _state_timestamp_seconds(data):
    if not isinstance(data, dict):
        return None
    value = data.get("snapshot_ts_ms")
    if value is None:
        value = data.get("snapshot_ts", data.get("ts"))
    if value is None:
        return None
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    if timestamp >= 100_000_000_000:
        timestamp /= 1000.0
    return timestamp


def _state_timestamp_ms(data):
    timestamp = _state_timestamp_seconds(data)
    return int(round(timestamp * 1000.0)) if timestamp is not None else None


class FileBridge:
    def __init__(self, files_dir: str):
        # files_dir = <terminal>\MQL4\Files\qhbridge
        self.root = files_dir
        self.state = os.path.join(files_dir, "state")
        self.commands = os.path.join(files_dir, "commands")
        self.results = os.path.join(files_dir, "results")
        self.dispatch = os.path.join(files_dir, "dispatch")
        for d in (self.root, self.state, self.commands, self.results, self.dispatch):
            os.makedirs(d, exist_ok=True)
        # Diagnostics only. A failed read never falls back to an old snapshot.
        self._state_read_retries = 0
        self._state_read_transient_misses = 0
        self._state_read_failures = 0
        # MT4 Exness can publish several files in one timer tick. Adapt the
        # retry gap to that publication pressure instead of sleeping a fixed
        # interval on every state type; successful reads quickly decay back
        # to the 1.5 ms fast path.
        self._state_backoff_sec = STATE_READ_BACKOFF_SEC

    # ── 状态读取(容忍 EA 半写,重试一次)──
    def _read_json(self, path: str):
        for attempt in range(2):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except FileNotFoundError:
                return None
            except (json.JSONDecodeError, ValueError, OSError):
                if attempt == 0:
                    time.sleep(0.03)  # EA 可能正在 rename,等一拍
                    continue
                return None
        return None

    def _read_json_once(self, path: str):
        """Read an atomically published file without sleeping in the event loop."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, ValueError, OSError):
            return None

    def read_state(self, name: str):
        """读 state/<name>.json,返回 (data, age_sec)。data=None 表示缺失。"""
        path = os.path.join(self.state, name + ".json")
        for _attempt in range(STATE_READ_ATTEMPTS):
            try:
                before = os.stat(path)
            except (FileNotFoundError, OSError):
                self._state_read_transient_misses += 1
                if _attempt + 1 < STATE_READ_ATTEMPTS:
                    self._state_read_retries += 1
                    time.sleep(self._state_backoff_sec)
                    self._state_backoff_sec = min(
                        STATE_READ_BACKOFF_MAX_SEC,
                        self._state_backoff_sec * 1.5,
                    )
                    continue
                self._state_read_failures += 1
                return None, None
            data = self._read_json_once(path)
            try:
                after = os.stat(path)
            except (FileNotFoundError, OSError):
                self._state_read_transient_misses += 1
                if _attempt + 1 < STATE_READ_ATTEMPTS:
                    self._state_read_retries += 1
                    time.sleep(self._state_backoff_sec)
                    self._state_backoff_sec = min(
                        STATE_READ_BACKOFF_MAX_SEC,
                        self._state_backoff_sec * 1.5,
                    )
                continue
            if (data is None or before.st_mtime_ns != after.st_mtime_ns or
                    before.st_size != after.st_size):
                self._state_read_transient_misses += 1
                if _attempt + 1 < STATE_READ_ATTEMPTS:
                    self._state_read_retries += 1
                    time.sleep(self._state_backoff_sec)
                    self._state_backoff_sec = min(
                        STATE_READ_BACKOFF_MAX_SEC,
                        self._state_backoff_sec * 1.5,
                    )
                continue
            now = time.time()
            age = now - after.st_mtime
            source_ts = _state_timestamp_seconds(data)
            if source_ts is not None:
                # MT4's embedded timestamp is not a wall-clock millisecond
                # value: the EA appends a monotonic-counter remainder.  Use
                # the atomic file mtime for freshness and tolerate that
                # bounded publication skew; reject anything beyond one second.
                precision = EA_TIMESTAMP_SKEW_SEC
                if source_ts > now + precision:
                    return data, -1.0
                age = max(age, max(0.0, now - source_ts - precision))
            self._state_backoff_sec = max(
                STATE_READ_BACKOFF_SEC,
                self._state_backoff_sec * STATE_READ_BACKOFF_DECAY,
            )
            return data, age
        self._state_read_failures += 1
        return None, None

    def state_read_stats(self):
        """Return bounded-read diagnostics without exposing snapshot contents."""
        return {
            "retries": int(self._state_read_retries),
            "transient_misses": int(self._state_read_transient_misses),
            "failures": int(self._state_read_failures),
            "attempts": STATE_READ_ATTEMPTS,
            "backoff_ms": STATE_READ_BACKOFF_SEC * 1000.0,
        }

    def meta(self):
        data, age = self.read_state("meta")
        return data, age

    def is_fresh(self, age) -> bool:
        return age is not None and 0.0 <= age <= STATE_STALE_SEC

    def is_fresh_for(self, age, data_type: str) -> bool:
        """P0-B: 按数据类型判断新鲜度。data_type: heartbeat|quote|positions|account|symbols"""
        ttl_map = {
            'heartbeat': STALE_HEARTBEAT_SEC,
            'quote':     STALE_QUOTE_SEC,
            'positions': STALE_POSITIONS_SEC,
            'account':   STALE_ACCOUNT_SEC,
            'symbols':   STALE_SYMBOLS_SEC,
        }
        return (age is not None and 0.0 <= age <=
                ttl_map.get(data_type, STATE_STALE_SEC))

    # ── watch 列表(Agent→EA,告诉 EA 要导出哪些符号)──
    def ensure_watch(self, symbols):
        """Keep a bounded least-recently-used watch set. Return whether a symbol was new."""
        path = os.path.join(self.root, "watch.json")
        cur = self._read_json(path) or {"symbols": []}
        current = [s for s in (cur.get("symbols") or []) if s]
        incoming = list(dict.fromkeys(s for s in symbols if s))
        if not incoming:
            return False
        had = set(current)
        merged = [s for s in current if s not in incoming] + incoming
        bounded = merged[-MAX_WATCH_SYMBOLS:]
        if bounded != current:
            self._atomic_write(path, {"symbols": bounded})
        return any(s not in had for s in incoming)

    # ── 命令投递 / 结果收取(Phase D 写端点用)──
    def submit_command(self, request_id: str, payload: dict):
        started = time.perf_counter_ns()
        payload["agent_command_ready_ns"] = time.time_ns()
        self._atomic_write(os.path.join(self.commands, request_id + ".json"), payload)
        return {"write_ms": (time.perf_counter_ns() - started) / 1_000_000.0,
                "command_ready_ns": payload["agent_command_ready_ns"]}

    def read_result(self, request_id: str):
        return self._read_json(os.path.join(self.results, request_id + ".json"))

    def read_result_once(self, request_id: str):
        # EA writes result.tmp + FileMove, so the async poller can retry a failed
        # single read without invoking the state-file repair sleep.
        return self._read_json_once(os.path.join(self.results, request_id + ".json"))

    def command_exists(self, request_id: str):
        return os.path.exists(os.path.join(self.commands, request_id + ".json"))

    def was_dispatched(self, request_id: str):
        return os.path.exists(os.path.join(self.dispatch, request_id + ".json"))

    def dispatch_observed(self, request_id: str):
        """Return once the EA has claimed a command or already published its result."""
        return self.was_dispatched(request_id) or os.path.exists(
            os.path.join(self.results, request_id + ".json")
        )

    def dispatch_mtime_ns(self, request_id: str):
        """Host-clock timestamp for pickup latency tracing; None if not claimed."""
        try:
            return os.stat(os.path.join(self.dispatch, request_id + ".json")).st_mtime_ns
        except (FileNotFoundError, OSError):
            return None

    def wait_result(self, request_id: str, timeout: float = 30.0, poll: float = 0.01):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            r = self.read_result(request_id)
            if r is not None:
                return r
            time.sleep(poll)
        return None

    def wait_dispatch(self, request_id: str, timeout: float = 30.0, poll: float = 0.005):
        """Wait until EA durably claims a command, preserving FIFO dispatch order."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.dispatch_observed(request_id):
                return True
            time.sleep(poll)
        return False

    def _atomic_write(self, path: str, data: dict):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
