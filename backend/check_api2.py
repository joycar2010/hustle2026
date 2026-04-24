import asyncio
from app.services.account_service import account_data_service
from app.core.database import AsyncSessionLocal
from sqlalchemy import text, select
from app.models.account import Account

async def check():
    async with AsyncSessionLocal() as db:
        uid_r = await db.execute(text("SELECT user_id FROM users WHERE username = 'cq456'"))
        uid = uid_r.scalar()
        accs_r = await db.execute(select(Account).where(Account.user_id == uid))
        accounts = accs_r.scalars().all()
        print(f'Found {len(accounts)} accounts')

        result = await account_data_service.get_aggregated_account_data(accounts)
        for acc in result.get('accounts', []):
            name = acc.get('account_name')
            pid = acc.get('platform_id')
            pc = acc.get('pair_code')
            mt5 = acc.get('is_mt5_account')
            b = acc.get('balance')
            if hasattr(b, 'model_dump'):
                bd = b.model_dump()
            elif hasattr(b, 'dict'):
                bd = b.dict()
            else:
                bd = b
            ll = bd.get('long_liquidation_price')
            sl = bd.get('short_liquidation_price')
            print(f'Account: {name} platform={pid} pair={pc} mt5={mt5} long_liq={ll} short_liq={sl}')

asyncio.run(check())
