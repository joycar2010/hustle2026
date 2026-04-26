import asyncio, asyncpg

MIGRATE_SQL = """
INSERT INTO agent_proposals (created_at, scope_user_id, scope_pair_code, title, description, status, source_decision_id, proposal_snapshot)
SELECT
    d.created_at,
    d.scope_user_id,
    d.scope_pair_code,
    COALESCE(
        (d.proposal::jsonb ->> 'action') || ' ' || COALESCE(d.scope_pair_code, 'XAU'),
        'decision-' || d.id::text
    ),
    d.proposal::jsonb ->> 'reason',
    CASE
        WHEN d.verdict = 'executed' THEN 'approved'
        WHEN d.verdict = 'rejected' THEN 'rejected'
        WHEN d.verdict = 'pending' THEN 'pending'
        ELSE 'rejected'
    END,
    d.id,
    d.proposal::jsonb
FROM agent_decisions d
WHERE d.proposal IS NOT NULL
  AND d.proposal != ''
  AND length(d.proposal) > 10
  AND d.proposal LIKE '{%'
  AND (d.proposal::jsonb ->> 'action') IS NOT NULL
  AND (d.proposal::jsonb ->> 'action') != 'noop'
ORDER BY d.created_at DESC
LIMIT 500;
"""

async def main():
    conn = await asyncpg.connect('postgresql://postgres:Lk106504@127.0.0.1:5432/postgres')
    count = await conn.fetchval("SELECT count(*) FROM agent_proposals")
    if count > 0:
        print(f"Already has {count} rows, skipping")
    else:
        await conn.execute(MIGRATE_SQL)
        new_count = await conn.fetchval("SELECT count(*) FROM agent_proposals")
        print(f"Migrated {new_count} proposals")
    await conn.close()

asyncio.run(main())
