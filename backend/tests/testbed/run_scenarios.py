# QH 执行链契约测试床 — 场景编排(V1.1 移植)。改执行链必跑:
#   本机:  python tests/testbed/run_scenarios.py
#   服务器: cd /opt/quanthedge && venv/bin/python tests/testbed/run_scenarios.py
# 直接锻炼生产 connector.py(开/平仓时序/裸空守护/rid幂等/UNKNOWN查真相) 与 engine.py(新鲜度闸),
# 不依赖 DB/Redis/app.py; 假桥完全复刻 mt5-bridge 协议。
import asyncio, os, sys, threading, time
try: sys.stdout.reconfigure(encoding="utf-8")   # Windows 控制台 cp1252 打不出中文场景名
except Exception: pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, _HERE)

import uvicorn
import connector as CN
import engine as ENG
from fake_bridge import make_app, API_KEY

CN.GET_TIMEOUT = 1.2      # 调小超时: timeout 场景秒级演练(生产默认 10/15 不受影响)
CN.POST_TIMEOUT = 1.2

MAIN_PORT, HEDGE_PORT = 18021, 18001
m_app = make_app("main"); h_app = make_app("hedge")
MS = m_app.state.st; HS = h_app.state.st

def _serve(app, port):
    cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical")
    srv = uvicorn.Server(cfg)
    threading.Thread(target=srv.run, daemon=True).start()
    return srv

def _mkconn():
    return CN._bridge_from_urls("http://127.0.0.1:%d" % MAIN_PORT, API_KEY,
                                "http://127.0.0.1:%d" % HEDGE_PORT, API_KEY)

def _reset():
    for st in (MS, HS):
        st.update({"order_mode": "ok", "close_mode": "ok", "read_down": False,
                   "delay_sec": 3.0, "tick_age_sec": 0.0,
                   "positions": [], "deals": [], "orders_received": 0,
                   "closes_received": 0, "idem": {}})

PASS = []; FAIL = []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s %s" % ("PASS" if cond else "FAIL", name, detail if not cond else ""))

async def scenarios():
    c = _mkconn()

    # S1 双腿开仓成功: comment 带 #rid, request_id 落幂等表, 双腿各 1 仓
    _reset()
    r = await c.open_pair("reverse", "XAUUSD", "XAUUSD+", 0.01, 0.01, mode="concurrent")
    rid = r["request_id"]
    check("S1 双腿成功", r["main_ok"] and r["hedge_ok"])
    check("S1 comment带#rid", ("#" + rid) in MS["positions"][0]["comment"] and ("#" + rid) in HS["positions"][0]["comment"])
    check("S1 桥幂等键入账", (rid + "m") in MS["idem"] and (rid + "h") in HS["idem"])

    # S2 main_first 主腿硬失败(500) → 对冲绝不尝试
    _reset(); MS["order_mode"] = "http500"
    r = await c.open_pair("reverse", "XAUUSD", "XAUUSD+", 0.01, 0.01, mode="main_first")
    check("S2 主腿失败不开对冲", (not r["main_ok"]) and HS["orders_received"] == 0 and not r["main"].get("unknown"))

    # S3 对冲硬失败 → 裸空如实上抛(main_ok=True/hedge_ok=False)
    _reset(); HS["order_mode"] = "http500"
    r = await c.open_pair("reverse", "XAUUSD", "XAUUSD+", 0.01, 0.01, mode="main_first")
    check("S3 裸空如实返回", r["main_ok"] and (not r["hedge_ok"]) and len(MS["positions"]) == 1)

    # S4 主腿超时但实际已成交 → UNKNOWN → order-status 快路径恢复 → 继续开对冲, 无双开
    _reset(); MS["order_mode"] = "timeout_exec"
    r = await c.open_pair("reverse", "XAUUSD", "XAUUSD+", 0.01, 0.01, mode="main_first")
    check("S4 UNKNOWN恢复成交", r["main_ok"] and r["main"].get("recovered") and r["main"].get("src") == "order-status")
    check("S4 恢复后继续开对冲", r["hedge_ok"] and len(HS["positions"]) == 1)
    check("S4 主腿无双开", MS["orders_received"] == 1 and len(MS["positions"]) == 1)

    # S5 主腿超时且未成交 → comment 扫描 NOFILL → 安全判失败, 不开对冲, 零持仓
    _reset(); MS["order_mode"] = "timeout_noexec"; MS["delay_sec"] = 2.0
    r = await c.open_pair("reverse", "XAUUSD", "XAUUSD+", 0.01, 0.01, mode="main_first")
    check("S5 超时未成交判失败", (not r["main_ok"]) and r["main"].get("unknown_resolved") == "not_filled")
    check("S5 未开对冲无持仓", HS["orders_received"] == 0 and len(MS["positions"]) == 0)

    # S6 幂等重放: 同 request_id 二次下单 → 桥只回原结果, 只有一单
    _reset()
    r1 = await c.main.open_order("XAUUSD", 0.01, "buy", comment="QH-t#deadbee1", request_id="deadbee1m")
    r2 = await c.main.open_order("XAUUSD", 0.01, "buy", comment="QH-t#deadbee1", request_id="deadbee1m")
    check("S6 幂等重放同结果", r1["order"] == r2["order"] and MS["orders_received"] == 1 and len(MS["positions"]) == 1)

    # S7 平仓按 ticket 成功
    _reset()
    r = await c.open_pair("reverse", "XAUUSD", "XAUUSD+", 0.01, 0.01, mode="concurrent")
    mtk = r["main"]["order"]; htk = r["hedge"]["order"]
    rc = await c.close_pair("XAUUSD", "XAUUSD+", "sell", "buy", main_ticket=mtk, hedge_ticket=htk)
    check("S7 按ticket平仓", "error" not in rc["main"] and "error" not in rc["hedge"] and len(MS["positions"]) == 0 and len(HS["positions"]) == 0)

    # S8 平仓超时但实际已平 → ticket 消失 → 恢复成功(防重复平仓)
    _reset()
    r = await c.open_pair("reverse", "XAUUSD", "XAUUSD+", 0.01, 0.01, mode="concurrent")
    mtk = r["main"]["order"]; htk = r["hedge"]["order"]
    MS["close_mode"] = "timeout_exec"
    rc = await c.close_pair("XAUUSD", "XAUUSD+", "sell", "buy", main_ticket=mtk, hedge_ticket=htk)
    check("S8 平仓UNKNOWN恢复", rc["main"].get("recovered") and rc["main"].get("ok") and "error" not in rc["hedge"])

    # S9 平仓超时且未平 → ticket 仍在 → 确认未平(error/still_open), 不误报成功
    _reset()
    r = await c.open_pair("reverse", "XAUUSD", "XAUUSD+", 0.01, 0.01, mode="concurrent")
    mtk = r["main"]["order"]; htk = r["hedge"]["order"]
    MS["close_mode"] = "timeout_noexec"; MS["delay_sec"] = 2.0
    rc = await c.close_pair("XAUUSD", "XAUUSD+", "sell", "buy", main_ticket=mtk, hedge_ticket=htk,
                            truth=None)
    check("S9 超时未平如实报错", rc["main"].get("unknown_resolved") == "still_open" and len(MS["positions"]) == 1)

    # S10 新鲜度闸(engine 纯函数): 新鲜/陈旧/毫秒优先/broker_off 剥离/缺time放行/闸关闭
    now = time.time(); off = 10800
    fresh = {"time": int(now + off - 1), "time_msc": int((now + off - 1) * 1000)}
    stale = {"time": int(now + off - 60), "time_msc": int((now + off - 60) * 1000)}
    check("S10 新鲜通过", ENG.quote_stale_reason(fresh, fresh, off, 15, now) is None)
    check("S10 陈旧拦截", "陈旧" in (ENG.quote_stale_reason(fresh, stale, off, 15, now) or ""))
    check("S10 offset剥离", ENG.quote_stale_reason({"time": int(now + off)}, None, off, 15, now) is None
                        and "陈旧" in (ENG.quote_stale_reason({"time": int(now)}, None, off, 15, now + 60) or ""))
    check("S10 缺time放行", ENG.quote_stale_reason({"bid": 1}, {"time": "2026-07-16T00:00:00"}, off, 15, now) is None)
    check("S10 闸关闭", ENG.quote_stale_reason(stale, stale, off, 0, now) is None)
    a2t_utc = {"time": int(now), "time_msc": int(now * 1000), "src": "a2t"}   # Exness 型: A2T time=UTC, 与桥off不符
    check("S10 a2t云端tick豁免", ENG.quote_stale_reason(fresh, a2t_utc, off, 15, now) is None)

    # S11 真相扫描三态: 命中/确认无(NOFILL)/真相源不可达(None=查不清)
    _reset()
    MS["deals"].append({"ticket": 1, "order": 2, "symbol": "XAUUSD", "type": 0, "entry": 0,
                        "volume": 0.01, "price": 4000.0, "comment": "QH-reverse-main#cafe0001",
                        "time": int(time.time())})
    v = await CN.verify_leg_open(c.main, "cafe0001", tries=1)
    check("S11 comment命中恢复", isinstance(v, dict) and v["src"] == "history" and v["order"] == 2)
    v = await CN.verify_leg_open(c.main, "beef0002", tries=2, delay=0.1)
    check("S11 确认未成交NOFILL", v == "NOFILL")
    MS["read_down"] = True
    v = await CN.verify_leg_open(c.main, "beef0002", tries=2, delay=0.1)
    check("S11 真相源不可达=查不清", v is None)
    MS["read_down"] = False

    # S12 concurrent 双腿同时超时且都已成交 → 双双恢复, 整对完整
    _reset(); MS["order_mode"] = "timeout_exec"; HS["order_mode"] = "timeout_exec"
    r = await c.open_pair("forward", "XAUUSD", "XAUUSD+", 0.01, 0.01, mode="concurrent")
    check("S12 并发双超时双恢复", r["main_ok"] and r["hedge_ok"]
          and r["main"].get("recovered") and r["hedge"].get("recovered")
          and MS["orders_received"] == 1 and HS["orders_received"] == 1)

    # S13 hedge_first 对冲腿超时未成交 → 判失败, 主腿绝不开(防裸空)
    _reset(); HS["order_mode"] = "timeout_noexec"; HS["delay_sec"] = 2.0
    r = await c.open_pair("reverse", "XAUUSD", "XAUUSD+", 0.01, 0.01, mode="hedge_first")
    check("S13 hedge_first超时未成交不开主腿", (not r["hedge_ok"]) and MS["orders_received"] == 0)

async def main():
    _serve(m_app, MAIN_PORT); _serve(h_app, HEDGE_PORT)
    for _ in range(50):
        try:
            import httpx
            httpx.get("http://127.0.0.1:%d/mt5/connection/status" % MAIN_PORT,
                      headers={"X-API-Key": API_KEY}, timeout=1)
            httpx.get("http://127.0.0.1:%d/mt5/connection/status" % HEDGE_PORT,
                      headers={"X-API-Key": API_KEY}, timeout=1)
            break
        except Exception:
            await asyncio.sleep(0.2)
    t0 = time.time()
    await scenarios()
    print("\n== %d PASS / %d FAIL (%.1fs) ==" % (len(PASS), len(FAIL), time.time() - t0))
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
