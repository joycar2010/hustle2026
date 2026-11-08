"""P2 exit agent: 审计退出决策质量，分析止损效果。

统计各类退出（reversal/early/partial/late）的触发频率、反事实收益，
提议调整退出窗口参数。
"""
from __future__ import annotations

import sqlite3

from agents.schemas import Proposal


def run(db_path: str) -> dict:
    """Audit exit decisions and propose exit window tuning."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            o.entry_rule,
            COUNT(*) as n_exits,
            AVG(o.price) as avg_exit_price
        FROM orders o
        WHERE o.status IN ('exit_filled', 'exit_matched', 'exit_partial', 'exit_dry_run')
        AND o.ts > (strftime('%s', 'now') - 86400 * 7)
        GROUP BY o.entry_rule
        ORDER BY n_exits DESC
    """)
    exit_rows = cursor.fetchall()

    cursor.execute("""
        SELECT COUNT(*) as total_positions
        FROM orders
        WHERE status IN ('filled', 'matched', 'dry_run')
        AND ts > (strftime('%s', 'now') - 86400 * 7)
    """)
    row = cursor.fetchone()
    total_positions = row[0] if row else 0

    conn.close()

    exit_stats = []
    total_exits = 0
    for rule, n_exits, avg_price in exit_rows:
        exit_stats.append({
            "exit_type": rule or "unknown",
            "n_exits": n_exits,
            "avg_exit_price": round(avg_price or 0, 3),
        })
        total_exits += n_exits

    exit_rate = total_exits / max(1, total_positions)

    proposals = []
    if exit_rate > 0.3:
        proposals.append(Proposal(
            key="reversal_exit_window_sec",
            current=60,
            proposed=90,
            reason=(
                f"过去7天退出率{exit_rate:.1%}过高（{total_exits}/{total_positions}个仓位），"
                f"可能提前止损过于频繁。建议放宽反转退出窗口。"
            ),
            source_agent="exit",
            confidence="low",
        ))

    if exit_rate < 0.05:
        proposals.append(Proposal(
            key="early_reversal_held_bid_threshold",
            current=0.85,
            proposed=0.90,
            reason=(
                f"过去7天退出率{exit_rate:.1%}过低，可能错失止损时机。"
                f"建议收紧early reversal阈值。"
            ),
            source_agent="exit",
            confidence="low",
        ))

    return {
        "exit_stats": exit_stats,
        "total_exits": total_exits,
        "total_positions": total_positions,
        "exit_rate": round(exit_rate, 4),
        "proposals": proposals,
        "n_proposals": len(proposals),
    }
