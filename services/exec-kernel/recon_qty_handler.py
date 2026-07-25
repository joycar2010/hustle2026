"""
QTY_MISMATCH 自动化处理 (关3 Phase 4)

QTY_MISMATCH: 引擎期望数量与实盘数量不一致(相差>2%)
可能原因:
1. 部分成交未更新到引擎状态
2. 手动调整了实盘仓位
3. 交易所强平/清算
4. 引擎状态与实盘漂移

处理策略:
1. **连续N次确认**: 避免瞬时误报(TOL_PCT=2%边界震荡)
2. **记录差异历史**: 存储连续N次的diff_pct
3. **达到阈值时调整**: 连续3次>2%且趋势一致时触发
4. **调整方式**: 更新引擎状态数量,不下单(shadow模式)

配置参数:
- DCM_RECON_QTY_THRESHOLD: 连续N次触发阈值(默认3)
- DCM_RECON_QTY_MIN_DIFF: 最小差异百分比(默认5%, 避免小幅抖动)
"""
import os
import asyncio
import asyncpg
import json
from datetime import datetime
from typing import Dict, List
import time


class QtyMismatchHandler:
    """QTY_MISMATCH 处理器 - 连续确认+调整"""

    def __init__(self, pool: asyncpg.Pool, redis_client=None):
        self.pool = pool
        self.redis = redis_client
        # 连续确认阈值
        self.threshold = int(os.environ.get("DCM_RECON_QTY_THRESHOLD", "3"))
        # 最小差异百分比(小于此值不处理)
        self.min_diff_pct = float(os.environ.get("DCM_RECON_QTY_MIN_DIFF", "5.0"))

    async def can_handle(self, break_type: str) -> bool:
        """判断是否可以处理该类型的异常"""
        return break_type == "QTY_MISMATCH"

    async def handle(self, break_info: dict) -> dict:
        """
        处理 QTY_MISMATCH

        参数:
            break_info: {
                "type": "QTY_MISMATCH",
                "venue": "binance",
                "symbol": "BTCUSDT",
                "source": "MGR:BTCUSDT:perp",
                "expected": 100.0,
                "actual": 95.0,
                "diff_pct": 5.0
            }

        返回:
            {
                "action": "QTY_ADJUSTED" | "QTY_TRACKING" | "SKIP",
                "success": bool,
                "details": {...}
            }
        """
        venue = break_info.get("venue")
        symbol = break_info.get("symbol")
        source = break_info.get("source")
        expected = break_info.get("expected")
        actual = break_info.get("actual")
        diff_pct = break_info.get("diff_pct")

        # 1. 检查差异是否达到最小阈值
        if abs(diff_pct) < self.min_diff_pct:
            return {
                "action": "SKIP",
                "success": True,
                "details": {
                    "note": f"Diff {diff_pct}% below threshold {self.min_diff_pct}%",
                    "diff_pct": diff_pct
                }
            }

        # 2. 获取历史记录(连续确认)
        key = f"{venue}:{symbol}:{source}"
        history = await self._get_history(key)

        # 3. 添加当前观察
        history.append({
            "ts": int(time.time()),
            "expected": expected,
            "actual": actual,
            "diff_pct": diff_pct
        })

        # 只保留最近N+2次
        history = history[-(self.threshold + 2):]
        await self._save_history(key, history)

        # 4. 检查是否满足连续N次确认
        if len(history) < self.threshold:
            return {
                "action": "QTY_TRACKING",
                "success": True,
                "details": {
                    "note": f"Tracking {len(history)}/{self.threshold} cycles",
                    "history": history[-3:]  # 只返回最近3次
                }
            }

        # 5. 验证连续性(最近N次都超过阈值)
        recent = history[-self.threshold:]
        all_exceed = all(abs(h["diff_pct"]) >= self.min_diff_pct for h in recent)

        if not all_exceed:
            return {
                "action": "QTY_TRACKING",
                "success": True,
                "details": {
                    "note": "Not all recent cycles exceed threshold",
                    "history": recent
                }
            }

        # 6. 趋势一致性检查(都是正向或都是负向)
        signs = [1 if h["actual"] > h["expected"] else -1 for h in recent]
        consistent = all(s == signs[0] for s in signs)

        if not consistent:
            return {
                "action": "QTY_TRACKING",
                "success": True,
                "details": {
                    "note": "Direction not consistent",
                    "history": recent
                }
            }

        # 7. 满足条件,执行调整
        result = await self._adjust_quantity(source, venue, symbol, expected, actual, recent)

        # 8. 清除历史记录
        await self._clear_history(key)

        return result

    async def _adjust_quantity(self, source: str, venue: str, symbol: str,
                               expected: float, actual: float, history: List[dict]) -> dict:
        """
        调整仓位数量

        根据 source 类型更新对应的引擎状态:
        - MGR: 更新 exec_saga 或 exec_pairs
        - C2: 更新 dualperp_positions
        - C3: 记录日志(Redis快照无法直接更新)
        """
        parts = source.split(":")
        if len(parts) < 2:
            return {"action": "SKIP", "success": False, "error": "Invalid source format"}

        engine_type = parts[0]  # MGR, C2, C3

        if engine_type == "MGR":
            return await self._adjust_manager_qty(parts, venue, symbol, expected, actual, history)
        elif engine_type == "C2":
            return await self._adjust_c2_qty(parts, venue, symbol, expected, actual, history)
        elif engine_type == "C3":
            return await self._adjust_c3_qty(parts, symbol, expected, actual, history)
        else:
            return {"action": "SKIP", "success": False, "error": f"Unknown engine type: {engine_type}"}

    async def _adjust_manager_qty(self, parts: List[str], venue: str, symbol: str,
                                   expected: float, actual: float, history: List[dict]) -> dict:
        """MGR 源诚实语义修正(2026-07-25):原实现查不存在的 exec_pairs 表=死代码。
        MGR 的 expected 来自 manager 20s 快照,而快照本身就是从交易所实读的——
        无 DB 账本可"调",持续 QTY_MISMATCH 只可能是 recon 与 manager 两次实盘读之间的
        时序差/所侧 API 不一致。正确动作=升级告警交人工,绝不伪造调整。"""
        return {
            "action": "MGR_READ_DIVERGENCE",
            "success": True,
            "details": {
                "note": ("MGR expected 每20s自实盘刷新,无账本可调;连续3轮读数分歧="
                         "recon/manager 双读不一致(所侧API或时序),须人工核查该 venue 读路径"),
                "pair_id": parts[1], "venue": venue,
                "expected": expected, "actual": actual,
                "recent": history[-3:],
            },
        }

    async def _adjust_c2_qty(self, parts: List[str], venue: str, symbol: str,
                             expected: float, actual: float, history: List[dict]) -> dict:
        """调整 C2 (dualperp) 的仓位数量"""
        pair_symbol = parts[1]  # BTCUSDT
        leg_type = parts[2] if len(parts) > 2 else None  # long/short

        # 查找 dualperp_positions
        positions = await self.pool.fetch(
            """
            SELECT id, symbol, venue_long, venue_short, qty_base
            FROM dualperp_positions
            WHERE symbol = $1
            AND state NOT IN ('CLOSED', 'FAILED')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            pair_symbol
        )

        if not positions:
            return {
                "action": "C2_NO_ACTIVE_POSITION",
                "success": False,
                "details": {"note": "No active dualperp position", "symbol": pair_symbol}
            }

        pos = positions[0]

        # 更新 qty_base
        await self.pool.execute(
            """
            UPDATE dualperp_positions
            SET qty_base = $1,
                updated_at = NOW(),
                note = COALESCE(note, '') || ' [RECON QTY adjusted: ' || $2::text || ' → ' || $3::text || ']'
            WHERE id = $4
            """,
            actual, expected, actual, pos["id"]
        )

        return {
            "action": "C2_QTY_ADJUSTED",
            "success": True,
            "details": {
                "position_id": pos["id"],
                "symbol": pair_symbol,
                "leg_type": leg_type,
                "venue": venue,
                "old_qty": expected,
                "new_qty": actual,
                "confirmed_cycles": len(history)
            }
        }

    async def _adjust_c3_qty(self, parts: List[str], symbol: str,
                             expected: float, actual: float, history: List[dict]) -> dict:
        """C3 引擎使用 Redis 快照,记录日志等待下次更新"""
        return {
            "action": "C3_QTY_SNAPSHOT_STALE",
            "success": True,
            "details": {
                "note": "C3 uses Redis snapshot, will auto-sync in next cycle",
                "symbol": symbol,
                "old_qty": expected,
                "new_qty": actual,
                "confirmed_cycles": len(history),
                "recommendation": "Monitor C3 engine status"
            }
        }

    async def _get_history(self, key: str) -> List[dict]:
        """从Redis获取历史记录"""
        if not self.redis:
            return []

        try:
            data = await self.redis.get(f"dcm:recon:qty_history:{key}")
            if data:
                return json.loads(data)
        except Exception:
            pass

        return []

    async def _save_history(self, key: str, history: List[dict]):
        """保存历史记录到Redis"""
        if not self.redis:
            return

        try:
            await self.redis.set(
                f"dcm:recon:qty_history:{key}",
                json.dumps(history),
                ex=86400  # 24小时过期
            )
        except Exception:
            pass

    async def _clear_history(self, key: str):
        """清除历史记录"""
        if not self.redis:
            return

        try:
            await self.redis.delete(f"dcm:recon:qty_history:{key}")
        except Exception:
            pass
