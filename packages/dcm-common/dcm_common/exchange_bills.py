"""五所账单(收入流水)拉取:资金费/手续费/已实现盈亏,归一化 IncomeRec。

真相源纪律(coin PnL 学费):PnL 一律以交易所账单为准,拉取失败返回空列表+err,
绝不猜测补数;去重靠 (venue, ext_id);增量拉取按毫秒游标,重叠窗口由唯一约束吸收。

各所端点:
- binance /fapi/v1/income (FUNDING_FEE/COMMISSION/REALIZED_PNL, startTime, limit1000)
- bybit   /v5/account/transaction-log (accountType=UNIFIED, category=linear, startTime)
- okx     /api/v5/account/bills (type 8=资金费;含手续费字段)
- gate    /futures/usdt/account_book (type fund/fee/pnl)
- bitget  /api/v2/mix/account/bill (productType=USDT-FUTURES)
"""
import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from .exchanges import _norm


@dataclass
class IncomeRec:
    venue: str
    ext_id: str
    symbol: str
    itype: str   # FUNDING | FEE | PNL | OTHER
    amount: float
    ts_ms: int
    raw: dict


def _f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


async def _binance(cli, cfg, since_ms) -> list[IncomeRec]:
    q = urlencode({"startTime": since_ms, "limit": 1000,
                   "timestamp": int(time.time() * 1000), "recvWindow": 5000})
    sig = hmac.new(cfg["secret"].encode(), q.encode(), hashlib.sha256).hexdigest()
    r = (await cli.get(f"https://fapi.binance.com/fapi/v1/income?{q}&signature={sig}",
                       headers={"X-MBX-APIKEY": cfg["key"]})).json()
    if isinstance(r, dict):
        raise RuntimeError(f"binance income: {r.get('code')}:{r.get('msg')}")
    out = []
    tmap = {"FUNDING_FEE": "FUNDING", "COMMISSION": "FEE", "REALIZED_PNL": "PNL", "TRANSFER": "TRANSFER"}
    for x in r:
        out.append(IncomeRec("binance", f"{x.get('tranId')}_{x.get('incomeType')}",
                             _norm(x.get("symbol") or ""), tmap.get(x.get("incomeType"), "OTHER"),
                             _f(x.get("income")), int(x.get("time") or 0), x))
    return out


async def _bybit_page(cli, cfg, query) -> dict:
    recv = "5000"
    ts = str(int(time.time() * 1000))
    pre = ts + cfg["key"] + recv + query
    sign = hmac.new(cfg["secret"].encode(), pre.encode(), hashlib.sha256).hexdigest()
    h = {"X-BAPI-API-KEY": cfg["key"], "X-BAPI-TIMESTAMP": ts,
         "X-BAPI-RECV-WINDOW": recv, "X-BAPI-SIGN": sign}
    r = (await cli.get(f"https://api.bybit.com/v5/account/transaction-log?{query}", headers=h)).json()
    if r.get("retCode") != 0:
        raise RuntimeError(f"bybit txlog: {r.get('retCode')}:{r.get('retMsg')}")
    return r.get("result") or {}


async def _bybit(cli, cfg, since_ms) -> list[IncomeRec]:
    """⚠️bybit 大坑:transaction-log 不带 endTime 时只返回 startTime 起 24h 窗内数据——
    游标停在无交易的旧时点会永远拉空、永不前进(bybit 账单黑洞根因,2026-07-12 修)。
    修法=显式 endTime 逐 24h 窗行走 + nextPageCursor 窗内翻页,单轮最多回补 8 天。"""
    out = []
    win = 24 * 3600 * 1000 - 60_000
    start = int(since_ms)
    now_ms = int(time.time() * 1000)
    windows = 0
    while start < now_ms and windows < 8:
        end = min(start + win, now_ms)
        cursor = ""
        for _page in range(20):  # 窗内翻页上限,防异常死循环
            query = (f"accountType=UNIFIED&category=linear&startTime={start}&endTime={end}&limit=50"
                     + (f"&cursor={cursor}" if cursor else ""))
            result = await _bybit_page(cli, cfg, query)
            lst = result.get("list") or []
            out.extend(_bybit_parse(lst))
            cursor = result.get("nextPageCursor") or ""
            if not cursor or len(lst) < 50:
                break
        start = end
        windows += 1
    return out


def _bybit_parse(lst) -> list[IncomeRec]:
    out = []
    tmap = {"SETTLEMENT": "FUNDING", "TRADE": "FEE", "TRANSFER_IN": "TRANSFER", "TRANSFER_OUT": "TRANSFER"}
    for x in lst:
        typ = x.get("type")
        # TRADE 行含 fee 与 change;fee 记 FEE,change(已实现)记 PNL;SETTLEMENT=资金费
        base_id = f"{x.get('id') or x.get('orderId')}_{x.get('transactionTime')}"
        if typ == "SETTLEMENT":
            out.append(IncomeRec("bybit", f"{base_id}_F", _norm(x.get("symbol") or ""),
                                 "FUNDING", _f(x.get("funding")) * -1 if _f(x.get("funding")) else _f(x.get("change")),
                                 int(x.get("transactionTime") or 0), x))
        elif typ == "TRADE":
            fee = _f(x.get("fee"))
            if fee:
                out.append(IncomeRec("bybit", f"{base_id}_fee", _norm(x.get("symbol") or ""),
                                     "FEE", -abs(fee), int(x.get("transactionTime") or 0), x))
        else:
            out.append(IncomeRec("bybit", f"{base_id}_{typ}", _norm(x.get("symbol") or ""),
                                 tmap.get(typ, "OTHER"), _f(x.get("change")),
                                 int(x.get("transactionTime") or 0), x))
    return out


async def _okx(cli, cfg, since_ms) -> list[IncomeRec]:
    path = f"/api/v5/account/bills?instType=SWAP&begin={since_ms}&limit=100"
    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + ".000Z"
    pre = ts + "GET" + path
    sign = base64.b64encode(hmac.new(cfg["secret"].encode(), pre.encode(), hashlib.sha256).digest()).decode()
    h = {"OK-ACCESS-KEY": cfg["key"], "OK-ACCESS-SIGN": sign,
         "OK-ACCESS-TIMESTAMP": ts, "OK-ACCESS-PASSPHRASE": cfg["passphrase"]}
    r = (await cli.get(f"https://www.okx.com{path}", headers=h)).json()
    if r.get("code") != "0":
        raise RuntimeError(f"okx bills: {r.get('code')}:{r.get('msg')}")
    out = []
    for x in r.get("data", []) or []:
        typ = x.get("type")
        itype = "FUNDING" if typ == "8" else ("FEE" if typ in ("6", "7") else ("PNL" if typ == "2" else "OTHER"))
        amt = _f(x.get("pnl")) if itype != "FEE" else _f(x.get("fee"))
        if itype == "OTHER" and typ == "2":
            amt = _f(x.get("pnl"))
        out.append(IncomeRec("okx", x.get("billId") or "", _norm(x.get("instId") or ""),
                             itype, amt, int(x.get("ts") or 0), x))
        fee = _f(x.get("fee"))
        if itype != "FEE" and fee:
            out.append(IncomeRec("okx", f"{x.get('billId')}_fee", _norm(x.get("instId") or ""),
                                 "FEE", fee, int(x.get("ts") or 0), {}))
    return out


async def _gate(cli, cfg, since_ms) -> list[IncomeRec]:
    pfx = "/api/v4"
    query = f"from={since_ms // 1000}&limit=100"
    path = "/futures/usdt/account_book"
    ts = str(int(time.time()))
    bh = hashlib.sha512(b"").hexdigest()
    pre = f"GET\n{pfx}{path}\n{query}\n{bh}\n{ts}"
    sign = hmac.new(cfg["secret"].encode(), pre.encode(), hashlib.sha512).hexdigest()
    r = (await cli.get(f"https://api.gateio.ws{pfx}{path}?{query}",
                       headers={"KEY": cfg["key"], "Timestamp": ts, "SIGN": sign})).json()
    if isinstance(r, dict):
        raise RuntimeError(f"gate book: {str(r)[:120]}")
    out = []
    tmap = {"fund": "FUNDING", "fee": "FEE", "pnl": "PNL", "dnw": "TRANSFER"}
    for x in r:
        t_ms = int(_f(x.get("time")) * 1000)
        ext = f"{x.get('id') or ''}_{x.get('type')}_{t_ms}_{x.get('change')}"
        out.append(IncomeRec("gate", ext, _norm((x.get("contract") or x.get("text") or "")),
                             tmap.get(x.get("type"), "OTHER"), _f(x.get("change")), t_ms, x))
    return out


async def _bitget(cli, cfg, since_ms) -> list[IncomeRec]:
    query = f"productType=USDT-FUTURES&startTime={since_ms}&limit=100"
    path = "/api/v2/mix/account/bill"
    ts = str(int(time.time() * 1000))
    pre = ts + "GET" + path + f"?{query}"
    sign = base64.b64encode(hmac.new(cfg["secret"].encode(), pre.encode(), hashlib.sha256).digest()).decode()
    h = {"ACCESS-KEY": cfg["key"], "ACCESS-SIGN": sign, "ACCESS-TIMESTAMP": ts,
         "ACCESS-PASSPHRASE": cfg["passphrase"], "locale": "en-US"}
    r = (await cli.get(f"https://api.bitget.com{path}?{query}", headers=h)).json()
    if r.get("code") != "00000":
        raise RuntimeError(f"bitget bill: {r.get('code')}:{r.get('msg')}")
    out = []
    for x in (r.get("data", {}) or {}).get("bills", []) or []:
        bt = (x.get("businessType") or "").lower()
        if "funding" in bt or bt == "contract_settle_fee":
            itype = "FUNDING"
        elif "fee" in bt:
            itype = "FEE"
        # bitget v2 成交账单 businessType 实测为 buy/sell(开腿 amount=0,平腿 amount=已实现盈亏)——
        # 此前落 OTHER 被 net 口径排除,对冲对里 bitget 腿盈亏隐身(EVAA -28.19 假盈利事故 2026-07-13)
        elif "pnl" in bt or "close" in bt or bt in ("buy", "sell") or "open" in bt:
            itype = "PNL"
        elif "trans" in bt:
            itype = "TRANSFER"
        else:
            itype = "OTHER"
        amt = _f(x.get("amount"))
        fee = _f(x.get("fee"))
        out.append(IncomeRec("bitget", x.get("billId") or "", _norm(x.get("symbol") or ""),
                             itype, amt, int(x.get("cTime") or 0), x))
        if fee:
            out.append(IncomeRec("bitget", f"{x.get('billId')}_fee", _norm(x.get("symbol") or ""),
                                 "FEE", -abs(fee), int(x.get("cTime") or 0), {}))
    return out


FETCHERS = {"binance": _binance, "bybit": _bybit, "okx": _okx, "gate": _gate, "bitget": _bitget}


async def fetch_income(cli: httpx.AsyncClient, venue: str, cfg: dict, since_ms: int) -> list[IncomeRec]:
    return await FETCHERS[venue](cli, cfg, since_ms)
