"""币安 Simple Earn 活期(Flexible)客户端——PM 质押层(蓝图底仓层"双份收益")。

用途:basis 期现底仓的现货多腿闲置持有 → 申购活期理财吃利息;平仓前先赎回。
只做**活期**(实时赎回,不锁仓)——定期(Locked)会把平仓路径钉死在锁仓期上,禁用。

纪律:
- 申购/赎回都是"钱包内部移动",不出账户,风险=赎回延迟(活期即时,极端下秒级);
- 平仓流程必须"赎回确认 → 现货余额到位 → 再卖"两段式,绝不带着理财仓卖现货;
- 产品不存在(长尾币无活期产品)→ 如实返回 None,调用方跳过,绝不报错阻塞主流程。
"""
import hashlib
import hmac
import time

import httpx

SAPI = "https://api.binance.com"


class BinanceEarn:
    def __init__(self, cfg: dict):
        self.key, self.secret = cfg["key"], cfg["secret"]

    def _signed_qs(self, params: dict) -> str:
        params = {**params, "timestamp": int(time.time() * 1000), "recvWindow": 5000}
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        sig = hmac.new(self.secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
        return f"{qs}&signature={sig}"

    @property
    def _hdr(self):
        return {"X-MBX-APIKEY": self.key}

    async def flexible_product(self, cli: httpx.AsyncClient, asset: str) -> dict | None:
        """该资产的活期产品(取首个可申购的);无产品返回 None。"""
        r = (await cli.get(
            f"{SAPI}/sapi/v1/simple-earn/flexible/list?"
            + self._signed_qs({"asset": asset, "size": 10}), headers=self._hdr)).json()
        for row in (r.get("rows") or []):
            if row.get("canPurchase") in (True, "true", "TRUE", None):
                return row
        return None

    async def subscribe(self, cli: httpx.AsyncClient, product_id: str, amount) -> tuple[bool, dict]:
        r = (await cli.post(
            f"{SAPI}/sapi/v1/simple-earn/flexible/subscribe?"
            + self._signed_qs({"productId": product_id, "amount": f"{amount}"}),
            headers=self._hdr)).json()
        if r.get("success") is True or r.get("purchaseId"):
            return True, r
        return False, r

    async def redeem_all(self, cli: httpx.AsyncClient, product_id: str) -> tuple[bool, dict]:
        r = (await cli.post(
            f"{SAPI}/sapi/v1/simple-earn/flexible/redeem?"
            + self._signed_qs({"productId": product_id, "redeemAll": "true"}),
            headers=self._hdr)).json()
        if r.get("success") is True or r.get("redeemId"):
            return True, r
        return False, r

    async def position(self, cli: httpx.AsyncClient, asset: str) -> float:
        """该资产活期在管总额(base 数量);无仓返回 0。"""
        r = (await cli.get(
            f"{SAPI}/sapi/v1/simple-earn/flexible/position?"
            + self._signed_qs({"asset": asset, "size": 10}), headers=self._hdr)).json()
        total = 0.0
        for row in (r.get("rows") or []):
            try:
                total += float(row.get("totalAmount") or 0)
            except (TypeError, ValueError):
                continue
        return total

    async def spot_free(self, cli: httpx.AsyncClient, asset: str) -> float:
        """现货可用余额(赎回确认用)。"""
        r = (await cli.get(
            f"{SAPI}/api/v3/account?" + self._signed_qs({"omitZeroBalances": "true"}),
            headers=self._hdr)).json()
        for b in (r.get("balances") or []):
            if b.get("asset") == asset:
                return float(b.get("free") or 0)
        return 0.0
