"""交易客户端(币安 USDM + Bybit linear):下单/撤单/查单/查仓,含精度处理。

与只读 exchanges.py 分文件:交易能力是显式独立导入,谁 import 谁负责 armed。
精度铁律:price 对齐 tickSize、qty 对齐 stepSize、满足 minNotional/minQty——
交易所对不齐即拒单,armed 下拒单=单腿裸露风险,精度必须在客户端落地不留给运气。
签名复用各所已验证口径(只读路径证过)。所有方法返回 (ok, data/err),不抛。
"""
import base64
import hashlib
import hmac
import json
import time
from decimal import ROUND_DOWN, Decimal

import httpx


def _round_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def _fmt(d: Decimal) -> str:
    return format(d.normalize(), "f")


def _dget(d, *keys, default="0"):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d[k]
    return default


class BinanceTrade:
    def __init__(self, cfg: dict):
        self.key, self.secret = cfg["key"], cfg["secret"]
        self.base = "https://fapi.binance.com"
        self.tick: dict[str, Decimal] = {}
        self.step: dict[str, Decimal] = {}
        self.min_notional: dict[str, Decimal] = {}

    def _signed_qs(self, params: dict) -> str:
        params = {**params, "timestamp": int(time.time() * 1000), "recvWindow": 5000}
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        sig = hmac.new(self.secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
        return f"{qs}&signature={sig}"

    @property
    def _hdr(self):
        return {"X-MBX-APIKEY": self.key}

    async def load_filter(self, cli: httpx.AsyncClient, symbol: str):
        d = (await cli.get(f"{self.base}/fapi/v1/exchangeInfo?symbol={symbol}")).json()
        for s in d.get("symbols", []):
            if s["symbol"] != symbol:
                continue
            for f in s["filters"]:
                if f["filterType"] == "PRICE_FILTER":
                    self.tick[symbol] = Decimal(f["tickSize"])
                elif f["filterType"] == "LOT_SIZE":
                    self.step[symbol] = Decimal(f["stepSize"])
                elif f["filterType"] in ("MIN_NOTIONAL", "NOTIONAL"):
                    self.min_notional[symbol] = Decimal(f.get("notional") or f.get("minNotional") or "5")

    async def place_limit(self, cli, symbol, side, qty: Decimal, price: Decimal, reduce_only=False):
        price = _round_step(price, self.tick.get(symbol, Decimal("0.0001")))
        qty = _round_step(qty, self.step.get(symbol, Decimal("0.001")))
        params = {"symbol": symbol, "side": side, "type": "LIMIT", "timeInForce": "GTC",
                  "quantity": _fmt(qty), "price": _fmt(price)}
        if reduce_only:
            params["reduceOnly"] = "true"
        r = (await cli.post(f"{self.base}/fapi/v1/order?{self._signed_qs(params)}", headers=self._hdr)).json()
        if r.get("orderId"):
            return True, {"order_id": str(r["orderId"]), "status": r.get("status"), "raw": r}
        return False, {"err": f"{r.get('code')}:{r.get('msg')}", "raw": r}

    async def fetch_order(self, cli, symbol, order_id, retries=4):
        # 读后写一致性:币安下单后订单查询端点可能短暂 -2013(未落库),重试而非误判失败
        # (armed 铁律:HTTP 结果不确定时靠查询定论,查询本身要抗延迟)
        import asyncio
        for i in range(retries):
            r = (await cli.get(f"{self.base}/fapi/v1/order?{self._signed_qs({'symbol': symbol, 'orderId': order_id})}",
                               headers=self._hdr)).json()
            if r.get("orderId"):
                return True, {"status": r.get("status"), "filled": r.get("executedQty"),
                              "avg": r.get("avgPrice"), "raw": r}
            if r.get("code") == -2013 and i < retries - 1:
                await asyncio.sleep(0.5 * (i + 1))
                continue
            return False, {"err": f"{r.get('code')}:{r.get('msg')}", "raw": r}

    async def cancel(self, cli, symbol, order_id):
        r = (await cli.request("DELETE",
             f"{self.base}/fapi/v1/order?{self._signed_qs({'symbol': symbol, 'orderId': order_id})}",
             headers=self._hdr)).json()
        if r.get("orderId"):
            return True, {"status": r.get("status"), "raw": r}
        return False, {"err": f"{r.get('code')}:{r.get('msg')}", "raw": r}

    async def fetch_position(self, cli, symbol) -> Decimal:
        """净持仓 base(带方向,多+空-)。实盘真相源,对账/回滚用。"""
        r = (await cli.get(f"{self.base}/fapi/v2/positionRisk?{self._signed_qs({'symbol': symbol})}",
                           headers=self._hdr)).json()
        if isinstance(r, list):
            return sum(Decimal(str(p.get("positionAmt") or 0)) for p in r)
        raise RuntimeError(f"binance positionRisk: {r}")


class BybitTrade:
    def __init__(self, cfg: dict):
        self.key, self.secret = cfg["key"], cfg["secret"]
        self.base = "https://api.bybit.com"
        self.recv = "5000"
        self.tick: dict[str, Decimal] = {}
        self.step: dict[str, Decimal] = {}
        self.min_qty: dict[str, Decimal] = {}

    def _headers(self, ts: str, payload: str) -> dict:
        pre = ts + self.key + self.recv + payload
        sign = hmac.new(self.secret.encode(), pre.encode(), hashlib.sha256).hexdigest()
        return {"X-BAPI-API-KEY": self.key, "X-BAPI-TIMESTAMP": ts,
                "X-BAPI-RECV-WINDOW": self.recv, "X-BAPI-SIGN": sign,
                "Content-Type": "application/json"}

    async def load_filter(self, cli, symbol):
        d = (await cli.get(f"{self.base}/v5/market/instruments-info?category=linear&symbol={symbol}")).json()
        for it in d.get("result", {}).get("list", []):
            if it["symbol"] != symbol:
                continue
            self.tick[symbol] = Decimal(it["priceFilter"]["tickSize"])
            self.step[symbol] = Decimal(it["lotSizeFilter"]["qtyStep"])
            self.min_qty[symbol] = Decimal(it["lotSizeFilter"]["minOrderQty"])

    async def _get(self, cli, path, query):
        ts = str(int(time.time() * 1000))
        url = f"{self.base}{path}?{query}"
        return (await cli.get(url, headers=self._headers(ts, query))).json()

    async def _post(self, cli, path, body: dict):
        ts = str(int(time.time() * 1000))
        raw = json.dumps(body)
        return (await cli.post(f"{self.base}{path}", headers=self._headers(ts, raw), content=raw)).json()

    async def place_limit(self, cli, symbol, side, qty: Decimal, price: Decimal, reduce_only=False):
        price = _round_step(price, self.tick.get(symbol, Decimal("0.0001")))
        qty = _round_step(qty, self.step.get(symbol, Decimal("0.001")))
        side = "Buy" if side.upper() == "BUY" else "Sell"  # 统一接受大写,内部转 Bybit 格式
        body = {"category": "linear", "symbol": symbol, "side": side, "orderType": "Limit",
                "qty": _fmt(qty), "price": _fmt(price), "timeInForce": "GTC"}
        if reduce_only:
            body["reduceOnly"] = True
        r = await self._post(cli, "/v5/order/create", body)
        if r.get("retCode") == 0:
            return True, {"order_id": r["result"]["orderId"], "raw": r}
        return False, {"err": f"{r.get('retCode')}:{r.get('retMsg')}", "raw": r}

    async def fetch_order(self, cli, symbol, order_id):
        r = await self._get(cli, "/v5/order/realtime", f"category=linear&symbol={symbol}&orderId={order_id}")
        lst = r.get("result", {}).get("list", [])
        if r.get("retCode") == 0 and lst:
            o = lst[0]
            return True, {"status": o.get("orderStatus"), "filled": o.get("cumExecQty"),
                          "avg": o.get("avgPrice"), "raw": o}
        return False, {"err": f"{r.get('retCode')}:{r.get('retMsg')}", "raw": r}

    async def cancel(self, cli, symbol, order_id):
        r = await self._post(cli, "/v5/order/cancel",
                             {"category": "linear", "symbol": symbol, "orderId": order_id})
        if r.get("retCode") == 0:
            return True, {"raw": r}
        return False, {"err": f"{r.get('retCode')}:{r.get('retMsg')}", "raw": r}

    async def fetch_position(self, cli, symbol) -> Decimal:
        r = await self._get(cli, "/v5/position/list", f"category=linear&symbol={symbol}")
        net = Decimal("0")
        for p in r.get("result", {}).get("list", []):
            size = Decimal(str(p.get("size") or 0))
            net += size if p.get("side") == "Buy" else -size
        return net


class OkxTrade:
    """OKX SWAP:下单 sz=张(base÷ctVal);对执行器统一暴露 base 单位。"""
    def __init__(self, cfg: dict):
        self.key, self.secret, self.passphrase = cfg["key"], cfg["secret"], cfg["passphrase"]
        self.base = "https://www.okx.com"
        self.tick: dict[str, Decimal] = {}
        self.lot: dict[str, Decimal] = {}      # lotSz(张步进)
        self.ctval: dict[str, Decimal] = {}    # 每张=ctVal base
        self.instid: dict[str, str] = {}

    def _hdr(self, ts, method, path, body=""):
        pre = ts + method + path + body
        sign = base64.b64encode(hmac.new(self.secret.encode(), pre.encode(), hashlib.sha256).digest()).decode()
        return {"OK-ACCESS-KEY": self.key, "OK-ACCESS-SIGN": sign, "OK-ACCESS-TIMESTAMP": ts,
                "OK-ACCESS-PASSPHRASE": self.passphrase, "Content-Type": "application/json"}

    @staticmethod
    def _ts():
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + ".000Z"

    def _inst(self, symbol):
        return self.instid.get(symbol) or f"{symbol[:-4]}-USDT-SWAP"

    async def load_filter(self, cli, symbol):
        inst = self._inst(symbol)
        d = (await cli.get(f"{self.base}/api/v5/public/instruments?instType=SWAP&instId={inst}")).json()
        for it in d.get("data", []):
            if it["instId"] == inst:
                self.instid[symbol] = inst
                self.tick[symbol] = Decimal(str(it["tickSz"]))
                self.lot[symbol] = Decimal(str(it["lotSz"]))
                self.ctval[symbol] = Decimal(str(it.get("ctVal") or "1"))

    def _contracts(self, symbol, base_qty: Decimal) -> Decimal:
        ct = base_qty / self.ctval.get(symbol, Decimal("1"))
        return _round_step(ct, self.lot.get(symbol, Decimal("1")))

    async def _post(self, cli, path, body: dict):
        ts, raw = self._ts(), json.dumps(body)
        return (await cli.post(f"{self.base}{path}", headers=self._hdr(ts, "POST", path, raw), content=raw)).json()

    async def _get(self, cli, path):
        ts = self._ts()
        return (await cli.get(f"{self.base}{path}", headers=self._hdr(ts, "GET", path))).json()

    async def place_limit(self, cli, symbol, side, base_qty: Decimal, price: Decimal, reduce_only=False):
        inst = self._inst(symbol)
        px = _round_step(price, self.tick.get(symbol, Decimal("0.0001")))
        sz = self._contracts(symbol, base_qty)
        body = {"instId": inst, "tdMode": "cross", "side": side.lower(), "ordType": "limit",
                "sz": _fmt(sz), "px": _fmt(px)}
        if reduce_only:
            body["reduceOnly"] = "true"
        r = await self._post(cli, "/api/v5/trade/order", body)
        d = (r.get("data") or [{}])[0]
        if r.get("code") == "0" and d.get("ordId"):
            return True, {"order_id": d["ordId"], "raw": r}
        return False, {"err": f"{d.get('sCode') or r.get('code')}:{d.get('sMsg') or r.get('msg')}", "raw": r}

    async def fetch_order(self, cli, symbol, order_id):
        inst = self._inst(symbol)
        r = await self._get(cli, f"/api/v5/trade/order?instId={inst}&ordId={order_id}")
        d = (r.get("data") or [{}])[0]
        if r.get("code") == "0" and d.get("ordId"):
            st = {"live": "NEW", "partially_filled": "PARTIAL", "filled": "FILLED",
                  "canceled": "CANCELED"}.get(d.get("state"), d.get("state"))
            filled_base = Decimal(str(d.get("accFillSz") or 0)) * self.ctval.get(symbol, Decimal("1"))
            return True, {"status": st, "filled": _fmt(filled_base), "avg": d.get("avgPx") or "0", "raw": d}
        return False, {"err": f"{r.get('code')}:{r.get('msg')}", "raw": r}

    async def cancel(self, cli, symbol, order_id):
        r = await self._post(cli, "/api/v5/trade/cancel-order", {"instId": self._inst(symbol), "ordId": order_id})
        if r.get("code") == "0":
            return True, {"raw": r}
        return False, {"err": f"{r.get('code')}:{r.get('msg')}", "raw": r}

    async def fetch_position(self, cli, symbol) -> Decimal:
        inst = self._inst(symbol)
        r = await self._get(cli, f"/api/v5/account/positions?instType=SWAP&instId={inst}")
        net = Decimal("0")
        for p in r.get("data", []):
            net += Decimal(str(p.get("pos") or 0)) * self.ctval.get(symbol, Decimal("1"))  # 张→base
        return net


class GateTrade:
    """Gate USDT 永续:下单 size=张带符号(base÷quanto,+多-空);统一暴露 base。"""
    def __init__(self, cfg: dict):
        self.key, self.secret = cfg["key"], cfg["secret"]
        self.base = "https://api.gateio.ws"
        self.prefix = "/api/v4"
        self.qm: dict[str, Decimal] = {}       # 每张=quanto_multiplier base
        self.tick: dict[str, Decimal] = {}

    def _contract(self, symbol):
        return f"{symbol[:-4]}_USDT"

    def _hdr(self, method, path, query, body):
        ts = str(int(time.time()))
        bh = hashlib.sha512(body.encode()).hexdigest()
        pre = f"{method}\n{self.prefix}{path}\n{query}\n{bh}\n{ts}"
        sign = hmac.new(self.secret.encode(), pre.encode(), hashlib.sha512).hexdigest()
        return {"KEY": self.key, "Timestamp": ts, "SIGN": sign, "Content-Type": "application/json"}

    async def load_filter(self, cli, symbol):
        con = self._contract(symbol)
        d = (await cli.get(f"{self.base}{self.prefix}/futures/usdt/contracts/{con}")).json()
        if isinstance(d, dict):
            self.qm[symbol] = Decimal(str(d.get("quanto_multiplier") or "1")) or Decimal("1")
            self.tick[symbol] = Decimal(str(d.get("order_price_round") or "0.0001"))

    async def place_limit(self, cli, symbol, side, base_qty: Decimal, price: Decimal, reduce_only=False):
        con = self._contract(symbol)
        px = _round_step(price, self.tick.get(symbol, Decimal("0.0001")))
        contracts = int((base_qty / self.qm.get(symbol, Decimal("1"))).to_integral_value(rounding=ROUND_DOWN))
        size = contracts if side.upper() == "BUY" else -contracts  # 带符号
        body = json.dumps({"contract": con, "size": size, "price": _fmt(px), "tif": "gtc",
                           **({"reduce_only": True} if reduce_only else {})})
        path = "/futures/usdt/orders"
        r = (await cli.post(f"{self.base}{self.prefix}{path}",
                            headers=self._hdr("POST", path, "", body), content=body)).json()
        if isinstance(r, dict) and r.get("id"):
            return True, {"order_id": str(r["id"]), "raw": r}
        return False, {"err": str(r.get("label") or r.get("message") or r)[:120], "raw": r}

    async def fetch_order(self, cli, symbol, order_id):
        path = f"/futures/usdt/orders/{order_id}"
        r = (await cli.get(f"{self.base}{self.prefix}{path}", headers=self._hdr("GET", path, "", ""))).json()
        if isinstance(r, dict) and r.get("id"):
            left = Decimal(str(r.get("left") or 0))
            size = Decimal(str(r.get("size") or 0))
            filled_ct = abs(size) - abs(left)
            filled_base = filled_ct * self.qm.get(symbol, Decimal("1"))
            st = "FILLED" if left == 0 and r.get("status") == "finished" else (
                "CANCELED" if r.get("status") == "finished" else "NEW")
            return True, {"status": st, "filled": _fmt(filled_base), "avg": r.get("fill_price") or "0", "raw": r}
        return False, {"err": str(r)[:120], "raw": r}

    async def cancel(self, cli, symbol, order_id):
        path = f"/futures/usdt/orders/{order_id}"
        r = (await cli.request("DELETE", f"{self.base}{self.prefix}{path}",
                               headers=self._hdr("DELETE", path, "", ""))).json()
        if isinstance(r, dict) and r.get("id"):
            return True, {"raw": r}
        return False, {"err": str(r)[:120], "raw": r}

    async def fetch_position(self, cli, symbol) -> Decimal:
        con = self._contract(symbol)
        path = f"/futures/usdt/positions/{con}"
        r = (await cli.get(f"{self.base}{self.prefix}{path}", headers=self._hdr("GET", path, "", ""))).json()
        if isinstance(r, dict):
            return Decimal(str(r.get("size") or 0)) * self.qm.get(symbol, Decimal("1"))  # 张(带符号)→base
        return Decimal("0")


class BitgetTrade:
    """Bitget USDT 永续:下单 size=base 币(与币安同);统一 base。"""
    def __init__(self, cfg: dict):
        self.key, self.secret, self.passphrase = cfg["key"], cfg["secret"], cfg["passphrase"]
        self.base = "https://api.bitget.com"
        self.tick: dict[str, Decimal] = {}
        self.step: dict[str, Decimal] = {}

    def _hdr(self, ts, method, path, query, body):
        pre = ts + method + path + (f"?{query}" if query else "") + body
        sign = base64.b64encode(hmac.new(self.secret.encode(), pre.encode(), hashlib.sha256).digest()).decode()
        return {"ACCESS-KEY": self.key, "ACCESS-SIGN": sign, "ACCESS-TIMESTAMP": ts,
                "ACCESS-PASSPHRASE": self.passphrase, "locale": "en-US", "Content-Type": "application/json"}

    async def load_filter(self, cli, symbol):
        d = (await cli.get(f"{self.base}/api/v2/mix/market/contracts?productType=USDT-FUTURES&symbol={symbol}")).json()
        for c in d.get("data", []) or []:
            if c["symbol"] == symbol:
                self.tick[symbol] = Decimal("1").scaleb(-int(c.get("pricePlace") or 4)) * Decimal(str(c.get("priceEndStep") or 1))
                self.step[symbol] = Decimal("1").scaleb(-int(c.get("volumePlace") or 3))

    async def place_limit(self, cli, symbol, side, base_qty: Decimal, price: Decimal, reduce_only=False):
        px = _round_step(price, self.tick.get(symbol, Decimal("0.0001")))
        sz = _round_step(base_qty, self.step.get(symbol, Decimal("0.001")))
        body = json.dumps({"symbol": symbol, "productType": "USDT-FUTURES", "marginMode": "crossed",
                           "marginCoin": "USDT", "side": side.lower(), "orderType": "limit",
                           "size": _fmt(sz), "price": _fmt(px),
                           **({"reduceOnly": "YES"} if reduce_only else {})})
        path = "/api/v2/mix/order/place-order"
        ts = str(int(time.time() * 1000))
        r = (await cli.post(f"{self.base}{path}", headers=self._hdr(ts, "POST", path, "", body), content=body)).json()
        if r.get("code") == "00000" and r.get("data", {}).get("orderId"):
            return True, {"order_id": r["data"]["orderId"], "raw": r}
        return False, {"err": f"{r.get('code')}:{r.get('msg')}", "raw": r}

    async def fetch_order(self, cli, symbol, order_id):
        query = f"symbol={symbol}&productType=USDT-FUTURES&orderId={order_id}"
        path = "/api/v2/mix/order/detail"
        ts = str(int(time.time() * 1000))
        r = (await cli.get(f"{self.base}{path}?{query}", headers=self._hdr(ts, "GET", path, query, ""))).json()
        d = r.get("data") or {}
        if isinstance(d, list):
            d = d[0] if d else {}
        if r.get("code") == "00000" and d:
            raw_st = d.get("state") or d.get("status")  # bitget v2 用 state
            st = {"live": "NEW", "new": "NEW", "init": "NEW", "partially_filled": "PARTIAL",
                  "filled": "FILLED", "full_fill": "FILLED", "canceled": "CANCELED",
                  "cancelled": "CANCELED"}.get(raw_st, raw_st)
            return True, {"status": st, "filled": d.get("baseVolume") or "0", "avg": d.get("priceAvg") or "0", "raw": d}
        return False, {"err": f"{r.get('code')}:{r.get('msg')}", "raw": r}

    async def cancel(self, cli, symbol, order_id):
        body = json.dumps({"symbol": symbol, "productType": "USDT-FUTURES", "orderId": order_id})
        path = "/api/v2/mix/order/cancel-order"
        ts = str(int(time.time() * 1000))
        r = (await cli.post(f"{self.base}{path}", headers=self._hdr(ts, "POST", path, "", body), content=body)).json()
        if r.get("code") == "00000":
            return True, {"raw": r}
        return False, {"err": f"{r.get('code')}:{r.get('msg')}", "raw": r}

    async def fetch_position(self, cli, symbol) -> Decimal:
        query = f"symbol={symbol}&productType=USDT-FUTURES&marginCoin=USDT"
        path = "/api/v2/mix/position/single-position"
        ts = str(int(time.time() * 1000))
        r = (await cli.get(f"{self.base}{path}?{query}", headers=self._hdr(ts, "GET", path, query, ""))).json()
        net = Decimal("0")
        for p in r.get("data", []) or []:
            size = Decimal(str(p.get("total") or 0))
            net += size if p.get("holdSide") == "long" else -size
        return net


class BinanceSpotTrade:
    """币安现货(api/v3):basis 引擎现货腿。接口形状与 BinanceTrade 一致(place/fetch/cancel)。
    fetch_position 语义=现货 free 余额(现货没有净持仓概念,对账用 base 资产余额)。"""

    def __init__(self, cfg: dict):
        self.key, self.secret = cfg["key"], cfg["secret"]
        self.base = "https://api.binance.com"
        self.tick: dict[str, Decimal] = {}
        self.step: dict[str, Decimal] = {}
        self.min_notional: dict[str, Decimal] = {}

    _signed_qs = BinanceTrade._signed_qs
    _hdr = BinanceTrade._hdr

    async def load_filter(self, cli: httpx.AsyncClient, symbol: str):
        d = (await cli.get(f"{self.base}/api/v3/exchangeInfo?symbol={symbol}")).json()
        for s in d.get("symbols", []):
            if s["symbol"] != symbol:
                continue
            for f in s["filters"]:
                if f["filterType"] == "PRICE_FILTER":
                    self.tick[symbol] = Decimal(f["tickSize"])
                elif f["filterType"] == "LOT_SIZE":
                    self.step[symbol] = Decimal(f["stepSize"])
                elif f["filterType"] in ("MIN_NOTIONAL", "NOTIONAL"):
                    self.min_notional[symbol] = Decimal(f.get("minNotional") or f.get("notional") or "5")

    async def place_limit(self, cli, symbol, side, qty: Decimal, price: Decimal, reduce_only=False):
        # 现货无 reduce_only 概念,参数保留仅为与合约客户端同形
        price = _round_step(price, self.tick.get(symbol, Decimal("0.0001")))
        qty = _round_step(qty, self.step.get(symbol, Decimal("0.001")))
        params = {"symbol": symbol, "side": side, "type": "LIMIT", "timeInForce": "GTC",
                  "quantity": _fmt(qty), "price": _fmt(price)}
        r = (await cli.post(f"{self.base}/api/v3/order?{self._signed_qs(params)}", headers=self._hdr)).json()
        if r.get("orderId"):
            return True, {"order_id": str(r["orderId"]), "status": r.get("status"), "raw": r}
        return False, {"err": f"{r.get('code')}:{r.get('msg')}", "raw": r}

    async def fetch_order(self, cli, symbol, order_id, retries=4):
        import asyncio
        for i in range(retries):
            r = (await cli.get(f"{self.base}/api/v3/order?{self._signed_qs({'symbol': symbol, 'orderId': order_id})}",
                               headers=self._hdr)).json()
            if r.get("orderId"):
                filled = Decimal(str(r.get("executedQty") or 0))
                quote = Decimal(str(r.get("cummulativeQuoteQty") or 0))
                avg = quote / filled if filled > 0 else Decimal("0")
                return True, {"status": r.get("status"), "filled": str(filled), "avg": str(avg), "raw": r}
            if r.get("code") == -2013 and i < retries - 1:
                await asyncio.sleep(0.5 * (i + 1))
                continue
            return False, {"err": f"{r.get('code')}:{r.get('msg')}", "raw": r}

    async def cancel(self, cli, symbol, order_id):
        r = (await cli.request("DELETE",
             f"{self.base}/api/v3/order?{self._signed_qs({'symbol': symbol, 'orderId': order_id})}",
             headers=self._hdr)).json()
        if r.get("orderId") or r.get("status") == "CANCELED":
            return True, {"status": r.get("status"), "raw": r}
        return False, {"err": f"{r.get('code')}:{r.get('msg')}", "raw": r}

    async def fetch_position(self, cli, base_asset) -> Decimal:
        """现货 free 余额(base 资产)。对账真相源。"""
        r = (await cli.get(f"{self.base}/api/v3/account?{self._signed_qs({'omitZeroBalances': 'true'})}",
                           headers=self._hdr)).json()
        for b in r.get("balances", []):
            if b.get("asset") == base_asset:
                return Decimal(str(b.get("free") or 0))
        if "balances" not in r:
            raise RuntimeError(f"binance spot account: {r}")
        return Decimal("0")


TRADE_CLIENTS = {"binance": BinanceTrade, "bybit": BybitTrade,
                 "okx": OkxTrade, "gate": GateTrade, "bitget": BitgetTrade}
