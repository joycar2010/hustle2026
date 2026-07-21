"""
ledger.py — 命令账本(M2 幂等层),逐字节复刻 mt5-bridge 的 _idem_get/_idem_put。
(权威源:D:\\QHMT5\\runtime\\releases\\v1\\ic\\app\\main.py 第 516-565 行)

同一 request_id 重放只返回原结果,绝不二次下单;状态机 SENDING→DONE/FAILED。
SENDING = 已投命令但结果未知(崩溃/超时中),拒绝重发,由 QH order-status 查真相或人工对账。
SQLite WAL,每 Agent 实例独立 DB(ic/exness 不共享 request_id 空间)。
"""
import json
import sqlite3
import threading
import time


class Ledger:
    def __init__(self, db_path: str):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS order_requests ("
            "request_id TEXT PRIMARY KEY, state TEXT, result TEXT,"
            "created_at REAL, updated_at REAL)")
        self._conn.commit()

    def get(self, request_id):
        """返回 (state, result_json_str) 或 None。"""
        if not request_id:
            return None
        with self._lock:
            return self._conn.execute(
                "SELECT state, result FROM order_requests WHERE request_id=?",
                (request_id,)).fetchone()

    def put(self, request_id, state, result=None):
        if not request_id:
            return
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO order_requests (request_id, state, result, created_at, updated_at)"
                " VALUES (?,?,?,?,?)"
                " ON CONFLICT(request_id) DO UPDATE SET state=excluded.state,"
                " result=excluded.result, updated_at=excluded.updated_at",
                (request_id, state,
                 json.dumps(result) if result is not None else None, now, now))
            self._conn.commit()

    def get_result(self, request_id):
        """已存的结果 dict(state=DONE/FAILED 时),否则 None。"""
        row = self.get(request_id)
        if not row:
            return None
        _state, _res = row
        if _res:
            try:
                return json.loads(_res)
            except Exception:
                return None
        return None
