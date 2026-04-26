import sys
path = "/data/hustle2026/backend/app/services/okx_client.py"
with open(path, "r") as f:
    c = f.read()

new_methods = '''
    async def get_account_balance(self, ccy: str = "") -> Dict[str, Any]:
        """GET /api/v5/account/balance — trading account balance."""
        params = {}
        if ccy:
            params["ccy"] = ccy
        resp = await self._request("GET", "/api/v5/account/balance", params=params or None)
        if str(resp.get("code")) != "0":
            logger.warning(f"[OKX] account/balance code={resp.get('code')} msg={resp.get('msg')}")
            return {}
        data = resp.get("data") or []
        return data[0] if data else {}

    async def get_positions(self, inst_type: str = "SWAP") -> List[Dict[str, Any]]:
        """GET /api/v5/account/positions — open positions."""
        params = {"instType": inst_type}
        resp = await self._request("GET", "/api/v5/account/positions", params=params)
        if str(resp.get("code")) != "0":
            logger.warning(f"[OKX] positions code={resp.get('code')} msg={resp.get('msg')}")
            return []
        data = resp.get("data") or []
        return data if isinstance(data, list) else []
'''

# Insert before get_open_orders
anchor = "    async def get_open_orders("
assert anchor in c, "anchor not found"
c = c.replace(anchor, new_methods + "\n" + anchor, 1)

with open(path, "w") as f:
    f.write(c)
print("OKX client methods added")
