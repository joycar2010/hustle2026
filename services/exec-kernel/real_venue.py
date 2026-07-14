"""RealVenue 适配器(V4.0 §6.1)—— 与混沌测试的 SimVenue **同一套接口**,
换上它 exec_core 即武装执行器。**只在 B 机(执行面,有密钥)运行**。
安全铁律:
- place()/cancel() 硬门控:非 DCM_EXEC_ARMED=true 或 symbol 不在 DCM_EXEC_ARM_SYMBOLS → 直接拒绝,绝不下单;
- 读路径(query/position)先行验证:证明签名+解析正确,再谈武装;
- 确定性 clientOrderId 幂等:重试先 query 再 place(exec_core 已保证)。
本文件当前只投产 query/position(读);place 仅占位+门控,武装另行专场。
"""
import asyncio
import base64
import hashlib
import hmac
import json
import math
import os
import time
from urllib.parse import urlencode

import httpx

# 与 exec_core 一致的状态常量(此处内联,B 上可独立部署)
FILLED, ACK, PARTIAL, NOTFOUND, REJECT, TIMEOUT = \
    "FILLED", "ACK", "PARTIAL", "NOTFOUND", "REJECT", "TIMEOUT"

BINANCE_FAPI = "https://fapi.binance.com"
BINANCE_SPOT = "https://api.binance.com"


class VenueError(Exception):
    pass


def venue_sym(venue: str, sym: str) -> str:
    """dcm 符号(BASEUSDT)→ 各所格式:gate=BASE_USDT / okx=BASE-USDT-SWAP / HL=BASE;其余原样。"""
    if not sym.endswith("USDT"):
        return sym
    base = sym[:-4]
    return {"gate": base + "_USDT", "okx": base + "-USDT-SWAP", "hyperliquid": base}.get(venue, sym)


def _qstr(q) -> str:
    """数量→字符串,trim 尾零("83.0"→"83")——bybit/bitget 对小数位超步长精度会拒单。"""
    return f"{float(q):.8f}".rstrip("0").rstrip(".")


def _det_coid(cid: str, maxlen: int, prefix: str = "") -> str:
    """确定性客户单号,截断安全:可读前缀 + sha1 短哈希(8位)。
    ⚠️真金课(gate DOGE):裸截断 [:N] 会把 ':open'/':close' 后缀切掉 → open/close 撞同一单号
    → close 时 query 查到旧 open 单 FILLED 误判已平,静默跳过下单=裸腿。哈希尾保证任意截断下唯一。"""
    h = hashlib.sha1(cid.encode()).hexdigest()[:8]
    room = maxlen - len(prefix) - 9   # 9 = "-" + 8位哈希
    return prefix + cid.replace(":", "-")[:room] + "-" + h


def _env_armed(armed, arm_symbols):
    """armed/arm_symbols 构造覆盖(manager 按 symbol 精细控制),否则回落 env。"""
    a = (os.environ.get("DCM_EXEC_ARMED", "false").lower() == "true") if armed is None else bool(armed)
    s = ({x.strip() for x in os.environ.get("DCM_EXEC_ARM_SYMBOLS", "").split(",") if x.strip()}
         if arm_symbols is None else set(arm_symbols))
    return a, s


class _GatedPos:
    """公共件:下单硬门控 + all_positions→get_position 派生(单币仓)。"""
    armed = False
    arm_symbols = frozenset()

    def _gate(self, cid, sym):
        if not self.armed:
            raise PermissionError(f"exec 未武装(DCM_EXEC_ARMED!=true),拒绝下单 {cid}")
        if sym not in self.arm_symbols:
            raise PermissionError(f"{sym} 不在武装白名单 {sorted(self.arm_symbols)},拒绝下单 {cid}")

    async def get_position(self, symbol: str) -> dict:
        r = await self.all_positions()
        if not r.get("ok"):
            return {"ok": False, "err": r.get("err")}
        amt = float(r["positions"].get(symbol, 0.0))
        return {"ok": True, "symbol": symbol, "amt": amt, "flat": abs(amt) < 1e-12}


class BinanceRealVenue:
    """binance 永续/现货 读适配器 + 门控下单。key/secret 从环境(B 机 .env / cred-agent)。"""

    def __init__(self, key: str = "", secret: str = "", armed=None, arm_symbols=None):
        self.key = key or os.environ.get("BINANCE_KEY", "")
        self.secret = secret or os.environ.get("BINANCE_SECRET", "")
        # armed/arm_symbols 可构造覆盖(manager 按 symbol 精细控制),否则回落 env
        self.armed = (os.environ.get("DCM_EXEC_ARMED", "false").lower() == "true") if armed is None else bool(armed)
        self.arm_symbols = ({s.strip() for s in os.environ.get("DCM_EXEC_ARM_SYMBOLS", "").split(",") if s.strip()}
                            if arm_symbols is None else set(arm_symbols))

    def _sign(self, params: dict) -> str:
        q = urlencode({**params, "timestamp": int(time.time() * 1000), "recvWindow": 5000})
        sig = hmac.new(self.secret.encode(), q.encode(), hashlib.sha256).hexdigest()
        return f"{q}&signature={sig}"

    @staticmethod
    def _bcoid(cid: str) -> str:
        """确定性 cid → 币安 newClientOrderId(≤36,截断安全);place 与 query 必须一致。"""
        return _det_coid(cid, 36)

    async def _get(self, base: str, path: str, params: dict):
        """返回 (status_code, parsed_json_or_text)。parsed 可能是 dict 或 list。"""
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(f"{base}{path}?{self._sign(params)}",
                              headers={"X-MBX-APIKEY": self.key})
        try:
            return r.status_code, r.json()
        except Exception:  # noqa: BLE001
            return r.status_code, r.text

    # ---------- 读路径(投产) ----------
    async def query(self, cid: str, leg: dict = None) -> dict:
        """按 clientOrderId 查订单状态 → exec_core 接口 dict(与 exec_core query(cid,leg) 契约一致)。
        找不到=NOTFOUND(幂等安全)。coid 与 place 同一归一化。"""
        leg = leg or {}
        symbol = leg.get("symbol", "")
        market = leg.get("market", "perp")
        base, path = (BINANCE_FAPI, "/fapi/v1/order") if market == "perp" else (BINANCE_SPOT, "/api/v3/order")
        try:
            code, d = await self._get(base, path, {"symbol": symbol, "origClientOrderId": self._bcoid(cid)})
        except Exception:  # noqa: BLE001
            return {"status": TIMEOUT, "filled": 0}
        if code != 200 or not isinstance(d, dict):
            return {"status": NOTFOUND, "filled": 0}   # -2013 无此单 = 未下到,可安全重试
        st = d.get("status", "")
        m = {"FILLED": FILLED, "NEW": ACK, "PARTIALLY_FILLED": PARTIAL}.get(st, NOTFOUND)
        return {"status": m, "filled": float(d.get("executedQty") or 0)}

    async def get_position(self, symbol: str) -> dict:
        """读永续实盘持仓(reconcile 对账用)。"""
        code, d = await self._get(BINANCE_FAPI, "/fapi/v2/positionRisk", {"symbol": symbol})
        if code != 200 or not isinstance(d, list):
            return {"ok": False, "err": f"http {code}: {str(d)[:120]}"}
        pos = next((p for p in d if p.get("symbol") == symbol), None)
        if not pos:
            return {"ok": True, "symbol": symbol, "amt": 0.0, "entry": 0.0, "flat": True}
        amt = float(pos.get("positionAmt") or 0)
        return {"ok": True, "symbol": symbol, "amt": amt, "entry": float(pos.get("entryPrice") or 0),
                "unrealized": float(pos.get("unRealizedProfit") or 0), "flat": abs(amt) < 1e-12}

    async def all_positions(self) -> dict:
        """扫全部非空永续持仓 → {symbol: amt}。用于抓「裸露实盘」(内核不知道的仓,最危险)。"""
        code, d = await self._get(BINANCE_FAPI, "/fapi/v2/positionRisk", {})
        if code != 200 or not isinstance(d, list):
            return {"ok": False, "err": f"http {code}: {str(d)[:120]}"}
        out = {}
        for p in d:
            amt = float(p.get("positionAmt") or 0)
            if abs(amt) > 1e-12:
                out[p.get("symbol")] = amt
        return {"ok": True, "positions": out}

    async def get_spot_balance(self, asset: str) -> float:
        """现货某资产 free 余额(C1 现货腿平仓按实际余额卖,防手续费残留超卖)。"""
        code, d = await self._get(BINANCE_SPOT, "/api/v3/account", {})
        if code != 200 or not isinstance(d, dict):
            return 0.0
        for b in d.get("balances", []):
            if b.get("asset") == asset:
                return float(b.get("free") or 0)
        return 0.0

    async def _post(self, base: str, path: str, params: dict):
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.post(f"{base}{path}?{self._sign(params)}", headers={"X-MBX-APIKEY": self.key})
        try:
            return r.status_code, r.json()
        except Exception:  # noqa: BLE001
            return r.status_code, r.text

    # ---------- 下单路径(硬门控 + 市价单) ----------
    async def place(self, cid: str, leg: dict) -> dict:
        """市价单(binance 永续/现货)。leg={symbol,side(BUY/SELL),market,qty|quote_qty,reduce_only}。
        硬门控:非 armed 或 symbol 不在白名单 → 拒绝。确定性 cid→newClientOrderId(交易所端幂等)。"""
        sym = leg.get("symbol", "")
        if not self.armed:
            raise PermissionError(f"exec 未武装(DCM_EXEC_ARMED!=true),拒绝下单 {cid}")
        if sym not in self.arm_symbols:
            raise PermissionError(f"{sym} 不在武装白名单 {self.arm_symbols},拒绝下单 {cid}")
        market = leg.get("market", "perp")
        base, path = (BINANCE_FAPI, "/fapi/v1/order") if market == "perp" else (BINANCE_SPOT, "/api/v3/order")
        params = {"symbol": sym, "side": leg["side"], "type": "MARKET",
                  "newClientOrderId": self._bcoid(cid)}
        if leg.get("quote_qty") is not None and market == "spot":
            params["quoteOrderQty"] = leg["quote_qty"]
        else:
            params["quantity"] = leg["qty"]
        if leg.get("reduce_only") and market == "perp":
            params["reduceOnly"] = "true"
        try:
            code, d = await self._post(base, path, params)
        except Exception as e:  # noqa: BLE001
            return {"status": TIMEOUT, "filled": 0, "err": repr(e)[:120]}
        if code != 200 or not isinstance(d, dict):
            return {"status": REJECT, "filled": 0, "err": f"http {code}: {str(d)[:150]}"}
        st = d.get("status", "")
        return {"status": {"FILLED": FILLED, "NEW": ACK, "PARTIALLY_FILLED": PARTIAL}.get(st, ACK),
                "filled": float(d.get("executedQty") or 0), "venue_order_id": str(d.get("orderId") or "")}

    async def cancel(self, cid: str, symbol: str = "", market: str = "perp") -> None:
        if not self.armed:
            raise PermissionError("exec 未武装,拒绝撤单")


class BinanceMarginRealVenue(_GatedPos):
    """C3 借币现货空腿适配器(V4.0 §6.1 BORROW_SPOT_SHORT_DERIVATIVE_LONG 模板 / §15 borrow-repay action adapter)。
    币安全仓杠杆(sapi/v1/margin),用 sideEffectType 让借+卖 / 买+还在交易所端**原子完成**——
    彻底消除裸债窗口(§11 naked debt 铁律):
      开空腿 = 市价 SELL + MARGIN_BUY(自动借基础币再卖出 → 债务即空头)
      平空腿 = 市价 BUY  + AUTO_REPAY(买回再自动还债 → 平空)
    「仓位」= 基础币负债(borrowed+interest);get_position 返回 -debt(§11 债务现查:还币按活口径)。
    与 exec_core/Pair Saga 同接口:换上它内核即能驱动 C3 短腿。**只在 B 机(有密钥)运行**。
    ⚠️engine-lending/coin C3.S 引擎不动(§21 不重写);本适配器是给统一内核补 C3 执行能力。"""

    SAPI = "https://api.binance.com"

    def __init__(self, key: str = "", secret: str = "", armed=None, arm_symbols=None):
        self.key = key or os.environ.get("BINANCE_KEY", "")
        self.secret = secret or os.environ.get("BINANCE_SECRET", "")
        self.armed, self.arm_symbols = _env_armed(armed, arm_symbols)
        self._step = {}   # symbol -> LOT_SIZE stepSize(现货规格)

    def _sign(self, params: dict) -> str:
        q = urlencode({**params, "timestamp": int(time.time() * 1000), "recvWindow": 5000})
        sig = hmac.new(self.secret.encode(), q.encode(), hashlib.sha256).hexdigest()
        return f"{q}&signature={sig}"

    @staticmethod
    def _coid(cid: str) -> str:
        return _det_coid(cid, 36)

    async def _get(self, path, params):
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(f"{self.SAPI}{path}?{self._sign(params)}", headers={"X-MBX-APIKEY": self.key})
        try:
            return r.status_code, r.json()
        except Exception:  # noqa: BLE001
            return r.status_code, r.text

    async def _post(self, path, params):
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.post(f"{self.SAPI}{path}?{self._sign(params)}", headers={"X-MBX-APIKEY": self.key})
        try:
            return r.status_code, r.json()
        except Exception:  # noqa: BLE001
            return r.status_code, r.text

    async def _lot_step(self, symbol: str):
        """现货 LOT_SIZE stepSize(margin 下单量须落步长)。缓存。"""
        if symbol not in self._step:
            self._step[symbol] = 0.0
            try:
                async with httpx.AsyncClient(timeout=15) as cli:
                    d = (await cli.get(f"{BINANCE_SPOT}/api/v3/exchangeInfo?symbol={symbol}")).json()
                for s in d.get("symbols", []):
                    if s["symbol"] == symbol:
                        for f in s.get("filters", []):
                            if f["filterType"] == "LOT_SIZE":
                                self._step[symbol] = float(f["stepSize"])
            except Exception:  # noqa: BLE001
                pass
        return self._step[symbol] or 0.0

    async def query(self, cid: str, leg: dict = None) -> dict:
        """GET margin/order by origClientOrderId → exec_core dict。-2013 无此单=NOTFOUND(可安全重下)。"""
        leg = leg or {}
        symbol = leg.get("symbol", "")
        code, d = await self._get("/sapi/v1/margin/order",
                                  {"symbol": symbol, "origClientOrderId": self._coid(cid), "isIsolated": "FALSE"})
        if code != 200 or not isinstance(d, dict) or not d.get("orderId"):
            return {"status": NOTFOUND, "filled": 0}
        st = d.get("status", "")
        m = {"FILLED": FILLED, "NEW": ACK, "PARTIALLY_FILLED": PARTIAL}.get(st, NOTFOUND)
        return {"status": m, "filled": float(d.get("executedQty") or 0)}

    async def place(self, cid: str, leg: dict) -> dict:
        """C3 借币短腿市价单。开=SELL+MARGIN_BUY(借+卖);平=BUY+AUTO_REPAY(买+还)。硬门控。
        leg={symbol,side(SELL开/BUY平),qty(base),reduce_only}。"""
        symbol = leg.get("symbol", "")
        self._gate(cid, symbol)
        side = str(leg["side"]).upper()
        # 开空=借币卖出;平空=买回还债。reduce_only 或 side=BUY 视为平仓侧。
        closing = bool(leg.get("reduce_only")) or side == "BUY"
        side_effect = "AUTO_REPAY" if closing else "MARGIN_BUY"
        step = await self._lot_step(symbol)
        qty = leg["qty"]
        if step > 0:
            qty = math.floor(float(qty) / step) * step
        if float(qty) <= 0:
            return {"status": REJECT, "filled": 0, "err": f"qty {leg['qty']} 落步长 {step} 后为 0"}
        params = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": _qstr(qty),
                  "isIsolated": "FALSE", "sideEffectType": side_effect, "newClientOrderId": self._coid(cid)}
        code, d = await self._post("/sapi/v1/margin/order", params)
        if code != 200 or not isinstance(d, dict) or not d.get("orderId"):
            return {"status": REJECT, "filled": 0, "err": f"http {code}: {str(d)[:150]}"}
        st = d.get("status", "")
        return {"status": {"FILLED": FILLED, "NEW": ACK, "PARTIALLY_FILLED": PARTIAL}.get(st, ACK),
                "filled": float(d.get("executedQty") or 0), "venue_order_id": str(d.get("orderId") or "")}

    async def all_positions(self) -> dict:
        """全仓杠杆逐资产负债(borrowed+interest)=空头仓位;返回 {BASEUSDT: -debt}。§11 债务现查。"""
        code, d = await self._get("/sapi/v1/margin/account", {})
        if code != 200 or not isinstance(d, dict) or "userAssets" not in d:
            return {"ok": False, "err": f"http {code}: {str(d)[:120]}"}
        out = {}
        for a in d.get("userAssets", []):
            debt = float(a.get("borrowed") or 0) + float(a.get("interest") or 0)
            if debt > 1e-12 and a.get("asset") != "USDT":
                out[f"{a['asset']}USDT"] = -debt   # 负债=空头,带负号
        return {"ok": True, "positions": out}

    async def debt(self, base_asset: str) -> float:
        """某基础币活负债(borrowed+interest);平仓/还币按此现查(§11:绝不用开仓快照)。"""
        code, d = await self._get("/sapi/v1/margin/account", {})
        if code != 200 or not isinstance(d, dict):
            return 0.0
        for a in d.get("userAssets", []):
            if a.get("asset") == base_asset:
                return float(a.get("borrowed") or 0) + float(a.get("interest") or 0)
        return 0.0


class BybitRealVenue(_GatedPos):
    """bybit 永续读+门控下单(v5 HMAC-SHA256)。GET 签 ts+key+recv+query;POST 签 ts+key+recv+body。"""

    def __init__(self, key="", secret="", armed=None, arm_symbols=None):
        self.key = key or os.environ.get("BYBIT_KEY", "")
        self.secret = secret or os.environ.get("BYBIT_SECRET", "")
        self.armed, self.arm_symbols = _env_armed(armed, arm_symbols)

    @staticmethod
    def _coid(cid):
        return _det_coid(cid, 36)

    async def _get_signed(self, path, qs):
        ts = str(int(time.time() * 1000)); recv = "5000"
        sign = hmac.new(self.secret.encode(), (ts + self.key + recv + qs).encode(), hashlib.sha256).hexdigest()
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(f"https://api.bybit.com{path}?{qs}",
                              headers={"X-BAPI-API-KEY": self.key, "X-BAPI-TIMESTAMP": ts,
                                       "X-BAPI-RECV-WINDOW": recv, "X-BAPI-SIGN": sign})
        return r.json()

    async def query(self, cid, leg=None):
        """按 orderLinkId 查单 → exec_core dict。⚠️市价单成交后 realtime 可能查不到(挪 history),
        必须兜底查 order/history,否则误判 NOTFOUND → 重下单=双仓。"""
        qs = f"category=linear&orderLinkId={self._coid(cid)}"
        try:
            d = await self._get_signed("/v5/order/realtime", qs)
            lst = (d.get("result", {}) or {}).get("list") or []
            if not lst:
                d = await self._get_signed("/v5/order/history", qs)
                lst = (d.get("result", {}) or {}).get("list") or []
        except Exception:  # noqa: BLE001
            return {"status": TIMEOUT, "filled": 0}
        if not lst:
            return {"status": NOTFOUND, "filled": 0}
        st = lst[0].get("orderStatus", "")
        m = {"Filled": FILLED, "New": ACK, "PartiallyFilled": PARTIAL,
             "Created": ACK, "Untriggered": ACK}.get(st, NOTFOUND)
        return {"status": m, "filled": float(lst[0].get("cumExecQty") or 0)}

    async def place(self, cid, leg):
        """市价单(v5)。硬门控。side Buy/Sell;reduceOnly 平仓。orderLinkId=确定性 cid(交易所端幂等)。"""
        sym = leg.get("symbol", "")
        self._gate(cid, sym)
        side = "Buy" if str(leg["side"]).upper() == "BUY" else "Sell"
        body = {"category": "linear", "symbol": sym, "side": side, "orderType": "Market",
                "qty": _qstr(leg["qty"]), "orderLinkId": self._coid(cid)}
        if leg.get("reduce_only"):
            body["reduceOnly"] = True
        bj = json.dumps(body)
        ts = str(int(time.time() * 1000)); recv = "5000"
        sign = hmac.new(self.secret.encode(), (ts + self.key + recv + bj).encode(), hashlib.sha256).hexdigest()
        try:
            async with httpx.AsyncClient(timeout=15) as cli:
                r = await cli.post("https://api.bybit.com/v5/order/create", content=bj,
                                   headers={"X-BAPI-API-KEY": self.key, "X-BAPI-TIMESTAMP": ts,
                                            "X-BAPI-RECV-WINDOW": recv, "X-BAPI-SIGN": sign,
                                            "Content-Type": "application/json"})
            d = r.json()
        except Exception as e:  # noqa: BLE001
            return {"status": TIMEOUT, "filled": 0, "err": repr(e)[:120]}
        if d.get("retCode") != 0:
            return {"status": REJECT, "filled": 0, "err": f"{d.get('retCode')}: {d.get('retMsg')}"}
        return {"status": ACK, "filled": 0, "venue_order_id": (d.get("result") or {}).get("orderId", "")}

    async def all_positions(self) -> dict:
        ts = str(int(time.time() * 1000)); recv = "5000"
        qs = "category=linear&settleCoin=USDT"
        sign = hmac.new(self.secret.encode(), (ts + self.key + recv + qs).encode(), hashlib.sha256).hexdigest()
        try:
            async with httpx.AsyncClient(timeout=15) as cli:
                r = await cli.get(f"https://api.bybit.com/v5/position/list?{qs}",
                                  headers={"X-BAPI-API-KEY": self.key, "X-BAPI-TIMESTAMP": ts,
                                           "X-BAPI-RECV-WINDOW": recv, "X-BAPI-SIGN": sign})
            d = r.json()
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "err": repr(e)[:120]}
        if d.get("retCode") != 0:
            return {"ok": False, "err": f"{d.get('retCode')}: {d.get('retMsg')}"}
        out = {}
        for p in (d.get("result", {}).get("list") or []):
            sz = float(p.get("size") or 0)
            if sz > 1e-12:
                out[p["symbol"]] = sz if p.get("side") == "Buy" else -sz
        return {"ok": True, "positions": out}


class GateRealVenue(_GatedPos):
    """gate USDT 永续读+门控下单(v4 签名:HMAC-SHA512 五段)。size 单位=张(带符号),×乘数=base。
    符号=BASE_USDT;text=t-前缀确定性客户单号(30分钟内可按 text 查单)。"""

    def __init__(self, key="", secret="", armed=None, arm_symbols=None):
        self.key = key or os.environ.get("GATE_KEY", "")
        self.secret = secret or os.environ.get("GATE_SECRET", "")
        self.armed, self.arm_symbols = _env_armed(armed, arm_symbols)
        self._mult = None

    def _sign(self, method, path, query="", body=b""):
        ts = str(int(time.time()))
        body_hash = hashlib.sha512(body).hexdigest()
        s = f"{method}\n{path}\n{query}\n{body_hash}\n{ts}"
        sign = hmac.new(self.secret.encode(), s.encode(), hashlib.sha512).hexdigest()
        h = {"KEY": self.key, "Timestamp": ts, "SIGN": sign, "Accept": "application/json"}
        if body:
            h["Content-Type"] = "application/json"
        return h

    @staticmethod
    def _coid(cid):
        # gate text:须 t- 前缀,字符 [0-9a-zA-Z_.-],总长≤30(截断安全哈希尾,真金课)
        return _det_coid(cid, 30, "t-")

    async def mult_of(self, symbol_gate: str) -> float:
        async with httpx.AsyncClient(timeout=15) as cli:
            return (await self._mults(cli)).get(symbol_gate, 1) or 1

    async def query(self, cid, leg=None):
        """GET /futures/usdt/orders/{text}(30分钟内支持按 t- text 查)。filled 单位=base。"""
        coid = self._coid(cid)
        path = f"/api/v4/futures/usdt/orders/{coid}"
        try:
            async with httpx.AsyncClient(timeout=15) as cli:
                r = await cli.get(f"https://api.gateio.ws{path}", headers=self._sign("GET", path))
                if r.status_code == 404:
                    return {"status": NOTFOUND, "filled": 0}
                d = r.json()
                mult = (await self._mults(cli)).get(d.get("contract", ""), 1) or 1
        except Exception:  # noqa: BLE001
            return {"status": TIMEOUT, "filled": 0}
        if not isinstance(d, dict) or "status" not in d:
            return {"status": NOTFOUND, "filled": 0}
        size = abs(float(d.get("size") or 0)); left = abs(float(d.get("left") or 0))
        filled = (size - left) * mult
        if d["status"] == "open":
            return {"status": ACK if filled <= 1e-12 else PARTIAL, "filled": filled}
        # finished:ioc 市价单可能零成交(finish_as=ioc/cancelled)→ NOTFOUND(可安全重下)
        if filled <= 1e-12:
            return {"status": NOTFOUND, "filled": 0}
        return {"status": FILLED if left <= 1e-12 else PARTIAL, "filled": filled}

    async def place(self, cid, leg):
        """市价单(price=0,tif=ioc)。leg.qty 单位=base → 换算张(带符号:BUY+ SELL-)。硬门控。"""
        sym = leg.get("symbol", "")
        self._gate(cid, sym)
        async with httpx.AsyncClient(timeout=15) as cli:
            mult = (await self._mults(cli)).get(sym, 0) or 0
        if mult <= 0:
            return {"status": REJECT, "filled": 0, "err": f"{sym} 无 quanto_multiplier(合约不存在?)"}
        n = int(round(float(leg["qty"]) / mult))
        if n <= 0:
            return {"status": REJECT, "filled": 0, "err": f"qty {leg['qty']} 不足 1 张(乘数={mult})"}
        size = n if str(leg["side"]).upper() == "BUY" else -n
        body = {"contract": sym, "size": size, "price": "0", "tif": "ioc", "text": self._coid(cid)}
        if leg.get("reduce_only"):
            body["reduce_only"] = True
        bj = json.dumps(body).encode()
        path = "/api/v4/futures/usdt/orders"
        try:
            async with httpx.AsyncClient(timeout=15) as cli:
                r = await cli.post(f"https://api.gateio.ws{path}", content=bj,
                                   headers=self._sign("POST", path, body=bj))
            d = r.json()
        except Exception as e:  # noqa: BLE001
            return {"status": TIMEOUT, "filled": 0, "err": repr(e)[:120]}
        if r.status_code not in (200, 201) or not isinstance(d, dict) or d.get("label"):
            return {"status": REJECT, "filled": 0, "err": f"http {r.status_code}: {str(d)[:150]}"}
        left = abs(float(d.get("left") or 0)); filled = (abs(float(d.get("size") or 0)) - left) * mult
        if d.get("status") == "finished" and left <= 1e-12 and filled > 0:
            return {"status": FILLED, "filled": filled, "venue_order_id": str(d.get("id") or "")}
        return {"status": ACK, "filled": filled, "venue_order_id": str(d.get("id") or "")}

    async def _mults(self, cli):
        if self._mult is None:
            self._mult = {}
            try:
                d = (await cli.get("https://api.gateio.ws/api/v4/futures/usdt/contracts", timeout=15)).json()
                for c in d:
                    self._mult[c["name"]] = float(c.get("quanto_multiplier") or 1) or 1
            except Exception:  # noqa: BLE001
                pass
        return self._mult

    async def all_positions(self) -> dict:
        path = "/api/v4/futures/usdt/positions"
        try:
            async with httpx.AsyncClient(timeout=15) as cli:
                r = await cli.get(f"https://api.gateio.ws{path}", headers=self._sign("GET", path))
                d = r.json()
                if not isinstance(d, list):
                    return {"ok": False, "err": f"{str(d)[:120]}"}
                mult = await self._mults(cli)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "err": repr(e)[:120]}
        out = {}
        for p in d:
            sz = float(p.get("size") or 0)   # 已带符号(+多/-空),单位=张
            if abs(sz) > 1e-12:
                contract = p.get("contract")
                out[contract] = sz * mult.get(contract, 1)   # 转 base
        return {"ok": True, "positions": out}


class BitgetRealVenue(_GatedPos):
    """bitget USDT 永续读+门控下单(base64(HMAC-SHA256(ts+method+path+body)))。size 单位=base。"""

    def __init__(self, key="", secret="", passphrase="", armed=None, arm_symbols=None):
        self.key = key or os.environ.get("BITGET_KEY", "")
        self.secret = secret or os.environ.get("BITGET_SECRET", "")
        self.passphrase = passphrase or os.environ.get("BITGET_PASSPHRASE", "")
        self.armed, self.arm_symbols = _env_armed(armed, arm_symbols)

    def _hdr(self, ts, sign):
        return {"ACCESS-KEY": self.key, "ACCESS-SIGN": sign, "ACCESS-TIMESTAMP": ts,
                "ACCESS-PASSPHRASE": self.passphrase, "locale": "en-US",
                "Content-Type": "application/json"}

    @staticmethod
    def _coid(cid):
        return _det_coid(cid, 60)

    async def query(self, cid, leg=None):
        """GET /api/v2/mix/order/detail?clientOid=。无此单(40109等)=NOTFOUND。filled=baseVolume。"""
        sym = (leg or {}).get("symbol", "")
        ts = str(int(time.time() * 1000))
        path = "/api/v2/mix/order/detail"
        query = f"symbol={sym}&productType=USDT-FUTURES&clientOid={self._coid(cid)}"
        prehash = ts + "GET" + path + "?" + query
        sign = base64.b64encode(hmac.new(self.secret.encode(), prehash.encode(), hashlib.sha256).digest()).decode()
        try:
            async with httpx.AsyncClient(timeout=15) as cli:
                r = await cli.get(f"https://api.bitget.com{path}?{query}", headers=self._hdr(ts, sign))
            d = r.json()
        except Exception:  # noqa: BLE001
            return {"status": TIMEOUT, "filled": 0}
        if str(d.get("code")) != "00000" or not d.get("data"):
            return {"status": NOTFOUND, "filled": 0}
        o = d["data"]
        filled = float(o.get("baseVolume") or 0)
        st = str(o.get("state") or o.get("status") or "")
        m = {"filled": FILLED, "live": ACK, "new": ACK, "partially_filled": PARTIAL}.get(st)
        if m is None:
            m = PARTIAL if filled > 1e-12 else NOTFOUND   # canceled 半成交如实报
        return {"status": m, "filled": filled}

    async def place(self, cid, leg):
        """市价单(v2 place-order,单向持仓 crossed)。size 单位=base。硬门控。clientOid 幂等。"""
        sym = leg.get("symbol", "")
        self._gate(cid, sym)
        body = {"symbol": sym, "productType": "USDT-FUTURES", "marginMode": "crossed",
                "marginCoin": "USDT", "size": _qstr(leg["qty"]),
                "side": "buy" if str(leg["side"]).upper() == "BUY" else "sell",
                "orderType": "market", "clientOid": self._coid(cid)}
        if leg.get("reduce_only"):
            body["reduceOnly"] = "YES"
        bj = json.dumps(body)
        ts = str(int(time.time() * 1000))
        path = "/api/v2/mix/order/place-order"
        prehash = ts + "POST" + path + bj
        sign = base64.b64encode(hmac.new(self.secret.encode(), prehash.encode(), hashlib.sha256).digest()).decode()
        try:
            async with httpx.AsyncClient(timeout=15) as cli:
                r = await cli.post(f"https://api.bitget.com{path}", content=bj, headers=self._hdr(ts, sign))
            d = r.json()
        except Exception as e:  # noqa: BLE001
            return {"status": TIMEOUT, "filled": 0, "err": repr(e)[:120]}
        if str(d.get("code")) != "00000":
            return {"status": REJECT, "filled": 0, "err": f"{d.get('code')}: {d.get('msg')}"}
        return {"status": ACK, "filled": 0, "venue_order_id": str((d.get("data") or {}).get("orderId") or "")}

    async def all_positions(self) -> dict:
        ts = str(int(time.time() * 1000))
        path = "/api/v2/mix/position/all-position"
        query = "productType=USDT-FUTURES&marginCoin=USDT"
        prehash = ts + "GET" + path + "?" + query
        sign = base64.b64encode(hmac.new(self.secret.encode(), prehash.encode(), hashlib.sha256).digest()).decode()
        try:
            async with httpx.AsyncClient(timeout=15) as cli:
                r = await cli.get(f"https://api.bitget.com{path}?{query}", headers=self._hdr(ts, sign))
            d = r.json()
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "err": repr(e)[:120]}
        if str(d.get("code")) != "00000":
            return {"ok": False, "err": f"{d.get('code')}: {d.get('msg')}"}
        out = {}
        for p in (d.get("data") or []):
            tot = float(p.get("total") or 0)
            if tot > 1e-12:
                out[p["symbol"]] = tot if p.get("holdSide") == "long" else -tot
        return {"ok": True, "positions": out}


def venue_for(name: str):
    return {"binance": BinanceRealVenue, "bybit": BybitRealVenue, "gate": GateRealVenue,
            "bitget": BitgetRealVenue, "okx": OkxRealVenue,
            "hyperliquid": HyperliquidRealVenue,
            "binance-margin": BinanceMarginRealVenue}.get(name, lambda: None)()


class OkxRealVenue(_GatedPos):
    """okx 永续读+门控下单(base64(HMAC-SHA256(ts+method+path+body)))。sz 单位=张(×ctVal=base);
    符号 BASE-USDT-SWAP;clOrdId 只允许字母数字→sha1 归一(place/query 逐字节一致)。"""

    def __init__(self, key="", secret="", passphrase="", armed=None, arm_symbols=None):
        self.key = key or os.environ.get("OKX_KEY", "")
        self.secret = secret or os.environ.get("OKX_SECRET", "")
        self.passphrase = passphrase or os.environ.get("OKX_PASSPHRASE", "")
        self.armed, self.arm_symbols = _env_armed(armed, arm_symbols)
        self._ctval = None
        self._lot = {}

    def _hdr(self, method, path, body=""):
        ts = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
        sig = base64.b64encode(hmac.new(self.secret.encode(), (ts + method + path + body).encode(),
                                        hashlib.sha256).digest()).decode()
        h = {"OK-ACCESS-KEY": self.key, "OK-ACCESS-SIGN": sig,
             "OK-ACCESS-TIMESTAMP": ts, "OK-ACCESS-PASSPHRASE": self.passphrase}
        if body:
            h["Content-Type"] = "application/json"
        return h

    async def _ctvals(self, cli):
        if self._ctval is None:
            self._ctval = {}
            try:
                d = (await cli.get("https://www.okx.com/api/v5/public/instruments?instType=SWAP", timeout=15)).json()
                for c in d.get("data", []):
                    self._ctval[c["instId"]] = float(c.get("ctVal") or 1) or 1
                    self._lot[c["instId"]] = float(c.get("lotSz") or 1) or 1
            except Exception:  # noqa: BLE001
                pass
        return self._ctval

    @staticmethod
    def _coid(cid):
        return "m" + hashlib.sha1(cid.encode()).hexdigest()[:30]

    async def query(self, cid, leg=None):
        """GET /api/v5/trade/order?instId&clOrdId(覆盖 live+近7天成交)。filled=accFillSz×ctVal。"""
        inst = (leg or {}).get("symbol", "")
        path = f"/api/v5/trade/order?instId={inst}&clOrdId={self._coid(cid)}"
        try:
            async with httpx.AsyncClient(timeout=15) as cli:
                r = await cli.get("https://www.okx.com" + path, headers=self._hdr("GET", path))
                d = r.json()
                ctv = (await self._ctvals(cli)).get(inst, 1)
        except Exception:  # noqa: BLE001
            return {"status": TIMEOUT, "filled": 0}
        if d.get("code") != "0" or not d.get("data"):
            return {"status": NOTFOUND, "filled": 0}   # 51603 无此单 = 未下到
        o = d["data"][0]
        filled = float(o.get("accFillSz") or 0) * ctv
        st = o.get("state", "")
        m = {"filled": FILLED, "live": ACK, "partially_filled": PARTIAL}.get(st)
        if m is None:
            m = PARTIAL if filled > 1e-12 else NOTFOUND   # canceled 半成交如实报
        return {"status": m, "filled": filled}

    async def place(self, cid, leg):
        """市价单(tdMode=cross)。leg.qty=base → sz 张(÷ctVal,落到 lotSz 步长)。硬门控。"""
        inst = leg.get("symbol", "")
        self._gate(cid, inst)
        async with httpx.AsyncClient(timeout=15) as cli:
            ctv = (await self._ctvals(cli)).get(inst, 0)
        lot = self._lot.get(inst, 1) or 1
        if not ctv:
            return {"status": REJECT, "filled": 0, "err": f"{inst} 无 ctVal(合约不存在?)"}
        sz = math.floor(float(leg["qty"]) / ctv / lot) * lot
        if sz <= 0:
            return {"status": REJECT, "filled": 0, "err": f"qty {leg['qty']} 不足最小张数(ctVal={ctv},lotSz={lot})"}
        body = {"instId": inst, "tdMode": "cross", "side": "buy" if str(leg["side"]).upper() == "BUY" else "sell",
                "ordType": "market", "sz": f"{sz:.8f}".rstrip("0").rstrip("."), "clOrdId": self._coid(cid)}
        if leg.get("reduce_only"):
            body["reduceOnly"] = True
        bj = json.dumps(body)
        path = "/api/v5/trade/order"
        try:
            async with httpx.AsyncClient(timeout=15) as cli:
                r = await cli.post("https://www.okx.com" + path, content=bj,
                                   headers=self._hdr("POST", path, bj))
            d = r.json()
        except Exception as e:  # noqa: BLE001
            return {"status": TIMEOUT, "filled": 0, "err": repr(e)[:120]}
        data0 = (d.get("data") or [{}])[0]
        if d.get("code") != "0" or str(data0.get("sCode", "0")) not in ("0",):
            return {"status": REJECT, "filled": 0,
                    "err": f"{d.get('code')}/{data0.get('sCode')}: {data0.get('sMsg') or d.get('msg')}"}
        return {"status": ACK, "filled": 0, "venue_order_id": str(data0.get("ordId") or "")}

    async def all_positions(self) -> dict:
        path = "/api/v5/account/positions?instType=SWAP"
        try:
            async with httpx.AsyncClient(timeout=15) as cli:
                r = await cli.get("https://www.okx.com" + path, headers=self._hdr("GET", path))
                d = r.json()
                if d.get("code") != "0":
                    return {"ok": False, "err": f"{d.get('code')}: {d.get('msg')}"}
                ctv = await self._ctvals(cli)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "err": repr(e)[:120]}
        out = {}
        for p in d.get("data", []):
            pos = float(p.get("pos") or 0)   # 已带符号(多+空-);单位=张
            if abs(pos) > 1e-12:
                out[p["instId"]] = pos * ctv.get(p["instId"], 1)   # 转 base
        return {"ok": True, "positions": out}


class HyperliquidRealVenue(_GatedPos):
    """HL 永续读+门控下单。读=clearinghouseState(只读钱包地址无签名);
    写=hyperliquid-python-sdk(agent 钱包签名,agent 只能交易不能提现,approveAgent 已授权)。
    szi/sz=base 带符号;符号=币名;cloid=128bit 确定性(md5(cid))。SDK 同步→to_thread。
    ⚠️HL 最小单 $10 名义;市价单=IOC+滑点保护价(SDK market_open/close 封装)。"""

    HL_AGENT_ENV = "/home/ec2-user/dexcexmix/.hl_agent.env"

    def __init__(self, address="", agent_key="", armed=None, arm_symbols=None):
        self.address = address or os.environ.get("HL_WALLET_ADDRESS", "")
        self._agent_key = agent_key or os.environ.get("HL_AGENT_PRIVKEY", "")
        self.armed, self.arm_symbols = _env_armed(armed, arm_symbols)
        self._ex = None       # lazy Exchange(签名端)
        self._info = None     # lazy Info(查询端)
        self._szdec = None    # coin -> szDecimals

    def _load_agent_key(self):
        if not self._agent_key and os.path.exists(self.HL_AGENT_ENV):
            for ln in open(self.HL_AGENT_ENV, encoding="utf-8"):
                if ln.strip().startswith("HL_AGENT_PRIVKEY="):
                    self._agent_key = ln.strip().split("=", 1)[1]
        if not self._agent_key:
            raise VenueError("HL agent 私钥缺失(.hl_agent.env)")

    def _exchange(self):
        if self._ex is None:
            self._load_agent_key()
            from eth_account import Account
            from hyperliquid.exchange import Exchange
            self._ex = Exchange(Account.from_key(self._agent_key),
                                account_address=self.address)
        return self._ex

    def _info_cli(self):
        if self._info is None:
            from hyperliquid.info import Info
            self._info = Info(skip_ws=True)
        return self._info

    def _szdecs(self):
        if self._szdec is None:
            self._szdec = {}
            try:
                m = self._info_cli().meta()
                for u in m.get("universe", []):
                    self._szdec[u["name"]] = int(u.get("szDecimals") or 0)
            except Exception:  # noqa: BLE001
                pass
        return self._szdec

    @staticmethod
    def _coid(cid):
        return "0x" + hashlib.md5(cid.encode()).hexdigest()   # 128bit,截断安全(哈希本体)

    async def query(self, cid, leg=None):
        """orderStatus by cloid → exec_core dict。unknownOid=NOTFOUND(可安全重下)。"""
        def _q():
            from hyperliquid.utils.types import Cloid
            return self._info_cli().query_order_by_cloid(self.address, Cloid.from_str(self._coid(cid)))
        try:
            d = await asyncio.to_thread(_q)
        except Exception:  # noqa: BLE001
            return {"status": TIMEOUT, "filled": 0}
        if not isinstance(d, dict) or d.get("status") != "order":
            return {"status": NOTFOUND, "filled": 0}
        o = d.get("order") or {}
        st = str(o.get("status") or "")
        od = o.get("order") or {}
        orig = float(od.get("origSz") or 0)
        rest = float(od.get("sz") or 0)     # 剩余量
        filled = max(0.0, orig - rest)
        if st == "filled":
            return {"status": FILLED, "filled": orig}
        if st == "open":
            return {"status": ACK if filled <= 1e-12 else PARTIAL, "filled": filled}
        # canceled/rejected/marginCanceled:半成交如实报,零成交=NOTFOUND
        return {"status": PARTIAL if filled > 1e-12 else NOTFOUND, "filled": filled}

    async def place(self, cid, leg):
        """市价单(SDK market_open;reduce_only→market_close)。leg.qty=base;硬门控。"""
        coin = leg.get("symbol", "")
        self._gate(cid, coin)
        dec = self._szdecs().get(coin)
        if dec is None:
            return {"status": REJECT, "filled": 0, "err": f"HL 无 {coin} 合约(meta 查无)"}
        sz = math.floor(float(leg["qty"]) * (10 ** dec)) / (10 ** dec)
        if sz <= 0:
            return {"status": REJECT, "filled": 0, "err": f"qty {leg['qty']} 落 szDecimals={dec} 后为 0"}
        is_buy = str(leg["side"]).upper() == "BUY"

        def _p():
            from hyperliquid.utils.types import Cloid
            cl = Cloid.from_str(self._coid(cid))
            ex = self._exchange()
            if leg.get("reduce_only"):
                # market_close 按仓位反向平 sz(内部 reduce-only IOC)
                return ex.market_close(coin, sz=sz, cloid=cl)
            return ex.market_open(coin, is_buy, sz, cloid=cl)
        try:
            d = await asyncio.to_thread(_p)
        except Exception as e:  # noqa: BLE001
            return {"status": TIMEOUT, "filled": 0, "err": repr(e)[:120]}
        if not isinstance(d, dict) or d.get("status") != "ok":
            return {"status": REJECT, "filled": 0, "err": str(d)[:150]}
        sts = (((d.get("response") or {}).get("data") or {}).get("statuses") or [{}])
        s0 = sts[0]
        if "error" in s0:
            return {"status": REJECT, "filled": 0, "err": str(s0["error"])[:150]}
        if "filled" in s0:
            f = s0["filled"]
            return {"status": FILLED, "filled": float(f.get("totalSz") or 0),
                    "venue_order_id": str(f.get("oid") or "")}
        if "resting" in s0:
            return {"status": ACK, "filled": 0, "venue_order_id": str(s0["resting"].get("oid") or "")}
        return {"status": ACK, "filled": 0}

    async def all_positions(self) -> dict:
        if not self.address:
            return {"ok": False, "err": "HL_WALLET_ADDRESS 未设"}
        try:
            async with httpx.AsyncClient(timeout=15) as cli:
                r = await cli.post("https://api.hyperliquid.xyz/info",
                                   json={"type": "clearinghouseState", "user": self.address})
            d = r.json()
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "err": repr(e)[:120]}
        out = {}
        for ap in (d.get("assetPositions") or []):
            pos = ap.get("position") or {}
            szi = float(pos.get("szi") or 0)
            if abs(szi) > 1e-12:
                out[pos.get("coin")] = szi
        return {"ok": True, "positions": out}


def venue_armed(name: str, armed: bool, arm_symbols):
    """带武装门控构造适配器(manager/canary 按 pair 精细控制)。六所全支持写路径;
    binance-margin=C3 借币短腿(§6.1 BORROW_SPOT_SHORT_DERIVATIVE_LONG)。"""
    cls = {"binance": BinanceRealVenue, "bybit": BybitRealVenue, "gate": GateRealVenue,
           "bitget": BitgetRealVenue, "okx": OkxRealVenue,
           "hyperliquid": HyperliquidRealVenue,
           "binance-margin": BinanceMarginRealVenue}.get(name)
    if cls is None:
        raise VenueError(f"{name} 无可武装适配器")
    return cls(armed=armed, arm_symbols=arm_symbols)


class MultiVenue:
    """多所分派器:exec_core 跨所驱动——按 leg['venue'] 路由 place/query 到对应适配器。
    C2 跨所对(gate 多 / bybit 空 等)用它,exec_core 无感。leg 必须带 venue 字段。"""

    def __init__(self, venues: dict):
        self.venues = venues   # {venue_name: adapter}

    def _pick(self, leg):
        v = self.venues.get((leg or {}).get("venue"))
        if v is None:
            raise VenueError(f"无 {(leg or {}).get('venue')} 适配器")
        return v

    async def place(self, cid, leg):
        return await self._pick(leg).place(cid, leg)

    async def query(self, cid, leg=None):
        return await self._pick(leg).query(cid, leg)

    async def cancel(self, cid, leg=None):
        v = self._pick(leg)
        if hasattr(v, "cancel"):
            return await v.cancel(cid)

    async def get_position(self, venue: str, symbol: str) -> dict:
        v = self.venues.get(venue)
        if v is None:
            return {"ok": False, "err": f"无 {venue} 适配器"}
        return await v.get_position(symbol)
