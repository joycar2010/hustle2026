"""Add per-target cap editing + LLM health endpoints to agent.py"""
path = "/data/hustle2026/backend/app/api/v1/agent.py"
with open(path, "r") as f:
    c = f.read()

# Insert after toggle_scope_target function
anchor = """    from app.services.agent.scope import toggle_target
    ok = await toggle_target(db, target_id, req.enabled)
    return {'ok': ok, 'enabled': req.enabled}"""
assert anchor in c, "toggle_scope_target anchor not found"

new_code = """    from app.services.agent.scope import toggle_target
    ok = await toggle_target(db, target_id, req.enabled)
    return {'ok': ok, 'enabled': req.enabled}


class TargetCapsUpdateReq(BaseModel):
    single_trade_pct: Optional[float] = None
    total_position_pct: Optional[float] = None
    daily_volume_pct: Optional[float] = None


@router.post('/scope/targets/{target_id}/caps')
async def update_target_caps(target_id: int, req: TargetCapsUpdateReq,
                             db: AsyncSession = Depends(get_db),
                             user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    import json as _json
    existing = await db.execute(text(
        "SELECT value FROM agent_target_config WHERE target_id = :t AND key = 'position_caps'"
    ), {'t': target_id})
    row = existing.first()
    if row:
        caps = _json.loads(row[0]) if isinstance(row[0], str) else (row[0] if isinstance(row[0], dict) else {})
    else:
        gr = await db.execute(text("SELECT value FROM agent_active_config WHERE key = 'position_caps'"))
        g = gr.first()
        caps = _json.loads(g[0]) if g and isinstance(g[0], str) else {'single_trade_pct': 0.10, 'total_position_pct': 0.50, 'daily_volume_pct': 5.0}
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
        ), {'v': caps_json, 't': target_id, 'u': user_id})
    else:
        await db.execute(text(
            "INSERT INTO agent_target_config (target_id, key, value, updated_at, updated_by) VALUES (:t, 'position_caps', :v, now(), CAST(:u AS UUID))"
        ), {'t': target_id, 'v': caps_json, 'u': user_id})
    await db.commit()
    config_loader.invalidate(target_id=target_id)
    return {'ok': True, 'caps': caps}


@router.get('/scope/targets/{target_id}/caps')
async def get_target_caps(target_id: int,
                          db: AsyncSession = Depends(get_db),
                          user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    cfg = await config_loader.load_config(db, target_id=target_id)
    caps = cfg.get('position_caps', {})
    global_cfg = await config_loader.load_config(db)
    global_caps = global_cfg.get('position_caps', {})
    return {'caps': caps, 'global_caps': global_caps, 'target_id': target_id}


@router.get('/llm-health')
async def llm_health(db: AsyncSession = Depends(get_db),
                     user_id: str = Depends(require_admin)) -> Dict[str, Any]:
    import time as _time
    try:
        from app.services.agent.codex_client import (
            _is_circuit_open, _circuit_open_until, _failure_log,
            _pick_fallback_model, _CIRCUIT_WINDOW, _CIRCUIT_THRESHOLD,
            get_runtime_model_and_stream,
        )
        now = _time.time()
        recent_failures = sum(1 for t in _failure_log if now - t < _CIRCUIT_WINDOW)
        model, streaming = await get_runtime_model_and_stream(db)
        return {
            'circuit_open': _is_circuit_open(),
            'circuit_open_until': _circuit_open_until if _is_circuit_open() else None,
            'recent_failures': recent_failures,
            'failure_threshold': _CIRCUIT_THRESHOLD,
            'failure_window_s': _CIRCUIT_WINDOW,
            'primary_model': model,
            'fallback_model': _pick_fallback_model(model),
        }
    except Exception as e:
        return {'error': str(e), 'circuit_open': False}"""

c = c.replace(anchor, new_code, 1)

with open(path, "w") as f:
    f.write(c)
print("agent.py: per-target caps + LLM health endpoints added")
