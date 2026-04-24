import asyncio
import json
from app.core.database import AsyncSessionLocal
from app.services.account_service import account_service
from app.models.account import Account
from sqlalchemy import text

async def check():
    async with AsyncSessionLocal() as db:
        r = await db.execute(text("SELECT account_id, user_id, platform_id, account_name, api_key, api_secret, is_mt5_account, mt5_id, mt5_server, mt5_password, proxy_config, account_role FROM accounts WHERE user_id = (SELECT user_id FROM users WHERE username='cq456')"))
        rows = r.fetchall()

        accounts = []
        for row in rows:
            acc = Account()
            acc.account_id = row[0]
            acc.user_id = row[1]
            acc.platform_id = row[2]
            acc.account_name = row[3]
            acc.api_key = row[4]
            acc.api_secret = row[5]
            acc.is_mt5_account = row[6]
            acc.mt5_id = row[7]
            acc.mt5_server = row[8]
            acc.mt5_password = row[9]
            acc.proxy_config = row[10]
            acc.account_role = row[11]
            acc.is_active = True
            accounts.append(acc)

        result = await account_service.get_aggregated_account_data(accounts)

        for acc in result.get("accounts", []):
            print(f"\n=== Account: {acc.get('account_name')} (platform={acc.get('platform_id')}) ===")
            print(f"  pair_code: {acc.get('pair_code')}")
            print(f"  is_mt5_account: {acc.get('is_mt5_account')}")
            b = acc.get("balance", {})
            if hasattr(b, 'dict'):
                b = b.dict()
            elif hasattr(b, 'model_dump'):
                b = b.model_dump()
            print(f"  long_liquidation_price: {b.get('long_liquidation_price')}")
            print(f"  short_liquidation_price: {b.get('short_liquidation_price')}")

asyncio.run(check())
