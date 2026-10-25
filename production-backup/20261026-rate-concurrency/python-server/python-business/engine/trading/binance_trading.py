import asyncio
import hashlib
import hmac
import inspect
import logging
import time
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP
from urllib.parse import urlencode

import httpx

from engine.metrics import get_metrics
from engine.trading.market_ws import get_ws_book_ticker, get_ws_price

logger = logging.getLogger(__name__)

SPOT_BASE = "https://api.binance.com"
FUTURES_BASE = "https://fapi.binance.com"

# 业务状态码:这些是市场状态/正常拒单,非 API 故障,不计入健康面板错误率。
#   -3045 = 杠杆系统无可借库存(无券);后续如有同类"非故障"码可加进来。
MARKET_STATE_CODES = {-3045}

# 被币安 API 限制的"硬"错误码 → 逐账户中文提示(立即置位;任一成功调用即自愈)。
# 418 IP封禁 / 429·-1003 超频 走瞬时滑窗去抖(见 _request)。
_RESTRICTION_HARD = {
    -2015: "API Key/IP 异常",   # invalid API-key, IP, or permissions
    -2008: "API Key 失效",      # invalid Api-Key ID
    -2014: "API Key 格式错",    # bad API-key format
    -1022: "签名错误",          # signature invalid
    -1002: "未授权",            # unauthorized
}


class BinancePreSubmitRejected(RuntimeError):
    """A caller-side guard proved that no HTTP request may be submitted."""


async def _ensure_pre_submit_allowed(callback) -> None:
    if callback is None:
        return
    async_check = getattr(callback, "async_check", None)
    if callable(async_check):
        try:
            allowed = async_check()
            if inspect.isawaitable(allowed):
                allowed = await allowed
            if not bool(allowed):
                raise BinancePreSubmitRejected("pre-submit guard rejected request")
            return
        except BinancePreSubmitRejected:
            raise
        except Exception as exc:
            raise BinancePreSubmitRejected("pre-submit guard failed") from exc
    try:
        allowed = bool(callback())
    except Exception as exc:
        raise BinancePreSubmitRejected("pre-submit guard failed") from exc
    if not allowed:
        raise BinancePreSubmitRejected("pre-submit guard rejected request")


def _response_text_preview(response: httpx.Response, limit: int = 512) -> str:
    """Return a bounded, useful body preview for non-JSON HTTP errors.

    Binance occasionally answers a transient gateway failure with an empty
    body or HTML.  Calling ``response.json()`` unconditionally hides the real
    HTTP status behind ``JSONDecodeError`` and makes the worker report a
    misleading reconciliation failure.  Keep diagnostics bounded because a
    proxy can return a very large document.
    """
    try:
        text = response.text or ""
    except Exception:
        return ""
    text = " ".join(text.split())
    return text[:limit]


def _decode_http_error(response: httpx.Response) -> tuple[int, str]:
    """Extract Binance's ``code``/``msg`` without assuming a JSON body."""
    status = int(response.status_code)
    try:
        payload = response.json()
    except (TypeError, ValueError):
        payload = None
    if isinstance(payload, dict):
        try:
            code = int(payload.get("code", 0) or 0)
        except (TypeError, ValueError, InvalidOperation):
            code = 0
        message = payload.get("msg")
        if message is not None and str(message).strip():
            return code, str(message).strip()
    preview = _response_text_preview(response)
    message = f"HTTP {status} non-JSON response"
    if preview:
        message += f": {preview}"
    return 0, message

_global_semaphore = asyncio.Semaphore(20)

# ── Per-account UID-weight pacer (per-sub-account configurable target rate) ──
# borrow AND repay both POST /margin/borrow-repay at 1500 UID weight each and draw
# from the SAME 180000/min UID budget, so BOTH must be spaced through this one pacer
# per sub-account to its configured req/s. The reactive UID governor is the hard cap.
DIRECT_BORROW_RATE_CEILING = 2.0
ORDER_BORROW_RATE_CEILING = 3.9
THREE_LEG_OTOCO_RATE_CEILING = 3.0
_DEFAULT_BORROW_RATE: float = ORDER_BORROW_RATE_CEILING
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


def borrow_route_rate_ceiling(mode: str | None, legs: int = 2) -> float:
    """Return the sustainable request ceiling for the selected borrow route.

    Direct borrow/repay costs 1500 UID weight and is limited to 2/s. Margin
    MARGIN_BUY routes consume order count instead; single and two-leg OTO can
    safely target 3.9/s. Three-leg OTOCO is capped lower because each request
    consumes three of Binance's 100 orders/10 seconds allowance.
    """
    normalized = str(mode or "repay").lower()
    if normalized in ("single", "multi"):
        return ORDER_BORROW_RATE_CEILING
    if normalized == "otoco":
        return (
            THREE_LEG_OTOCO_RATE_CEILING
            if int(legs or 2) >= 3
            else ORDER_BORROW_RATE_CEILING
        )
    return DIRECT_BORROW_RATE_CEILING


async def _pace_borrow(sub_account_id: int, *, max_rate: float | None = None) -> None:
    rate = _borrow_rate.get(sub_account_id, _DEFAULT_BORROW_RATE)
    if max_rate is not None:
        rate = min(rate, float(max_rate))
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
        self._tick_cache: dict[str, dict] = {}      # symbol -> {tick, step, min_notional} (spot filters, 1h TTL)
        self._tick_cache_ts: dict[str, float] = {}
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
        query = urlencode(params, doseq=True)  # doseq: list 值展开为 asset=A&asset=B(dust 等数组参数);标量不受影响
        sig = hmac.new(self._api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        return f"{query}&signature={sig}"

    def _headers(self) -> dict:
        return {"X-MBX-APIKEY": self._api_key}

    async def _request(
        self,
        method: str,
        url: str,
        params: dict = None,
        signed: bool = True,
        pre_submit_guard=None,
        retry_rate_limit: bool = True,
    ) -> dict:
        metrics = get_metrics(self._sub_account_id)
        if params is None:
            params = {}
        # 预先编码成 querystring 并直接拼到 URL,绕过 httpx 的二次编码 —— 保证「签名串==发送串」
        qs = self._sign(params) if signed else urlencode(params, doseq=True)
        full_url = f"{url}?{qs}" if qs else url

        # Backoff is COMPUTED while holding the semaphore but SLEPT after releasing it,
        # so a throttled/429 response never keeps a concurrency slot parked idle.
        backoff = 0.0
        retry_after = 0
        status = 0
        err = None
        result = None

        async with _global_semaphore, self._semaphore:
            # This is the final caller-controlled boundary. Any semaphore,
            # pacing, metadata, or retry wait has completed before this check.
            await _ensure_pre_submit_allowed(pre_submit_guard)
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
            # Order-count (unfilled-order rate): per-UID, 100/10s spot+margin. OTOCO=3单/OTO=2/单腿=1,
            # 且 IOC 过期不返还额度 → 提速建仓时第一个撞的墙(-1015)。仅下单端点(/margin/order*)返回此头。
            order_c = h.get("X-MBX-ORDER-COUNT-10S") or h.get("x-mbx-order-count-10s")

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

            # ── Order-count governor (借币提速安全护栏: 接近 100/10s 时退避防 -1015) ──
            if order_c:
                try:
                    c = int(order_c)
                    metrics.record_order_count(c, 100)
                    r = c / 100
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
                metrics.note_restriction("请求超频", time.time() + max(retry_after, 5), transient=True)
                if not retry_rate_limit:
                    code, msg = _decode_http_error(resp)
                    err = BinanceAPIError(status, code, msg)
            elif status >= 400:
                # Binance or an upstream proxy can return HTML/empty bodies
                # for gateway failures.  Keep the HTTP status and parse such
                # responses defensively instead of leaking JSONDecodeError.
                code, msg = _decode_http_error(resp)
                # -3045 = 杠杆池无可借库存,是市场状态(无券)非 API 故障 → 不计入错误率,
                # 否则每 ~10min 一次的无券复查会把 total_errors 越刷越高(健康面板虚高)。
                # 仍照常抛 BinanceAPIError,上层无券判定/置 0 逻辑不变。
                if code in MARKET_STATE_CODES:
                    metrics.record_skip()
                else:
                    metrics.record_error(f"[{status}] {msg}")
                    # 被币安 API 限制 → 置逐账户限制态(前端规则列红字提示)
                    try:
                        ra = int(resp.headers.get("Retry-After", 0) or 0)
                    except ValueError:
                        ra = 0
                    if status == 418:
                        metrics.note_restriction("IP 被封禁", time.time() + (ra or 300))
                    elif code == -1003:
                        metrics.note_restriction("请求超频", time.time() + (ra or 60), transient=True)
                    elif code in _RESTRICTION_HARD:
                        metrics.note_restriction(_RESTRICTION_HARD[code], time.time() + 120)
                err = BinanceAPIError(status, code, msg)
            else:
                try:
                    result = resp.json()
                except (TypeError, ValueError):
                    msg = f"HTTP {status} returned non-JSON response"
                    preview = _response_text_preview(resp)
                    if preview:
                        msg += f": {preview}"
                    metrics.record_error(msg)
                    err = BinanceAPIError(status, 0, msg)
                else:
                    metrics.record_success()
        # ── semaphore released: safe to sleep now without starving other requests ──

        if status == 429 and retry_rate_limit:
            logger.warning(f"Rate limited, sleeping {retry_after}s")
            await asyncio.sleep(retry_after)
            params.pop("timestamp", None)
            params.pop("signature", None)
            return await self._request(
                method,
                url,
                params,
                signed=signed,
                pre_submit_guard=pre_submit_guard,
                retry_rate_limit=retry_rate_limit,
            )
        if status == 429 and not retry_rate_limit:
            raise err or BinanceAPIError(status, 0, "rate limited")

        if backoff > 0:
            await asyncio.sleep(backoff)

        if err is not None:
            raise err
        return result

    # ---- Margin ----

    async def margin_borrow(
        self, asset: str, amount: Decimal, pre_submit_guard=None
    ) -> dict:
        await _pace_borrow(
            self._sub_account_id, max_rate=DIRECT_BORROW_RATE_CEILING
        )
        return await self._request(
            "POST",
            f"{SPOT_BASE}/sapi/v1/margin/borrow-repay",
            {
                "asset": asset, "amount": str(amount),
                "type": "BORROW", "isIsolated": "FALSE",
            },
            pre_submit_guard=pre_submit_guard,
        )

    async def margin_borrow_otoco(
        self,
        symbol: str,
        qty: Decimal,
        legs: int = 2,
        pre_submit_guard=None,
    ) -> dict:
        """借币 via IOC OTO/OTOCO —— coinmini 1.92 同款"挂单借币"流程:
          MARGIN_BUY 触发自动借币到账;working SELL LIMIT @ spot_bid×1.5、IOC 无人接秒撤;
          连带撤销保护买单(legs=3: STOP_LOSS_LIMIT@1.05× + LIMIT_MAKER@0.933×;
          legs=2: 仅 LIMIT_MAKER@0.933×)。所有单 EXPIRED,借来的币留手上(可用=已借)。
        legs=2 走 /margin/order/oto(2 张撤单,反滥用压力更低,默认);legs=3 走 /margin/order/otoco。
        显式设置 autoRepayAtCancel=false，确保 IOC 撤销时借款不会被自动偿还。
        走 order-count 配速；两腿可达3.9/s，三腿按100单/10秒硬顶降至3.0/s。"""
        await _pace_borrow(
            self._sub_account_id,
            max_rate=borrow_route_rate_ceiling("otoco", legs),
        )

        def _floor(v: Decimal, s: Decimal) -> Decimal:
            return (v / s).to_integral_value(rounding=ROUND_DOWN) * s if s > 0 else v

        # Live prices come from the Rust Binance WS feed in Redis.  Do not use
        # a public REST ticker here: a stale REST response can size the borrow
        # and its protective order against a different market.
        book = await get_ws_book_ticker(symbol, "spot")
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
            return await self._request(
                "POST",
                f"{SPOT_BASE}/sapi/v1/margin/order/oto",
                {
                    "symbol": symbol,
                    "workingType": "LIMIT", "workingSide": "SELL",
                    "workingPrice": str(limit_price), "workingQuantity": str(q), "workingTimeInForce": "IOC",
                    "pendingType": "LIMIT_MAKER", "pendingSide": "BUY",
                    "pendingQuantity": str(q), "pendingPrice": str(pb),
                    "sideEffectType": "MARGIN_BUY", "isIsolated": "FALSE",
                    "autoRepayAtCancel": "false",
                },
                pre_submit_guard=pre_submit_guard,
            )
        return await self._request(
            "POST",
            f"{SPOT_BASE}/sapi/v1/margin/order/otoco",
            {
                "symbol": symbol,
                "workingType": "LIMIT", "workingSide": "SELL",
                "workingPrice": str(limit_price), "workingQuantity": str(q), "workingTimeInForce": "IOC",
                "pendingSide": "BUY", "pendingQuantity": str(q),
                "pendingAboveType": "STOP_LOSS_LIMIT", "pendingAbovePrice": str(pa),
                "pendingAboveStopPrice": str(pa), "pendingAboveTimeInForce": "GTC",
                "pendingBelowType": "LIMIT_MAKER", "pendingBelowPrice": str(pb),
                "sideEffectType": "MARGIN_BUY", "isIsolated": "FALSE",
                "autoRepayAtCancel": "false",
            },
            pre_submit_guard=pre_submit_guard,
        )

    async def _get_spot_filters(self, symbol: str) -> dict:
        """缓存现货价格、数量和最小名义过滤器(1h TTL)。"""
        now = time.time()
        if symbol in self._tick_cache and now - self._tick_cache_ts.get(symbol, 0) < 3600:
            return self._tick_cache[symbol]
        info = await self._request("GET", f"{SPOT_BASE}/api/v3/exchangeInfo",
                                   {"symbol": symbol}, signed=False)
        flt = {f["filterType"]: f for f in info["symbols"][0]["filters"]}
        min_notional = Decimal("0")
        for filter_name in ("NOTIONAL", "MIN_NOTIONAL"):
            raw_min_notional = (flt.get(filter_name) or {}).get("minNotional")
            try:
                candidate = Decimal(str(raw_min_notional))
            except (TypeError, ValueError, InvalidOperation):
                continue
            if candidate.is_finite() and candidate > 0:
                min_notional = candidate
                break
        if not min_notional.is_finite() or min_notional < 0:
            min_notional = Decimal("0")
        res = {
            "tick": Decimal(str(flt["PRICE_FILTER"]["tickSize"])),
            "step": Decimal(str(flt["LOT_SIZE"]["stepSize"])),
            "min_notional": min_notional,
        }
        self._tick_cache[symbol] = res
        self._tick_cache_ts[symbol] = now
        return res

    async def margin_borrow_single(
        self,
        symbol: str,
        qty: Decimal,
        bid: Decimal | None = None,
        pre_submit_guard=None,
    ) -> dict:
        """路线A: 单腿裸 MARGIN_BUY 挂单借币 —— order-count 仅 1 笔/次(vs OTO 2/OTOCO 3)。
        单条 IOC SELL LIMIT @ spot_bid×1.5(挂高绝不成交,秒撤/EXPIRED),MARGIN_BUY 触发自动借币到账,
        借来的币留手上(可用=已借),后续按单笔分批对冲。无保护腿(裸单)→ 最省下单额度,建仓速率上限 ~10/s。
        bid 优先由调用方从实时点差传入(省一个 bookTicker REST);缺省再打 bookTicker 兜底。"""
        await _pace_borrow(
            self._sub_account_id, max_rate=ORDER_BORROW_RATE_CEILING
        )

        def _floor(v: Decimal, s: Decimal) -> Decimal:
            return (v / s).to_integral_value(rounding=ROUND_DOWN) * s if s > 0 else v

        if bid is None or bid <= 0:
            book = await get_ws_book_ticker(symbol, "spot")
            bid = Decimal(str(book.get("bidPrice") or book.get("b") or "0"))
        if bid <= 0:
            raise BinanceAPIError(0, 0, f"single borrow: no bid for {symbol}")
        flt = await self._get_spot_filters(symbol)
        tick, step = flt["tick"], flt["step"]
        limit_price = _floor(bid * Decimal("1.5"), tick)        # 卖价 = spot_bid × 1.5(挂高不成交)
        q = _floor(qty, step)
        return await self._request(
            "POST",
            f"{SPOT_BASE}/sapi/v1/margin/order",
            {
                "symbol": symbol, "side": "SELL", "type": "LIMIT",
                "timeInForce": "IOC", "quantity": str(q), "price": str(limit_price),
                "sideEffectType": "MARGIN_BUY", "isIsolated": "FALSE",
                "autoRepayAtCancel": "false",
            },
            pre_submit_guard=pre_submit_guard,
        )

    async def margin_repay(self, asset: str, amount, pre_submit_guard=None) -> dict:
        await _pace_borrow(
            self._sub_account_id, max_rate=DIRECT_BORROW_RATE_CEILING
        )  # repay = 1500 UID weight, never exceed 2/s
        # 币安 amount 参数正则 ^[0-9]{1,20}(\.[0-9]{1,8})?$ —— 最多 8 位小数。
        # 手动还币路径把金额归一成 float 后,min()/×0.999 重试等浮点运算会让 str() 带出
        # 15+ 位小数(如 25.001517999999998)→ -1100 "Illegal characters found in a parameter"。
        # 在此咽喉点统一量化到 8 位(HALF_UP 贴回币安 8 位真值,不留 1e-8 债务尾差),
        # format(...,"f") 防科学计数法。引擎侧 Decimal 调用方(本就≤8位)行为不变。
        amt = amount if isinstance(amount, Decimal) else Decimal(str(amount))
        amt_s = format(amt.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP), "f")
        return await self._request(
            "POST",
            f"{SPOT_BASE}/sapi/v1/margin/borrow-repay",
            {
                "asset": asset, "amount": amt_s,
                "type": "REPAY", "isIsolated": "FALSE",
            },
            pre_submit_guard=pre_submit_guard,
        )

    async def set_bnb_burn(self, spot: bool = True, interest: bool = True) -> dict:
        """开/关 BNB 抵扣手续费: spotBNBBurn=现货&杠杆下单手续费, interestBNBBurn=杠杆利息。
        幂等开关,每次按期望状态下发即可纠偏。"""
        return await self._request("POST", f"{SPOT_BASE}/sapi/v1/bnbBurn", {
            "spotBNBBurn": "true" if spot else "false",
            "interestBNBBurn": "true" if interest else "false",
        })

    async def get_margin_account(self) -> dict:
        return await self._request("GET", f"{SPOT_BASE}/sapi/v1/margin/account")

    async def get_cross_margin_data(self, coin: str) -> dict:
        """全仓杠杆币种数据(按当前账户 VIP 档):borrowLimit/dailyInterest 等,与池子库存无关。
        maxBorrowable 在 -3045(无券)时整个报错、连 borrowLimit 一起拿不到 —— 此接口是
        无券币"账户最大可借额度"的唯一来源(推送即显示额度数字,而非只会写「无券」)。"""
        data = await self._request("GET", f"{SPOT_BASE}/sapi/v1/margin/crossMarginData", {"coin": coin})
        if isinstance(data, list):
            return data[0] if data else {}
        return data or {}

    async def get_dust_assets(self) -> dict:
        """现货钱包可转 BNB 的小额资产清单(币安「小额资产兑换 BNB」)。该端点为 POST(非 GET)。
        返回 {details:[{asset, amountFree, toBNB, ...}], totalTransferBtc:..., totalTransferBNB:...}。"""
        return await self._request("POST", f"{SPOT_BASE}/sapi/v1/asset/dust-btc")

    async def get_dust_convertible_assets(
        self,
        target_asset: str = "BNB",
        account_type: str = "SPOT",
        pre_submit_guard=None,
    ) -> dict:
        """Return assets currently eligible for the modern dust-convert route.

        Binance keeps the legacy ``/asset/dust-btc`` discovery endpoint for
        the older dust-transfer API.  The current conversion API has its own
        discovery route and requires camel-case ``targetAsset``/
        ``accountType`` parameters.  Keep this wrapper beside ``dust_to_bnb``
        so callers cannot accidentally mix the two contracts.
        """
        return await self._request(
            "POST",
            f"{SPOT_BASE}/sapi/v1/asset/dust-convert/query-convertible-assets",
            {
                "targetAsset": str(target_asset).upper(),
                "accountType": str(account_type).upper(),
            },
            pre_submit_guard=pre_submit_guard,
        )

    async def dust_to_bnb(self, assets: list[str], pre_submit_guard=None) -> dict:
        """Convert the named spot dust assets to BNB using Binance's current API.

        ``/sapi/v1/asset/dust`` is the legacy *dust transfer* contract and can
        now reject otherwise valid requests with ``-31002 illegal parameter``.
        The supported route is ``dust-convert/convert``.  Its ``asset`` value
        is a comma-separated string.  Binance defaults this USER_DATA route to
        the SPOT wallet and BNB target; sending ``targetAsset=BNB`` explicitly
        can be rejected as ``-31002 illegal parameter`` for accounts/assets
        where the target is fixed by the exchange contract, so keep the request
        to the documented account selector only.
        """
        normalized = []
        for asset in assets or []:
            value = str(asset or "").strip().upper()
            if value and value not in normalized:
                normalized.append(value)
        if not normalized:
            return {}
        params = {
            "asset": ",".join(normalized),
            "accountType": "SPOT",
        }
        return await self._request(
            "POST", f"{SPOT_BASE}/sapi/v1/asset/dust-convert/convert", params,
            pre_submit_guard=pre_submit_guard,
        )

    async def get_margin_interest_rate(self, asset: str) -> Decimal:
        data = await self._request("GET", f"{SPOT_BASE}/sapi/v1/margin/interestRateHistory", {
            "asset": asset, "limit": "1",
        })
        if data and len(data) > 0:
            return Decimal(str(data[0].get("dailyInterestRate", "0")))
        return Decimal("0")

    async def get_max_borrowable(self, asset: str) -> dict:
        """全仓杠杆最大可借:返回 {amount:当前实际可借(受抵押/VIP/库存取min), borrowLimit:VIP档借贷额度上限}。
        amount 受账户持U影响、各账户不同;borrowLimit 按VIP档、与持U无关、同VIP各账户相同。"""
        data = await self._request("GET", f"{SPOT_BASE}/sapi/v1/margin/maxBorrowable", {
            "asset": asset,
        })
        return {"amount": Decimal(str(data.get("amount", "0"))), "borrowLimit": Decimal(str(data.get("borrowLimit", "0")))}

    async def get_margin_available_inventory(self) -> dict:
        """Return Binance's full cross-margin borrow inventory snapshot.

        ``available-inventory`` is a signed USER_DATA read with UID weight 50.
        It is intentionally separate from ``maxBorrowable``: this endpoint
        answers whether Binance currently has pool inventory, while account
        collateral and VIP limits remain execution-time checks.
        """
        return await self._request(
            "GET",
            f"{SPOT_BASE}/sapi/v1/margin/available-inventory",
            {"type": "MARGIN"},
            signed=True,
            retry_rate_limit=False,
        )

    async def get_loan_records(self, txn_type: str = "BORROW", asset: str = None, size: int = 20) -> dict:
        """币安全仓借/还流水(原始 REST 对账用)。txn_type=BORROW/REPAY。返回 {rows,total}。"""
        params = {"type": txn_type, "size": str(size), "current": "1", "isIsolated": "FALSE"}
        if asset:
            params["asset"] = asset
        return await self._request("GET", f"{SPOT_BASE}/sapi/v1/margin/borrow-repay", params)

    async def get_interest_history(self, asset: str = None, size: int = 20) -> dict:
        """币安全仓利息流水(原始 REST 对账用)。返回 {rows,total}。"""
        params = {"size": str(size), "current": "1"}
        if asset:
            params["asset"] = asset
        return await self._request("GET", f"{SPOT_BASE}/sapi/v1/margin/interestHistory", params)

    # ---- Spot Orders ----

    async def spot_market_sell(
        self,
        symbol: str,
        quantity: Decimal,
        is_margin: bool = True,
        pre_submit_guard=None,
    ) -> dict:
        if is_margin:
            return await self._request(
                "POST",
                f"{SPOT_BASE}/sapi/v1/margin/order",
                {
                    "symbol": symbol, "side": "SELL", "type": "MARKET",
                    "quantity": str(quantity), "sideEffectType": "NO_SIDE_EFFECT",
                    # ACK only confirms request acceptance.  RESULT gives the
                    # executor an order id, status, and executed quantity so
                    # the master futures leg is never submitted on an
                    # unconfirmed spot sale.
                    "newOrderRespType": "RESULT",
                },
                pre_submit_guard=pre_submit_guard,
            )
        return await self._request(
            "POST",
            f"{SPOT_BASE}/api/v3/order",
            {
                "symbol": symbol, "side": "SELL", "type": "MARKET",
                "quantity": str(quantity), "newOrderRespType": "RESULT",
            },
            pre_submit_guard=pre_submit_guard,
        )

    async def spot_market_buy_qty(
        self,
        symbol: str,
        quantity: Decimal,
        is_margin: bool = True,
        pre_submit_guard=None,
    ) -> dict:
        if is_margin:
            return await self._request(
                "POST",
                f"{SPOT_BASE}/sapi/v1/margin/order",
                {
                    "symbol": symbol, "side": "BUY", "type": "MARKET",
                    "quantity": str(quantity), "sideEffectType": "NO_SIDE_EFFECT",
                    "newOrderRespType": "RESULT",
                },
                pre_submit_guard=pre_submit_guard,
            )
        return await self._request(
            "POST",
            f"{SPOT_BASE}/api/v3/order",
            {
                "symbol": symbol, "side": "BUY", "type": "MARKET",
                "quantity": str(quantity), "newOrderRespType": "RESULT",
            },
            pre_submit_guard=pre_submit_guard,
        )

    # ---- Spot maker (post-only) orders ----
    # 现货腿 maker 化:LIMIT_MAKER = post-only,只做挂单方(taker 费≈15bp→maker 费更低甚至返佣),
    # 砍近半 4 腿手续费、扩可做点差空间。现货/杠杆不支持 GTX,post-only 用 type=LIMIT_MAKER。
    # 若挂价会立即成交(穿越盘口),币安直接拒单(-2010),调用方据此改市价兜底,绝不留单腿。

    async def spot_limit_maker_sell(
        self,
        symbol: str,
        quantity: Decimal,
        price: Decimal,
        is_margin: bool = True,
        pre_submit_guard=None,
    ) -> dict:
        """post-only 限价卖(杠杆户,NO_SIDE_EFFECT 不借不还)。price 应挂在卖一或更高,确保做 maker。"""
        base = f"{SPOT_BASE}/sapi/v1/margin/order" if is_margin else f"{SPOT_BASE}/api/v3/order"
        params = {"symbol": symbol, "side": "SELL", "type": "LIMIT_MAKER",
                  "quantity": str(quantity), "price": str(price)}
        if is_margin:
            params["sideEffectType"] = "NO_SIDE_EFFECT"
        return await self._request(
            "POST", base, params, pre_submit_guard=pre_submit_guard
        )

    async def spot_limit_maker_buy(
        self,
        symbol: str,
        quantity: Decimal,
        price: Decimal,
        is_margin: bool = True,
        pre_submit_guard=None,
    ) -> dict:
        """post-only 限价买(杠杆户,NO_SIDE_EFFECT)。price 应挂在买一或更低,确保做 maker。"""
        base = f"{SPOT_BASE}/sapi/v1/margin/order" if is_margin else f"{SPOT_BASE}/api/v3/order"
        params = {"symbol": symbol, "side": "BUY", "type": "LIMIT_MAKER",
                  "quantity": str(quantity), "price": str(price)}
        if is_margin:
            params["sideEffectType"] = "NO_SIDE_EFFECT"
        return await self._request("POST", base, params, pre_submit_guard=pre_submit_guard)

    async def spot_query_order(self, symbol: str, order_id: str, is_margin: bool = True) -> dict:
        base = f"{SPOT_BASE}/sapi/v1/margin/order" if is_margin else f"{SPOT_BASE}/api/v3/order"
        return await self._request("GET", base, {"symbol": symbol, "orderId": str(order_id)})

    async def spot_cancel_order(self, symbol: str, order_id: str, is_margin: bool = True) -> dict:
        base = f"{SPOT_BASE}/sapi/v1/margin/order" if is_margin else f"{SPOT_BASE}/api/v3/order"
        return await self._request("DELETE", base, {"symbol": symbol, "orderId": str(order_id)})

    # ---- Futures Orders ----

    async def futures_market_long(
        self,
        symbol: str,
        quantity: Decimal,
        new_client_order_id: str = None,
        pre_submit_guard=None,
    ) -> dict:
        # newOrderRespType=RESULT: fapi 市价单默认 ACK 应答 executedQty=0(成交异步),
        # RESULT 等撮合结果返回真实 executedQty/avgPrice —— 否则落库 0 量,平仓 -1102
        params = {
            "symbol": symbol, "side": "BUY", "type": "MARKET",
            "quantity": str(quantity), "newOrderRespType": "RESULT",
        }
        if new_client_order_id:
            params["newClientOrderId"] = new_client_order_id
        return await self._request(
            "POST",
            f"{FUTURES_BASE}/fapi/v1/order",
            params,
            pre_submit_guard=pre_submit_guard,
        )

    async def futures_market_close(
        self, symbol: str, quantity: Decimal, pre_submit_guard=None
    ) -> dict:
        return await self._request(
            "POST",
            f"{FUTURES_BASE}/fapi/v1/order",
            {
                "symbol": symbol, "side": "SELL", "type": "MARKET",
                "quantity": str(quantity), "reduceOnly": "true",
                "newOrderRespType": "RESULT",
            },
            pre_submit_guard=pre_submit_guard,
        )

    async def futures_limit_long(
        self,
        symbol: str,
        quantity: Decimal,
        price: Decimal,
        pre_submit_guard=None,
    ) -> dict:
        return await self._request(
            "POST",
            f"{FUTURES_BASE}/fapi/v1/order",
            {
                "symbol": symbol, "side": "BUY", "type": "LIMIT", "timeInForce": "GTC",
                "quantity": str(quantity), "price": str(price),
            },
            pre_submit_guard=pre_submit_guard,
        )

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
        """Best bid/ask from the Rust Binance WS feed (fresh, for limit pricing)."""
        return await get_ws_book_ticker(symbol, "futures")

    async def ws_spot_price(self, symbol: str, side: str = "bid") -> Decimal:
        """Return a fresh Spot bid/ask from the Rust Binance WS feed."""
        return await get_ws_price(symbol, "spot", side)

    async def rest_book_ticker(self, symbol: str, market: str = "spot") -> dict:
        """独立于 Rust WS 链路的公共 REST 盘口(top-of-book)。

        C2 反插针二次确认专用:WS 单源(Rust 引擎→Redis spreads)若某腿被插针,
        重采同一路抓不住持久幻价;REST bookTicker 是唯一不经该链路的独立源,用来
        核对将要对冲的点差是否真实。``signed=False`` 公共读,**绝不用于下单定价**。
        现货 /api/v3/ticker/bookTicker 与合约 /fapi/v1/ticker/bookTicker 均返回
        bidPrice/askPrice。"""
        m = (market or "spot").lower().strip()
        if m == "spot":
            url = f"{SPOT_BASE}/api/v3/ticker/bookTicker"
        elif m in ("futures", "future", "fut"):
            url = f"{FUTURES_BASE}/fapi/v1/ticker/bookTicker"
        else:
            raise ValueError(f"unsupported market: {market}")
        data = await self._request("GET", url, {"symbol": symbol}, signed=False)
        return {
            "symbol": symbol,
            "bid": Decimal(str(data["bidPrice"])),
            "ask": Decimal(str(data["askPrice"])),
        }

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
        # Binance returns a list for positionRisk, including a zero-sized row
        # for a flat symbol.  Treat any other shape as an unknown response so
        # stale-repayment recovery cannot mistake a malformed/partial API
        # result for proof that the hedge is flat.
        if not isinstance(data, list):
            raise ValueError("Binance futures position-risk response was not a list")
        matched = False
        for p in data:
            if not isinstance(p, dict):
                raise ValueError("Binance futures position-risk row was not an object")
            if p.get("symbol") != symbol:
                continue
            matched = True
            raw_amount = p.get("positionAmt")
            if raw_amount is None:
                raise ValueError(
                    f"Binance futures position-risk row has no positionAmt for {symbol}"
                )
            try:
                amount = Decimal(str(raw_amount))
            except Exception as exc:
                raise ValueError(
                    f"Binance futures position-risk row has invalid positionAmt for {symbol}"
                ) from exc
            if not amount.is_finite():
                raise ValueError(
                    f"Binance futures position-risk row has non-finite positionAmt for {symbol}"
                )
            if amount != 0:
                return p
        if not matched:
            raise ValueError(
                f"Binance futures position-risk response had no row for {symbol}"
            )
        return None

    async def get_futures_open_orders(self, symbol: str) -> list:
        """Return currently open futures orders for one symbol.

        This is intentionally a REST safety read: stale repayment recovery
        must prove that no reduce/open order is still working before changing
        the persisted lifecycle state.
        """
        data = await self._request(
            "GET", f"{FUTURES_BASE}/fapi/v1/openOrders", {"symbol": symbol},
        )
        if not isinstance(data, list):
            raise ValueError("Binance futures open-orders response was not a list")
        return data

    async def get_margin_open_orders(self, symbol: str) -> list:
        """Return currently open cross-margin orders for one symbol."""
        data = await self._request(
            "GET", f"{SPOT_BASE}/sapi/v1/margin/openOrders", {"symbol": symbol},
        )
        if not isinstance(data, list):
            raise ValueError("Binance margin open-orders response was not a list")
        return data

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
        if not isinstance(data, dict) or "dualSidePosition" not in data:
            raise ValueError("position-mode response missing dualSidePosition")
        value = data["dualSidePosition"]
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
        raise ValueError(f"invalid dualSidePosition value: {value!r}")

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

    async def transfer(
        self,
        transfer_type: str,
        asset: str,
        amount: Decimal,
        pre_submit_guard=None,
    ) -> dict:
        return await self._request(
            "POST",
            f"{SPOT_BASE}/sapi/v1/asset/transfer",
            {
                "type": transfer_type, "asset": asset, "amount": str(amount),
            },
            pre_submit_guard=pre_submit_guard,
        )

    async def universal_transfer(
        self, asset: str, amount: Decimal,
        from_account_type: str = "SPOT", to_account_type: str = "SPOT",
        from_email: str = None, to_email: str = None, pre_submit_guard=None,
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
            pre_submit_guard=pre_submit_guard,
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
