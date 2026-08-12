
# === P1.3: tick缓存统计端点 ===
@app.get("/api/admin/tick_cache_stats")
def get_tick_cache_stats():
    """查询tick缓存使用统计"""
    try:
        keys = R.keys("bridge:*:tick:*")

        stats = {
            "total_cached_symbols": len(keys),
            "cached_ticks": []
        }

        for key in keys[:10]:
            data = R.hgetall(key)
            if data:
                stats["cached_ticks"].append({
                    "key": key,
                    "symbol": data.get('symbol'),
                    "pushed_at": data.get('pushed_at'),
                    "bid": data.get('bid'),
                    "ask": data.get('ask')
                })

        return stats
    except Exception as e:
        return {"error": str(e), "total_cached_symbols": 0}
