"""RealVenue 适配器(V4.0 §6.1)—— 与混沌测试的 SimVenue **同一套接口**,
换上它 exec_core 即武装执行器。**只在 B 机(执行面,有密钥)运行**。
安全铁律:
- place()/cancel() 硬门控:非 DCM_EXEC_ARMED=true 或 symbol 不在 DCM_EXEC_ARM_SYMBOLS → 直接拒绝,绝不下单;
- 读路径(query/position)先行验证:证明签名+解析正确,再谈武装;
- 确定性 clientOrderId 幂等:重试先 query 再 place(exec_core 已保证)。
本文件当前只投产 query/position(读);place 仅占位+门控,武装另行专场。
"""
import base64
import hashlib
import hmac
import os
import time
from urllib.parse import urlencode

import httpx

# 与 exec_core 一致的状态常量(此处内联,B 上可独立部署)
FILLED, ACK, PARTIAL, NOTFOUND, REJECT, TIMEOUT = \
    "FILLED", "ACK", "PARTIAL", "NOTFOUND", "REJECT", "TIMEOUT"

BINANCE_FAPI = "https://fapi.binance.com"
BINANCE_SPOT = "https://api.binance.com"


class BinanceRealVenue:
    """binance 永续/现货 读适配器 + 门控下单。key/secret 从环境(B 机 .env / cred-agent)。"""

    def __init__(self, key: str = "", secret: str = ""):
        self.key = key or os.environ.get("BINANCE_KEY", "")
        self.secret = secret or os.environ.get("BINANCE_SECRET", "")
        self.armed = os.environ.get("DCM_EXEC_ARMED", "false").lower() == "true"
        self.arm_symbols = {s.strip() for s in os.environ.get("DCM_EXEC_ARM_SYMBOLS", "").split(",") if s.strip()}

    def _sign(self, params: dict) -> str:
        q = urlencode({**params, "timestamp": int(time.time() * 1000), "recvWindow": 5000})
        sig = hmac.new(self.secret.encode(), q.encode(), hashlib.sha256).hexdigest()
        return f"{q}&signature={sig}"

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
    async def query(self, cid: str, symbol: str = "", market: str = "perp") -> dict:
        """按 clientOrderId 查订单状态 → exec_core 接口 dict。找不到=NOTFOUND(幂等安全)。"""
        base, path = (BINANCE_FAPI, "/fapi/v1/order") if market == "perp" else (BINANCE_SPOT, "/api/v3/order")
        try:
            code, d = await self._get(base, path, {"symbol": symbol, "origClientOrderId": cid})
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

    # ---------- 下单路径(硬门控,当前不投产) ----------
    async def place(self, cid: str, leg: dict) -> dict:
        sym = leg.get("symbol", "")
        if not self.armed:
            raise PermissionError(f"exec 未武装(DCM_EXEC_ARMED!=true),拒绝下单 {cid}")
        if sym not in self.arm_symbols:
            raise PermissionError(f"{sym} 不在武装白名单 {self.arm_symbols},拒绝下单 {cid}")
        raise NotImplementedError("place 真下单实现待武装专场(混沌已过,接线时启用)")

    async def cancel(self, cid: str, symbol: str = "", market: str = "perp") -> None:
        if not self.armed:
            raise PermissionError("exec 未武装,拒绝撤单")
        raise NotImplementedError("cancel 待武装专场")


class BybitRealVenue:
    """bybit 永续读适配器(v5 签名:HMAC-SHA256(ts+key+recv+query))。读路径。"""

    def __init__(self, key="", secret=""):
        self.key = key or os.environ.get("BYBIT_KEY", "")
        self.secret = secret or os.environ.get("BYBIT_SECRET", "")

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


class GateRealVenue:
    """gate USDT 永续读适配器(v4 签名:HMAC-SHA512 五段)。size 单位=张,×乘数=base。"""

    def __init__(self, key="", secret=""):
        self.key = key or os.environ.get("GATE_KEY", "")
        self.secret = secret or os.environ.get("GATE_SECRET", "")
        self._mult = None

    def _sign(self, method, path, query=""):
        ts = str(int(time.time()))
        body_hash = hashlib.sha512(b"").hexdigest()
        s = f"{method}\n{path}\n{query}\n{body_hash}\n{ts}"
        sign = hmac.new(self.secret.encode(), s.encode(), hashlib.sha512).hexdigest()
        return {"KEY": self.key, "Timestamp": ts, "SIGN": sign, "Accept": "application/json"}

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


class BitgetRealVenue:
    """bitget USDT 永续读适配器(base64(HMAC-SHA256(ts+method+path+body)))。total=base。"""

    def __init__(self, key="", secret="", passphrase=""):
        self.key = key or os.environ.get("BITGET_KEY", "")
        self.secret = secret or os.environ.get("BITGET_SECRET", "")
        self.passphrase = passphrase or os.environ.get("BITGET_PASSPHRASE", "")

    async def all_positions(self) -> dict:
        ts = str(int(time.time() * 1000))
        path = "/api/v2/mix/position/all-position"
        query = "productType=USDT-FUTURES&marginCoin=USDT"
        prehash = ts + "GET" + path + "?" + query
        sign = base64.b64encode(hmac.new(self.secret.encode(), prehash.encode(), hashlib.sha256).digest()).decode()
        try:
            async with httpx.AsyncClient(timeout=15) as cli:
                r = await cli.get(f"https://api.bitget.com{path}?{query}",
                                  headers={"ACCESS-KEY": self.key, "ACCESS-SIGN": sign,
                                           "ACCESS-TIMESTAMP": ts, "ACCESS-PASSPHRASE": self.passphrase,
                                           "locale": "en-US", "Content-Type": "application/json"})
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
    return {"binance": BinanceRealVenue, "bybit": BybitRealVenue,
            "gate": GateRealVenue, "bitget": BitgetRealVenue}.get(name, lambda: None)()
