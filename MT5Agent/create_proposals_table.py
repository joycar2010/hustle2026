"""Create agent_proposals table and migrate inline proposals from agent_decisions."""
import asyncio
import asyncpg

DDL = """
-- agent_proposals: independent proposal workflow
CREATE TABLE IF NOT EXISTS agent_proposals (
    id              SERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    target_id       INTEGER REFERENCES agent_scope_targets(id),
    scope_user_id   UUID,
    scope_pair_code VARCHAR(20),
    title           VARCHAR(200),
    description     TEXT,
    config_diff     JSONB,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','approved','rejected','rolled_back')),
    reviewed_by     UUID,
    reviewed_at     TIMESTAMPTZ,
    review_reason   TEXT,
    source_decision_id INTEGER,
    proposal_snapshot JSONB
);
CREATE INDEX IF NOT EXISTS idx_agent_proposals_status ON agent_proposals(status);
CREATE INDEX IF NOT EXISTS idx_agent_proposals_target ON agent_proposals(target_id);

-- audit trail for proposals
CREATE TABLE IF NOT EXISTS agent_proposal_audit (
    id           SERIAL PRIMARY KEY,
    proposal_id  INTEGER NOT NULL REFERENCES agent_proposals(id),
    action       VARCHAR(20) NOT NULL,
    performed_by UUID,
    performed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    reason       TEXT,
    snapshot     JSONB
);
CREATE INDEX IF NOT EXISTS idx_agent_proposal_audit_pid ON agent_proposal_audit(proposal_id);
"""

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
  AND (d.proposal::jsonb ->> 'action') IS NOT NULL
  AND (d.proposal::jsonb ->> 'action') != 'noop'
ORDER BY d.created_at DESC
LIMIT 500;
"""

async def main():
    conn = await asyncpg.connect('postgresql://postgres:Lk106504@127.0.0.1:5432/postgres')

    # Create tables
    await conn.execute(DDL)
    print("Tables created: agent_proposals, agent_proposal_audit")

    # Check if already migrated
    count = await conn.fetchval("SELECT count(*) FROM agent_proposals")
    if count > 0:
        print(f"agent_proposals already has {count} rows, skipping migration")
    else:
        # Migrate from decisions
        result = await conn.execute(MIGRATE_SQL)
        new_count = await conn.fetchval("SELECT count(*) FROM agent_proposals")
        print(f"Migrated {new_count} proposals from agent_decisions")

    await conn.close()

asyncio.run(main())
