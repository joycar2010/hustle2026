import asyncio
import hashlib
import hmac
import logging
import time
from decimal import Decimal, ROUND_DOWN
from urllib.parse import urlencode

import httpx

from engine.metrics import get_metrics

logger = logging.getLogger(__name__)

SPOT_BASE = "https://api.binance.com"
FUTURES_BASE = "https://fapi.binance.com"

_global_semaphore = asyncio.Semaphore(20)

# ── Per-account UID-weight pacer (per-sub-account configurable target rate) ──
# borrow AND repay both POST /margin/borrow-repay at 1500 UID weight each and draw
# from the SAME 180000/min UID budget, so BOTH must be spaced through this one pacer
# per sub-account to its configured req/s. The reactive UID governor is the hard cap.
_DEFAULT_BORROW_RATE: float = 2.0
_borrow_rate: dict[int, float] = {}            # sub_account_id -> rate (req/s)
_borrow_last_ts: dict[int, float] = {}
_borrow_locks: dict[int, "asyncio.Lock"] = {}


def set_borrow_rate(sub_account_id: int, rate) -> None:
    """Set the per-account borrow pacing rate. sub_account_id=0 sets the default."""
    try:
        r = float(rate)
        if r <= 0:
            return
        if sub_account_id == 0:
            global _DEFAULT_BORROW_RATE
            _DEFAULT_BORROW_RATE = r
        else:
            _borrow_rate[sub_account_id] = r
    except (TypeError, ValueError):
        pass


async def _pace_borrow(sub_account_id: int) -> None:
    rate = _borrow_rate.get(sub_account_id, _DEFAULT_BORROW_RATE)
    if not rate or rate <= 0:
        return
    interval = 1.0 / rate
    lock = _borrow_locks.setdefault(sub_account_id, asyncio.Lock())
    async with lock:
        wait = interval - (time.monotonic() - _borrow_last_ts.get(sub_account_id, 0.0))
        if wait > 0:
            await asyncio.sleep(wait)
        _borrow_last_ts[sub_account_id] = time.monotonic()


class BinanceTradingClient:
    def __init__(self, api_key: str, api_secret: str, timeout: int = 10, sub_account_id: int = 0):
        self._api_key = api_key
        self._api_secret = api_secret
        self._timeout = timeout
        self._sub_account_id = sub_account_id
        self._client: httpx.AsyncClient | None = None
        self._semaphore = asyncio.Semaphore(3)
        self._lot_cache: dict[str, dict] = {}
        self._lot_cache_ts: dict[str, float] = {}
        self._futures_exchange_info: dict | None = None
        self._futures_exchange_info_ts: float = 0

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    def _sign(self, params: dict) -> str:
        """返回已签名的完整 querystring。签名串与实际发送串必须逐字节一致 ——
        故用 urlencode(与发送同款编码),否则含 @ 等特殊字符的参数(如 email)
        会因 httpx 把 @→%40 与朴素 join 不一致而 -1022 签名错误。"""
        params["timestamp"] = int(time.time() * 1000)
        query = urlencode(params)
        sig = hmac.new(self._api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        return f"{query}&signature={sig}"

    def _headers(self) -> dict:
        return {"X-MBX-APIKEY": self._api_key}

    async def _request(self, method: str, url: str, params: dict = None, signed: bool = True) -> dict:
        metrics = get_metrics(self._sub_account_id)
        if params is None:
            params = {}
        # 预先编码成 querystring 并直接拼到 URL,绕过 httpx 的二次编码 —— 保证「签名串==发送串」
        qs = self._sign(params) if signed else urlencode(params)
        full_url = f"{url}?{qs}" if qs else url

        # Backoff is COMPUTED while holding the semaphore but SLEPT after releasing it,
        # so a throttled/429 response never keeps a concurrency slot parked idle.
        backoff = 0.0
        retry_after = 0
        status = 0
        err = None
        result = None

        async with _global_semaphore, self._semaphore:
            try:
                if method == "GET":
                    resp = await self._client.get(full_url, headers=self._headers())
                elif method == "POST":
                    resp = await self._client.post(full_url, headers=self._headers())
                elif method == "DELETE":
                    resp = await self._client.delete(full_url, headers=self._headers())
                else:
                    raise ValueError(f"Unsupported method: {method}")
            except (httpx.TimeoutException, httpx.TransportError) as te:
                # 传输层失败 ≠ 订单未送达(可能已成交)。包成 ambiguous BinanceAPIError,
                # 让失败处理统一走回滚分支(api_code=-1007 与币安"执行状态未知"同义)。
                metrics.record_error(f"[transport] {te}")
                raise BinanceAPIError(0, -1007, f"transport error (execution status UNKNOWN): {te}")

            # Two independent SAPI rate dimensions (verified by header probe):
            #  • UID weight (X-SAPI-USED-UID-WEIGHT-1M, limit 180000): borrow/repay = 1500
            #    each, 0 IP weight. Per sub-account → pace EACH account to ~2/s here.
            #  • IP weight (X-SAPI-USED-IP-WEIGHT-1M, limit ~12000): read endpoints; shared
            #    across all accounts on this host. spot/futures use X-MBX-USED-WEIGHT-1M.
            h = resp.headers
            uid_w = h.get("X-SAPI-USED-UID-WEIGHT-1M") or h.get("x-sapi-used-uid-weight-1m")
            sapi_ip = h.get("X-SAPI-USED-IP-WEIGHT-1M") or h.get("x-sapi-used-ip-weight-1m")
            mbx_w = h.get("X-MBX-USED-WEIGHT-1M") or h.get("X-MBX-USED-WEIGHT-1m")

            # ── Per-UID governor (borrow rate path) — record now, back off after unlock ──
            if uid_w:
                try:
                    u = int(uid_w)
                    metrics.record_uid_weight(u, 180000)
                    r = u / 180000
                    if r >= 0.92:
                        backoff = max(backoff, 2.0)
                    elif r >= 0.85:
                        backoff = max(backoff, 0.6)
                except ValueError:
                    pass

            # ── IP governor (read path, shared host budget) ──
            ip_used, ip_limit = None, 6000
            if sapi_ip:
                ip_used, ip_limit = sapi_ip, 12000
            elif mbx_w:
                ip_used = mbx_w
                ip_limit = 2400 if "fapi.binance.com" in url else 6000
            if ip_used:
                try:
                    w = int(ip_used)
                    metrics.record_weight(w, ip_limit)
                    r = w / ip_limit
                    if r >= 0.90:
                        backoff = max(backoff, 2.0)
                    elif r >= 0.80:
                        backoff = max(backoff, 1.0)
                    elif r >= 0.65:
                        backoff = max(backoff, 0.4)
                except ValueError:
                    pass

            status = resp.status_code
            if status == 429:
                metrics.record_rate_limit()
                retry_after = int(resp.headers.get("Retry-After", 5))
            elif status >= 400:
                data = resp.json()
                msg = data.get("msg", resp.text)
                metrics.record_error(f"[{status}] {msg}")
                err = BinanceAPIError(status, data.get("code", 0), msg)
            else:
                metrics.record_success()
                result = resp.json()
        # ── semaphore released: safe to sleep now without starving other requests ──

        if status == 429:
            logger.warning(f"Rate limited, sleeping {retry_after}s")
            await asyncio.sleep(retry_after)
            params.pop("timestamp", None)
            params.pop("signature", None)
            return await self._request(method, url, params, signed=True)

        if backoff > 0:
            await asyncio.sleep(backoff)

        if err is not None:
            raise err
        return result

    # ---- Margin ----

    async def margin_borrow(self, asset: str, amount: Decimal) -> dict:
        await _pace_borrow(self._sub_account_id)  # per-account配速 (可配, 默认2/s)
        return await self._request("POST", f"{SPOT_BASE}/sapi/v1/margin/borrow-repay", {
            "asset": asset, "amount": str(amount),
            "type": "BORROW", "isIsolated": "FALSE",
        })

    async def margin_borrow_otoco(self, symbol: str, qty: Decimal, legs: int = 2) -> dict:
        """借币 via IOC OTO/OTOCO —— coinmini 1.92 同款"挂单借币"流程:
          MARGIN_BUY 触发自动借币到账;working SELL LIMIT @ spot_bid×1.5、IOC 无人接秒撤;
          连带撤销保护买单(legs=3: STOP_LOSS_LIMIT@1.05× + LIMIT_MAKER@0.933×;
          legs=2: 仅 LIMIT_MAKER@0.933×)。所有单 EXPIRED,借来的币留手上(可用=已借)。
        legs=2 走 /margin/order/oto(2 张撤单,反滥用压力更低,默认);legs=3 走 /margin/order/otoco。
        注: 不设 autoRepayAtCancel(实测币安默认即"借币不冲销")。同样过 _pace_borrow 配速(1500 UID 量级)。"""
        await _pace_borrow(self._sub_account_id)

        def _floor(v: Decimal, s: Decimal) -> Decimal:
            return (v / s).to_integral_value(rounding=ROUND_DOWN) * s if s > 0 else v

        book = await self._request("GET", f"{SPOT_BASE}/api/v3/ticker/bookTicker",
                                   {"symbol": symbol}, signed=False)
        bid = Decimal(str(book.get("bidPrice") or book.get("b") or "0"))
        if bid <= 0:
            raise BinanceAPIError(0, 0, f"otoco borrow: no bid for {symbol}")
        info = await self._request("GET", f"{SPOT_BASE}/api/v3/exchangeInfo",
                                   {"symbol": symbol}, signed=False)
        flt = {f["filterType"]: f for f in info["symbols"][0]["filters"]}
        tick = Decimal(str(flt["PRICE_FILTER"]["tickSize"]))
        step = Decimal(str(flt["LOT_SIZE"]["stepSize"]))

        limit_price = _floor(bid * Decimal("1.5"), tick)        # 卖价 = spot_bid × 1.5
        pa = _floor(limit_price * Decimal("1.05"), tick)        # STOP_LOSS_LIMIT BUY (legs=3)
        pb = _floor(limit_price * Decimal("0.933"), tick)       # LIMIT_MAKER BUY
        q = _floor(qty, step)

        if legs == 2:
            return await self._request("POST", f"{SPOT_BASE}/sapi/v1/margin/order/oto", {
                "symbol": symbol,
                "workingType": "LIMIT", "workingSide": "SELL",
                "workingPrice": str(limit_price), "workingQuantity": str(q), "workingTimeInForce": "IOC",
                "pendingType": "LIMIT_MAKER", "pendingSide": "BUY",
                "pendingQuantity": str(q), "pendingPrice": str(pb),
                "sideEffectType": "MARGIN_BUY", "isIsolated": "FALSE",
            })
        return await self._request("POST", f"{SPOT_BASE}/sapi/v1/margin/order/otoco", {
            "symbol": symbol,
            "workingType": "LIMIT", "workingSide": "SELL",
            "workingPrice": str(limit_price), "workingQuantity": str(q), "workingTimeInForce": "IOC",
            "pendingSide": "BUY", "pendingQuantity": str(q),
            "pendingAboveType": "STOP_LOSS_LIMIT", "pendingAbovePrice": str(pa),
            "pendingAboveStopPrice": str(pa), "pendingAboveTimeInForce": "GTC",
            "pendingBelowType": "LIMIT_MAKER", "pendingBelowPrice": str(pb),
            "sideEffectType": "MARGIN_BUY", "isIsolated": "FALSE",
        })

    async def margin_repay(self, asset: str, amount: Decimal) -> dict:
        await _pace_borrow(self._sub_account_id)  # repay = 1500 UID, shares borrow budget → same pacer
        return await self._request("POST", f"{SPOT_BASE}/sapi/v1/margin/borrow-repay", {
            "asset": asset, "amount": str(amount),
            "type": "REPAY", "isIsolated": "FALSE",
        })

    async def get_margin_account(self) -> dict:
        return await self._request("GET", f"{SPOT_BASE}/sapi/v1/margin/account")

    async def get_margin_interest_rate(self, asset: str) -> Decimal:
        data = await self._request("GET", f"{SPOT_BASE}/sapi/v1/margin/interestRateHistory", {
            "asset": asset, "limit": "1",
        })
        if data and len(data) > 0:
            return Decimal(str(data[0].get("dailyInterestRate", "0")))
        return Decimal("0")

    async def get_max_borrowable(self, asset: str) -> Decimal:
        data = await self._request("GET", f"{SPOT_BASE}/sapi/v1/margin/maxBorrowable", {
            "asset": asset,
        })
        return Decimal(str(data.get("amount", "0")))

    # ---- Spot Orders ----

    async def spot_market_sell(self, symbol: str, quantity: Decimal, is_margin: bool = True) -> dict:
        if is_margin:
            return await self._request("POST", f"{SPOT_BASE}/sapi/v1/margin/order", {
                "symbol": symbol, "side": "SELL", "type": "MARKET",
                "quantity": str(quantity), "sideEffectType": "NO_SIDE_EFFECT",
            })
        return await self._request("POST", f"{SPOT_BASE}/api/v3/order", {
            "symbol": symbol, "side": "SELL", "type": "MARKET",
            "quantity": str(quantity),
        })

    async def spot_market_buy_qty(self, symbol: str, quantity: Decimal, is_margin: bool = True) -> dict:
        if is_margin:
            return await self._request("POST", f"{SPOT_BASE}/sapi/v1/margin/order", {
                "symbol": symbol, "side": "BUY", "type": "MARKET",
                "quantity": str(quantity), "sideEffectType": "NO_SIDE_EFFECT",
            })
        return await self._request("POST", f"{SPOT_BASE}/api/v3/order", {
            "symbol": symbol, "side": "BUY", "type": "MARKET",
            "quantity": str(quantity),
        })

    # ---- Futures Orders ----

    async def futures_market_long(self, symbol: str, quantity: Decimal,
                                  new_client_order_id: str = None) -> dict:
        # newOrderRespType=RESULT: fapi 市价单默认 ACK 应答 executedQty=0(成交异步),
        # RESULT 等撮合结果返回真实 executedQty/avgPrice —— 否则落库 0 量,平仓 -1102
        params = {
            "symbol": symbol, "side": "BUY", "type": "MARKET",
            "quantity": str(quantity), "newOrderRespType": "RESULT",
        }
        if new_client_order_id:
            params["newClientOrderId"] = new_client_order_id
        return await self._request("POST", f"{FUTURES_BASE}/fapi/v1/order", params)

    async def futures_market_close(self, symbol: str, quantity: Decimal) -> dict:
        return await self._request("POST", f"{FUTURES_BASE}/fapi/v1/order", {
            "symbol": symbol, "side": "SELL", "type": "MARKET",
            "quantity": str(quantity), "reduceOnly": "true",
            "newOrderRespType": "RESULT",
        })

    async def futures_limit_long(self, symbol: str, quantity: Decimal, price: Decimal) -> dict:
        return await self._request("POST", f"{FUTURES_BASE}/fapi/v1/order", {
            "symbol": symbol, "side": "BUY", "type": "LIMIT", "timeInForce": "GTC",
            "quantity": str(quantity), "price": str(price),
        })

    async def futures_get_order(self, symbol: str, order_id: str) -> dict:
        return await self._request("GET", f"{FUTURES_BASE}/fapi/v1/order", {
            "symbol": symbol, "orderId": str(order_id),
        })

    async def futures_get_order_by_client_id(self, symbol: str, client_order_id: str) -> dict:
        """按自定义 clientOrderId 查单 —— 下单响应丢失(超时/5xx)时复核实际成交量。"""
        return await self._request("GET", f"{FUTURES_BASE}/fapi/v1/order", {
            "symbol": symbol, "origClientOrderId": client_order_id,
        })

    async def futures_cancel_order(self, symbol: str, order_id: str) -> dict:
        return await self._request("DELETE", f"{FUTURES_BASE}/fapi/v1/order", {
            "symbol": symbol, "orderId": str(order_id),
        })

    async def futures_book_ticker(self, symbol: str) -> dict:
        """Best bid/ask for the futures symbol (fresh, for limit pricing)."""
        return await self._request("GET", f"{FUTURES_BASE}/fapi/v1/ticker/bookTicker", {
            "symbol": symbol,
        }, signed=False)

    async def get_futures_tick_size(self, symbol: str) -> Decimal:
        """PRICE_FILTER tickSize for the futures symbol (for limit price rounding)."""
        now = time.time()
        if not self._futures_exchange_info or now - self._futures_exchange_info_ts > 3600:
            # populate cache via get_lot_size path
            await self.get_lot_size(symbol, "futures")
        info = self._futures_exchange_info or {}
        for s in info.get("symbols", []):
            if s["symbol"] == symbol:
                for f in s.get("filters", []):
                    if f["filterType"] == "PRICE_FILTER":
                        return Decimal(str(f["tickSize"]))
        return Decimal("0.0001")

    async def get_futures_position(self, symbol: str) -> dict | None:
        data = await self._request("GET", f"{FUTURES_BASE}/fapi/v2/positionRisk", {
            "symbol": symbol,
        })
        for p in data:
            if p["symbol"] == symbol and float(p.get("positionAmt", 0)) != 0:
                return p
        return None

    async def futures_position_risk(self, symbol: str) -> dict | None:
        """positionRisk entry for the symbol even with zero positionAmt (leverage/mode读取用)."""
        data = await self._request("GET", f"{FUTURES_BASE}/fapi/v2/positionRisk", {
            "symbol": symbol,
        })
        for p in data:
            if p["symbol"] == symbol:
                return p
        return None

    async def get_position_mode(self) -> bool:
        """True = dual-side (双向持仓). 引擎下单不带 positionSide,要求单向模式."""
        data = await self._request("GET", f"{FUTURES_BASE}/fapi/v1/positionSide/dual")
        return bool(data.get("dualSidePosition", False))

    async def get_futures_account(self) -> dict:
        return await self._request("GET", f"{FUTURES_BASE}/fapi/v2/account")

    async def get_spot_account(self) -> dict:
        return await self._request("GET", f"{SPOT_BASE}/api/v3/account")

    async def get_funding_account(self) -> list:
        return await self._request("POST", f"{SPOT_BASE}/sapi/v1/asset/get-funding-asset")

    async def get_simple_earn_account(self) -> dict:
        try:
            data = await self._request("GET", f"{SPOT_BASE}/sapi/v1/simple-earn/flexible/position", {"size": "100"})
            return {"totalAmountInUSDT": "0", "rows": data.get("rows", [])}
        except Exception:
            return {"totalAmountInUSDT": "0", "rows": []}

    # ---- Transfers ----

    async def transfer(self, transfer_type: str, asset: str, amount: Decimal) -> dict:
        return await self._request("POST", f"{SPOT_BASE}/sapi/v1/asset/transfer", {
            "type": transfer_type, "asset": asset, "amount": str(amount),
        })

    async def universal_transfer(
        self, asset: str, amount: Decimal,
        from_account_type: str = "SPOT", to_account_type: str = "SPOT",
        from_email: str = None, to_email: str = None,
    ) -> dict:
        """主/子账户万向划转 —— 必须用【主账户】API key 调用。
        fromEmail/toEmail 省略=主账户;支持 master↔sub、sub↔sub 任意方向。
        账户类型: SPOT(现货)/USDT_FUTURE(U本位合约)/COIN_FUTURE/MARGIN(全仓杠杆)/ISOLATED_MARGIN。
        需主账户 key 开启「万向划转」权限,否则币安返回权限错误。"""
        params = {
            "fromAccountType": from_account_type,
            "toAccountType": to_account_type,
            "asset": asset,
            "amount": str(amount),
        }
        if from_email:
            params["fromEmail"] = from_email
        if to_email:
            params["toEmail"] = to_email
        return await self._request(
            "POST", f"{SPOT_BASE}/sapi/v1/sub-account/universalTransfer", params,
        )

    # ---- Utilities ----

    async def get_bnb_balance(self) -> dict:
        margin = await self.get_margin_account()
        bnb_margin = Decimal("0")
        for a in margin.get("userAssets", []):
            if a["asset"] == "BNB":
                bnb_margin = Decimal(str(a["free"]))
                break
        return {"margin": bnb_margin}

    async def get_funding_rate(self, symbol: str) -> Decimal:
        data = await self._request("GET", f"{FUTURES_BASE}/fapi/v1/premiumIndex", {
            "symbol": symbol,
        }, signed=False)
        return Decimal(str(data.get("lastFundingRate", "0")))

    async def get_funding_income(self, symbol: str, start_time: int | None = None) -> list:
        """FUNDING_FEE income since start_time, paginated (limit 1000/页,最多 10 页)。
        无 start_time 时保持旧语义: 单页最近 100 条。"""
        if not start_time:
            return await self._request("GET", f"{FUTURES_BASE}/fapi/v1/income", {
                "symbol": symbol, "incomeType": "FUNDING_FEE", "limit": "100",
            })
        out: list = []
        cursor = int(start_time)
        for _ in range(10):
            page = await self._request("GET", f"{FUTURES_BASE}/fapi/v1/income", {
                "symbol": symbol, "incomeType": "FUNDING_FEE",
                "limit": "1000", "startTime": str(cursor),
            })
            if not page:
                break
            out.extend(page)
            if len(page) < 1000:
                break
            cursor = int(page[-1].get("time", cursor)) + 1
        return out

    async def get_lot_size(self, symbol: str, market: str = "spot") -> dict:
        cache_key = f"{market}:{symbol}"
        now = time.time()

        if cache_key in self._lot_cache and now - self._lot_cache_ts.get(cache_key, 0) < 3600:
            return self._lot_cache[cache_key]

        if market == "spot":
            data = await self._request("GET", f"{SPOT_BASE}/api/v3/exchangeInfo", {
                "symbol": symbol,
            }, signed=False)
        else:
            if not self._futures_exchange_info or now - self._futures_exchange_info_ts > 3600:
                self._futures_exchange_info = await self._request(
                    "GET", f"{FUTURES_BASE}/fapi/v1/exchangeInfo", signed=False,
                )
                self._futures_exchange_info_ts = now
                for s in self._futures_exchange_info.get("symbols", []):
                    for f in s.get("filters", []):
                        if f["filterType"] == "LOT_SIZE":
                            fkey = f"futures:{s['symbol']}"
                            self._lot_cache[fkey] = {
                                "stepSize": f["stepSize"],
                                "minQty": f["minQty"],
                                "maxQty": f["maxQty"],
                            }
                            self._lot_cache_ts[fkey] = now
                            break
            if cache_key in self._lot_cache:
                return self._lot_cache[cache_key]
            data = self._futures_exchange_info

        for s in data.get("symbols", []):
            if s["symbol"] == symbol:
                for f in s.get("filters", []):
                    if f["filterType"] == "LOT_SIZE":
                        result = {
                            "stepSize": f["stepSize"],
                            "minQty": f["minQty"],
                            "maxQty": f["maxQty"],
                        }
                        self._lot_cache[cache_key] = result
                        self._lot_cache_ts[cache_key] = now
                        return result
        return {"stepSize": "0.001", "minQty": "0.001", "maxQty": "999999"}


class BinanceAPIError(Exception):
    def __init__(self, http_code: int, api_code: int, message: str):
        self.http_code = http_code
        self.api_code = api_code
        self.message = message
        super().__init__(f"Binance API error [{http_code}] code={api_code}: {message}")
