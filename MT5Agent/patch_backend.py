"""
1. Patch codex_decider.py: auto-create agent_proposals row for non-noop decisions
2. Patch agent.py: add endpoint for per-target cap editing + LLM health endpoint
"""
import json

# ── 1. codex_decider.py: add auto-proposal creation ──
path1 = "/data/hustle2026/backend/app/services/agent/codex_decider.py"
with open(path1, "r") as f:
    c1 = f.read()

# After "await db.commit()" (line 135), add auto-proposal insert for non-noop actions
old_commit = """    decision_id = res.scalar_one()
    await db.execute(text('UPDATE agent_state SET last_decision_at=now() WHERE id=1'))
    await db.commit()"""

new_commit = """    decision_id = res.scalar_one()
    await db.execute(text('UPDATE agent_state SET last_decision_at=now() WHERE id=1'))
    # Auto-create proposal record for non-noop decisions (independent audit trail)
    if proposal_dict.get('action') not in (None, 'noop'):
        try:
            await db.execute(text(\"\"\"
                INSERT INTO agent_proposals
                    (created_at, target_id, scope_user_id, scope_pair_code, title, description,
                     status, source_decision_id, proposal_snapshot)
                VALUES (now(), :tid, :uid, :pc,
                        :title, :desc, :status, :did, CAST(:snap AS JSONB))
            \"\"\"), {
                'tid': ctx.target_id if ctx else None,
                'uid': str(ctx.user_id) if ctx else None,
                'pc': ctx.pair_code if ctx else None,
                'title': f"{proposal_dict.get('action', 'unknown')} {ctx.pair_code if ctx else 'XAU'}",
                'desc': proposal_dict.get('reason', ''),
                'status': verdict,
                'did': decision_id,
                'snap': json.dumps(proposal_dict),
            })
        except Exception as _pe:
            logger.warning(f'[decider] auto-proposal insert failed: {_pe}')
    await db.commit()"""

if old_commit in c1:
    c1 = c1.replace(old_commit, new_commit, 1)
    print("codex_decider: auto-proposal insert added")
else:
    print("WARN: codex_decider commit anchor not found, trying alternate...")
    # Try simpler anchor
    old2 = "    decision_id = res.scalar_one()\n"
    if old2 in c1:
        # Find the next await db.commit() after it
        idx = c1.find(old2)
        commit_idx = c1.find("    await db.commit()", idx)
        if commit_idx > 0:
            insert_point = commit_idx
            proposal_code = """
    # Auto-create proposal record for non-noop decisions (independent audit trail)
    if proposal_dict.get('action') not in (None, 'noop'):
        try:
            await db.execute(text(\"\"\"
                INSERT INTO agent_proposals
                    (created_at, target_id, scope_user_id, scope_pair_code, title, description,
                     status, source_decision_id, proposal_snapshot)
                VALUES (now(), :tid, :uid, :pc,
                        :title, :desc, :status, :did, CAST(:snap AS JSONB))
            \"\"\"), {
                'tid': ctx.target_id if ctx else None,
                'uid': str(ctx.user_id) if ctx else None,
                'pc': ctx.pair_code if ctx else None,
                'title': f"{proposal_dict.get('action', 'unknown')} {ctx.pair_code if ctx else 'XAU'}",
                'desc': proposal_dict.get('reason', ''),
                'status': verdict,
                'did': decision_id,
                'snap': json.dumps(proposal_dict),
            })
        except Exception as _pe:
            logger.warning(f'[decider] auto-proposal insert failed: {_pe}')
"""
            c1 = c1[:insert_point] + proposal_code + c1[insert_point:]
            print("codex_decider: auto-proposal insert added (alternate)")
        else:
            print("ERROR: could not find commit after decision_id")
    else:
        print("ERROR: decision_id anchor not found")

# Ensure json import exists
if "\nimport json\n" not in c1 and "\nimport json," not in c1:
    c1 = c1.replace("import logging", "import json\nimport logging", 1)

with open(path1, "w") as f:
    f.write(c1)

# ── 2. agent.py: add per-target cap update endpoint + LLM health ──
path2 = "/data/hustle2026/backend/app/api/v1/agent.py"
with open(path2, "r") as f:
    c2 = f.read()

# Add per-target cap update endpoint after the existing scope targets toggle
toggle_anchor = "async def toggle_target("
toggle_idx = c2.find(toggle_anchor)
if toggle_idx < 0:
    print("WARN: toggle_target not found in agent.py")
else:
    # Find end of toggle_target function (next @router or end of function)
    next_router = c2.find("\n@router.", toggle_idx + 100)
    if next_router > 0:
        new_endpoints = """

class TargetCapsReq(BaseModel):
    single_trade_pct: Optional[float] = None
    total_position_pct: Optional[float] = None
    daily_volume_pct: Optional[float] = None


@router.post('/scope/targets/{tid}/caps')
async def update_target_caps(tid: int, req: TargetCapsReq,
                             db: AsyncSession = Depends(get_db),
                             user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    \"\"\"Update per-target position caps (hot-reloaded via config_loader 5s TTL).\"\"\"
    import json as _json
    # Load existing or start from global defaults
    existing = await db.execute(text(
        "SELECT value FROM agent_target_config WHERE target_id = :t AND key = 'position_caps'"
    ), {'t': tid})
    row = existing.first()
    if row:
        caps = _json.loads(row[0]) if isinstance(row[0], str) else row[0]
    else:
        global_row = await db.execute(text(
            "SELECT value FROM agent_active_config WHERE key = 'position_caps'"
        ))
        gr = global_row.first()
        caps = _json.loads(gr[0]) if gr and isinstance(gr[0], str) else {'single_trade_pct': 0.10, 'total_position_pct': 0.50, 'daily_volume_pct': 5.0}

    if req.single_trade_pct is not None:
        caps['single_trade_pct'] = req.single_trade_pct
    if req.total_position_pct is not None:
        caps['total_position_pct'] = req.total_position_pct
    if req.daily_volume_pct is not None:
        caps['daily_volume_pct'] = req.daily_volume_pct

    caps_json = _json.dumps(caps)
    if row:
        await db.execute(text(
            "UPDATE agent_target_config SET value = :v, updated_at = now(), updated_by = CAST(:u AS UUID) WHERE target_id = :t AND key = 'position_caps'"
        ), {'v': caps_json, 't': tid, 'u': user_id})
    else:
        await db.execute(text(
            "INSERT INTO agent_target_config (target_id, key, value, updated_at, updated_by) VALUES (:t, 'position_caps', :v, now(), CAST(:u AS UUID))"
        ), {'t': tid, 'v': caps_json, 'u': user_id})
    await db.commit()
    config_loader.invalidate(target_id=tid)
    return {'ok': True, 'caps': caps}


@router.get('/scope/targets/{tid}/caps')
async def get_target_caps(tid: int,
                          db: AsyncSession = Depends(get_db),
                          user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    \"\"\"Get effective position caps for a target (merged global + override).\"\"\"
    cfg = await config_loader.load_config(db, target_id=tid)
    caps = cfg.get('position_caps', {})
    # Also return global for comparison
    global_cfg = await config_loader.load_config(db)
    global_caps = global_cfg.get('position_caps', {})
    return {'caps': caps, 'global_caps': global_caps, 'target_id': tid}


@router.get('/llm-health')
async def llm_health(db: AsyncSession = Depends(get_db),
                     user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    \"\"\"LLM service health: circuit breaker status, recent failures, fallback model.\"\"\"
    from app.services.agent.codex_client import (
        _is_circuit_open, _circuit_open_until, _failure_log,
        _pick_fallback_model, _CIRCUIT_WINDOW, _CIRCUIT_THRESHOLD
    )
    import time
    now = time.time()
    recent_failures = sum(1 for t in _failure_log if now - t < _CIRCUIT_WINDOW)
    model, _ = await get_runtime_model_and_stream(db) if hasattr(db, 'execute') else ('unknown', True)
    try:
        from app.services.agent.codex_client import get_runtime_model_and_stream
        model, streaming = await get_runtime_model_and_stream(db)
    except:
        model, streaming = 'unknown', True
    return {
        'circuit_open': _is_circuit_open(),
        'circuit_open_until': _circuit_open_until if _is_circuit_open() else None,
        'recent_failures': recent_failures,
        'failure_threshold': _CIRCUIT_THRESHOLD,
        'failure_window_s': _CIRCUIT_WINDOW,
        'primary_model': model,
        'fallback_model': _pick_fallback_model(model),
        'failure_timestamps': [t for t in _failure_log if now - t < _CIRCUIT_WINDOW],
    }

"""
        c2 = c2[:next_router] + new_endpoints + c2[next_router:]
        print("agent.py: per-target caps + LLM health endpoints added")

# Ensure imports
if "from app.services.agent.codex_client import get_runtime_model_and_stream" not in c2:
    # It might already be imported elsewhere; just ensure the endpoint uses it correctly
    pass

with open(path2, "w") as f:
    f.write(c2)
print("Backend patches complete")
