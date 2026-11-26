"""P2 sports agent: 审计体育信号质量，分析odds edge校准。

统计各体育类型胜率、edge校准，
提议调整sports_max_days_ahead或禁用低胜率类型。
"""
from __future__ import annotations

import sqlite3

from agents.schemas import Proposal


def run(db_path: str) -> dict:
    """Audit sports signal quality and propose tuning."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            d.market_slug,
            COUNT(*) as n_decisions,
            SUM(CASE WHEN d.action = 'BUY' THEN 1 ELSE 0 END) as n_buys,
            SUM(CASE WHEN o.token_id = r.winning_token THEN 1 ELSE 0 END) as wins
        FROM decisions d
        LEFT JOIN orders o ON d.condition_id = o.condition_id
            AND d.side = o.side
            AND d.dry_run = o.dry_run
        LEFT JOIN resolutions r ON d.condition_id = r.condition_id
        WHERE d.asset = 'SPORTS'
        AND d.ts > (strftime('%s', 'now') - 86400 * 30)
        GROUP BY d.market_slug
        HAVING n_buys > 0
        ORDER BY n_buys DESC
        LIMIT 10
    """)
    rows = cursor.fetchall()

    conn.close()

    sports_stats = []
    for slug, n_decisions, n_buys, wins in rows:
        sport_type = "unknown"
        if "nba" in slug.lower() or "basketball" in slug.lower():
            sport_type = "basketball"
        elif "nfl" in slug.lower() or "football" in slug.lower():
            sport_type = "football"
        elif "mlb" in slug.lower() or "baseball" in slug.lower():
            sport_type = "baseball"

        wr = (wins or 0) / max(1, n_buys)
        sports_stats.append({
            "sport_type": sport_type,
            "market_slug": slug,
            "n_decisions": n_decisions,
            "n_buys": n_buys,
            "win_rate": round(wr, 4),
        })

    proposals = []
    for stat in sports_stats:
        if stat["n_buys"] >= 5 and stat["win_rate"] < 0.40:
            proposals.append(Proposal(
                key=f"{stat['sport_type']}_enabled",
                current=True,
                proposed=False,
                reason=(
                    f"体育类型 {stat['sport_type']} 过去30天胜率{stat['win_rate']:.1%}"
                    f"（{stat['n_buys']}笔交易），显著低于期望。建议禁用该类型。"
                ),
                source_agent="sports",
                confidence="low",
            ))

    total_buys = sum(s["n_buys"] for s in sports_stats)
    if total_buys < 5:
        proposals.append(Proposal(
            key="sports_max_days_ahead",
            current=30,
            proposed=60,
            reason=(
                f"过去30天体育交易仅{total_buys}笔，信号触发过少。"
                f"建议放宽sports_max_days_ahead扫描更远的比赛。"
            ),
            source_agent="sports",
            confidence="low",
        ))

    return {
        "sports_stats": sports_stats,
        "total_buys": total_buys,
        "proposals": proposals,
        "n_proposals": len(proposals),
    }
