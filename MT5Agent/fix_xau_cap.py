import asyncio, asyncpg, json

async def do():
    conn = await asyncpg.connect('postgresql://postgres:Lk106504@127.0.0.1:5432/postgres')
    new_caps = json.dumps({'daily_volume_pct': 5.0, 'single_trade_pct': 0.25, 'total_position_pct': 0.50})
    await conn.execute(
        "UPDATE agent_target_config SET value = $1, updated_at = now() WHERE target_id = 2 AND key = 'position_caps'",
        new_caps
    )
    r = await conn.fetchrow("SELECT value FROM agent_target_config WHERE target_id = 2 AND key = 'position_caps'")
    print('XAU caps updated:', r['value'])
    await conn.close()

asyncio.run(do())
