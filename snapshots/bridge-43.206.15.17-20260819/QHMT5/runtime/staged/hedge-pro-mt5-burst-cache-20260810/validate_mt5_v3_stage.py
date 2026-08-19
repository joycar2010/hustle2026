import json

import app.main as main


required = {
    ("POST", "/mt5/order"),
    ("POST", "/mt5/position/close"),
    ("POST", "/mt5/position/close-all"),
    ("POST", "/mt5/cancel-all"),
    ("GET", "/mt5/positions"),
    ("GET", "/mt5/order-status/{request_id}"),
}
actual = {
    (method, route.path)
    for route in main.app.routes
    for method in (route.methods or set())
}
missing = sorted(required - actual)
duplicates = {
    path: sum(1 for route in main.app.routes if route.path == path)
    for _, path in required
}
duplicates = {path: count for path, count in duplicates.items() if count != 1}
result = {
    "app_version": main.app.version,
    "missing_routes": missing,
    "duplicate_routes": duplicates,
    "positions_cache_ttl_ms": main.POSITIONS_CACHE_TTL_MS,
    "positions_stale_max_ms": main.POSITIONS_STALE_MAX_MS,
    "requote_retries": main.REQUOTE_RETRIES,
    "sync_wait_sec": main.EXEC_SYNC_WAIT_SEC,
    "mt5_connected_during_import": main.mgr.connected,
}
print(json.dumps(result, separators=(",", ":")))
main._EXECUTION.shutdown()
main._MT5_API_EXECUTOR.shutdown(wait=True, cancel_futures=False)
if missing or duplicates or main.app.version != "3.0.0" or main.mgr.connected:
    raise SystemExit(2)
