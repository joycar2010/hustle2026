# -*- coding: utf-8 -*-
"""20260716 M2 桥补丁(V1.1 §9.1/§9.2): request_id幂等 + /mt5/order-status端点。
用法: python patch_bridge_idempotency.py D:\\hustle-mt5-mt5-<inst> [...]
幂等: 检测到 idempotency.db 标记则跳过。自动备份+编译。前置: 已打 actualfill 补丁。
"""
import sys, os, shutil, time

E1_OLD = "    position_ticket: Optional[int] = None  # 用于平仓"
E1_NEW = """    position_ticket: Optional[int] = None  # 用于平仓
    request_id: Optional[str] = None  # M2幂等键(V1.1 §9.2): 同键重放只返回原结果"""

E2_OLD = '@app.post("/mt5/order", dependencies=[Depends(verify_api_key)])'
E2_NEW = '''# ── M2 幂等层(V1.1 §9.2): request_id → 结果, 本地SQLite(WAL) ────────────────
# 同一 request_id 重放只返回原结果, 绝不二次 order_send; SENDING=已进入
# order_send但结果未知(崩溃/超时中), 拒绝重发交由后端查询/人工对账。
import sqlite3 as _sq3
import threading as _thr
import json as _json_idem
_IDEM_LOCK = _thr.Lock()
_IDEM_CONN = None


def _idem_conn():
    global _IDEM_CONN
    if _IDEM_CONN is None:
        _IDEM_CONN = _sq3.connect("idempotency.db", check_same_thread=False)
        _IDEM_CONN.execute("PRAGMA journal_mode=WAL")
        _IDEM_CONN.execute(
            "CREATE TABLE IF NOT EXISTS order_requests ("
            "request_id TEXT PRIMARY KEY, state TEXT, result TEXT,"
            "created_at REAL, updated_at REAL)")
        _IDEM_CONN.commit()
    return _IDEM_CONN


def _idem_get(request_id):
    if not request_id:
        return None
    with _IDEM_LOCK:
        return _idem_conn().execute(
            "SELECT state, result FROM order_requests WHERE request_id=?",
            (request_id,)).fetchone()


def _idem_put(request_id, state, result=None):
    if not request_id:
        return
    import time as _t_idem
    _now = _t_idem.time()
    with _IDEM_LOCK:
        c = _idem_conn()
        c.execute(
            "INSERT INTO order_requests (request_id, state, result, created_at, updated_at)"
            " VALUES (?,?,?,?,?)"
            " ON CONFLICT(request_id) DO UPDATE SET state=excluded.state,"
            " result=excluded.result, updated_at=excluded.updated_at",
            (request_id, state,
             _json_idem.dumps(result) if result is not None else None, _now, _now))
        c.commit()


@app.post("/mt5/order", dependencies=[Depends(verify_api_key)])'''

E3_OLD = """    ot_key = req.order_type.lower()
    if ot_key not in ORDER_TYPE_MAP:
        raise HTTPException(400, f"Invalid order_type: {req.order_type}")"""
E3_NEW = """    # ── M2 幂等重放检查(V1.1 §9.2) ──
    if req.request_id:
        _prev = _idem_get(req.request_id)
        if _prev:
            _pstate, _pres = _prev
            if _pstate == "DONE" and _pres:
                _r = _json_idem.loads(_pres)
                _r["idempotency_hit"] = True
                return _r
            if _pstate == "FAILED":
                raise HTTPException(400, "idempotent-replay: previous attempt FAILED terminally")
            return {"success": False, "unknown": True, "state": _pstate,
                    "request_id": req.request_id, "idempotency_hit": True,
                    "error": "previous attempt outcome unknown (SENDING), refuse to resend"}
        _idem_put(req.request_id, "SENDING")

    ot_key = req.order_type.lower()
    if ot_key not in ORDER_TYPE_MAP:
        raise HTTPException(400, f"Invalid order_type: {req.order_type}")"""

E4_OLD = """            return {
                "success":  True,
                "retcode":  result.retcode,
                "order":    result.order,
                "deal":     result.deal,
                "volume":   _filled,
                "price":    result.price,
                "comment":  result.comment,
                "requested_volume": req.volume,
                "normalized_volume": volume,
                "filled_volume": _filled,
                "remaining_volume": max(0.0, round(volume - _filled, 8)),
                "partial": _partial,
            }"""
E4_NEW = """            _resp = {
                "success":  True,
                "retcode":  result.retcode,
                "order":    result.order,
                "deal":     result.deal,
                "volume":   _filled,
                "price":    result.price,
                "comment":  result.comment,
                "requested_volume": req.volume,
                "normalized_volume": volume,
                "filled_volume": _filled,
                "remaining_volume": max(0.0, round(volume - _filled, 8)),
                "partial": _partial,
                "request_id": req.request_id,
            }
            _idem_put(req.request_id, "DONE", _resp)
            return _resp"""

E5_OLD = '        raise HTTPException(400, f"Order failed retcode={result.retcode} comment={result.comment}")'
E5_NEW = '''        _idem_put(req.request_id, "FAILED", {"error": f"retcode={result.retcode} comment={result.comment}"})
        raise HTTPException(400, f"Order failed retcode={result.retcode} comment={result.comment}")'''

E6_APPEND = '''

# ── M2: 幂等状态查询(V1.1 §9.1) — 后端HTTP超时后按request_id查询, 禁止盲重发 ──
@app.get("/mt5/order-status/{request_id}", dependencies=[Depends(verify_api_key)])
async def order_status(request_id: str):
    row = _idem_get(request_id)
    if not row:
        raise HTTPException(404, "unknown request_id")
    _state, _result = row
    out = {"request_id": request_id, "state": _state,
           "terminal": _state in ("DONE", "FAILED")}
    if _result:
        try:
            out["result"] = _json_idem.loads(_result)
        except Exception:
            pass
    return out
'''


def patch(bridge_dir):
    p = os.path.join(bridge_dir, 'app', 'main.py')
    src = open(p, encoding='utf-8').read()
    if 'idempotency.db' in src:
        print('SKIP(already patched): ' + p)
        return True
    for i, old in enumerate((E1_OLD, E2_OLD, E3_OLD, E4_OLD, E5_OLD), 1):
        if src.count(old) != 1:
            print('ABORT: E%d match=%d (expect 1) in %s' % (i, src.count(old), p))
            return False
    bak = p + '.bak_idem_' + time.strftime('%Y%m%d_%H%M%S')
    shutil.copy2(p, bak)
    src = src.replace(E1_OLD, E1_NEW).replace(E2_OLD, E2_NEW).replace(E3_OLD, E3_NEW)
    src = src.replace(E4_OLD, E4_NEW).replace(E5_OLD, E5_NEW) + E6_APPEND
    open(p, 'w', encoding='utf-8').write(src)
    import py_compile
    py_compile.compile(p, doraise=True)
    print('PATCHED+COMPILED: %s (backup=%s)' % (p, os.path.basename(bak)))
    return True


if __name__ == '__main__':
    ok = all(patch(d) for d in sys.argv[1:])
    sys.exit(0 if ok else 1)
