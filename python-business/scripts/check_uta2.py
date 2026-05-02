"""Check UTA (Unified Trading Account) sub-accounts via various endpoints."""
import asyncio
import sys
sys.path.insert(0, "/home/ec2-user/hustlecoin-cex/python-business")

from app.db.session import SessionLocal
from app.db.models import SubAccount
from engine.trading.binance_trading import BinanceTradingClient, SPOT_BASE, FUTURES_BASE

PAPI_BASE = "https://papi.binance.com"


async def check_one(acc):
    print(f"=== ID={acc.id} | {acc.note} | {acc.email} ===")
    async with BinanceTradingClient(acc.api_key, acc.api_secret) as client:

        # 1. Spot account (works)
        try:
            resp = await client._request("GET", f"{SPOT_BASE}/api/v3/account", signed=True)
            for b in resp.get("balances", []):
                free = float(b["free"])
                locked = float(b["locked"])
                if free > 0.0001 or locked > 0.0001:
                    print(f"  现货 {b['asset']}: free={b['free']}, locked={b['locked']}")
        except Exception as e:
            print(f"  现货: {e}")

        # 2. Portfolio Margin / UTA account info
        try:
            resp = await client._request("GET", f"{PAPI_BASE}/papi/v1/balance", signed=True)
            for b in resp:
                total = float(b.get("totalWalletBalance", 0))
                if total > 0.001:
                    print(f"  PAPI余额 {b['asset']}: total={b.get('totalWalletBalance')}, available={b.get('availableBalance')}")
        except Exception as e:
            print(f"  PAPI余额: {e}")

        # 3. papi/v1/um/account (USDT-M futures under portfolio margin)
        try:
            resp = await client._request("GET", f"{PAPI_BASE}/papi/v1/um/account", signed=True)
            print(f"  PAPI-UM: totalWallet={resp.get('totalWalletBalance')}, available={resp.get('availableBalance')}, pnl={resp.get('totalUnrealizedProfit')}")
        except Exception as e:
            print(f"  PAPI-UM: {e}")

        # 4. Try fapi v3 balance (UTA-specific)
        try:
            resp = await client._request("GET", f"{FUTURES_BASE}/fapi/v3/balance", signed=True)
            for b in resp:
                bal = float(b.get("balance", 0))
                if bal > 0.001:
                    print(f"  FAPI-v3余额 {b['asset']}: balance={b['balance']}")
            if not any(float(b.get("balance", 0)) > 0.001 for b in resp):
                print(f"  FAPI-v3余额: 返回成功但无余额")
        except Exception as e:
            print(f"  FAPI-v3余额: {e}")

        # 5. Try fapi v3 account
        try:
            resp = await client._request("GET", f"{FUTURES_BASE}/fapi/v3/account", signed=True)
            print(f"  FAPI-v3账户: totalWallet={resp.get('totalWalletBalance')}, available={resp.get('availableBalance')}")
        except Exception as e:
            print(f"  FAPI-v3账户: {e}")

        # 6. Account type check
        try:
            resp = await client._request("GET", f"{SPOT_BASE}/sapi/v1/account/apiRestrictions", signed=True)
            print(f"  API权限: enableFutures={resp.get('enableFutures')}, enableSpotAndMarginTrading={resp.get('enableSpotAndMarginTrading')}, enablePortfolioMarginTrading={resp.get('enablePortfolioMarginTrading')}, tradingAuthorityExpirationTime={resp.get('tradingAuthorityExpirationTime')}")
        except Exception as e:
            print(f"  API权限: {e}")

    print()


async def main():
    db = SessionLocal()
    accounts = db.query(SubAccount).order_by(SubAccount.id).all()
    db.close()
    for acc in accounts:
        await check_one(acc)


asyncio.run(main())
