"""P2 weather agent: 审计天气信号质量，分析城市edge准确性。

统计各城市天气预报edge与实际outcome的校准，
提议调整weather_cities或weather_min_edge。
"""
from __future__ import annotations

import sqlite3

from agents.schemas import Proposal


def run(db_path: str) -> dict:
    """Audit weather signal quality and propose tuning."""
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
        WHERE d.asset = 'WEATHER'
        AND d.ts > (strftime('%s', 'now') - 86400 * 14)
        GROUP BY d.market_slug
        HAVING n_buys > 0
        ORDER BY n_buys DESC
        LIMIT 10
    """)
    rows = cursor.fetchall()

    conn.close()

    city_stats = []
    for slug, n_decisions, n_buys, wins in rows:
        city = slug.split('-')[0] if slug else "unknown"
        wr = (wins or 0) / max(1, n_buys)
        city_stats.append({
            "city": city,
            "market_slug": slug,
            "n_decisions": n_decisions,
            "n_buys": n_buys,
            "win_rate": round(wr, 4),
        })

    proposals = []
    for stat in city_stats:
        if stat["n_buys"] >= 5 and stat["win_rate"] < 0.40:
            proposals.append(Proposal(
                key="weather_cities",
                current="current_list",
                proposed=f"remove_{stat['city']}",
                reason=(
                    f"城市 {stat['city']} 过去14天天气信号胜率{stat['win_rate']:.1%}"
                    f"（{stat['n_buys']}笔交易），edge虚高。建议从weather_cities移除。"
                ),
                source_agent="weather",
                confidence="low",
            ))

    total_buys = sum(s["n_buys"] for s in city_stats)
    if total_buys < 10:
        proposals.append(Proposal(
            key="weather_min_edge",
            current=0.05,
            proposed=0.03,
            reason=(
                f"过去14天天气交易仅{total_buys}笔，信号触发过于保守。"
                f"建议下调weather_min_edge。"
            ),
            source_agent="weather",
            confidence="low",
        ))

    return {
        "city_stats": city_stats,
        "total_buys": total_buys,
        "proposals": proposals,
        "n_proposals": len(proposals),
    }
