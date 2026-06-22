"""币安 USDⓈ-M 永续【做空腿】执行客户端 —— 自 coin 的 binance_trading.py 拷贝去依赖。

去依赖改造:① 去掉 engine.metrics(改为本地日志+退避);② async→sync(requests,执行低频够用);
③ 做空腿方向(SELL 开空 / BUY reduceOnly 平空,与 coin 的 long 对冲腿相反);
④ base_url 可切币安合约测试网(testnet.binancefuture.com)。
⚠ 纯 httpx/requests + HMAC,无任何 coin 运行时/DB 依赖。绝不复用 coin 明文存 key 的做法:
   key 从 env 读(CROSSARB_BN_API_KEY/SECRET),仅在内存。
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import threading
import time
from decimal import ROUND_DOWN, Decimal
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

FUTURES_LIVE = "https://fapi.binance.com"
FUTURES_TESTNET = "https://testnet.binancefuture.com"
MARKET_STATE_CODES = {-3045}


class BinanceAPIError(Exception):
    def __init__(self, http_status: int, code: int, msg: str):
        self.http_status = http_status
        self.code = code
        self.msg = msg
        super().__init__(f"[{http_status}/{code}] {msg}")


class BinanceExec:
    """做空腿执行(同步)。base_url 决定 live / testnet。"""

    def __init__(self, api_key: str, api_secret: str, base_url: str = FUTURES_LIVE, timeout: int = 10):
        self._api_key = api_key
        self._api_secret = api_secret
        self.base = base_url.rstrip("/")
        self._timeout = timeout
        self._s = requests.Session()
        self._sem = threading.Semaphore(3)
        self._info = None
        self._info_ts = 0.0

    # ---- 签名/请求(保留 coin 的限频退避,去 metrics)----
    def _sign(self, params: dict) -> str:
        params["timestamp"] = int(time.time() * 1000)
        query = urlencode(params)
        sig = hmac.new(self._api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        return f"{query}&signature={sig}"

    def _request(self, method: str, path: str, params: dict | None = None, signed: bool = True) -> dict:
        if params is None:
            params = {}
        qs = self._sign(params) if signed else urlencode(params)
        url = f"{self.base}{path}" + (f"?{qs}" if qs else "")
        headers = {"X-MBX-APIKEY": self._api_key}
        backoff = 0.0
        with self._sem:
            try:
                resp = self._s.request(method, url, headers=headers, timeout=self._timeout)
            except requests.RequestException as te:
                # 传输失败 ≠ 订单未送达(可能已成交)→ -1007「执行状态未知」,上层按 clientOrderId 复核
                raise BinanceAPIError(0, -1007, f"transport error (status UNKNOWN): {te}")
            # IP weight 退避(读路径,合约 fapi 限 2400/min)
            mbx = resp.headers.get("X-MBX-USED-WEIGHT-1M") or resp.headers.get("x-mbx-used-weight-1m")
            if mbx:
                try:
                    r = int(mbx) / 2400
                    backoff = 2.0 if r >= 0.9 else (1.0 if r >= 0.8 else (0.4 if r >= 0.65 else 0.0))
                except ValueError:
                    pass
            status = resp.status_code
            if status == 429:
                ra = int(resp.headers.get("Retry-After", 5))
                logger.warning("binance 429, sleep %ss", ra)
                time.sleep(max(ra, 5))
                params.pop("timestamp", None)
                params.pop("signature", None)
                return self._request(method, path, params, signed)
            if status >= 400:
                data = resp.json() if resp.content else {}
                raise BinanceAPIError(status, data.get("code", 0), data.get("msg", resp.text))
            result = resp.json()
        if backoff > 0:
            time.sleep(backoff)
        return result

    # ---- 行情/精度 ----
    def book_ticker(self, symbol: str) -> dict:
        d = self._request("GET", "/fapi/v1/ticker/bookTicker", {"symbol": symbol}, signed=False)
        return {"bid": float(d["bidPrice"]), "ask": float(d["askPrice"]), "raw": d}

    def _exchange_info(self) -> dict:
        now = time.time()
        if self._info is None or now - self._info_ts > 3600:
            self._info = self._request("GET", "/fapi/v1/exchangeInfo", signed=False)
            self._info_ts = now
        return self._info

    def _filters(self, symbol: str) -> dict:
        for s in self._exchange_info().get("symbols", []):
            if s["symbol"] == symbol:
                return {f["filterType"]: f for f in s.get("filters", [])}
        return {}

    def round_qty(self, symbol: str, qty: Decimal) -> Decimal:
        step = Decimal(str(self._filters(symbol).get("LOT_SIZE", {}).get("stepSize", "0.001")))
        return (qty / step).to_integral_value(rounding=ROUND_DOWN) * step if step > 0 else qty

    # ---- 做空腿下单(方向与 coin 的 long 对冲腿相反)----
    def futures_market_short(self, symbol: str, quantity: Decimal, client_order_id: str | None = None) -> dict:
        """市价开空(SELL)。newOrderRespType=RESULT 拿真实 executedQty/avgPrice(fapi 市价单默认 ACK=0)。"""
        params = {"symbol": symbol, "side": "SELL", "type": "MARKET",
                  "quantity": str(quantity), "newOrderRespType": "RESULT"}
        if client_order_id:
            params["newClientOrderId"] = client_order_id
        return self._request("POST", "/fapi/v1/order", params)

    def futures_close_short(self, symbol: str, quantity: Decimal) -> dict:
        """市价平空(BUY reduceOnly)。"""
        return self._request("POST", "/fapi/v1/order", {
            "symbol": symbol, "side": "BUY", "type": "MARKET",
            "quantity": str(quantity), "reduceOnly": "true", "newOrderRespType": "RESULT"})

    def get_order_by_client_id(self, symbol: str, client_order_id: str) -> dict:
        """下单响应丢失(超时/5xx)时,按 clientOrderId 复核真实成交量,绝不按 0 计致裸腿。"""
        return self._request("GET", "/fapi/v1/order", {"symbol": symbol, "origClientOrderId": client_order_id})

    # ---- 持仓/账户 ----
    def get_position(self, symbol: str) -> dict | None:
        for p in self._request("GET", "/fapi/v2/positionRisk", {"symbol": symbol}):
            if p["symbol"] == symbol and float(p.get("positionAmt", 0)) != 0:
                return p
        return None

    def position_risk(self, symbol: str) -> dict | None:
        for p in self._request("GET", "/fapi/v2/positionRisk", {"symbol": symbol}):
            if p["symbol"] == symbol:
                return p
        return None

    def position_mode_dual(self) -> bool:
        """True=双向持仓。本策略下单不带 positionSide,要求单向模式(False)。"""
        return bool(self._request("GET", "/fapi/v1/positionSide/dual").get("dualSidePosition", False))

    def account(self) -> dict:
        return self._request("GET", "/fapi/v2/account")
