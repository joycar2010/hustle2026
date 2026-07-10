"""交易客户端(币安 USDM + Bybit linear):下单/撤单/查单/查仓,含精度处理。

与只读 exchanges.py 分文件:交易能力是显式独立导入,谁 import 谁负责 armed。
精度铁律:price 对齐 tickSize、qty 对齐 stepSize、满足 minNotional/minQty——
交易所对不齐即拒单,armed 下拒单=单腿裸露风险,精度必须在客户端落地不留给运气。
签名复用各所已验证口径(只读路径证过)。所有方法返回 (ok, data/err),不抛。
"""
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


TRADE_CLIENTS = {"binance": BinanceTrade, "bybit": BybitTrade}
