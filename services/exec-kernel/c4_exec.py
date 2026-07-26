"""C4 期现交割执行器 v2(canary 级)—— 现货多 + 同所交割空,持有到期吃基差。

设计铁律:
  - 独立自含:不改 real_venue.py(C2 armed 命脉零爆炸半径);签名内联(fee_probe 同路数)。
  - 授权账:开仓前查 PG c4_route_authorization(§11.2 产品隔离账,不入 C2 的
    route_qualification 免得按 symbol 键控污染刚翻 ENFORCE 的 C2 路由闸)。
  - 平台风控:接 policy_client.can_open(dcm:risk:policy,需 decode_responses=True 客户端);
    armed 时 policy 不可读=拒开(fail-closed)。
  - 两钥匙武装:env DCM_C4_ARMED=1 且 redis dcm:c4:exec:armed="1" 才是真钱;缺一=shadow。
  - 腿序:先现货 IOC(难成交腿),零成交=干净放弃;成交后交割空(bybit/binance 深盘市价,
    gate 薄盘限价 IOC 封顶滑点);交割腿失败/部分→卖回未对冲现货,ROLLBACK/PARTIAL 如实入账+告警。
  - 防逼仓 margin buffer:杠杆 2x;bybit UTA 需 (1+1/LEV+BUFFER)×名义(现货购买力同池);
    binance/gate 现货、合约两侧分查;gate delivery 独立钱包,缺口只许从 spot 划转
    (绝不碰 perp futures 钱包=C2 保证金池)。
  - gate 交割 size 按张(multiplier 配平):qty_base=张数×mult,现货腿=同一 qty_base 严丝合缝。

v2 新增:gate venue 全分支(spot + delivery/usdt);--notional 按名义开仓;薄盘实时基差复核闸3b。
命令:preflight | open --route <route_id> [--qty 0.001|--notional 60] | status | close --pos <id>
"""
import os
import sys
import json
import hmac
import base64
import hashlib
import asyncio
import datetime as dt

import httpx
import asyncpg
import redis.asyncio as aioredis

PG_DSN = os.environ["DCM_PG_DSN"]
MIX_DSN = os.environ.get("MIX_MAIN_DSN")
REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.95:6379/0")
ARMED_ENV = os.environ.get("DCM_C4_ARMED") == "1"
ARMED_KEY = "dcm:c4:exec:armed"
SNAP_KEY = "dcm:c4:basis:latest"
ALERT_KEY = "dcm:c4:alerts"

LEV = float(os.environ.get("DCM_C4_LEV", "2"))
BUFFER = float(os.environ.get("DCM_C4_BUFFER", "0.5"))
MIN_NET_ANN_CAP = float(os.environ.get("DCM_C4_MIN_NET_ANN_CAP", "2.5"))
MAX_TOTAL_NOTIONAL = float(os.environ.get("DCM_C4_MAX_TOTAL", "200"))
SNAP_FRESH_SEC = 900
LIVE_BASIS_TOL_BPS = 60.0   # 闸3b: 实时基差不得比快照差超过此值(薄盘幻价防线)
FUT_SLIP_BPS = 30.0         # gate 交割腿限价 IOC 封顶滑点
MAKER_WAIT_SPOT = int(os.environ.get("DCM_C4_MAKER_WAIT_SPOT", "120"))  # 现货 maker 挂单等待(超时=干净放弃)
MAKER_WAIT_FUT = int(os.environ.get("DCM_C4_MAKER_WAIT_FUT", "45"))     # 交割 maker 等待(超时=回退吃单保对冲;窗口内净多敞口)

_DDL = """
CREATE TABLE IF NOT EXISTS c4_route_authorization(
  id BIGSERIAL PRIMARY KEY,
  route_id TEXT UNIQUE NOT NULL,
  product TEXT NOT NULL DEFAULT 'C4',
  underlying TEXT NOT NULL,
  venue TEXT NOT NULL,
  symbol_spot TEXT NOT NULL,
  symbol_fut TEXT NOT NULL,
  expiry TIMESTAMPTZ,
  authorization_basis TEXT NOT NULL,
  mode TEXT NOT NULL DEFAULT 'ENFORCE',
  max_notional_usdt NUMERIC NOT NULL DEFAULT 100,
  authorized_by TEXT,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  note TEXT,
  created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS c4_position(
  id BIGSERIAL PRIMARY KEY,
  route_id TEXT NOT NULL,
  venue TEXT NOT NULL,
  symbol_spot TEXT, symbol_fut TEXT,
  qty NUMERIC NOT NULL,
  spot_px NUMERIC, fut_px NUMERIC,
  entry_basis_bps NUMERIC, notional_usdt NUMERIC,
  status TEXT NOT NULL,
  opened_at TIMESTAMPTZ DEFAULT now(), closed_at TIMESTAMPTZ,
  close_spot_px NUMERIC, close_fut_px NUMERIC, note TEXT);
ALTER TABLE c4_position ADD COLUMN IF NOT EXISTS product TEXT DEFAULT 'C4';
ALTER TABLE c4_route_authorization ADD COLUMN IF NOT EXISTS product TEXT DEFAULT 'C4';
"""
C5_SNAP_KEY = "dcm:c5:basis:latest"
C5_MIN_EXF = float(os.environ.get("DCM_C5_MIN_EXF", "2.5"))       # 硬边际闸(不含funding)
C5_MIN_TOTAL = float(os.environ.get("DCM_C5_MIN_TOTAL", "1.0"))   # 含funding指示总闸
# C1 期现收费(现货多+永续空,funding=收益源,无到期锚;退出纪律=funding转负走 close)
C1_MIN_FUNDING_ANN = float(os.environ.get("DCM_C1_MIN_FUNDING_ANN", "3.0"))
C1_HORIZON_DAYS = float(os.environ.get("DCM_C1_HORIZON_DAYS", "60"))
C1_MIN_NET_ANN = float(os.environ.get("DCM_C1_MIN_NET_ANN", "1.5"))
C1_FEES_RT_BPS = float(os.environ.get("DCM_C1_FEES_RT_BPS", "30"))  # 现货10×2+永续5×2 双边全程


def _now_ms() -> str:
    return str(int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000))


def _fmt(x: float) -> str:
    return f"{x:.10f}".rstrip("0").rstrip(".")


class VenueErr(Exception):
    pass


# ---------------- bybit v5(自含签名) ----------------
class Bybit:
    def __init__(self):
        self.k, self.s = os.environ["BYBIT_KEY"], os.environ["BYBIT_SECRET"]

    def _hdr(self, payload: str):
        ts, recv = _now_ms(), "10000"
        sign = hmac.new(self.s.encode(), (ts + self.k + recv + payload).encode(), hashlib.sha256).hexdigest()
        return {"X-BAPI-API-KEY": self.k, "X-BAPI-TIMESTAMP": ts,
                "X-BAPI-RECV-WINDOW": recv, "X-BAPI-SIGN": sign,
                "Content-Type": "application/json"}

    async def get(self, cli, path, qs):
        r = await cli.get(f"https://api.bybit.com{path}?{qs}", headers=self._hdr(qs), timeout=10)
        d = r.json()
        if d.get("retCode") != 0:
            raise VenueErr(f"bybit GET {path}: {str(d)[:200]}")
        return d.get("result") or {}

    async def post(self, cli, path, body: dict):
        bj = json.dumps(body)
        r = await cli.post(f"https://api.bybit.com{path}", content=bj, headers=self._hdr(bj), timeout=10)
        d = r.json()
        if d.get("retCode") not in (0, 110043):  # 110043=杠杆未变,视为成功
            raise VenueErr(f"bybit POST {path}: {str(d)[:200]}")
        return d.get("result") or {}

    async def ask(self, cli, cat, sym) -> float:
        r = await cli.get(f"https://api.bybit.com/v5/market/tickers?category={cat}&symbol={sym}", timeout=8)
        lst = (r.json().get("result") or {}).get("list") or []
        if not lst:
            raise VenueErr(f"bybit ticker {sym} 空")
        return float(lst[0]["ask1Price"] if cat == "spot" else (lst[0].get("markPrice") or lst[0]["lastPrice"]))

    async def order_result(self, cli, cat, oid) -> tuple[float, float, str]:
        for _ in range(16):  # ≤8s
            for path in ("/v5/order/realtime", "/v5/order/history"):
                try:
                    res = await self.get(cli, path, f"category={cat}&orderId={oid}")
                    lst = res.get("list") or []
                    if lst:
                        o = lst[0]
                        st = o.get("orderStatus")
                        if st in ("Filled", "PartiallyFilledCanceled", "Cancelled", "Rejected", "Deactivated"):
                            return float(o.get("cumExecQty") or 0), float(o.get("avgPrice") or 0), st
                except VenueErr:
                    pass
            await asyncio.sleep(0.5)
        raise VenueErr(f"bybit 订单 {oid} 8s 未定型")

    async def wallet_usdt(self, cli) -> dict:
        last = None
        for acct in ("UNIFIED", "CONTRACT"):
            try:
                res = await self.get(cli, "/v5/account/wallet-balance", f"accountType={acct}")
                for a in res.get("list") or []:
                    total_avail = a.get("totalAvailableBalance")
                    for c in a.get("coin") or []:
                        if c.get("coin") == "USDT":
                            return {"acct": acct,
                                    "usdt_wallet": float(c.get("walletBalance") or 0),
                                    "avail": float(total_avail or c.get("availableToWithdraw") or 0)}
            except VenueErr as e:
                last = e
        raise VenueErr(f"bybit 钱包读取失败: {last}")

    async def perms(self, cli) -> dict:
        res = await self.get(cli, "/v5/user/query-api", "")
        return {"readOnly": res.get("readOnly"), "permissions": res.get("permissions")}

    async def position(self, cli, sym) -> dict:
        res = await self.get(cli, "/v5/position/list", f"category=linear&symbol={sym}")
        lst = res.get("list") or []
        return lst[0] if lst else {}

    async def top(self, cli, cat, sym) -> tuple[float, float]:
        r = await cli.get(f"https://api.bybit.com/v5/market/tickers?category={cat}&symbol={sym}", timeout=8)
        lst = (r.json().get("result") or {}).get("list") or []
        if not lst:
            raise VenueErr(f"bybit ticker {sym} 空")
        return float(lst[0]["bid1Price"]), float(lst[0]["ask1Price"])

    async def spot_base_step(self, cli, sym) -> float:
        r = await cli.get(f"https://api.bybit.com/v5/market/instruments-info?category=spot&symbol={sym}", timeout=8)
        lst = (r.json().get("result") or {}).get("list") or []
        try:
            return float(lst[0]["lotSizeFilter"]["basePrecision"])
        except Exception:  # noqa: BLE001
            return 1e-6

    async def coin_balance(self, cli, coin) -> float:
        for acct in ("UNIFIED", "CONTRACT"):
            try:
                res = await self.get(cli, "/v5/account/wallet-balance", f"accountType={acct}")
                for a in res.get("list") or []:
                    for c in a.get("coin") or []:
                        if c.get("coin") == coin:
                            return float(c.get("walletBalance") or 0)
            except VenueErr:
                pass
        return 0.0

    async def cancel(self, cli, cat, sym, oid):
        try:
            await self.post(cli, "/v5/order/cancel", {"category": cat, "symbol": sym, "orderId": oid})
        except VenueErr:
            pass  # 已成/已撤都算达成目的

    async def order_wait(self, cli, cat, oid, wait_s: float) -> tuple[float, float, str]:
        """等到终态或超时;超时返回当前累计(state='open')。"""
        t0 = dt.datetime.now(dt.timezone.utc).timestamp()
        last = (0.0, 0.0, "open")
        while dt.datetime.now(dt.timezone.utc).timestamp() - t0 < wait_s:
            for path in ("/v5/order/realtime", "/v5/order/history"):
                try:
                    res = await self.get(cli, path, f"category={cat}&orderId={oid}")
                    lst = res.get("list") or []
                    if lst:
                        o = lst[0]
                        st = o.get("orderStatus")
                        cum, avg = float(o.get("cumExecQty") or 0), float(o.get("avgPrice") or 0)
                        if st in ("Filled", "PartiallyFilledCanceled", "Cancelled", "Rejected", "Deactivated"):
                            return cum, avg, st
                        last = (cum, avg, "open")
                        break
                except VenueErr:
                    pass
            await asyncio.sleep(1.0)
        return last


# ---------------- binance(自含签名) ----------------
class Binance:
    def __init__(self):
        self.k, self.s = os.environ["BINANCE_KEY"], os.environ["BINANCE_SECRET"]
        self.hdr = {"X-MBX-APIKEY": self.k}

    def _sign(self, params: dict) -> str:
        q = "&".join(f"{a}={b}" for a, b in params.items())
        q += f"&timestamp={_now_ms()}&recvWindow=10000"
        return q + "&signature=" + hmac.new(self.s.encode(), q.encode(), hashlib.sha256).hexdigest()

    async def get(self, cli, base, path, params):
        r = await cli.get(f"{base}{path}?{self._sign(params)}", headers=self.hdr, timeout=10)
        d = r.json()
        if r.status_code != 200:
            raise VenueErr(f"binance GET {path}: {str(d)[:200]}")
        return d

    async def post(self, cli, base, path, params):
        r = await cli.post(f"{base}{path}?{self._sign(params)}", headers=self.hdr, timeout=10)
        d = r.json()
        if r.status_code != 200:
            raise VenueErr(f"binance POST {path}: {str(d)[:200]}")
        return d

    async def ask(self, cli, market, sym) -> float:
        if market == "spot":
            r = await cli.get(f"https://api.binance.com/api/v3/ticker/bookTicker?symbol={sym}", timeout=8)
            return float(r.json()["askPrice"])
        r = await cli.get(f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={sym}", timeout=8)
        return float(r.json()["price"])

    async def order_result(self, cli, base, sym, oid) -> tuple[float, float, str]:
        for _ in range(20):
            try:
                d = await self.get(cli, base, "/fapi/v1/order" if "fapi" in base else "/api/v3/order",
                                   {"symbol": sym, "orderId": oid})
            except VenueErr as e:
                if "-2013" in str(e):   # 下单后立即查=传播延迟"Order does not exist",重试(pos#5救场课)
                    await asyncio.sleep(0.5)
                    continue
                raise
            st = d.get("status")
            if st in ("FILLED", "EXPIRED", "CANCELED", "REJECTED"):
                qty = float(d.get("executedQty") or 0)
                quote = float(d.get("cummulativeQuoteQty") or d.get("cumQuote") or 0)
                px = (quote / qty) if qty > 0 else float(d.get("avgPrice") or 0)
                return qty, px, st
            await asyncio.sleep(0.5)
        raise VenueErr(f"binance 订单 {oid} 10s 未定型")

    async def spot_step(self, cli, sym) -> float:
        r = await cli.get(f"https://api.binance.com/api/v3/exchangeInfo?symbol={sym}", timeout=8)
        for s in r.json().get("symbols", []):
            for f in s.get("filters", []):
                if f.get("filterType") == "LOT_SIZE":
                    return float(f.get("stepSize") or 1e-5)
        return 1e-5

    async def spot_free(self, cli, asset) -> float:
        d = await self.get(cli, "https://api.binance.com", "/api/v3/account", {})
        for b in d.get("balances", []):
            if b.get("asset") == asset:
                return float(b.get("free") or 0)
        return 0.0


# ---------------- gate v4(自含签名;交割=独立前缀/张数/独立钱包) ----------------
class Gate:
    BASE = "https://api.gateio.ws"

    def __init__(self):
        self.k, self.s = os.environ["GATE_KEY"], os.environ["GATE_SECRET"]

    def _hdr(self, method, path, query="", body=""):
        ts = str(int(dt.datetime.now(dt.timezone.utc).timestamp()))
        bh = hashlib.sha512((body or "").encode()).hexdigest()
        msg = f"{method}\n{path}\n{query}\n{bh}\n{ts}"
        sign = hmac.new(self.s.encode(), msg.encode(), hashlib.sha512).hexdigest()
        h = {"KEY": self.k, "Timestamp": ts, "SIGN": sign}
        if body:
            h["Content-Type"] = "application/json"
        return h

    async def get(self, cli, path, query=""):
        url = f"{self.BASE}{path}" + (f"?{query}" if query else "")
        r = await cli.get(url, headers=self._hdr("GET", path, query), timeout=10)
        if r.status_code // 100 != 2:
            raise VenueErr(f"gate GET {path}: {r.status_code} {r.text[:200]}")
        return r.json()

    async def post(self, cli, path, body=None, query=""):
        bj = json.dumps(body) if body is not None else ""
        url = f"{self.BASE}{path}" + (f"?{query}" if query else "")
        r = await cli.post(url, content=(bj or None), headers=self._hdr("POST", path, query, bj), timeout=10)
        if r.status_code // 100 != 2:
            raise VenueErr(f"gate POST {path}: {r.status_code} {r.text[:200]}")
        try:
            return r.json()
        except Exception:  # noqa: BLE001 空体 2xx
            return {}

    # --- 行情/元数据(公开) ---
    async def spot_meta(self, cli, pair) -> dict:
        r = await cli.get(f"{self.BASE}/api/v4/spot/currency_pairs/{pair}", timeout=8)
        return r.json()

    async def spot_book_top(self, cli, pair) -> tuple[float, float]:
        r = await cli.get(f"{self.BASE}/api/v4/spot/order_book?currency_pair={pair}&limit=1", timeout=8)
        d = r.json()
        return float(d["bids"][0][0]), float(d["asks"][0][0])

    async def dlv_book_top(self, cli, contract) -> tuple[float, float]:
        r = await cli.get(f"{self.BASE}/api/v4/delivery/usdt/order_book?contract={contract}&limit=5", timeout=8)
        d = r.json()
        bid = float(d["bids"][0]["p"]) if d.get("bids") else 0.0
        ask = float(d["asks"][0]["p"]) if d.get("asks") else 0.0
        return bid, ask

    # --- 钱包 ---
    async def spot_usdt(self, cli) -> float:
        d = await self.get(cli, "/api/v4/spot/accounts", "currency=USDT")
        return float(d[0]["available"]) if d else 0.0

    async def spot_coin_avail(self, cli, ccy) -> float:
        d = await self.get(cli, "/api/v4/spot/accounts", f"currency={ccy}")
        return float(d[0]["available"]) if d else 0.0

    async def dlv_account(self, cli) -> dict:
        d = await self.get(cli, "/api/v4/delivery/usdt/accounts")
        return {"total": float(d.get("total") or 0), "avail": float(d.get("available") or 0)}

    async def transfer_spot_to_delivery(self, cli, amount: float):
        return await self.post(cli, "/api/v4/wallet/transfers",
                               {"currency": "USDT", "from": "spot", "to": "delivery",
                                "amount": _fmt(round(amount, 4)), "settle": "usdt"})

    # --- 订单 ---
    async def spot_order(self, cli, pair, side, amount, price=None, tif="ioc", typ="limit"):
        body = {"currency_pair": pair, "side": side, "type": typ, "time_in_force": tif,
                "amount": _fmt(amount)}
        if typ == "limit":
            body["price"] = _fmt(price)
        else:
            body.pop("time_in_force")  # market 单不带 tif
        return await self.post(cli, "/api/v4/spot/orders", body)

    async def spot_order_result(self, cli, pair, oid) -> tuple[float, float, str]:
        for _ in range(16):
            d = await self.get(cli, f"/api/v4/spot/orders/{oid}", f"currency_pair={pair}")
            st = d.get("status")
            if st in ("closed", "cancelled"):
                amt, left = float(d.get("amount") or 0), float(d.get("left") or 0)
                fb = amt - left
                px = float(d.get("avg_deal_price") or 0)
                if px <= 0 and fb > 0:
                    px = float(d.get("filled_total") or 0) / fb
                return fb, px, st
            await asyncio.sleep(0.5)
        raise VenueErr(f"gate spot 订单 {oid} 8s 未定型")

    async def dlv_order(self, cli, contract, size: int, price, tif="ioc", reduce_only=False):
        body = {"contract": contract, "size": size, "price": _fmt(price), "tif": tif,
                "text": f"t-c4-{_now_ms()[-8:]}"}
        if reduce_only:
            body["reduce_only"] = True
        return await self.post(cli, "/api/v4/delivery/usdt/orders", body)

    async def dlv_order_result(self, cli, oid) -> tuple[int, float, str]:
        for _ in range(16):
            d = await self.get(cli, f"/api/v4/delivery/usdt/orders/{oid}")
            st = d.get("status")
            if st == "finished":
                size, left = int(d.get("size") or 0), int(d.get("left") or 0)
                filled = abs(size) - abs(left)
                px = float(d.get("fill_price") or 0)
                return filled, px, f"{st}/{d.get('finish_as')}"
            await asyncio.sleep(0.5)
        raise VenueErr(f"gate delivery 订单 {oid} 8s 未定型")

    async def dlv_position(self, cli, contract) -> dict:
        try:
            return await self.get(cli, f"/api/v4/delivery/usdt/positions/{contract}")
        except VenueErr as e:
            if "POSITION_NOT_FOUND" in str(e) or " 404" in str(e) or " 400" in str(e):
                return {}
            raise

    # --- gate 永续(/futures/usdt 前缀;C5 近腿) ---
    async def fut_book_top(self, cli, contract) -> tuple[float, float]:
        r = await cli.get(f"{self.BASE}/api/v4/futures/usdt/order_book?contract={contract}&limit=5", timeout=8)
        d = r.json()
        bid = float(d["bids"][0]["p"]) if d.get("bids") else 0.0
        ask = float(d["asks"][0]["p"]) if d.get("asks") else 0.0
        return bid, ask

    async def fut_account_avail(self, cli) -> float:
        d = await self.get(cli, "/api/v4/futures/usdt/accounts")
        # gate credit(统一保证金)模式 total≈0 但 available=现货可作保证金(exchanges.py 同款课)
        return max(float(d.get("total") or 0), float(d.get("available") or 0))

    async def fut_order(self, cli, contract, size: int, price, tif="ioc", reduce_only=False):
        body = {"contract": contract, "size": size, "price": _fmt(price), "tif": tif,
                "text": f"t-c5-{_now_ms()[-8:]}"}
        if reduce_only:
            body["reduce_only"] = True
        return await self.post(cli, "/api/v4/futures/usdt/orders", body)

    async def fut_order_result(self, cli, oid) -> tuple[int, float, str]:
        for _ in range(16):
            d = await self.get(cli, f"/api/v4/futures/usdt/orders/{oid}")
            st = d.get("status")
            if st == "finished":
                size, left = int(d.get("size") or 0), int(d.get("left") or 0)
                return abs(size) - abs(left), float(d.get("fill_price") or 0), f"{st}/{d.get('finish_as')}"
            await asyncio.sleep(0.5)
        raise VenueErr(f"gate futures 订单 {oid} 8s 未定型")

    async def fut_position(self, cli, contract) -> dict:
        try:
            return await self.get(cli, f"/api/v4/futures/usdt/positions/{contract}")
        except VenueErr as e:
            if "POSITION_NOT_FOUND" in str(e) or " 404" in str(e) or " 400" in str(e):
                return {}
            raise

    async def try_set_fut_leverage(self, cli, contract, lev: int) -> str:
        try:
            await self.post(cli, f"/api/v4/futures/usdt/positions/{contract}/leverage",
                            None, f"leverage={lev}")
            return f"perp isolated {lev}x"
        except VenueErr as e:
            return f"perp 杠杆设置失败走默认(钱包级 buffer 兜底): {str(e)[:80]}"

    async def try_set_leverage(self, cli, contract, lev: int) -> str:
        try:
            await self.post(cli, f"/api/v4/delivery/usdt/positions/{contract}/leverage",
                            None, f"leverage={lev}")
            return f"isolated {lev}x"
        except VenueErr as e:
            return f"杠杆设置失败走默认(钱包级 buffer 兜底): {str(e)[:80]}"

    async def delete(self, cli, path, query=""):
        url = f"{self.BASE}{path}" + (f"?{query}" if query else "")
        r = await cli.delete(url, headers=self._hdr("DELETE", path, query), timeout=10)
        if r.status_code // 100 != 2:
            raise VenueErr(f"gate DELETE {path}: {r.status_code} {r.text[:150]}")
        try:
            return r.json()
        except Exception:  # noqa: BLE001
            return {}

    async def spot_cancel(self, cli, pair, oid):
        try:
            await self.delete(cli, f"/api/v4/spot/orders/{oid}", f"currency_pair={pair}")
        except VenueErr:
            pass

    async def dlv_cancel(self, cli, oid):
        try:
            await self.delete(cli, f"/api/v4/delivery/usdt/orders/{oid}")
        except VenueErr:
            pass

    async def spot_order_wait(self, cli, pair, oid, wait_s: float) -> tuple[float, float, str]:
        t0 = dt.datetime.now(dt.timezone.utc).timestamp()
        last = (0.0, 0.0, "open")
        while dt.datetime.now(dt.timezone.utc).timestamp() - t0 < wait_s:
            try:
                d = await self.get(cli, f"/api/v4/spot/orders/{oid}", f"currency_pair={pair}")
                st = d.get("status")
                amt, left = float(d.get("amount") or 0), float(d.get("left") or 0)
                fb = amt - left
                px = float(d.get("avg_deal_price") or 0)
                if px <= 0 and fb > 0:
                    px = float(d.get("filled_total") or 0) / fb
                if st in ("closed", "cancelled"):
                    return fb, px, st
                last = (fb, px, "open")
            except VenueErr:
                pass
            await asyncio.sleep(1.0)
        return last

    async def dlv_order_wait(self, cli, oid, wait_s: float) -> tuple[int, float, str]:
        t0 = dt.datetime.now(dt.timezone.utc).timestamp()
        last = (0, 0.0, "open")
        while dt.datetime.now(dt.timezone.utc).timestamp() - t0 < wait_s:
            try:
                d = await self.get(cli, f"/api/v4/delivery/usdt/orders/{oid}")
                st = d.get("status")
                size, left = int(d.get("size") or 0), int(d.get("left") or 0)
                filled = abs(size) - abs(left)
                px = float(d.get("fill_price") or 0)
                if st == "finished":
                    return filled, px, f"{st}/{d.get('finish_as')}"
                last = (filled, px, "open")
            except VenueErr:
                pass
            await asyncio.sleep(1.0)
        return last


# ---------------- okx v5(自含签名;C4-inverse:现货币本身=空头保证金) ----------------
class Okx:
    BASE = "https://www.okx.com"

    def __init__(self):
        self.k = os.environ["OKX_KEY"]
        self.s = os.environ["OKX_SECRET"]
        self.p = os.environ["OKX_PASSPHRASE"]

    def _hdr(self, method, path, body=""):
        ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        sign = base64.b64encode(hmac.new(self.s.encode(), (ts + method + path + body).encode(),
                                         hashlib.sha256).digest()).decode()
        h = {"OK-ACCESS-KEY": self.k, "OK-ACCESS-SIGN": sign,
             "OK-ACCESS-TIMESTAMP": ts, "OK-ACCESS-PASSPHRASE": self.p}
        if body:
            h["Content-Type"] = "application/json"
        return h

    async def get(self, cli, path):
        r = await cli.get(f"{self.BASE}{path}", headers=self._hdr("GET", path), timeout=10)
        d = r.json()
        if d.get("code") != "0":
            raise VenueErr(f"okx GET {path}: {str(d)[:200]}")
        return d.get("data") or []

    async def post(self, cli, path, body: dict):
        bj = json.dumps(body)
        r = await cli.post(f"{self.BASE}{path}", content=bj, headers=self._hdr("POST", path, bj), timeout=10)
        d = r.json()
        rows = d.get("data") or []
        if d.get("code") != "0" or (rows and rows[0].get("sCode") not in (None, "0")):
            raise VenueErr(f"okx POST {path}: {str(d)[:220]}")
        return rows[0] if rows else {}

    async def top(self, cli, inst_id) -> tuple[float, float]:
        r = await cli.get(f"{self.BASE}/api/v5/market/ticker?instId={inst_id}", timeout=8)
        d = (r.json().get("data") or [{}])[0]
        return float(d.get("bidPx") or 0), float(d.get("askPx") or 0)

    async def fut_meta(self, cli, inst_id) -> dict:
        r = await cli.get(f"{self.BASE}/api/v5/public/instruments?instType=FUTURES&instId={inst_id}", timeout=8)
        d = (r.json().get("data") or [{}])[0]
        return {"ctVal": float(d.get("ctVal") or 0), "ctValCcy": d.get("ctValCcy"),
                "lotSz": float(d.get("lotSz") or 1), "tickSz": float(d.get("tickSz") or 0.1),
                "settleCcy": d.get("settleCcy")}

    async def usdt_avail(self, cli) -> float:
        d = await self.get(cli, "/api/v5/account/balance?ccy=USDT")
        for a in (d[0].get("details") or []) if d else []:
            if a.get("ccy") == "USDT":
                return float(a.get("availBal") or 0)
        return 0.0

    async def coin_avail(self, cli, ccy) -> float:
        d = await self.get(cli, f"/api/v5/account/balance?ccy={ccy}")
        for a in (d[0].get("details") or []) if d else []:
            if a.get("ccy") == ccy:
                return float(a.get("availBal") or 0)
        return 0.0

    async def order(self, cli, inst_id, td_mode, side, sz, px=None, ord_type="ioc", reduce_only=False):
        body = {"instId": inst_id, "tdMode": td_mode, "side": side,
                "ordType": ord_type, "sz": _fmt(sz)}
        if px is not None:
            body["px"] = _fmt(px)
        if reduce_only:
            body["reduceOnly"] = True
        return await self.post(cli, "/api/v5/trade/order", body)

    async def order_result(self, cli, inst_id, ord_id) -> tuple[float, float, str]:
        for _ in range(16):
            d = await self.get(cli, f"/api/v5/trade/order?instId={inst_id}&ordId={ord_id}")
            if d:
                o = d[0]
                st = o.get("state")
                if st in ("filled", "canceled", "mmp_canceled"):
                    return float(o.get("accFillSz") or 0), float(o.get("avgPx") or 0), st
            await asyncio.sleep(0.5)
        raise VenueErr(f"okx 订单 {ord_id} 8s 未定型")

    async def try_set_leverage(self, cli, inst_id, lev: int) -> str:
        try:
            await self.post(cli, "/api/v5/account/set-leverage",
                            {"instId": inst_id, "lever": str(lev), "mgnMode": "cross"})
            return f"cross {lev}x"
        except VenueErr as e:
            return f"杠杆设置失败走默认(币本位全额押品兜底): {str(e)[:80]}"

    async def position(self, cli, inst_id) -> dict:
        d = await self.get(cli, f"/api/v5/account/positions?instId={inst_id}")
        return d[0] if d else {}


# ---------------- 通用 ----------------
def round_step(x: float, step: float) -> float:
    n = round(x / step)
    return round(n * step, 10)


def floor_step(x: float, step: float) -> float:
    """向下取整到步长——现货卖出必须按实际余额留尘(taker费从币里扣,账面qty永远>可卖量)。"""
    if step <= 0:
        return x
    import math
    return round(math.floor(x / step + 1e-12) * step, 12)


async def sellable(venue_cli, cli, venue: str, symbol_spot: str, target: float) -> tuple[float, float]:
    """(可卖量, 步长):min(目标, 实际余额) 向下取整到步长。venue_cli=对应 venue 客户端实例。"""
    if venue == "binance":
        base = symbol_spot.replace("USDT", "")
        step = await venue_cli.spot_step(cli, symbol_spot)
        avail = await venue_cli.spot_free(cli, base)
    elif venue == "bybit":
        base = symbol_spot.replace("USDT", "")
        step = await venue_cli.spot_base_step(cli, symbol_spot)
        avail = await venue_cli.coin_balance(cli, base)
    elif venue == "gate":
        base = symbol_spot.split("_")[0]
        meta = await venue_cli.spot_meta(cli, symbol_spot)
        step = 10 ** -int(meta.get("amount_precision") or 6)
        avail = await venue_cli.spot_coin_avail(cli, base)
    elif venue == "okx":
        base = symbol_spot.split("-")[0]
        step = 1e-8
        avail = await venue_cli.coin_avail(cli, base)
    else:
        return target, 0.0
    return floor_step(min(target, avail), step), step


async def load_route(pg, route_id):
    row = await pg.fetchrow("SELECT * FROM c4_route_authorization WHERE route_id=$1", route_id)
    if not row:
        raise SystemExit(f"授权账无此路由: {route_id}(§11.2 无授权=拒)")
    if not row["active"]:
        raise SystemExit(f"路由已停用: {route_id}")
    return row


async def fut_spec(symbol_fut, venue) -> dict:
    """instrument_spec 读交割合约 multiplier/tick/min_qty(gate 张数配平必需)。"""
    if not MIX_DSN:
        raise SystemExit("MIX_MAIN_DSN 缺失,读不到合约规格")
    c = await asyncpg.connect(MIX_DSN)
    row = await c.fetchrow(
        "SELECT contract_multiplier, tick_size, min_qty FROM instrument_spec "
        "WHERE venue=$1 AND instrument_id=$2", venue, symbol_fut)
    await c.close()
    if not row:
        raise SystemExit(f"instrument_spec 无 {venue}/{symbol_fut}")
    return {"mult": float(row["contract_multiplier"] or 1),
            "tick": float(row["tick_size"] or 0.0001),
            "min_qty": float(row["min_qty"] or 1)}


async def snap_row(r, venue, symbol_fut):
    raw = await r.get(SNAP_KEY)
    if not raw:
        return None, "快照缺失(采样器stale)"
    s = json.loads(raw)
    age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(s["ts"])).total_seconds()
    if age > SNAP_FRESH_SEC:
        return None, f"快照过龄 {age:.0f}s>{SNAP_FRESH_SEC}"
    for x in s["rows"]:
        if x["venue"] == venue and x["instrument_id"] == symbol_fut:
            x["_age_sec"] = age
            return x, None
    return None, f"快照无 {venue}/{symbol_fut}"


async def armed_state(r) -> tuple[bool, str]:
    rk = await r.get(ARMED_KEY)
    rk = (rk or b"").decode() if isinstance(rk, bytes) else (rk or "")
    on = ARMED_ENV and rk == "1"
    return on, f"env={'1' if ARMED_ENV else '0'} redis={rk or '0'}"


async def alert(r, msg):
    print(f"!! ALERT: {msg}")
    try:
        await r.lpush(ALERT_KEY, json.dumps({"ts": dt.datetime.now(dt.timezone.utc).isoformat(), "msg": msg}, ensure_ascii=False))
    except Exception:  # noqa: BLE001
        pass


async def policy_gate(venue, armed_on) -> None:
    sys.path.insert(0, "/home/ec2-user/dexcexmix")
    r2 = aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        from policy_client import can_open
        ok, why = await can_open(r2, venue)
        if not ok:
            raise SystemExit(f"闸2 拒: policy can_open[{venue}]={why}")
        print(f"闸2 policy: PASS ({why})")
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        if armed_on:
            raise SystemExit(f"闸2 拒: policy 不可读且 ARMED(fail-closed): {repr(e)[:100]}")
        print(f"闸2 policy 不可读(SHADOW 放过): {repr(e)[:80]}")
    finally:
        await r2.aclose()


# ---------------- 命令 ----------------
async def cmd_preflight():
    pg = await asyncpg.connect(PG_DSN)
    await pg.execute(_DDL)
    r = aioredis.from_url(REDIS_URL)
    on, detail = await armed_state(r)
    print(f"武装态: {'ARMED' if on else 'SHADOW'} ({detail})")
    routes = await pg.fetch("SELECT route_id,venue,symbol_spot,symbol_fut,max_notional_usdt,mode,active FROM c4_route_authorization ORDER BY id")
    print(f"授权账 {len(routes)} 条:")
    for x in routes:
        print(f"  {x['route_id']:36s} max={float(x['max_notional_usdt']):.0f}U mode={x['mode']} active={x['active']}")
    async with httpx.AsyncClient() as cli:
        by, bn, gt = Bybit(), Binance(), Gate()
        try:
            p = await by.perms(cli)
            perm = p.get("permissions") or {}
            print(f"bybit key: readOnly={p.get('readOnly')} Spot={perm.get('Spot')} Contract={perm.get('ContractTrade')}")
            w = await by.wallet_usdt(cli)
            print(f"bybit 钱包({w['acct']}): USDT={w['usdt_wallet']:.2f} avail={w['avail']:.2f}")
        except Exception as e:  # noqa: BLE001
            print(f"bybit 探测失败: {repr(e)[:120]}")
        try:
            d = await bn.get(cli, "https://api.binance.com", "/sapi/v1/account/apiRestrictions", {})
            print(f"binance key: spot&margin={d.get('enableSpotAndMarginTrading')} futures={d.get('enableFutures')}")
            bal = await bn.get(cli, "https://fapi.binance.com", "/fapi/v2/balance", {})
            u = [b for b in bal if b.get("asset") == "USDT"]
            if u:
                print(f"binance fapi: USDT={float(u[0]['balance']):.2f} avail={float(u[0]['availableBalance']):.2f}")
        except Exception as e:  # noqa: BLE001
            print(f"binance 探测失败: {repr(e)[:120]}")
        try:
            sp = await gt.spot_usdt(cli)
            dv = await gt.dlv_account(cli)
            print(f"gate 钱包: spot USDT={sp:.2f} | delivery total={dv['total']:.2f} avail={dv['avail']:.2f}(⚠perp futures 钱包=C2 保证金池,不读不动)")
        except Exception as e:  # noqa: BLE001
            print(f"gate 钱包探测失败: {repr(e)[:120]}")
        # 平台风控
        sys.path.insert(0, "/home/ec2-user/dexcexmix")
        r2 = aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            from policy_client import can_open
            for v in ("bybit", "binance", "gate"):
                ok, why = await can_open(r2, v)
                print(f"policy can_open[{v}]: {ok} ({why})")
        except Exception as e:  # noqa: BLE001
            print(f"policy 读取失败(armed 时=拒开): {repr(e)[:120]}")
        finally:
            await r2.aclose()
        for x in routes:
            row, err = await snap_row(r, x["venue"], x["symbol_fut"])
            if row:
                print(f"基差快照 {x['route_id']}: net/占用={row['net_ann_capital_pct']:+.3f}% "
                      f"(毛{row['ann_pct']:+.3f}% 费{row['fees_bps']:.1f}bps 龄{row['_age_sec']:.0f}s) 闸线={MIN_NET_ANN_CAP}%")
            else:
                print(f"基差快照 {x['route_id']}: {err}")
            if x["venue"] == "gate":
                try:
                    spec = await fut_spec(x["symbol_fut"], "gate")
                    bid, ask = await gt.dlv_book_top(cli, x["symbol_fut"])
                    sbid, sask = await gt.spot_book_top(cli, x["symbol_spot"])
                    live_bps = (bid - sask) / sask * 1e4 if bid > 0 else float("nan")
                    print(f"  gate 细节: mult={spec['mult']} tick={spec['tick']} 交割盘口 bid={bid} ask={ask} "
                          f"现货 ask={sask} 实时基差={live_bps:+.1f}bps")
                except Exception as e:  # noqa: BLE001
                    print(f"  gate 细节探测失败: {repr(e)[:100]}")
    await r.aclose()
    await pg.close()


async def _audit_intent(pg, kind, *, symbol, venue, notional=None, reason="", extra=None):
    """R2-2:c4_exec 收编进 Intent 链 —— 真金 开/平/交割 各在 exec_intent 落一条审计意图。
    best-effort:审计失败绝不影响已完成的钱路动作(永不 raise)。"""
    try:
        import uuid as _uuid
        ts = int(dt.datetime.now(dt.timezone.utc).timestamp())
        iid = f"intent-c4-{_uuid.uuid4().hex[:12]}-{ts}"
        itype = "OPEN_PAIR" if kind == "open" else "CLOSE_PAIR"
        payload = {"intent_id": iid, "intent_type": itype, "created_at": ts,
                   "source": "c4_exec", "action": kind, "venue": venue, "symbol": symbol}
        if extra:
            payload.update({k: v for k, v in extra.items() if v is not None})
        await pg.execute(
            "INSERT INTO exec_intent(intent_id,intent_type,created_at,pair_id,symbol,"
            "venue_long,venue_short,target_notional_usdt,current_notional_usdt,reason,payload) "
            "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb) ON CONFLICT (intent_id) DO NOTHING",
            iid, itype, ts, symbol, symbol, venue, venue, notional, notional, reason,
            json.dumps(payload, ensure_ascii=False))
        return iid
    except Exception as e:  # noqa: BLE001
        print(f"  [audit] exec_intent 落库失败(不影响执行): {repr(e)[:80]}")
        return None


async def _insert_pos(pg, route, qty, spot_px, fut_px, status, note):
    basis = (fut_px - spot_px) / spot_px * 1e4 if (spot_px and fut_px) else None
    prod = str(route["product"] or "C4") if "product" in dict(route) else "C4"
    pid = await pg.fetchval(
        "INSERT INTO c4_position(route_id,venue,symbol_spot,symbol_fut,qty,spot_px,fut_px,"
        "entry_basis_bps,notional_usdt,status,note,product) "
        "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12) RETURNING id",
        route["route_id"], route["venue"], route["symbol_spot"], route["symbol_fut"], qty, spot_px, fut_px,
        round(basis, 4) if basis is not None else None, (qty or 0) * (spot_px or 0), status, note, prod)
    if status == "OPEN":
        await _audit_intent(
            pg, "open", symbol=route["symbol_spot"], venue=route["venue"],
            notional=(qty or 0) * (spot_px or 0),
            reason=f"c4_exec 开仓 route={route['route_id']} product={prod}",
            extra={"c4_position_id": pid, "route_id": route["route_id"],
                   "symbol_fut": route["symbol_fut"], "qty": qty,
                   "spot_px": spot_px, "fut_px": fut_px, "product": prod,
                   "entry_basis_bps": round(basis, 4) if basis is not None else None})
    return pid


async def funding_daily(r, venue, underlying):
    """dcm:feed:funding:{v} 的 daily_pct(<1h 新鲜);None=缺失/过龄。"""
    raw = await r.hget(f"dcm:feed:funding:{venue}", f"{underlying}USDT")
    if not raw:
        return None
    try:
        j = json.loads(raw)
        ts = float(j.get("ts") or 0)
        if ts > 1e12:
            ts /= 1000.0
        if ts and dt.datetime.now(dt.timezone.utc).timestamp() - ts > 3600:
            return None
        return float(j["daily_pct"]) if j.get("daily_pct") is not None else None
    except (ValueError, TypeError):
        return None


async def c5_snap_row(r, venue, symbol_fut):
    raw = await r.get(C5_SNAP_KEY)
    if not raw:
        return None, "C5 快照缺失(采样器stale)"
    s = json.loads(raw)
    age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(s["ts"])).total_seconds()
    if age > SNAP_FRESH_SEC:
        return None, f"C5 快照过龄 {age:.0f}s>{SNAP_FRESH_SEC}"
    for x in s["rows"]:
        if x["venue"] == venue and x["instrument_id"] == symbol_fut:
            x["_age_sec"] = age
            return x, None
    return None, f"C5 快照无 {venue}/{symbol_fut}"


async def cmd_open(route_id, qty=None, notional=None, maker=False):
    pg = await asyncpg.connect(PG_DSN)
    await pg.execute(_DDL)
    r = aioredis.from_url(REDIS_URL)
    route = await load_route(pg, route_id)
    venue = route["venue"]
    on, detail = await armed_state(r)
    mode = "ARMED" if on else "SHADOW"
    print(f"=== C4 open {route_id} qty={qty} notional={notional} maker={maker} mode={mode} ({detail}) ===")

    dup = await pg.fetchval("SELECT count(*) FROM c4_position WHERE route_id=$1 AND status='OPEN'", route_id)
    if dup:
        raise SystemExit(f"闸1 拒: 该路由已有 OPEN 仓 {dup} 个(单路由单仓)")
    await policy_gate(venue, on)

    prod = str(route["product"] or "C4")
    if prod == "C1":
        # C1 期现收费:funding 是收益源(浮动无锚)。闸=当前funding年化够厚 且 摊完费仍有肉。
        fd = await funding_daily(r, venue, route["underlying"])
        if fd is None:
            raise SystemExit("闸3 拒: funding feed 缺失/过龄(>1h)")
        f_ann = fd * 365.0
        if f_ann < C1_MIN_FUNDING_ANN:
            raise SystemExit(f"闸3 拒: funding年化 {f_ann:+.2f}% < {C1_MIN_FUNDING_ANN}%(C1=空头收费,须正且够厚)")
        fees_ann = C1_FEES_RT_BPS * 365.0 / C1_HORIZON_DAYS / 100.0
        net_ann = f_ann - fees_ann
        if net_ann < C1_MIN_NET_ANN:
            raise SystemExit(f"闸3e 拒: 净年化 {net_ann:+.2f}%(费{C1_FEES_RT_BPS:.0f}bps按{C1_HORIZON_DAYS:.0f}天摊={fees_ann:.2f}%) < {C1_MIN_NET_ANN}%")
        occ1 = 1.0 + 1.0 / LEV + BUFFER
        print(f"闸3 C1 funding: PASS 年化={f_ann:+.2f}% 净(摊{C1_HORIZON_DAYS:.0f}d费)={net_ann:+.2f}% "
              f"净/占用≈{net_ann / occ1:+.2f}%(退出纪律:funding转负走 close)")
        c1row = {"basis_bps": round(fd, 4), "net_ann_capital_pct": round(net_ann / occ1, 4)}
        async with httpx.AsyncClient() as cli:
            if venue in ("binance", "bybit"):
                await _open_bybit_binance(cli, pg, r, route, c1row, qty or 0.001, on,
                                          is_bybit=(venue == "bybit"), maker=(maker and venue == "bybit"))
            else:
                raise SystemExit(f"C1 v1 只支持 binance/bybit(现货+永续同APIfamily),venue={venue}")
        await r.aclose()
        await pg.close()
        return

    if prod == "C5":
        c5row, err = await c5_snap_row(r, venue, route["symbol_fut"])
        if not c5row:
            raise SystemExit(f"闸3 拒: {err}")
        if c5row["net_ann_capital_ex_funding_pct"] < C5_MIN_EXF:
            raise SystemExit(f"闸3 拒: 硬边际 {c5row['net_ann_capital_ex_funding_pct']:+.3f}% < {C5_MIN_EXF}%")
        if (c5row.get("net_ann_capital_pct") or -99) < C5_MIN_TOTAL:
            raise SystemExit(f"闸3f 拒: 含funding总净 {c5row.get('net_ann_capital_pct')}% < {C5_MIN_TOTAL}%(浮动腿当前太贵)")
        if c5row.get("direction") != "LONG_PERP_SHORT_FUT":
            raise SystemExit(f"闸3d 拒: v1 只支持 LONG_PERP_SHORT_FUT(现 {c5row.get('direction')})")
        print(f"闸3 C5基差: PASS 硬边际={c5row['net_ann_capital_ex_funding_pct']:+.3f}% "
              f"含funding={c5row.get('net_ann_capital_pct')}% 龄{c5row['_age_sec']:.0f}s")
        async with httpx.AsyncClient() as cli:
            if venue == "gate":
                await _open_c5_gate(cli, pg, r, route, c5row, notional or 60.0, on)
            else:
                raise SystemExit(f"C5 v1 只支持 gate(bybit UTA 余量不足/binance funding 正在付费)")
        await r.aclose()
        await pg.close()
        return

    row, err = await snap_row(r, venue, route["symbol_fut"])
    if not row:
        raise SystemExit(f"闸3 拒: {err}")
    if row["net_ann_capital_pct"] < MIN_NET_ANN_CAP:
        raise SystemExit(f"闸3 拒: net/占用 {row['net_ann_capital_pct']:+.3f}% < {MIN_NET_ANN_CAP}%")
    print(f"闸3 基差: PASS net/占用={row['net_ann_capital_pct']:+.3f}% 龄{row['_age_sec']:.0f}s")

    async with httpx.AsyncClient() as cli:
        if venue == "bybit":
            await _open_bybit_binance(cli, pg, r, route, row, qty or 0.001, on, is_bybit=True, maker=maker)
        elif venue == "binance":
            if maker:
                print("binance maker 暂未实现,本路由走 taker(备用路由,放量前不扩)")
            await _open_bybit_binance(cli, pg, r, route, row, qty or 0.001, on, is_bybit=False, maker=False)
        elif venue == "gate":
            await _open_gate(cli, pg, r, route, row, notional or 60.0, on, maker=maker)
        elif venue == "okx":
            await _open_c4_okx_inverse(cli, pg, r, route, row, notional or 100.0, on)
        else:
            raise SystemExit(f"执行器不支持 venue={venue}")
    await r.aclose()
    await pg.close()


async def _check_total(pg, notional):
    tot = await pg.fetchval("SELECT coalesce(sum(notional_usdt),0) FROM c4_position WHERE status='OPEN'")
    if float(tot) + notional > MAX_TOTAL_NOTIONAL:
        raise SystemExit(f"闸4 拒: 总名义 {float(tot):.0f}+{notional:.2f} > {MAX_TOTAL_NOTIONAL}")


async def _open_bybit_binance(cli, pg, r, route, snaprow, qty, on, is_bybit, maker=False):
    by, bn = Bybit(), Binance()
    route_id = route["route_id"]
    if is_bybit:
        spot_ask = await by.ask(cli, "spot", route["symbol_spot"])
    else:
        spot_ask = await bn.ask(cli, "spot", route["symbol_spot"])
    notional = qty * spot_ask
    if notional > float(route["max_notional_usdt"]):
        raise SystemExit(f"闸4 拒: 名义 {notional:.2f} > 路由上限 {float(route['max_notional_usdt']):.0f}")
    await _check_total(pg, notional)
    print(f"闸4 名义: PASS {notional:.2f}U (spot_ask={spot_ask})")
    if is_bybit:
        need = (1.0 + 1.0 / LEV + BUFFER) * notional
        w = await by.wallet_usdt(cli)
        if w["avail"] < need:
            raise SystemExit(f"闸5 拒: UTA可用 {w['avail']:.2f} < 需 {need:.2f}")
        print(f"闸5 margin buffer: PASS UTA avail={w['avail']:.2f} ≥ need={need:.2f}")
    else:
        need_fut = (1.0 / LEV + BUFFER) * notional
        bal = await bn.get(cli, "https://fapi.binance.com", "/fapi/v2/balance", {})
        avail_fut = max((float(b["availableBalance"]) for b in bal if b.get("asset") == "USDT"), default=0.0)
        acct = await bn.get(cli, "https://api.binance.com", "/api/v3/account", {})
        free_spot = max((float(b["free"]) for b in acct.get("balances", []) if b.get("asset") == "USDT"), default=0.0)
        if free_spot < notional:
            raise SystemExit(f"闸5 拒: 现货侧 USDT {free_spot:.2f} < 名义 {notional:.2f}")
        if avail_fut < need_fut:
            raise SystemExit(f"闸5 拒: 合约侧可用 {avail_fut:.2f} < 需 {need_fut:.2f}")
        print(f"闸5 margin buffer: PASS spot={free_spot:.2f} fapi={avail_fut:.2f}")

    limit_px = round_step(spot_ask * 1.003, 0.1)
    tactic = ("maker: 现货 PostOnly@bid 等{}s 超时放弃 → 交割 PostOnly@ask 等{}s 超时回退市价"
              .format(MAKER_WAIT_SPOT, MAKER_WAIT_FUT)) if (maker and is_bybit) else "taker: 现货 LIMIT-IOC → 交割 MARKET"
    plan = {"tactic": tactic,
            "leg1": f"{route['venue']} SPOT BUY {qty} {route['symbol_spot']}",
            "leg2": f"{route['venue']} DELIVERY SELL {qty} {route['symbol_fut']} (lev={LEV}x)",
            "entry_basis_bps": snaprow["basis_bps"], "net_ann_capital_pct": snaprow["net_ann_capital_pct"]}
    print("执行计划:", json.dumps(plan, ensure_ascii=False))
    if not on:
        await r.lpush("dcm:c4:shadow:log", json.dumps(
            {"ts": dt.datetime.now(dt.timezone.utc).isoformat(), "route": route_id, "qty": qty, "plan": plan}, ensure_ascii=False))
        print("SHADOW 结束: 全闸 PASS,未下单")
        return

    if is_bybit:
        await by.post(cli, "/v5/position/set-leverage",
                      {"category": "linear", "symbol": route["symbol_fut"],
                       "buyLeverage": str(int(LEV)), "sellLeverage": str(int(LEV))})
        if maker:
            sbid, _sask = await by.top(cli, "spot", route["symbol_spot"])
            o1 = await by.post(cli, "/v5/order/create",
                               {"category": "spot", "symbol": route["symbol_spot"], "side": "Buy",
                                "orderType": "Limit", "timeInForce": "PostOnly",
                                "qty": f"{qty}", "price": f"{round_step(sbid, 0.1)}"})
            fq, fpx, st = await by.order_wait(cli, "spot", o1["orderId"], MAKER_WAIT_SPOT)
            if st == "open":
                await by.cancel(cli, "spot", route["symbol_spot"], o1["orderId"])
                fq, fpx, st = await by.order_result(cli, "spot", o1["orderId"])
            print(f"腿1 现货(maker): {st} filled={fq}@{fpx}")
        else:
            o1 = await by.post(cli, "/v5/order/create",
                               {"category": "spot", "symbol": route["symbol_spot"], "side": "Buy",
                                "orderType": "Limit", "timeInForce": "IOC", "qty": f"{qty}", "price": f"{limit_px}"})
            fq, fpx, st = await by.order_result(cli, "spot", o1["orderId"])
            print(f"腿1 现货: {st} filled={fq}@{fpx}")
        if fq <= 0:
            print("腿1 零成交,干净放弃")
            return
        try:
            fq2, fpx2 = 0.0, 0.0
            if maker:
                _fbid, fask = await by.top(cli, "linear", route["symbol_fut"])
                om = await by.post(cli, "/v5/order/create",
                                   {"category": "linear", "symbol": route["symbol_fut"], "side": "Sell",
                                    "orderType": "Limit", "timeInForce": "PostOnly",
                                    "qty": f"{fq}", "price": f"{round_step(fask, 0.1)}", "positionIdx": 0})
                fq2, fpx2, st2 = await by.order_wait(cli, "linear", om["orderId"], MAKER_WAIT_FUT)
                if st2 == "open":
                    await by.cancel(cli, "linear", route["symbol_fut"], om["orderId"])
                    fq2, fpx2, st2 = await by.order_result(cli, "linear", om["orderId"])
                print(f"腿2 交割空(maker尝试): {st2} filled={fq2}@{fpx2}")
            if fq2 < fq * 0.999:  # maker 未完成(或非 maker)→ 市价补齐对冲
                remain = round(fq - fq2, 8)
                o2 = await by.post(cli, "/v5/order/create",
                                   {"category": "linear", "symbol": route["symbol_fut"], "side": "Sell",
                                    "orderType": "Market", "qty": f"{remain}", "positionIdx": 0})
                q_t, px_t, st2 = await by.order_result(cli, "linear", o2["orderId"])
                if q_t + fq2 < fq * 0.999:
                    raise VenueErr(f"交割腿部分成交 {q_t + fq2}<{fq}")
                fpx2 = (fpx2 * fq2 + px_t * q_t) / (fq2 + q_t) if (fq2 + q_t) > 0 else px_t
                fq2 = fq2 + q_t
            print(f"腿2 交割空: 合计 {fq2}@{fpx2}")
        except Exception as e:  # noqa: BLE001
            await alert(r, f"C4 {route_id} 交割腿失败({repr(e)[:100]}),市价卖回现货 {fq} 回滚")
            sq, _st = await sellable(by, cli, "bybit", route["symbol_spot"], fq)
            if sq <= 0:
                await _insert_pos(pg, route, fq, fpx, None, "ROLLBACK", "回滚卖出不足一步长,须人工")
                return
            ob = await by.post(cli, "/v5/order/create",
                               {"category": "spot", "symbol": route["symbol_spot"], "side": "Sell",
                                "orderType": "Market", "qty": _fmt(sq)})
            rq, rpx, rst = await by.order_result(cli, "spot", ob["orderId"])
            await _insert_pos(pg, route, fq, fpx, None, "ROLLBACK", f"交割腿失败已卖回 {rq}@{rpx} {rst}(费扣币留尘)")
            print(f"回滚完成: 卖回 {rq}@{rpx} ({rst})")
            return
    else:
        await bn.post(cli, "https://fapi.binance.com", "/fapi/v1/leverage",
                      {"symbol": route["symbol_fut"], "leverage": int(LEV)})
        o1 = await bn.post(cli, "https://api.binance.com", "/api/v3/order",
                           {"symbol": route["symbol_spot"], "side": "BUY", "type": "LIMIT",
                            "timeInForce": "IOC", "quantity": f"{qty}", "price": f"{limit_px}"})
        fq, fpx, st = await bn.order_result(cli, "https://api.binance.com", route["symbol_spot"], o1["orderId"])
        print(f"腿1 现货: {st} filled={fq}@{fpx}")
        if fq <= 0:
            print("腿1 零成交,干净放弃")
            return
        try:
            o2 = await bn.post(cli, "https://fapi.binance.com", "/fapi/v1/order",
                               {"symbol": route["symbol_fut"], "side": "SELL", "type": "MARKET", "quantity": f"{fq}"})
            fq2, fpx2, st2 = await bn.order_result(cli, "https://fapi.binance.com", route["symbol_fut"], o2["orderId"])
            if fq2 < fq * 0.999:
                raise VenueErr(f"交割腿部分成交 {fq2}<{fq}")
            print(f"腿2 交割空: {st2} filled={fq2}@{fpx2}")
        except Exception as e:  # noqa: BLE001
            await alert(r, f"C4 {route_id} 交割腿失败({repr(e)[:100]}),市价卖回现货回滚")
            sq, _st = await sellable(bn, cli, "binance", route["symbol_spot"], fq)
            if sq <= 0:
                await _insert_pos(pg, route, fq, fpx, None, "ROLLBACK", "回滚卖出不足一步长,须人工")
                return
            ob = await bn.post(cli, "https://api.binance.com", "/api/v3/order",
                               {"symbol": route["symbol_spot"], "side": "SELL", "type": "MARKET", "quantity": _fmt(sq)})
            rq, rpx, rst = await bn.order_result(cli, "https://api.binance.com", route["symbol_spot"], ob["orderId"])
            await _insert_pos(pg, route, fq, fpx, None, "ROLLBACK", f"交割腿失败已卖回 {rq}@{rpx} {rst}(费扣币留尘)")
            print(f"回滚完成: 卖回 {rq}@{rpx} ({rst})")
            return

    pid = await _insert_pos(pg, route, fq, fpx, fpx2, "OPEN",
                            f"canary armed; snapshot net/cap={snaprow['net_ann_capital_pct']:+.3f}%")
    print(f"✅ 开仓完成 pos#{pid}: spot {fq}@{fpx} / fut空 {fq2}@{fpx2} 入场基差={(fpx2-fpx)/fpx*1e4:+.1f}bps")


async def _open_gate(cli, pg, r, route, snaprow, notional_target, on, maker=False):
    """gate 分支:张数配平 + 独立 delivery 钱包(只许 spot→delivery 划转)+ 薄盘限价 IOC;
    maker=poc(post-only):现货挂 bid 超时放弃,交割挂 ask 超时回退封顶 IOC 保对冲。"""
    gt = Gate()
    route_id = route["route_id"]
    pair, contract = route["symbol_spot"], route["symbol_fut"]
    spec = await fut_spec(contract, "gate")
    mult, tick = spec["mult"], spec["tick"]
    meta = await gt.spot_meta(cli, pair)
    amt_prec = int(meta.get("amount_precision") or 4)
    px_prec = int(meta.get("precision") or 6)
    sbid, sask = await gt.spot_book_top(cli, pair)
    fbid, fask = await gt.dlv_book_top(cli, contract)
    if fbid <= 0:
        raise SystemExit(f"闸3b 拒: 交割盘无买盘({contract} bids 空)")
    # 张数配平:qty_base = 张数×mult,现货腿同量
    contracts = max(1, int(notional_target / sask / mult))
    qty_base = round(contracts * mult, amt_prec)
    notional = qty_base * sask
    # 闸3b 实时基差复核(薄盘幻价防线)
    live_bps = (fbid - sask) / sask * 1e4
    if live_bps < float(snaprow["basis_bps"]) - LIVE_BASIS_TOL_BPS:
        raise SystemExit(f"闸3b 拒: 实时基差 {live_bps:+.1f}bps 比快照 {snaprow['basis_bps']:+.1f} 差超 {LIVE_BASIS_TOL_BPS}bps")
    print(f"闸3b 实时基差: PASS live={live_bps:+.1f}bps (快照{snaprow['basis_bps']:+.1f}) "
          f"盘口 fut_bid={fbid} spot_ask={sask}")
    if notional > float(route["max_notional_usdt"]):
        raise SystemExit(f"闸4 拒: 名义 {notional:.2f} > 路由上限 {float(route['max_notional_usdt']):.0f}")
    await _check_total(pg, notional)
    print(f"闸4 名义: PASS {notional:.2f}U ({contracts}张×{mult}={qty_base} {pair.split('_')[0]})")
    # 闸5: 独立钱包;缺口只从 spot 划转(绝不碰 perp futures 钱包)
    need_dlv = (1.0 / LEV + BUFFER) * notional
    sp_avail = await gt.spot_usdt(cli)
    dv = await gt.dlv_account(cli)
    transfer_amt = max(0.0, round(need_dlv - dv["avail"] + 1.0, 2)) if dv["avail"] < need_dlv else 0.0
    if sp_avail < notional + transfer_amt:
        raise SystemExit(f"闸5 拒: gate spot USDT {sp_avail:.2f} < 名义{notional:.2f}+划转{transfer_amt:.2f}"
                         f"(delivery avail={dv['avail']:.2f} 需{need_dlv:.2f};不动 perp 钱包)")
    print(f"闸5 margin buffer: PASS spot={sp_avail:.2f} delivery={dv['avail']:.2f} "
          f"需delivery={need_dlv:.2f} 划转计划={transfer_amt:.2f}(spot→delivery)")

    spot_limit = round_step(sask * 1.003, 10 ** -px_prec)
    fut_limit = round_step(fbid * (1 - FUT_SLIP_BPS / 1e4), tick)
    tactic = (f"maker(poc): 现货挂bid等{MAKER_WAIT_SPOT}s超时放弃 → 交割挂ask等{MAKER_WAIT_FUT}s超时回退封顶IOC"
              if maker else "taker: 现货 LIMIT-IOC → 交割 LIMIT-IOC 封顶滑点")
    plan = {"transfer": f"spot→delivery {transfer_amt:.2f}U" if transfer_amt else "无需划转",
            "tactic": tactic,
            "leg1": f"gate SPOT BUY {qty_base} {pair} @{_fmt(spot_limit)}",
            "leg2": f"gate DELIVERY SELL {contracts}张({qty_base}) {contract} @{_fmt(fut_limit)}(封顶滑点{FUT_SLIP_BPS}bps)",
            "live_basis_bps": round(live_bps, 1), "net_ann_capital_pct": snaprow["net_ann_capital_pct"]}
    print("执行计划:", json.dumps(plan, ensure_ascii=False))
    if not on:
        await r.lpush("dcm:c4:shadow:log", json.dumps(
            {"ts": dt.datetime.now(dt.timezone.utc).isoformat(), "route": route_id,
             "notional": notional, "plan": plan}, ensure_ascii=False))
        print("SHADOW 结束: 全闸 PASS,未下单")
        return

    # ===== ARMED =====
    if transfer_amt:
        await gt.transfer_spot_to_delivery(cli, transfer_amt)
        print(f"划转完成: spot→delivery {transfer_amt:.2f}U")
    print("杠杆:", await gt.try_set_leverage(cli, contract, int(LEV)))
    if maker:
        o1 = await gt.spot_order(cli, pair, "buy", qty_base, round_step(sbid, 10 ** -px_prec), tif="poc")
        fb, fpx, st = await gt.spot_order_wait(cli, pair, o1["id"], MAKER_WAIT_SPOT)
        if st == "open":
            await gt.spot_cancel(cli, pair, o1["id"])
            fb, fpx, st = await gt.spot_order_result(cli, pair, o1["id"])
        print(f"腿1 现货(maker): {st} filled={fb}@{fpx}")
    else:
        o1 = await gt.spot_order(cli, pair, "buy", qty_base, spot_limit)
        fb, fpx, st = await gt.spot_order_result(cli, pair, o1["id"])
        print(f"腿1 现货: {st} filled={fb}@{fpx}")
    if fb <= 0:
        print("腿1 零成交,干净放弃")
        return
    hedge_contracts = int(fb / mult + 1e-9)
    dust = round(fb - hedge_contracts * mult, amt_prec)
    if hedge_contracts <= 0:
        await alert(r, f"C4 {route_id} 现货成交 {fb} 不足 1 张({mult}),全量卖回")
        sq, _st = await sellable(gt, cli, "gate", pair, fb)
        ob = await gt.spot_order(cli, pair, "sell", sq, None, typ="market")
        rq, rpx, rst = await gt.spot_order_result(cli, pair, ob["id"])
        await _insert_pos(pg, route, fb, fpx, None, "ROLLBACK", f"不足1张已卖回 {rq}@{rpx}(费扣币留尘)")
        return
    try:
        fc, fpx2 = 0, 0.0
        if maker:
            _fb2, fask2 = await gt.dlv_book_top(cli, contract)
            om = await gt.dlv_order(cli, contract, -hedge_contracts,
                                    round_step(fask2 if fask2 > 0 else fbid, tick), tif="poc")
            fc, fpx2, stm = await gt.dlv_order_wait(cli, om["id"], MAKER_WAIT_FUT)
            if stm == "open":
                await gt.dlv_cancel(cli, om["id"])
                fc, fpx2, stm = await gt.dlv_order_result(cli, om["id"])
            print(f"腿2 交割空(maker尝试): {stm} filled={fc}张@{fpx2}")
        if fc < hedge_contracts:  # maker 未吃满(或非 maker)→ 封顶 IOC 补齐对冲
            fbid3, _ = await gt.dlv_book_top(cli, contract)
            o2 = await gt.dlv_order(cli, contract, -(hedge_contracts - fc),
                                    round_step((fbid3 or fbid) * (1 - FUT_SLIP_BPS / 1e4), tick))
            fc2, fpx2b, st2 = await gt.dlv_order_result(cli, o2["id"])
            if fc + fc2 > 0:
                fpx2 = (fpx2 * fc + fpx2b * fc2) / (fc + fc2) if fpx2 > 0 else fpx2b
            fc = fc + fc2
            print(f"腿2 交割空: 合计 {fc}张@{fpx2} ({st2})")
    except Exception as e:  # noqa: BLE001
        print(f"腿2 下单/查询失败: {repr(e)[:120]}")
    unhedged = round(fb - fc * mult, amt_prec)
    if fc <= 0:
        await alert(r, f"C4 {route_id} 交割腿零成交,市价卖回现货 {fb}")
        sq, _st = await sellable(gt, cli, "gate", pair, fb)
        ob = await gt.spot_order(cli, pair, "sell", sq, None, typ="market")
        rq, rpx, rst = await gt.spot_order_result(cli, pair, ob["id"])
        await _insert_pos(pg, route, fb, fpx, None, "ROLLBACK", f"交割零成交已卖回 {rq}@{rpx} {rst}(费扣币留尘)")
        print(f"回滚完成: 卖回 {rq}@{rpx}")
        return
    if unhedged > mult * 0.5:  # 超过半张的未对冲现货卖回(半张以下按 dust 保留)
        await alert(r, f"C4 {route_id} 交割部分成交 {fc}张,卖回未对冲现货 {unhedged}")
        sq, _st = await sellable(gt, cli, "gate", pair, unhedged)
        ob = await gt.spot_order(cli, pair, "sell", sq, None, typ="market")
        rq, rpx, _ = await gt.spot_order_result(cli, pair, ob["id"])
        print(f"部分回滚: 卖回 {rq}@{rpx}")
    matched = round(fc * mult, amt_prec)
    pid = await _insert_pos(pg, route, matched, fpx, fpx2, "OPEN",
                            f"canary armed; {fc}张×{mult}; dust={dust}; snapshot net/cap={snaprow['net_ann_capital_pct']:+.3f}%")
    print(f"✅ 开仓完成 pos#{pid}: spot {matched}@{fpx} / fut空 {fc}张@{fpx2} "
          f"入场基差={(fpx2-fpx)/fpx*1e4:+.1f}bps")


async def _open_c5_gate(cli, pg, r, route, c5row, notional_target, on):
    """C5 gate:LONG perp + SHORT 交割,同所双衍生品腿。张数配平两腿(mult 须一致);
    perp 侧=credit 模式保证金(现货 USDT 作押),delivery 侧缺口只从 spot 划转。
    腿序=交割空(薄腿)先行,perp 多(深腿)断后;perp 失败→交割 reduce_only 买回回滚。"""
    gt = Gate()
    route_id = route["route_id"]
    perp_sym, contract = route["symbol_spot"], route["symbol_fut"]
    spec_f = await fut_spec(contract, "gate")
    spec_p = await fut_spec(perp_sym, "gate")
    if abs(spec_f["mult"] - spec_p["mult"]) > 1e-12:
        raise SystemExit(f"两腿 mult 不一致 fut={spec_f['mult']} perp={spec_p['mult']},v1 不支持")
    mult, tick_f, tick_p = spec_f["mult"], spec_f["tick"], spec_p["tick"]
    fbid, _fask = await gt.dlv_book_top(cli, contract)
    pbid, pask = await gt.fut_book_top(cli, perp_sym)
    if fbid <= 0 or pask <= 0:
        raise SystemExit(f"闸3b 拒: 盘口缺失 fut_bid={fbid} perp_ask={pask}")
    live_bps = (fbid - pask) / pask * 1e4
    if live_bps < float(c5row["basis_bps"]) - LIVE_BASIS_TOL_BPS:
        raise SystemExit(f"闸3b 拒: 实时基差 {live_bps:+.1f}bps 比快照 {c5row['basis_bps']:+.1f} 差超 {LIVE_BASIS_TOL_BPS}")
    print(f"闸3b 实时基差: PASS live={live_bps:+.1f}bps (快照{c5row['basis_bps']:+.1f}) fut_bid={fbid} perp_ask={pask}")
    contracts = max(1, int(notional_target / pask / mult))
    qty_base = round(contracts * mult, 10)
    notional = qty_base * pask
    if notional > float(route["max_notional_usdt"]):
        raise SystemExit(f"闸4 拒: 名义 {notional:.2f} > 路由上限 {float(route['max_notional_usdt']):.0f}")
    await _check_total(pg, notional)
    print(f"闸4 名义: PASS {notional:.2f}U ({contracts}张×{mult}={qty_base})")
    # 闸5: 双侧保证金(buffer 均分两腿)
    need_side = (1.0 / LEV + BUFFER / 2) * notional
    perp_avail = await gt.fut_account_avail(cli)
    dv = await gt.dlv_account(cli)
    sp_avail = await gt.spot_usdt(cli)
    transfer_amt = max(0.0, round(need_side - dv["avail"] + 1.0, 2)) if dv["avail"] < need_side else 0.0
    if perp_avail < need_side:
        raise SystemExit(f"闸5 拒: perp侧(credit)可用 {perp_avail:.2f} < 需 {need_side:.2f}")
    if transfer_amt and sp_avail < transfer_amt:
        raise SystemExit(f"闸5 拒: spot USDT {sp_avail:.2f} 不够划转 {transfer_amt:.2f} 补 delivery(不动 perp 钱包)")
    print(f"闸5 margin: PASS perp(credit)={perp_avail:.2f} delivery={dv['avail']:.2f} "
          f"各需{need_side:.2f} 划转计划={transfer_amt:.2f}(spot→delivery)")

    fut_limit = round_step(fbid * (1 - FUT_SLIP_BPS / 1e4), tick_f)
    perp_limit = round_step(pask * (1 + FUT_SLIP_BPS / 1e4), tick_p)
    plan = {"transfer": f"spot→delivery {transfer_amt:.2f}U" if transfer_amt else "无需划转",
            "leg1": f"gate DELIVERY SELL {contracts}张({qty_base}) {contract} LIMIT-IOC @{_fmt(fut_limit)}",
            "leg2": f"gate PERP BUY {contracts}张({qty_base}) {perp_sym} LIMIT-IOC @{_fmt(perp_limit)}",
            "live_basis_bps": round(live_bps, 1),
            "hard_edge_pct": c5row["net_ann_capital_ex_funding_pct"],
            "funding_ann_pct": c5row.get("funding_ann_pct")}
    print("执行计划:", json.dumps(plan, ensure_ascii=False))
    if not on:
        await r.lpush("dcm:c4:shadow:log", json.dumps(
            {"ts": dt.datetime.now(dt.timezone.utc).isoformat(), "route": route_id,
             "notional": notional, "plan": plan}, ensure_ascii=False))
        print("SHADOW 结束: 全闸 PASS,未下单")
        return

    # ===== ARMED =====
    if transfer_amt:
        await gt.transfer_spot_to_delivery(cli, transfer_amt)
        print(f"划转完成: spot→delivery {transfer_amt:.2f}U")
    print("杠杆:", await gt.try_set_leverage(cli, contract, int(LEV)), "/",
          await gt.try_set_fut_leverage(cli, perp_sym, int(LEV)))
    o1 = await gt.dlv_order(cli, contract, -contracts, fut_limit)
    fc, fpx, st1 = await gt.dlv_order_result(cli, o1["id"])
    print(f"腿1 交割空: {st1} filled={fc}张@{fpx}")
    if fc <= 0:
        print("腿1 零成交,干净放弃")
        return
    try:
        o2 = await gt.fut_order(cli, perp_sym, fc, perp_limit)
        pc, ppx, st2 = await gt.fut_order_result(cli, o2["id"])
        if pc < fc:
            raise VenueErr(f"perp 腿部分成交 {pc}<{fc}")
        print(f"腿2 perp多: {st2} filled={pc}张@{ppx}")
    except Exception as e:  # noqa: BLE001 反向回滚:买回交割空
        await alert(r, f"C5 {route_id} perp腿失败({repr(e)[:100]}),买回交割 {fc}张 回滚")
        _fb2, fask2 = await gt.dlv_book_top(cli, contract)
        ob = await gt.dlv_order(cli, contract, fc,
                                round_step((fask2 or fpx) * (1 + FUT_SLIP_BPS / 1e4), tick_f),
                                reduce_only=True)
        rq, rpx, rst = await gt.dlv_order_result(cli, ob["id"])
        await _insert_pos(pg, route, fc * mult, None, fpx, "ROLLBACK",
                          f"perp腿失败,交割已买回 {rq}张@{rpx} {rst}")
        print(f"回滚完成: 交割买回 {rq}张@{rpx}")
        return
    matched = round(fc * mult, 10)
    pid = await _insert_pos(pg, route, matched, ppx, fpx, "OPEN",
                            f"C5 canary armed; {fc}张; 硬边际={c5row['net_ann_capital_ex_funding_pct']:+.3f}% "
                            f"funding指示={c5row.get('funding_ann_pct')}%/y")
    print(f"✅ C5 开仓完成 pos#{pid}: perp多 {matched}@{ppx} / 交割空 {fc}张@{fpx} "
          f"入场基差={(fpx - ppx) / ppx * 1e4:+.1f}bps")


async def _open_c4_okx_inverse(cli, pg, r, route, snaprow, notional_target, on):
    """okx C4-inverse:现货买币 + 空币本位交割(ctVal=USD面值/张),tdMode=cross,
    买入的币本身即空头保证金——对冲完美,理论零强平(经典 coin-margined cash&carry)。
    腿序=现货先行(保证金前置),交割空失败→现货卖回回滚。"""
    ox = Okx()
    route_id = route["route_id"]
    spot_pair, contract = route["symbol_spot"], route["symbol_fut"]
    meta = await ox.fut_meta(cli, contract)
    if meta["ctValCcy"] != "USD":
        raise SystemExit(f"v1 okx 只支持 inverse(ctValCcy=USD),{contract} 是 {meta['ctValCcy']}")
    ctval, tick = meta["ctVal"], meta["tickSz"]
    coin = route["underlying"]
    sbid, sask = await ox.top(cli, spot_pair)
    fbid, _fask = await ox.top(cli, contract)
    if sask <= 0 or fbid <= 0:
        raise SystemExit(f"闸3b 拒: 盘口缺失 spot_ask={sask} fut_bid={fbid}")
    live_bps = (fbid - sask) / sask * 1e4
    if live_bps < float(snaprow["basis_bps"]) - LIVE_BASIS_TOL_BPS:
        raise SystemExit(f"闸3b 拒: 实时基差 {live_bps:+.1f}bps 比快照 {snaprow['basis_bps']:+.1f} 差超 {LIVE_BASIS_TOL_BPS}")
    print(f"闸3b 实时基差: PASS live={live_bps:+.1f}bps (快照{snaprow['basis_bps']:+.1f})")
    contracts = max(1, int(notional_target / ctval))
    face = contracts * ctval                      # USD 面值
    base_qty = round(face / sask, 8)              # 现货腿:恰好背书 face
    if face > float(route["max_notional_usdt"]):
        raise SystemExit(f"闸4 拒: 面值 {face:.0f} > 路由上限 {float(route['max_notional_usdt']):.0f}")
    await _check_total(pg, face)
    print(f"闸4 名义: PASS face={face:.0f}USD ({contracts}张×{ctval:.0f}) 现货腿={base_qty} {coin}")
    # 闸5: USDT 够买现货(现货买完,币即保证金,无额外 USDT 需求;留 1% 费与滑点余量)
    avail = await ox.usdt_avail(cli)
    need = base_qty * sask * 1.01
    if avail < need:
        raise SystemExit(f"闸5 拒: okx USDT 可用 {avail:.2f} < 需 {need:.2f}(现货腿+1%余量)"
                         f"——账户差口 ≈{need - avail:.1f}U,跨所调款属提现治理域须人工")
    print(f"闸5 margin: PASS USDT avail={avail:.2f} ≥ need={need:.2f}(币本位空头由现货币背书,零额外保证金)")

    spot_limit = round_step(sask * 1.003, 0.1)
    fut_limit = round_step(fbid * (1 - FUT_SLIP_BPS / 1e4), tick)
    plan = {"leg1": f"okx SPOT BUY {base_qty} {spot_pair} IOC @{_fmt(spot_limit)}",
            "leg2": f"okx FUTURES SELL {contracts}张(face {face:.0f}USD) {contract} IOC @{_fmt(fut_limit)} tdMode=cross(币押)",
            "live_basis_bps": round(live_bps, 1), "net_ann_capital_pct": snaprow["net_ann_capital_pct"],
            "structure": "inverse coin-margined cash&carry(理论零强平)"}
    print("执行计划:", json.dumps(plan, ensure_ascii=False))
    if not on:
        await r.lpush("dcm:c4:shadow:log", json.dumps(
            {"ts": dt.datetime.now(dt.timezone.utc).isoformat(), "route": route_id,
             "face": face, "plan": plan}, ensure_ascii=False))
        print("SHADOW 结束: 全闸 PASS,未下单")
        return

    # ===== ARMED =====
    print("杠杆:", await ox.try_set_leverage(cli, contract, int(LEV)))
    o1 = await ox.order(cli, spot_pair, "cash", "buy", base_qty, spot_limit)
    fq, fpx, st = await ox.order_result(cli, spot_pair, o1["ordId"])
    print(f"腿1 现货: {st} filled={fq}@{fpx}")
    if fq <= 0:
        print("腿1 零成交,干净放弃")
        return
    try:
        o2 = await ox.order(cli, contract, "cross", "sell", contracts, fut_limit)
        fc, fpx2, st2 = await ox.order_result(cli, contract, o2["ordId"])
        if fc < contracts:
            raise VenueErr(f"交割腿部分成交 {fc}<{contracts}")
        print(f"腿2 交割空: {st2} filled={fc}张@{fpx2}")
    except Exception as e:  # noqa: BLE001
        await alert(r, f"C4 {route_id} 交割腿失败({repr(e)[:100]}),市价卖回现货 {fq} 回滚")
        sq, _st = await sellable(ox, cli, "okx", spot_pair, fq)
        ob = await ox.order(cli, spot_pair, "cash", "sell", sq, round_step(sbid * 0.997, 0.1))
        rq, rpx, rst = await ox.order_result(cli, spot_pair, ob["ordId"])
        await _insert_pos(pg, route, fq, fpx, None, "ROLLBACK", f"交割腿失败已卖回 {rq}@{rpx} {rst}(费扣币留尘)")
        print(f"回滚完成: 卖回 {rq}@{rpx} ({rst})")
        return
    pid = await _insert_pos(pg, route, fq, fpx, fpx2, "OPEN",
                            f"okx inverse canary; {fc}张 face={face:.0f}USD; 币押零强平结构; "
                            f"snapshot net/cap={snaprow['net_ann_capital_pct']:+.3f}%")
    p = await ox.position(cli, contract)
    print(f"✅ 开仓完成 pos#{pid}: spot {fq}@{fpx} / 交割空 {fc}张@{fpx2} "
          f"入场基差={(fpx2 - fpx) / fpx * 1e4:+.1f}bps liqPx={p.get('liqPx') or '无(全额押品)'}")


async def cmd_status():
    pg = await asyncpg.connect(PG_DSN)
    await pg.execute(_DDL)
    r = aioredis.from_url(REDIS_URL)
    on, detail = await armed_state(r)
    print(f"武装态: {'ARMED' if on else 'SHADOW'} ({detail})")
    rows = await pg.fetch("SELECT * FROM c4_position ORDER BY id")
    async with httpx.AsyncClient() as cli:
        by, gt, ox = Bybit(), Gate(), Okx()
        for x in rows:
            line = (f"pos#{x['id']} {x['status']:8s} {x['route_id']} qty={float(x['qty'])} "
                    f"spot={float(x['spot_px'] or 0)} fut={float(x['fut_px'] or 0)} "
                    f"基差入场={float(x['entry_basis_bps'] or 0):+.1f}bps")
            if x["status"] == "OPEN":
                try:
                    if x["venue"] == "bybit":
                        p = await by.position(cli, x["symbol_fut"])
                        line += f" | 交割腿 size={p.get('size')} liq={p.get('liqPrice') or 'n/a'} upnl={p.get('unrealisedPnl')}"
                    elif x["venue"] == "gate":
                        p = await gt.dlv_position(cli, x["symbol_fut"])
                        line += (f" | 交割腿 size={p.get('size')}张 liq={p.get('liq_price') or 'n/a'} "
                                 f"entry={p.get('entry_price')} upnl={p.get('unrealised_pnl')}")
                        if dict(x).get("product") == "C5":
                            pp = await gt.fut_position(cli, x["symbol_spot"])
                            line += (f" | perp腿 size={pp.get('size')}张 liq={pp.get('liq_price') or 'n/a'} "
                                     f"upnl={pp.get('unrealised_pnl')}")
                    elif x["venue"] == "okx":
                        p = await ox.position(cli, x["symbol_fut"])
                        line += (f" | 交割腿 pos={p.get('pos')}张 liq={p.get('liqPx') or '无(全额押品)'} "
                                 f"upnl={p.get('upl')}")
                    elif x["venue"] == "binance":
                        bn2 = Binance()
                        d = await bn2.get(cli, "https://fapi.binance.com", "/fapi/v2/positionRisk",
                                          {"symbol": x["symbol_fut"]})
                        pr = d[0] if isinstance(d, list) and d else {}
                        line += (f" | 永续腿 amt={pr.get('positionAmt')} liq={pr.get('liquidationPrice')} "
                                 f"upnl={pr.get('unRealizedProfit')}")
                    if dict(x).get("product") == "C1":
                        ul = str(x["symbol_fut"]).replace("USDT", "")
                        fd = await funding_daily(r, x["venue"], ul)
                        line += f" | funding日={fd if fd is not None else '?'}%(转负=close纪律)"
                except Exception as e:  # noqa: BLE001
                    line += f" | 交割腿查询失败 {repr(e)[:60]}"
            print(line)
    if not rows:
        print("(无仓位记录)")
    await r.aclose()
    await pg.close()


async def cmd_close(pos_id):
    pg = await asyncpg.connect(PG_DSN)
    r = aioredis.from_url(REDIS_URL)
    x = await pg.fetchrow("SELECT * FROM c4_position WHERE id=$1", pos_id)
    if not x or x["status"] != "OPEN":
        raise SystemExit(f"pos#{pos_id} 不存在或非 OPEN")
    on, detail = await armed_state(r)
    if not on:
        raise SystemExit(f"close 是真钱动作,须武装({detail})")
    qty = float(x["qty"])
    async with httpx.AsyncClient() as cli:
        if x["venue"] == "bybit":
            by = Bybit()
            o2 = await by.post(cli, "/v5/order/create",
                               {"category": "linear", "symbol": x["symbol_fut"], "side": "Buy",
                                "orderType": "Market", "qty": f"{qty}", "reduceOnly": True, "positionIdx": 0})
            q2, p2, s2 = await by.order_result(cli, "linear", o2["orderId"])
            sq, _st = await sellable(by, cli, "bybit", x["symbol_spot"], qty)
            o1 = await by.post(cli, "/v5/order/create",
                               {"category": "spot", "symbol": x["symbol_spot"], "side": "Sell",
                                "orderType": "Market", "qty": _fmt(sq)})
            q1, p1, s1 = await by.order_result(cli, "spot", o1["orderId"])
        elif x["venue"] == "gate":
            gt = Gate()
            spec = await fut_spec(x["symbol_fut"], "gate")
            contracts = int(round(qty / spec["mult"]))
            _, fask = await gt.dlv_book_top(cli, x["symbol_fut"])
            buy_limit = round_step(fask * (1 + FUT_SLIP_BPS / 1e4), spec["tick"])
            o2 = await gt.dlv_order(cli, x["symbol_fut"], contracts, buy_limit, reduce_only=True)
            q2c, p2, s2 = await gt.dlv_order_result(cli, o2["id"])
            q2 = q2c * spec["mult"]
            if dict(x).get("product") == "C5":
                # C5 近腿=perp 多,reduce_only 卖出平仓(封顶滑点)
                pspec = await fut_spec(x["symbol_spot"], "gate")
                pbid, _pa = await gt.fut_book_top(cli, x["symbol_spot"])
                sell_limit = round_step(pbid * (1 - FUT_SLIP_BPS / 1e4), pspec["tick"])
                o1 = await gt.fut_order(cli, x["symbol_spot"], -contracts, sell_limit, reduce_only=True)
                q1c, p1, s1 = await gt.fut_order_result(cli, o1["id"])
                q1 = q1c * pspec["mult"]
            else:
                sq, _st = await sellable(gt, cli, "gate", x["symbol_spot"], qty)
                o1 = await gt.spot_order(cli, x["symbol_spot"], "sell", sq, None, typ="market")
                q1, p1, s1 = await gt.spot_order_result(cli, x["symbol_spot"], o1["id"])
        elif x["venue"] == "okx":
            ox = Okx()
            meta = await ox.fut_meta(cli, x["symbol_fut"])
            p = await ox.position(cli, x["symbol_fut"])
            n = abs(int(float(p.get("pos") or 0)))
            if n:
                _fb, fask = await ox.top(cli, x["symbol_fut"])
                o2 = await ox.order(cli, x["symbol_fut"], "cross", "buy", n,
                                    round_step(fask * (1 + FUT_SLIP_BPS / 1e4), meta["tickSz"]),
                                    reduce_only=True)
                q2, p2, s2 = await ox.order_result(cli, x["symbol_fut"], o2["ordId"])
            else:
                q2, p2, s2 = 0, None, "已无交割仓"
            sbid, _sa = await ox.top(cli, x["symbol_spot"])
            sq, _st = await sellable(ox, cli, "okx", x["symbol_spot"], qty)
            o1 = await ox.order(cli, x["symbol_spot"], "cash", "sell", sq, round_step(sbid * 0.997, 0.1))
            q1, p1, s1 = await ox.order_result(cli, x["symbol_spot"], o1["ordId"])
        else:
            bn = Binance()
            o2 = await bn.post(cli, "https://fapi.binance.com", "/fapi/v1/order",
                               {"symbol": x["symbol_fut"], "side": "BUY", "type": "MARKET",
                                "quantity": f"{qty}", "reduceOnly": "true"})
            q2, p2, s2 = await bn.order_result(cli, "https://fapi.binance.com", x["symbol_fut"], o2["orderId"])
            sq, _st = await sellable(bn, cli, "binance", x["symbol_spot"], qty)
            o1 = await bn.post(cli, "https://api.binance.com", "/api/v3/order",
                               {"symbol": x["symbol_spot"], "side": "SELL", "type": "MARKET",
                                "quantity": _fmt(sq)})
            q1, p1, s1 = await bn.order_result(cli, "https://api.binance.com", x["symbol_spot"], o1["orderId"])
    await pg.execute("UPDATE c4_position SET status='CLOSED', closed_at=now(), close_spot_px=$1, close_fut_px=$2 WHERE id=$3",
                     p1, p2, pos_id)
    await _audit_intent(pg, "close", symbol=x["symbol_spot"], venue=x["venue"],
                        reason=f"c4_exec 平仓 pos#{pos_id}",
                        extra={"c4_position_id": pos_id, "symbol_fut": x["symbol_fut"],
                               "qty": qty, "close_spot_px": p1, "close_fut_px": p2})
    print(f"✅ 平仓 pos#{pos_id}: fut买回 {q2}@{p2}({s2}) / spot卖出 {q1}@{p1}({s1})")
    await r.aclose()
    await pg.close()


async def cmd_settle(pos_id):
    """到期处置:future 已交割结算(仓位消失)后,卖出现货腿收尾,标记 CLOSED。
    只在 now>expiry 且实盘确认交割腿已消失时执行;真钱动作须武装。"""
    pg = await asyncpg.connect(PG_DSN)
    r = aioredis.from_url(REDIS_URL)
    x = await pg.fetchrow("SELECT * FROM c4_position WHERE id=$1", pos_id)
    if not x or x["status"] != "OPEN":
        raise SystemExit(f"pos#{pos_id} 不存在或非 OPEN")
    if dict(x).get("product") == "C1":
        raise SystemExit("C1 无到期锚(funding 收益型),退出请用 close(funding 转负纪律)")
    auth = await pg.fetchrow("SELECT expiry FROM c4_route_authorization WHERE route_id=$1", x["route_id"])
    now = dt.datetime.now(dt.timezone.utc)
    if not auth or not auth["expiry"] or now < auth["expiry"]:
        raise SystemExit(f"未到期(expiry={auth['expiry'] if auth else '?'}),提前退出请用 close")
    on, detail = await armed_state(r)
    if not on:
        raise SystemExit(f"settle 是真钱动作,须武装({detail})")
    qty = float(x["qty"])
    async with httpx.AsyncClient() as cli:
        # ① 确认交割腿已结算消失(还在=交易所未交割完,等)
        if x["venue"] == "bybit":
            by = Bybit()
            p = await by.position(cli, x["symbol_fut"])
            if p and float(p.get("size") or 0) != 0:
                raise SystemExit(f"交割腿仍在场 size={p.get('size')},交易所尚未结算,稍后再试")
            sq, _st = await sellable(by, cli, "bybit", x["symbol_spot"], qty)
            o1 = await by.post(cli, "/v5/order/create",
                               {"category": "spot", "symbol": x["symbol_spot"], "side": "Sell",
                                "orderType": "Market", "qty": _fmt(sq)})
            q1, p1, s1 = await by.order_result(cli, "spot", o1["orderId"])
        elif x["venue"] == "gate":
            gt = Gate()
            p = await gt.dlv_position(cli, x["symbol_fut"])
            if p and float(p.get("size") or 0) != 0:
                raise SystemExit(f"交割腿仍在场 size={p.get('size')},交易所尚未结算,稍后再试")
            if dict(x).get("product") == "C5":
                pspec = await fut_spec(x["symbol_spot"], "gate")
                contracts = int(round(qty / pspec["mult"]))
                pbid, _pa = await gt.fut_book_top(cli, x["symbol_spot"])
                o1 = await gt.fut_order(cli, x["symbol_spot"], -contracts,
                                        round_step(pbid * (1 - FUT_SLIP_BPS / 1e4), pspec["tick"]),
                                        reduce_only=True)
                q1c, p1, s1 = await gt.fut_order_result(cli, o1["id"])
                q1 = q1c * pspec["mult"]
            else:
                sq, _st = await sellable(gt, cli, "gate", x["symbol_spot"], qty)
                o1 = await gt.spot_order(cli, x["symbol_spot"], "sell", sq, None, typ="market")
                q1, p1, s1 = await gt.spot_order_result(cli, x["symbol_spot"], o1["id"])
        elif x["venue"] == "okx":
            ox = Okx()
            p = await ox.position(cli, x["symbol_fut"])
            if p and float(p.get("pos") or 0) != 0:
                raise SystemExit(f"交割腿仍在场 pos={p.get('pos')},交易所尚未结算,稍后再试")
            sbid, _sa = await ox.top(cli, x["symbol_spot"])
            sq, _st = await sellable(ox, cli, "okx", x["symbol_spot"], qty)
            o1 = await ox.order(cli, x["symbol_spot"], "cash", "sell", sq, round_step(sbid * 0.997, 0.1))
            q1, p1, s1 = await ox.order_result(cli, x["symbol_spot"], o1["ordId"])
        else:
            bn = Binance()
            d = await bn.get(cli, "https://fapi.binance.com", "/fapi/v2/positionRisk", {"symbol": x["symbol_fut"]})
            amt = float((d[0] if isinstance(d, list) and d else {}).get("positionAmt") or 0)
            if amt != 0:
                raise SystemExit(f"交割腿仍在场 {amt},交易所尚未结算,稍后再试")
            sq, _st = await sellable(bn, cli, "binance", x["symbol_spot"], qty)
            o1 = await bn.post(cli, "https://api.binance.com", "/api/v3/order",
                               {"symbol": x["symbol_spot"], "side": "SELL", "type": "MARKET", "quantity": _fmt(sq)})
            q1, p1, s1 = await bn.order_result(cli, "https://api.binance.com", x["symbol_spot"], o1["orderId"])
    await pg.execute("UPDATE c4_position SET status='CLOSED', closed_at=now(), close_spot_px=$1, "
                     "note=coalesce(note,'')||' | SETTLED@expiry 现货收尾 '||$2 WHERE id=$3",
                     p1, f"{q1}@{p1}({s1})", pos_id)
    await _audit_intent(pg, "close", symbol=x["symbol_spot"], venue=x["venue"],
                        reason=f"c4_exec 到期交割收尾 pos#{pos_id}",
                        extra={"c4_position_id": pos_id, "symbol_fut": x["symbol_fut"],
                               "qty": qty, "settle": True, "close_spot_px": p1})
    print(f"✅ 到期处置 pos#{pos_id}: 交割已结算,现货卖出 {q1}@{p1}({s1})")
    await r.aclose()
    await pg.close()


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    cmd = args[0]
    kv = {}
    for i, a in enumerate(args):
        if a.startswith("--") and i + 1 < len(args):
            kv[a[2:]] = args[i + 1]
    if cmd == "preflight":
        asyncio.run(cmd_preflight())
    elif cmd == "open":
        asyncio.run(cmd_open(kv["route"],
                             qty=float(kv["qty"]) if "qty" in kv else None,
                             notional=float(kv["notional"]) if "notional" in kv else None,
                             maker=str(kv.get("maker", "")).lower() in ("1", "true", "yes")))
    elif cmd == "status":
        asyncio.run(cmd_status())
    elif cmd == "close":
        asyncio.run(cmd_close(int(kv["pos"])))
    elif cmd == "settle":
        asyncio.run(cmd_settle(int(kv["pos"])))
    else:
        print(f"未知命令 {cmd}")


if __name__ == "__main__":
    main()
