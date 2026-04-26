"""
Patch codex_decider.py to auto-create agent_proposals rows from non-noop decisions.
This bridges the gap between inline decision proposals and the independent proposals table.
"""
path = "/data/hustle2026/backend/app/services/agent/codex_decider.py"
with open(path, "r") as f:
    c = f.read()

# Find where decision is persisted and add proposal auto-creation after it
# Look for the INSERT INTO agent_decisions pattern
anchor = "await db.commit()"
# We need to find the specific commit after decision insert
# Let's add a function that creates a proposal from a decision

# Add the auto-proposal function near the top, after imports
import_anchor = "from app.services.agent.guard import"
assert import_anchor in c, f"import anchor not found"

auto_proposal_func = '''from app.services.agent.guard import'''

# Actually, let's just add a helper and call it after decision persist.
# Find the section where decision_id is returned after INSERT

# Look for the persist pattern
persist_anchor = "decision_id = res.scalar_one()"
if persist_anchor not in c:
    # Try alternate
    persist_anchor = "decision_id ="

print("Checking codex_decider structure...")
# Let's just read and find the persist logic
import re
matches = list(re.finditer(r'decision_id\s*=', c))
print(f"Found {len(matches)} decision_id assignments")
for m in matches:
    print(f"  at pos {m.start()}: ...{c[m.start():m.start()+80]}...")

# Find the commit after decision insert
commits = [(m.start(), c[max(0,m.start()-100):m.start()+50]) for m in re.finditer(r'await db\.commit\(\)', c)]
print(f"\nFound {len(commits)} await db.commit()")
for pos, ctx in commits:
    print(f"  at pos {pos}: ...{ctx[-60:]}...")
