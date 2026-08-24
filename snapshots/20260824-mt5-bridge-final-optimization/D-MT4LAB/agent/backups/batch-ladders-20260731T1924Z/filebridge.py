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
STALE_QUOTE_SEC      = 1.0     # tick 行情
STALE_POSITIONS_SEC  = 5.0     # 持仓快照
STALE_ACCOUNT_SEC    = 10.0    # 账户权益/保证金
STALE_SYMBOLS_SEC    = 1800.0  # 合约规格(digits/point)
STATE_STALE_SEC      = STALE_HEARTBEAT_SEC  # 向后兼容
MAX_WATCH_SYMBOLS    = 8        # keep MT4's single event loop bounded


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

    def read_state(self, name: str):
        """读 state/<name>.json,返回 (data, age_sec)。data=None 表示缺失。"""
        data = self._read_json(os.path.join(self.state, name + ".json"))
        if data is None:
            return None, None
        ts = data.get("ts", data.get("snapshot_ts"))
        age = (time.time() - float(ts)) if ts else None
        return data, age

    def meta(self):
        data, age = self.read_state("meta")
        return data, age

    def is_fresh(self, age) -> bool:
        return age is not None and age <= STATE_STALE_SEC

    def is_fresh_for(self, age, data_type: str) -> bool:
        """P0-B: 按数据类型判断新鲜度。data_type: heartbeat|quote|positions|account|symbols"""
        ttl_map = {
            'heartbeat': STALE_HEARTBEAT_SEC,
            'quote':     STALE_QUOTE_SEC,
            'positions': STALE_POSITIONS_SEC,
            'account':   STALE_ACCOUNT_SEC,
            'symbols':   STALE_SYMBOLS_SEC,
        }
        return age is not None and age <= ttl_map.get(data_type, STATE_STALE_SEC)

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
        dispatch_path = os.path.join(self.dispatch, request_id + ".json")
        result_path = os.path.join(self.results, request_id + ".json")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if os.path.exists(dispatch_path) or os.path.exists(result_path):
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
