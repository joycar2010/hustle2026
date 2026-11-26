"""P2 sniper agent: 审计入场决策质量，分析各entry_rule胜率。

统计BUY决策按entry_rule分组的胜率、edge分布、时间窗口，
提议禁用低胜率规则或调整窗口参数。
"""
from __future__ import annotations

import sqlite3

from agents.schemas import Proposal


def run(db_path: str) -> dict:
    """Audit sniper entry decisions and propose entry_rule tuning."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            o.entry_rule,
            COUNT(*) as n_trades,
            SUM(CASE WHEN o.token_id = r.winning_token THEN 1 ELSE 0 END) as wins,
            AVG(o.price) as avg_price,
            AVG(d.t_remaining) as avg_t_remaining
        FROM orders o
        JOIN decisions d ON o.condition_id = d.condition_id
            AND o.side = d.side
            AND o.dry_run = d.dry_run
        JOIN resolutions r ON o.condition_id = r.condition_id
        WHERE o.status IN ('filled', 'matched', 'dry_run')
        AND d.action = 'BUY'
        AND d.asset IN ('BTC', 'ETH')
        AND d.ts > (strftime('%s', 'now') - 86400 * 7)
        AND o.entry_rule IS NOT NULL
        GROUP BY o.entry_rule
        HAVING n_trades >= 5
        ORDER BY n_trades DESC
    """)
    rows = cursor.fetchall()

    conn.close()

    rule_stats = []
    for entry_rule, n_trades, wins, avg_price, avg_t_rem in rows:
        wr = wins / n_trades if n_trades > 0 else 0
        rule_stats.append({
            "entry_rule": entry_rule,
            "n_trades": n_trades,
            "win_rate": round(wr, 4),
            "avg_price": round(avg_price or 0, 3),
            "avg_t_remaining_sec": round(avg_t_rem or 0, 1),
        })

    proposals = []
    for stat in rule_stats:
        rule = stat["entry_rule"]
        wr = stat["win_rate"]
        n = stat["n_trades"]

        if wr < 0.45 and n >= 10:
            proposals.append(Proposal(
                key=f"{rule}_enabled",
                current=True,
                proposed=False,
                reason=(
                    f"入场规则 {rule} 过去7天胜率{wr:.1%}（{n}笔交易），"
                    f"显著低于50%基准。建议禁用或收紧该规则条件。"
                ),
                source_agent="sniper",
                confidence="medium" if n >= 20 else "low",
            ))

        if wr > 0.55 and n < 5:
            proposals.append(Proposal(
                key=f"{rule}_window_sec",
                current="unknown",
                proposed="expand",
                reason=(
                    f"入场规则 {rule} 胜率{wr:.1%}优秀但仅{n}笔交易，"
                    f"使用率过低。建议放宽时间窗口或入场条件。"
                ),
                source_agent="sniper",
                confidence="low",
            ))

    return {
        "rule_stats": rule_stats,
        "proposals": proposals,
        "n_proposals": len(proposals),
    }
