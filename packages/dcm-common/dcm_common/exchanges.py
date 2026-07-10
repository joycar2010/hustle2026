"""五所只读账户客户端:余额(USDT 权益)+ 持仓(统一符号→带方向 base/张数)。

只读路径(本模块只有 GET,不含任何下单)——先用真实账户证明签名正确、点亮实盘对账;
交易路径(下单/撤单)在 armed 步单独实现,共用此处的签名函数。

签名各所差异(每所一套自建应用 HMAC):
- binance USDM: query+ts, HMAC-SHA256 hex, header X-MBX-APIKEY
- bybit v5: HMAC-SHA256 hex over ts+key+recv+query, headers X-BAPI-*
- okx v5: base64(HMAC-SHA256 over ts+method+path+body), ISO ts, headers OK-ACCESS-* + passphrase
- gate v4: HMAC-SHA512 over method\npath\nquery\nSHA512(body)\nts, headers KEY/SIGN/Timestamp
- bitget v2: base64(HMAC-SHA256 over ts+method+path+query+body), headers ACCESS-* + passphrase

统一返回 AccountSnapshot(equity_usdt, positions{sym:signed_size}, ok, err)。
异常吞掉进 err,绝不抛(采集面纪律);符号统一大写无分隔符。
"""
import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from urllib.parse import urlencode

import httpx


@dataclass
class AccountSnapshot:
    venue: str
    ok: bool = False
    equity_usdt: float = 0.0
    positions: dict[str, float] = field(default_factory=dict)  # 统一符号 -> 带方向数量
    # 逐仓风险明细(风控三护栏数据源):qty/mark/liq/upnl/dist_liq_pct/adl
    pos_detail: dict[str, dict] = field(default_factory=dict)
    err: str = ""


def _norm(sym: str) -> str:
    return sym.replace("-SWAP", "").replace("-", "").replace("_", "").upper()


def _f2(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def _dist_liq_pct(mark: float, liq: float) -> float | None:
    """距强平价百分比(越大越安全)。cross 无 liq(0/空)→None=暂无强平风险读数。"""
    if mark > 0 and liq > 0:
        return round(abs(mark - liq) / mark * 100, 3)
    return None


# ───────────── binance USDM ─────────────

async def _binance(cli: httpx.AsyncClient, cfg: dict) -> AccountSnapshot:
    snap = AccountSnapshot("binance")
    base = "https://fapi.binance.com"

    def signed(path: str) -> str:
        q = urlencode({"timestamp": int(time.time() * 1000), "recvWindow": 5000})
        sig = hmac.new(cfg["secret"].encode(), q.encode(), hashlib.sha256).hexdigest()
        return f"{base}{path}?{q}&signature={sig}"

    headers = {"X-MBX-APIKEY": cfg["key"]}
    try:
        bal = (await cli.get(signed("/fapi/v2/balance"), headers=headers)).json()
        if isinstance(bal, dict):  # 错误响应 {"code":-2015,"msg":...}(IP/权限/签名)
            snap.err = f"{bal.get('code')}:{bal.get('msg')}"
            return snap
        for b in bal:
            if b.get("asset") == "USDT":
                snap.equity_usdt = float(b.get("balance") or 0)
        pos = (await cli.get(signed("/fapi/v2/positionRisk"), headers=headers)).json()
        if isinstance(pos, dict):
            snap.err = f"{pos.get('code')}:{pos.get('msg')}"
            return snap
        # ADL 分位(单独端点):one-way 用 BOTH 档
        adl_map: dict[str, float] = {}
        try:
            adl = (await cli.get(signed("/fapi/v1/adlQuantile"), headers=headers)).json()
            if isinstance(adl, list):
                for a in adl:
                    q = a.get("adlQuantile") or {}
                    adl_map[_norm(a["symbol"])] = _f2(q.get("BOTH") or q.get("LONG") or q.get("SHORT"))
        except Exception:
            pass
        for p in pos:
            amt = float(p.get("positionAmt") or 0)
            if amt != 0:
                s = _norm(p["symbol"])
                mark, liq = _f2(p.get("markPrice")), _f2(p.get("liquidationPrice"))
                snap.positions[s] = amt
                snap.pos_detail[s] = {"qty": amt, "mark": mark, "liq": liq,
                                      "upnl": _f2(p.get("unRealizedProfit")),
                                      "dist_liq_pct": _dist_liq_pct(mark, liq),
                                      "adl": adl_map.get(s)}
        snap.ok = True
    except Exception as e:
        snap.err = repr(e)[:200]
    return snap


# ───────────── bybit v5 ─────────────

async def _bybit(cli: httpx.AsyncClient, cfg: dict) -> AccountSnapshot:
    snap = AccountSnapshot("bybit")
    base = "https://api.bybit.com"
    recv = "5000"

    async def get(path: str, query: str):
        ts = str(int(time.time() * 1000))
        pre = ts + cfg["key"] + recv + query
        sign = hmac.new(cfg["secret"].encode(), pre.encode(), hashlib.sha256).hexdigest()
        headers = {"X-BAPI-API-KEY": cfg["key"], "X-BAPI-TIMESTAMP": ts,
                   "X-BAPI-RECV-WINDOW": recv, "X-BAPI-SIGN": sign}
        url = f"{base}{path}" + (f"?{query}" if query else "")
        return (await cli.get(url, headers=headers)).json()

    try:
        wb = await get("/v5/account/wallet-balance", "accountType=UNIFIED")
        lst = wb.get("result", {}).get("list", [])
        if lst:
            snap.equity_usdt = float(lst[0].get("totalEquity") or 0)
        pl = await get("/v5/position/list", "category=linear&settleCoin=USDT")
        for p in pl.get("result", {}).get("list", []):
            size = float(p.get("size") or 0)
            if size != 0:
                s = _norm(p["symbol"])
                signed = size if p.get("side") == "Buy" else -size
                mark, liq = _f2(p.get("markPrice")), _f2(p.get("liqPrice"))
                snap.positions[s] = signed
                snap.pos_detail[s] = {"qty": signed, "mark": mark, "liq": liq,
                                      "upnl": _f2(p.get("unrealisedPnl")),
                                      "dist_liq_pct": _dist_liq_pct(mark, liq),
                                      "adl": _f2(p.get("adlRankIndicator")) or None}
        if wb.get("retCode") == 0 and pl.get("retCode") == 0:
            snap.ok = True
        else:
            snap.err = f"wb={wb.get('retMsg')} pl={pl.get('retMsg')}"
    except Exception as e:
        snap.err = repr(e)[:200]
    return snap


# ───────────── okx v5 ─────────────

async def _okx(cli: httpx.AsyncClient, cfg: dict) -> AccountSnapshot:
    snap = AccountSnapshot("okx")
    base = "https://www.okx.com"

    async def get(path: str):
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + ".000Z"
        pre = ts + "GET" + path
        sign = base64.b64encode(hmac.new(cfg["secret"].encode(), pre.encode(), hashlib.sha256).digest()).decode()
        headers = {"OK-ACCESS-KEY": cfg["key"], "OK-ACCESS-SIGN": sign,
                   "OK-ACCESS-TIMESTAMP": ts, "OK-ACCESS-PASSPHRASE": cfg["passphrase"]}
        return (await cli.get(f"{base}{path}", headers=headers)).json()

    try:
        bal = await get("/api/v5/account/balance")
        data = bal.get("data", [])
        if data:
            snap.equity_usdt = float(data[0].get("totalEq") or 0)
        pos = await get("/api/v5/account/positions")
        for p in pos.get("data", []):
            amt = float(p.get("pos") or 0)
            if amt != 0 and p.get("instId"):
                s = _norm(p["instId"])
                mark, liq = _f2(p.get("markPx")), _f2(p.get("liqPx"))
                snap.positions[s] = amt
                snap.pos_detail[s] = {"qty": amt, "mark": mark, "liq": liq,
                                      "upnl": _f2(p.get("upl")),
                                      "dist_liq_pct": _dist_liq_pct(mark, liq),
                                      "adl": _f2(p.get("adl")) or None}
        if bal.get("code") == "0" and pos.get("code") == "0":
            snap.ok = True
        else:
            snap.err = f"bal={bal.get('msg')} pos={pos.get('msg')}"
    except Exception as e:
        snap.err = repr(e)[:200]
    return snap


# ───────────── gate v4 ─────────────

async def _gate(cli: httpx.AsyncClient, cfg: dict) -> AccountSnapshot:
    snap = AccountSnapshot("gate")
    base = "https://api.gateio.ws"
    prefix = "/api/v4"

    async def get(path: str):
        ts = str(int(time.time()))
        body_hash = hashlib.sha512(b"").hexdigest()
        pre = f"GET\n{prefix}{path}\n\n{body_hash}\n{ts}"
        sign = hmac.new(cfg["secret"].encode(), pre.encode(), hashlib.sha512).hexdigest()
        headers = {"KEY": cfg["key"], "Timestamp": ts, "SIGN": sign}
        return (await cli.get(f"{base}{prefix}{path}", headers=headers)).json()

    try:
        acc = await get("/futures/usdt/accounts")
        if isinstance(acc, dict):
            snap.equity_usdt = float(acc.get("total") or 0)
        pos = await get("/futures/usdt/positions")
        if isinstance(pos, list):
            for p in pos:
                size = float(p.get("size") or 0)
                if size != 0 and p.get("contract"):
                    s = _norm(p["contract"])
                    mark, liq = _f2(p.get("mark_price")), _f2(p.get("liq_price"))
                    snap.positions[s] = size  # 注意:张数,非 base
                    snap.pos_detail[s] = {"qty": size, "mark": mark, "liq": liq,
                                          "upnl": _f2(p.get("unrealised_pnl")),
                                          "dist_liq_pct": _dist_liq_pct(mark, liq),
                                          "adl": _f2(p.get("adl_ranking")) or None}
            snap.ok = True
        else:
            snap.err = f"pos={str(pos)[:120]}"
    except Exception as e:
        snap.err = repr(e)[:200]
    return snap


# ───────────── bitget v2 ─────────────

async def _bitget(cli: httpx.AsyncClient, cfg: dict) -> AccountSnapshot:
    snap = AccountSnapshot("bitget")
    base = "https://api.bitget.com"

    async def get(path: str, query: str):
        ts = str(int(time.time() * 1000))
        pre = ts + "GET" + path + (f"?{query}" if query else "")
        sign = base64.b64encode(hmac.new(cfg["secret"].encode(), pre.encode(), hashlib.sha256).digest()).decode()
        headers = {"ACCESS-KEY": cfg["key"], "ACCESS-SIGN": sign, "ACCESS-TIMESTAMP": ts,
                   "ACCESS-PASSPHRASE": cfg["passphrase"], "locale": "en-US",
                   "Content-Type": "application/json"}
        url = f"{base}{path}" + (f"?{query}" if query else "")
        return (await cli.get(url, headers=headers)).json()

    try:
        acc = await get("/api/v2/mix/account/accounts", "productType=USDT-FUTURES")
        for a in acc.get("data", []) or []:
            if a.get("marginCoin") == "USDT":
                snap.equity_usdt = float(a.get("accountEquity") or a.get("usdtEquity") or 0)
        pos = await get("/api/v2/mix/position/all-position", "productType=USDT-FUTURES&marginCoin=USDT")
        for p in pos.get("data", []) or []:
            size = float(p.get("total") or 0)
            if size != 0 and p.get("symbol"):
                s = _norm(p["symbol"])
                signed = size if p.get("holdSide") == "long" else -size
                mark, liq = _f2(p.get("markPrice")), _f2(p.get("liquidationPrice"))
                snap.positions[s] = signed
                snap.pos_detail[s] = {"qty": signed, "mark": mark, "liq": liq,
                                      "upnl": _f2(p.get("unrealizedPL")),
                                      "dist_liq_pct": _dist_liq_pct(mark, liq),
                                      "adl": None}
        if acc.get("code") == "00000" and pos.get("code") == "00000":
            snap.ok = True
        else:
            snap.err = f"acc={acc.get('msg')} pos={pos.get('msg')}"
    except Exception as e:
        snap.err = repr(e)[:200]
    return snap


_FETCHERS = {"binance": _binance, "bybit": _bybit, "okx": _okx, "gate": _gate, "bitget": _bitget}


async def fetch_account(cli: httpx.AsyncClient, venue: str, cfg: dict) -> AccountSnapshot:
    fn = _FETCHERS.get(venue)
    if fn is None:
        return AccountSnapshot(venue, err="unknown venue")
    return await fn(cli, cfg)
