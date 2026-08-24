"""
test_phased.py — Phase D 测试床 S1-S13(对 Broker Simulator)

前置:Simulator 跑在 <testdir>,测试 Agent 跑在 :8043 且 TERMINAL_FILES_DIR=<testdir>。
本脚本用 HTTP 驱动 Agent 写端点,用 sim/mode.json 注入故障,断言幂等/超时/恢复/UNKNOWN。

用法:python test_phased.py <testdir> [port]
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

TESTDIR = sys.argv[1] if len(sys.argv) > 1 else "simtest/qhbridge"
PORT = sys.argv[2] if len(sys.argv) > 2 else "8043"
BASE = "http://127.0.0.1:%s" % PORT
KEY = "QHMT4-TEST-KEY-2026"

_results = []


def set_mode(mode, delay_sec=0):
    p = os.path.join(TESTDIR, "sim", "mode.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"mode": mode, "delay_sec": delay_sec}, f)
    time.sleep(0.15)   # 让 sim 读到新模式


def _req(method, path, body=None, auth=True):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    if auth:
        r.add_header("X-API-Key", KEY)
    if data:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}


def order(symbol="XAUUSD", volume=0.01, order_type="buy", request_id=None, auth=True):
    b = {"symbol": symbol, "volume": volume, "order_type": order_type}
    if request_id:
        b["request_id"] = request_id
    return _req("POST", "/mt5/order", b, auth)


def check(name, cond, detail=""):
    _results.append((name, cond, detail))
    print(("  PASS " if cond else "  FAIL ") + name + ((" :: " + detail) if detail else ""))


# ═══ S1 正常下单 → DONE ═══
set_mode("normal")
st, r = order(request_id="rid-s1")
check("S1 normal order", st == 200 and r.get("success") and r.get("order", 0) > 0, "st=%s order=%s" % (st, r.get("order")))
s1_ticket = r.get("order")

# ═══ S2 幂等重放(同 request_id)→ 原结果,不重开 ═══
st, r2 = order(request_id="rid-s1")
check("S2 idempotent replay", st == 200 and r2.get("idempotency_hit") and r2.get("order") == s1_ticket,
      "hit=%s order=%s" % (r2.get("idempotency_hit"), r2.get("order")))

# ═══ S3 超时 → UNKNOWN(SENDING),后续 order-status 解决为 DONE ═══
set_mode("timeout")
st, r = order(request_id="rid-s3")
check("S3 timeout -> UNKNOWN", st == 200 and r.get("unknown") and r.get("state") == "SENDING",
      "unknown=%s state=%s" % (r.get("unknown"), r.get("state")))
set_mode("normal")   # sim 现在处理遗留命令
time.sleep(1.2)
st, r = _req("GET", "/mt5/order-status/rid-s3")
check("S3 order-status resolves DONE", st == 200 and r.get("state") == "DONE" and r.get("terminal"),
      "state=%s" % r.get("state"))

# ═══ S4 券商拒单 → FAILED,重放 → 400 ═══
set_mode("reject")
st, r = order(request_id="rid-s4")
check("S4 reject -> 400", st == 400, "st=%s" % st)
st, r = _req("GET", "/mt5/order-status/rid-s4")
check("S4 order-status FAILED", st == 200 and r.get("state") == "FAILED", "state=%s" % r.get("state"))
st, r = order(request_id="rid-s4")
check("S4 replay FAILED -> 400", st == 400, "st=%s" % st)

# ═══ S5 部分成交 ═══
set_mode("partial")
st, r = order(symbol="XAUUSD", volume=0.10, request_id="rid-s5")
check("S5 partial fill", st == 200 and r.get("success") and r.get("partial") and r.get("filled_volume", 0) < 0.10,
      "partial=%s filled=%s" % (r.get("partial"), r.get("filled_volume")))

# ═══ S6 Agent 崩溃恢复:SENDING + 结果文件已到 → 重放取结果不重发 ═══
set_mode("timeout")
st, r = order(request_id="rid-s6")   # SENDING,命令留存
set_mode("normal")
time.sleep(1.0)                       # sim 写结果(EA 已执行)
st, r = order(request_id="rid-s6")   # 重放:Agent 见 SENDING+结果文件 → 落账返回
check("S6 crash-recovery replay", st == 200 and r.get("success") and r.get("idempotency_hit"),
      "success=%s hit=%s" % (r.get("success"), r.get("idempotency_hit")))

# ═══ S7 平仓(按 ticket)═══
set_mode("normal")
st, r = order(request_id="rid-s7")
tk = r.get("order")
st, r = _req("POST", "/mt5/position/close", {"symbol": "XAUUSD", "side": "sell", "ticket": tk})
check("S7 close by ticket", st == 200 and r.get("success"), "st=%s" % st)

# ═══ S8 全平 ═══
order(request_id="rid-s8a"); order(request_id="rid-s8b")
st, r = _req("POST", "/mt5/position/close-all", {"symbol": None})
check("S8 close-all", st == 200 and r.get("closed", 0) >= 2, "closed=%s" % r.get("closed"))

# ═══ S9 撤挂单(sim 无挂单 → 0)═══
st, r = _req("POST", "/mt5/cancel-all", {"symbol": None})
check("S9 cancel-all", st == 200 and "cancelled" in r, "cancelled=%s" % r.get("cancelled"))

# ═══ S10 不重开:超时→SENDING,sim 处理留存命令,order-status DONE 单一票,重放同票 ═══
set_mode("timeout")
order(request_id="rid-s10")
set_mode("normal")
time.sleep(1.2)
st, r = _req("GET", "/mt5/order-status/rid-s10")
t10 = (r.get("result") or {}).get("order")
st, r2 = order(request_id="rid-s10")
check("S10 no double-open", r.get("state") == "DONE" and r2.get("idempotency_hit") and r2.get("order") == t10,
      "t10=%s replay=%s" % (t10, r2.get("order")))

# ═══ S11 无鉴权 → 拒绝 ═══
st, r = order(request_id="rid-s11", auth=False)
check("S11 no-auth rejected", st in (401, 422), "st=%s" % st)

# ═══ S12 无 request_id(一次性)→ 成功,无账本 ═══
set_mode("normal")
st, r = order()   # 无 request_id
check("S12 no-rid one-shot", st == 200 and r.get("success"), "st=%s" % st)

# ═══ S13 未知 request_id 查状态 → 404 ═══
st, r = _req("GET", "/mt5/order-status/does-not-exist")
check("S13 unknown rid -> 404", st == 404, "st=%s" % st)

# ═══ 汇总 ═══
passed = sum(1 for _, c, _ in _results if c)
total = len(_results)
print("\n=== S1-S13 RESULT: %d/%d PASS ===" % (passed, total))
sys.exit(0 if passed == total else 1)
