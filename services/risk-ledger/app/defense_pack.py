"""AccountDefensePack v0(V5 §6.8/批次6)——venue 限制事件的可验证证据包。

汇总:当轮策略快照该 venue 段 + 活跃/近期 Incident + restriction_event + 模式历史 +
提现事实/基线 + 修复意图。只提供可验证记录用于解释和申诉,不宣称绝对证明,
不保证平台恢复账户。人工修正=新包,不覆盖旧包(不可变)。
触发:①venue 进入 REDUCE_ONLY+ 时自动生成(risk-ledger _post_policy 钩);②CLI 手动:
    ~/dexcexmix/venv/bin/python defense_pack.py <venue>
"""
import asyncio
import json
import os
import sys
import time


async def generate(pool, venue: str, pol: dict | None = None, trigger_rule: str = "manual") -> int | None:
    """采集并落 account_defense_pack;返回包 id。任何子查询失败如实标注,不假装完整。"""
    if pool is None:
        return None
    content: dict = {"venue": venue, "generated_ts": int(time.time()),
                     "policy_snapshot": (pol or {}).get("venues", {}).get(venue),
                     "policy_epoch": (pol or {}).get("policy_epoch"),
                     "policy_version": (pol or {}).get("policy_version")}

    async def _rows(key, sql, *args):
        try:
            content[key] = [dict(r) for r in await pool.fetch(sql, *args)]
        except Exception as e:  # noqa: BLE001
            content[key] = {"error": repr(e)[:120]}

    await _rows("incidents",
                "SELECT incident_key, state, severity, title, detail, hit_count, "
                "first_seen::text, last_seen::text FROM venue_incident WHERE venue=$1 "
                "ORDER BY id DESC LIMIT 50", venue)
    await _rows("restriction_events",
                "SELECT signal_type, severity, raw_code, raw_payload, hit_count, "
                "first_seen::text, last_seen::text FROM restriction_event WHERE venue=$1 "
                "ORDER BY last_seen DESC LIMIT 50", venue)
    await _rows("mode_transitions",
                "SELECT before_mode, after_mode, reason, policy_epoch, policy_version, "
                "recorded_at::text FROM venue_mode_transition WHERE scope_key=$1 "
                "ORDER BY id DESC LIMIT 50", venue)
    await _rows("withdrawal_observations",
                "SELECT asset, network, amount::text, status, venue_tx_id, chain_tx, "
                "initiated_at::text, confirmed_at::text, duration_sec::text "
                "FROM withdrawal_observation WHERE venue=$1 ORDER BY id DESC LIMIT 50", venue)
    await _rows("withdrawal_baselines",
                "SELECT p50_sec::text, p95_sec::text, sample_n, pending_count, recent_failures, "
                "computed_at::text FROM withdrawal_baseline WHERE venue=$1 "
                "ORDER BY id DESC LIMIT 20", venue)
    await _rows("repair_intents",
                "SELECT intent_id, kind, state, feasible, reason, close_reason, "
                "est_notional_usdt::text, executor_fence, created_at::text "
                "FROM risk_repair_intent WHERE venue=$1 ORDER BY id DESC LIMIT 30", venue)
    try:
        row = await pool.fetchrow(
            "INSERT INTO account_defense_pack(venue, trigger_rule, content) VALUES($1,$2,$3::jsonb) "
            "RETURNING id", venue, trigger_rule, json.dumps(content, ensure_ascii=False, default=str))
        return int(row["id"])
    except Exception:  # noqa: BLE001
        return None


async def _cli():
    import asyncpg
    venue = sys.argv[1]
    pool = await asyncpg.create_pool(os.environ["DCM_PG_DSN"], min_size=1, max_size=1)
    pid = await generate(pool, venue, trigger_rule="manual-cli")
    print(f"DEFENSE_PACK id={pid} venue={venue}")


if __name__ == "__main__":
    asyncio.run(_cli())
