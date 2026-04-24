import asyncio
from app.services.account_service import account_data_service
from app.core.database import AsyncSessionLocal
from sqlalchemy import text, select
from app.models.account import Account

async def check():
    async with AsyncSessionLocal() as db:
        uid_r = await db.execute(text("SELECT user_id FROM users WHERE username = 'cq987'"))
        uid = uid_r.scalar()
        accs_r = await db.execute(select(Account).where(Account.user_id == uid))
        accounts = list(accs_r.scalars().all())

        # Find the OKX account
        okx_acc = [a for a in accounts if a.platform_id == 5]
        if not okx_acc:
            print('No OKX account found')
            return

        acc = okx_acc[0]
        print(f'Testing OKX account: {acc.account_name} (id={acc.account_id})')

        # Test direct OKX API call
        from app.services.okx_client import OKXClient
        from app.utils.proxy import build_proxy_url
        proxy_url = build_proxy_url(acc.proxy_config)
        print(f'Proxy: {proxy_url}')

        okx = OKXClient(
            api_key=acc.api_key or "",
            api_secret=acc.api_secret or "",
            passphrase=acc.passphrase or "",
            proxy_url=proxy_url,
        )
        try:
            bal = await okx.get_account_balance()
            print(f'Raw balance response: {bal}')
            total_eq = float(bal.get("totalEq", 0))
            details = bal.get("details", [])
            avail = sum(float(d.get("availBal", 0)) for d in details)
            print(f'totalEq={total_eq}, availBal={avail}')
            for d in details:
                print(f'  ccy={d.get("ccy")} eq={d.get("eq")} availBal={d.get("availBal")} cashBal={d.get("cashBal")}')
        except Exception as e:
            print(f'OKX API error: {e}')
        finally:
            await okx.close()

asyncio.run(check())
