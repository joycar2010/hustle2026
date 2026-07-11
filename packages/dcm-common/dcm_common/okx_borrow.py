"""OKX 借币执行原语(coin ①b 多venue借币;每个方法均经真金 canary 验证 2026-07-11)。

⚠️OKX 借币模型与币安根本不同(canary 实证):
- 无"显式借币持有"(币安 /sapi/v1/margin/borrow 那种两相);VIP loan 端点 borrow-repay 返 59307 不适用。
- **借币=cross 保证金卖单**:卖一个不持有的币(tdMode=cross)即自动借入并做空,autoLoan=off 不阻碍。
- **还币=买回该币**:买回借入量即自动抵偿 cross 债务。
- 对冲用同所永续(SAND-USDT-SWAP,ctVal=10 即 1 张=10 SAND,posSide=net)。

canary 验证要点(务必编码进执行器):
- 现货卖:市价 tgtCcy=base_ccy(sz=币量)可;或限价须在价格带内(卖有下限/买有上限,越界 51138)。
- 现货**买回不支持 tgtCcy=base_ccy**→必须限价穿价买(sz=base 币量,px 在带内)。
- 平永续:reduceOnly + 反向市价。
- 铁律:卖单成交=已裸空,对冲/平仓失败=裸腿,须逐所裸空网兜底(见 coin naked_short_guard 逐所化)。

用途:①b-2 引擎集成的验证建块。key=joycar002 专用子账户(B 机 .okx_borrow.env,与 dualperp 隔离)。
"""
import base64
import hashlib
import hmac
import json
import time

import httpx

BASE = "https://www.okx.com"


class OkxBorrow:
    def __init__(self, cfg: dict):
        self.key, self.secret, self.passphrase = cfg["key"], cfg["secret"], cfg["passphrase"]
        self.ct_val: dict[str, float] = {}   # 永续每张 base 数

    def _hdr(self, ts, method, path, body=""):
        sign = base64.b64encode(
            hmac.new(self.secret.encode(), (ts + method + path + body).encode(), hashlib.sha256).digest()).decode()
        return {"OK-ACCESS-KEY": self.key, "OK-ACCESS-SIGN": sign, "OK-ACCESS-TIMESTAMP": ts,
                "OK-ACCESS-PASSPHRASE": self.passphrase, "Content-Type": "application/json"}

    async def _req(self, cli, method, path, body=None):
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + ".000Z"
        b = json.dumps(body) if body else ""
        h = self._hdr(ts, method, path, b)
        if method == "GET":
            return (await cli.get(BASE + path, headers=h)).json()
        return (await cli.post(BASE + path, headers=h, content=b)).json()

    async def max_borrowable(self, cli, base: str) -> float:
        """USDT 抵押、cross 下 base 币最大可借量。无杠杆对/查询失败→0。"""
        r = await self._req(cli, "GET",
                            f"/api/v5/account/max-loan?instId={base}-USDT&mgnMode=cross&mgnCcy=USDT")
        if str(r.get("code")) == "0" and r.get("data"):
            return float(r["data"][0].get("maxLoan") or 0)
        return 0.0

    async def interest_rate(self, cli, base: str) -> float:
        """base 币借币利率(小时)。"""
        r = await self._req(cli, "GET", f"/api/v5/account/interest-rate?ccy={base}")
        if str(r.get("code")) == "0" and r.get("data"):
            return float(r["data"][0].get("interestRate") or 0)
        return 0.0

    async def borrow_by_sell(self, cli, base: str, qty_base: float) -> tuple[bool, dict]:
        """借币=市价 cross 卖 qty_base 个 base 币(自动借入做空)。返回 (ok, {ordId, filled, avgPx})。"""
        o = await self._req(cli, "POST", "/api/v5/trade/order", {
            "instId": f"{base}-USDT", "tdMode": "cross", "side": "sell",
            "ordType": "market", "sz": f"{qty_base}", "tgtCcy": "base_ccy", "ccy": "USDT"})
        if str(o.get("code")) != "0":
            return False, {"err": (o.get("data") or [{}])[0].get("sMsg") or o.get("msg"), "raw": o}
        return True, {"ordId": o["data"][0]["ordId"]}

    async def repay_by_buy(self, cli, base: str, qty_base: float, ref_px: float) -> tuple[bool, dict]:
        """还币=穿价限价买回 qty_base(市价买不支持 tgtCcy=base_ccy,必须限价)。ref_px×1.005 确保成交且在带内。"""
        px = round(ref_px * 1.005, 6)
        o = await self._req(cli, "POST", "/api/v5/trade/order", {
            "instId": f"{base}-USDT", "tdMode": "cross", "side": "buy",
            "ordType": "limit", "px": f"{px}", "sz": f"{qty_base}", "ccy": "USDT"})
        if str(o.get("code")) != "0":
            return False, {"err": (o.get("data") or [{}])[0].get("sMsg") or o.get("msg"), "raw": o}
        return True, {"ordId": o["data"][0]["ordId"]}

    async def _ct_val(self, cli, base: str) -> float:
        if base not in self.ct_val:
            r = await self._req(cli, "GET",
                                f"/api/v5/public/instruments?instType=SWAP&instId={base}-USDT-SWAP")
            self.ct_val[base] = float(r["data"][0]["ctVal"]) if (str(r.get("code")) == "0" and r.get("data")) else 1.0
        return self.ct_val[base]

    async def hedge_perp(self, cli, base: str, qty_base: float, side: str) -> tuple[bool, dict]:
        """同所永续对冲:side=buy(多,对冲现货短)/sell。qty_base→张数(÷ctVal 取整)。"""
        cv = await self._ct_val(cli, base)
        contracts = max(1, int(qty_base / cv))
        o = await self._req(cli, "POST", "/api/v5/trade/order", {
            "instId": f"{base}-USDT-SWAP", "tdMode": "cross", "side": side,
            "posSide": "net", "ordType": "market", "sz": f"{contracts}"})
        if str(o.get("code")) != "0":
            return False, {"err": (o.get("data") or [{}])[0].get("sMsg") or o.get("msg"), "raw": o}
        return True, {"ordId": o["data"][0]["ordId"], "contracts": contracts}

    async def close_perp(self, cli, base: str, contracts: int, side: str) -> tuple[bool, dict]:
        """平永续:reduceOnly 反向市价。side=平多传 sell/平空传 buy。"""
        o = await self._req(cli, "POST", "/api/v5/trade/order", {
            "instId": f"{base}-USDT-SWAP", "tdMode": "cross", "side": side, "posSide": "net",
            "ordType": "market", "sz": f"{contracts}", "reduceOnly": "true"})
        return str(o.get("code")) == "0", {"raw": o}

    async def debt(self, cli, base: str) -> float:
        """base 币当前 cross 债务(正数=欠;0=无债务)。"""
        r = await self._req(cli, "GET", "/api/v5/account/balance")
        if str(r.get("code")) != "0":
            return 0.0
        for c in r["data"][0].get("details", []):
            if c.get("ccy") == base:
                liab = c.get("liab") or "0"
                try:
                    return abs(float(liab))
                except (TypeError, ValueError):
                    return 0.0
        return 0.0

    async def perp_position(self, cli, base: str) -> int:
        """同所永续净张数(带符号)。"""
        r = await self._req(cli, "GET", f"/api/v5/account/positions?instId={base}-USDT-SWAP")
        if str(r.get("code")) == "0" and r.get("data"):
            try:
                return int(float(r["data"][0].get("pos") or 0))
            except (TypeError, ValueError):
                return 0
        return 0
