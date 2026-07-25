"""
RECON 自动化处理器 — ORPHAN_CLAIM (MGR / C1 / C2 / C3)
处理引擎声称在管但实盘已平的情况
"""
import asyncio
import asyncpg
import json
import time
from datetime import datetime
from typing import Optional


class OrphanClaimHandler:
    """处理 ORPHAN_CLAIM: 引擎声称在管,实盘已平"""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def can_handle(self, break_type: str) -> bool:
        return break_type == "ORPHAN_CLAIM"

    async def handle(self, break_info: dict) -> dict:
        """
        根据 source 前缀路由到对应引擎的处理逻辑:
          MGR:  → _handle_manager_orphan
          C1:   → _handle_c1_orphan (basis 引擎)
          C2:   → _handle_c2_orphan (dualperp 引擎)
          C3:   → _handle_c3_orphan (coin Redis 快照)
        """
        source = break_info.get("source", "")
        venue = break_info.get("venue", "")
        symbol = break_info.get("symbol", "")

        result = {"action": "UNKNOWN", "success": False, "details": {}, "error": None}

        try:
            if source.startswith("MGR:"):
                result = await self._handle_manager_orphan(venue, symbol, source)
            elif source.startswith("C1:"):
                result = await self._handle_c1_orphan(venue, symbol, source)
            elif source.startswith("C2:"):
                result = await self._handle_c2_orphan(venue, symbol, source)
            elif source.startswith("C3:"):
                result = await self._handle_c3_orphan(symbol, source)
            else:
                result["error"] = f"Unknown source type: {source}"

            await self._log_fix(break_info, result)

        except Exception as e:
            result["error"] = str(e)
            result["success"] = False

        return result

    # ── MGR ───────────────────────────────────────────────────────────────────
    async def _handle_manager_orphan(self, venue: str, symbol: str, source: str) -> dict:
        """Manager 接管仓:引擎声称在管,实盘已平 → 关闭对应 exec_saga"""
        parts = source.split(":")
        if len(parts) < 3:
            return {"action": "SKIP", "success": False, "error": "Invalid MGR source format"}

        pair_id = parts[1]

        sagas = await self.pool.fetch(
            """
            SELECT saga_id, state, legs
            FROM exec_saga
            WHERE state IN ('PROPOSED', 'EXECUTING', 'PAUSED')
            AND legs::text LIKE $1
            ORDER BY created_at DESC
            LIMIT 5
            """,
            f'%"{venue}"%"{symbol}"%'
        )

        if not sagas:
            return {
                "action": "NO_SAGA_FOUND",
                "success": True,
                "details": {"note": "No active saga found, orphan claim may be stale"}
            }

        target_saga = None
        for saga in sagas:
            legs = json.loads(saga["legs"]) if isinstance(saga["legs"], str) else saga["legs"]
            for leg in legs:
                if leg.get("venue") == venue and leg.get("symbol") == symbol:
                    target_saga = saga
                    break
            if target_saga:
                break

        if not target_saga:
            return {
                "action": "NO_MATCHING_SAGA",
                "success": True,
                "details": {"note": "No saga with matching leg found"}
            }

        await self.pool.execute(
            """
            UPDATE exec_saga
            SET state = 'CLOSED',
                updated_at = $1,
                note = COALESCE(note, '') || ' [RECON auto-cleared ORPHAN_CLAIM]'
            WHERE saga_id = $2
            """,
            datetime.fromtimestamp(time.time()),
            target_saga["saga_id"]
        )

        return {
            "action": "SAGA_CLOSED",
            "success": True,
            "details": {
                "saga_id": target_saga["saga_id"],
                "prev_state": target_saga["state"],
                "pair_id": pair_id
            }
        }

    # ── C1 (basis) ────────────────────────────────────────────────────────────
    async def _handle_c1_orphan(self, venue: str, symbol: str, source: str) -> dict:
        """
        C1 basis 引擎:basis_positions 表
        source 格式: C1:{symbol}:perp_short
        """
        parts = source.split(":")
        if len(parts) < 3:
            return {"action": "C1_INVALID_SOURCE", "success": False,
                    "error": f"Invalid C1 source format: {source}"}

        basis_symbol = parts[1]

        positions = await self.pool.fetch(
            """
            SELECT id, symbol, state, qty_base, created_at
            FROM basis_positions
            WHERE symbol = $1 AND state NOT IN ('CLOSED', 'FAILED')
            ORDER BY created_at DESC
            LIMIT 5
            """,
            basis_symbol
        )

        if not positions:
            return {
                "action": "C1_NO_ACTIVE_POSITION",
                "success": True,
                "details": {"note": "No active basis position found", "symbol": basis_symbol}
            }

        if venue != "binance":
            return {
                "action": "C1_VENUE_MISMATCH",
                "success": False,
                "error": f"C1 only supports binance, got: {venue}"
            }

        target = positions[0]

        await self.pool.execute(
            """
            UPDATE basis_positions
            SET state = 'CLOSED',
                closed_at = NOW(),
                error_message = COALESCE(error_message, '') ||
                                ' [RECON auto-cleared ORPHAN_CLAIM]',
                updated_at = NOW()
            WHERE id = $1
            """,
            target["id"]
        )

        return {
            "action": "C1_POSITION_CLOSED",
            "success": True,
            "details": {
                "position_id": target["id"],
                "symbol": basis_symbol,
                "old_state": target["state"],
                "qty_base": float(target["qty_base"] or 0)
            }
        }

    # ── C2 (dualperp) ─────────────────────────────────────────────────────────
    async def _handle_c2_orphan(self, venue: str, symbol: str, source: str) -> dict:
        """
        C2 dualperp 引擎:dualperp_positions 表
        source 格式: C2:{symbol}:long 或 C2:{symbol}:short
        """
        parts = source.split(":")
        if len(parts) < 3:
            return {"action": "C2_INVALID_SOURCE", "success": False,
                    "error": f"Invalid C2 source format: {source}"}

        pair_symbol = parts[1]
        leg_type = parts[2]

        positions = await self.pool.fetch(
            """
            SELECT id, symbol, venue_long, venue_short, state, qty_base
            FROM dualperp_positions
            WHERE symbol = $1 AND state NOT IN ('CLOSED', 'FAILED')
            ORDER BY created_at DESC
            LIMIT 5
            """,
            pair_symbol
        )

        if not positions:
            return {
                "action": "C2_NO_OPEN_POSITION",
                "success": True,
                "details": {"note": "No open dualperp position found", "symbol": pair_symbol}
            }

        target = None
        for pos in positions:
            if leg_type == "long" and pos["venue_long"] == venue:
                target = pos
                break
            elif leg_type == "short" and pos["venue_short"] == venue:
                target = pos
                break

        if not target:
            return {
                "action": "C2_VENUE_MISMATCH",
                "success": False,
                "details": {
                    "note": f"No position with {leg_type} leg on {venue}",
                    "symbol": pair_symbol
                }
            }

        await self.pool.execute(
            """
            UPDATE dualperp_positions
            SET state = 'CLOSED',
                closed_at = NOW(),
                note = COALESCE(note, '') || ' [RECON auto-cleared ORPHAN_CLAIM]'
            WHERE id = $1
            """,
            target["id"]
        )

        return {
            "action": "C2_POSITION_CLOSED",
            "success": True,
            "details": {
                "position_id": target["id"],
                "symbol": pair_symbol,
                "leg_type": leg_type,
                "venue": venue,
                "qty_base": float(target["qty_base"])
            }
        }

    # ── C3 (coin Redis 快照) ───────────────────────────────────────────────────
    async def _handle_c3_orphan(self, symbol: str, source: str) -> dict:
        """
        C3 使用 Redis 快照,无数据库持久化
        source 格式: C3:{symbol}
        策略:记录日志,等待 C3 引擎下次快照自动更新(20–60s)
        """
        parts = source.split(":")
        if len(parts) < 2:
            return {"action": "C3_INVALID_SOURCE", "success": False,
                    "error": f"Invalid C3 source format: {source}"}

        return {
            "action": "C3_SNAPSHOT_STALE",
            "success": True,
            "details": {
                "note": "C3 uses Redis snapshot, will auto-update in next engine cycle",
                "symbol": parts[1],
                "recommendation": "Monitor for 2-3 cycles; escalate if persists"
            }
        }

    # ── 审计日志 ──────────────────────────────────────────────────────────────
    async def _log_fix(self, break_info: dict, result: dict):
        """记录处理结果到 recon_fixes 表(失败不阻塞主流程)"""
        try:
            await self.pool.execute(
                """
                INSERT INTO recon_fixes
                    (ts, break_type, venue, symbol, action, result, error)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                datetime.fromtimestamp(time.time()),
                break_info.get("type"),
                break_info.get("venue"),
                break_info.get("symbol"),
                result.get("action"),
                json.dumps(result.get("details", {})),
                result.get("error")
            )
        except Exception as e:
            print(f"_log_fix failed: {e}")


# ── 单元测试 ──────────────────────────────────────────────────────────────────
async def _test():
    pool = await asyncpg.create_pool(
        "postgresql://dcm:696a6e2c29d393e322acdb068869137f@10.0.1.12:5432/dcm_main",
        min_size=1, max_size=2
    )
    handler = OrphanClaimHandler(pool)
    break_info = {
        "type": "ORPHAN_CLAIM",
        "venue": "binance",
        "symbol": "XVGUSDT",
        "source": "C1:XVGUSDT:perp_short",
        "note": "引擎声称在管,实盘平"
    }
    result = await handler.handle(break_info)
    print("Result:", json.dumps(result, indent=2, default=str))

    row = await pool.fetchrow(
        "SELECT symbol, state FROM basis_positions WHERE id=1"
    )
    print(f"basis_positions: {row[0]} state={row[1]}")

    await pool.close()


if __name__ == "__main__":
    asyncio.run(_test())
