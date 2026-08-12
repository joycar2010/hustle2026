# QH 契约级假桥(fake_bridge) — 完全复刻 mt5-bridge 协议面, 可编排故障场景(V1.1 测试床移植)
# 用途: 改执行链(connector/app 执行路径)必跑, 告别真金 canary 验证。
# 复刻端点: /mt5/tick /mt5/order(+request_id幂等) /mt5/order-status /mt5/position/close
#           /mt5/positions /mt5/history/deals /mt5/account/info /mt5/connection/status /mt5/position/close-all
# 场景旋钮(state 字典, 由编排器直接改内存; 不走网络):
#   order_mode: ok | http500 | timeout_exec(响应拖过客户端超时但订单已执行) | timeout_noexec(拖时且未执行)
#   close_mode: ok | http500 | timeout_exec | timeout_noexec
#   read_down:  True=读端点(positions/history)也502(演练"真相源不可达=查不清")
#   delay_sec:  timeout_* 模式拖多久(须 > 客户端超时)
#   tick_age_sec / broker_off: tick 时间做旧(演练新鲜度闸)
import asyncio, time, itertools
from fastapi import FastAPI, HTTPException, Header

API_KEY = "testbed-key"

def make_app(name="fake"):
    app = FastAPI(title="fake-bridge-" + name)
    st = {
        "order_mode": "ok", "close_mode": "ok", "read_down": False,
        "delay_sec": 3.0, "tick_age_sec": 0.0, "broker_off": 10800,
        "positions": [], "deals": [], "orders_received": 0, "closes_received": 0,
        "idem": {},  # request_id -> (state, result)  复刻幂等补丁
        "tick_seq": itertools.count(1), "ticket_seq": itertools.count(100000),
    }
    app.state.st = st

    def _auth(key):
        if key != API_KEY: raise HTTPException(403, "Invalid API Key")

    def _read_gate():
        if st["read_down"]: raise HTTPException(502, "fake read down")

    @app.get("/mt5/tick/{symbol}")
    async def tick(symbol: str, x_api_key: str = Header(default="")):
        _auth(x_api_key); _read_gate()
        t = time.time() + st["broker_off"] - st["tick_age_sec"]   # 经纪商墙钟 - 做旧
        return {"symbol": symbol, "bid": 4000.0, "ask": 4000.1, "last": 0.0, "volume": 0,
                "time": int(t), "time_msc": int(t * 1000)}

    @app.get("/mt5/positions")
    async def positions(x_api_key: str = Header(default="")):
        _auth(x_api_key); _read_gate()
        return {"positions": list(st["positions"])}

    @app.get("/mt5/history/deals")
    async def history(days: int = 1, x_api_key: str = Header(default="")):
        _auth(x_api_key); _read_gate()
        return {"deals": list(st["deals"])}

    @app.get("/mt5/account/info")
    async def account(x_api_key: str = Header(default="")):
        _auth(x_api_key); _read_gate()
        return {"balance": 1000.0, "equity": 1000.0, "margin": 0.0, "margin_free": 1000.0}

    @app.get("/mt5/connection/status")
    async def status(x_api_key: str = Header(default="")):
        _auth(x_api_key)
        return {"connected": True}

    @app.get("/mt5/order-status/{request_id}")
    async def order_status(request_id: str, x_api_key: str = Header(default="")):
        _auth(x_api_key)
        row = st["idem"].get(request_id)
        if not row: raise HTTPException(404, "unknown request_id")
        _state, _result = row
        out = {"request_id": request_id, "state": _state, "terminal": _state in ("DONE", "FAILED")}
        if _result: out["result"] = _result
        return out

    def _exec_order(body):
        tk = next(st["ticket_seq"])
        deal = tk + 500000
        res = {"success": True, "retcode": 10009, "order": tk, "deal": deal,
               "volume": body.get("volume"), "price": 4000.05,
               "comment": body.get("comment", ""), "filled_volume": body.get("volume"),
               "partial": False, "request_id": body.get("request_id")}
        st["positions"].append({"ticket": tk, "symbol": body.get("symbol"),
                                "volume": body.get("volume"),
                                "type": body.get("order_type"), "price_open": 4000.05,
                                "profit": 0.0, "comment": body.get("comment", "")})
        st["deals"].append({"ticket": deal, "order": tk, "symbol": body.get("symbol"),
                            "type": 0 if body.get("order_type") == "buy" else 1, "entry": 0,
                            "volume": body.get("volume"), "price": 4000.05, "profit": 0.0,
                            "comment": body.get("comment", ""),
                            "time": int(time.time() + st["broker_off"])})
        return res

    @app.post("/mt5/order")
    async def order(body: dict, x_api_key: str = Header(default="")):
        _auth(x_api_key)
        rid = body.get("request_id")
        if rid and rid in st["idem"]:               # 幂等重放: 只回原结果, 不再执行
            _state, _result = st["idem"][rid]
            if _state == "DONE": return _result
            raise HTTPException(409, "request in flight/failed")
        mode = st["order_mode"]
        st["orders_received"] += 1
        if mode == "http500":
            if rid: st["idem"][rid] = ("FAILED", {"error": "retcode=10013"})
            raise HTTPException(500, "fake order failure")
        if mode == "timeout_noexec":
            await asyncio.sleep(st["delay_sec"])
            raise HTTPException(504, "fake late failure")
        res = _exec_order(body)
        if rid: st["idem"][rid] = ("DONE", res)
        if mode == "timeout_exec":                   # 已执行(上面已入账), 但响应拖过客户端超时
            await asyncio.sleep(st["delay_sec"])
        return res

    @app.post("/mt5/position/close")
    async def close_pos(body: dict, x_api_key: str = Header(default="")):
        _auth(x_api_key)
        mode = st["close_mode"]
        st["closes_received"] += 1
        if mode == "http500":
            raise HTTPException(500, "fake close failure")
        if mode == "timeout_noexec":
            await asyncio.sleep(st["delay_sec"])
            raise HTTPException(504, "fake late failure")
        tk = body.get("ticket")
        if tk is not None:
            hit = [p for p in st["positions"] if str(p["ticket"]) == str(tk)]
            if not hit: raise HTTPException(404, "Position ticket %s not found" % tk)
        else:
            want = "buy" if str(body.get("side", "")).lower() == "buy" else "sell"
            hit = [p for p in st["positions"] if p["type"] == want]
            if not hit: raise HTTPException(404, "No matching positions found")
        p = hit[0]
        st["positions"] = [x for x in st["positions"] if x["ticket"] != p["ticket"]]
        st["deals"].append({"ticket": next(st["ticket_seq"]) + 500000, "order": next(st["ticket_seq"]),
                            "symbol": p["symbol"], "type": 1 if p["type"] == "buy" else 0, "entry": 1,
                            "volume": p["volume"], "price": 4000.10, "profit": 0.5,
                            "comment": "", "time": int(time.time() + st["broker_off"])})
        res = {"success": True, "closed_ticket": p["ticket"], "volume": p["volume"], "price": 4000.10}
        if mode == "timeout_exec":                   # 已平(上面已出账), 响应拖时
            await asyncio.sleep(st["delay_sec"])
        return res

    @app.post("/mt5/position/close-all")
    async def close_all(body: dict, x_api_key: str = Header(default="")):
        _auth(x_api_key)
        n = len(st["positions"]); st["positions"] = []
        return {"closed": n, "failed": 0}

    return app
