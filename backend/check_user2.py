import asyncio
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

async def check():
    async with AsyncSessionLocal() as db:
        r = await db.execute(text("SELECT user_id FROM users WHERE username='cq456'"))
        row = r.fetchone()
        if not row:
            print('User cq456 not found')
            return
        uid = str(row[0])
        print(f'User ID: {uid}')

        r2 = await db.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='accounts' ORDER BY ordinal_position"))
        print('Accounts columns:', [r[0] for r in r2.fetchall()])

        r3 = await db.execute(text("SELECT account_id, platform_id, account_name FROM accounts WHERE user_id = :uid"), {"uid": uid})
        accs = r3.fetchall()
        acc_ids = [str(a[0]) for a in accs]
        print(f'Accounts: {len(accs)}')
        for a in accs:
            print(f'  acc={a[0]} platform={a[1]} name={a[2]}')

        r4 = await db.execute(text(
            "SELECT pair_code, account_a_id, account_b_id FROM user_pair_accounts WHERE account_a_id = ANY(:ids) OR account_b_id = ANY(:ids)"
        ), {"ids": acc_ids})
        pairs = r4.fetchall()
        print(f'Pair mappings: {len(pairs)}')
        for p in pairs:
            print(f'  pair={p[0]} a={p[1]} b={p[2]}')

asyncio.run(check())
