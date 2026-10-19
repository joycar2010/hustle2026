"""P2 risk agent: 审计风控闸门决策质量，提议阈值调整。

分析 SKIP_RISK 决策的触发频率、假阳性率和熔断后的实际市场走势，
输出参数优化提案。
"""
from __future__ import annotations

import sqlite3

from agents.schemas import Proposal


def run(db_path: str) -> dict:
    """Audit risk gate decisions and generate threshold tuning proposals."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 统计各类熔断触发频率
    cursor.execute("""
        SELECT
            COUNT(*) as total_decisions,
            SUM(CASE WHEN action = 'SKIP_RISK' THEN 1 ELSE 0 END) as risk_skips,
            SUM(CASE WHEN action = 'BUY' THEN 1 ELSE 0 END) as buys
        FROM decisions
        WHERE asset IN ('BTC', 'ETH')
        AND ts > (strftime('%s', 'now') - 86400)
    """)
    row = cursor.fetchone()
    total = row[0] if row else 0
    risk_skips = row[1] if row and row[1] is not None else 0
    buys = row[2] if row and row[2] is not None else 0

    # 提取熔断原因分类
    cursor.execute("""
        SELECT reason, COUNT(*) as cnt
        FROM decisions
        WHERE action = 'SKIP_RISK'
        AND asset IN ('BTC', 'ETH')
        AND ts > (strftime('%s', 'now') - 86400)
        GROUP BY reason
        ORDER BY cnt DESC
        LIMIT 5
    """)
    top_reasons = cursor.fetchall()

    # 分析熔断后的市场走势
    cursor.execute("""
        SELECT
            d.condition_id,
            d.side,
            r.winning_token,
            d.token_id
        FROM decisions d
        JOIN resolutions r ON d.condition_id = r.condition_id
        WHERE d.action = 'SKIP_RISK'
        AND d.asset IN ('BTC', 'ETH')
        AND d.ts > (strftime('%s', 'now') - 86400)
    """)
    outcomes = cursor.fetchall()

    # 计算假阳性和真阳性
    false_positives = sum(1 for _, _, win_tok, d_tok in outcomes if d_tok == win_tok)
    true_positives = sum(1 for _, _, win_tok, d_tok in outcomes if d_tok != win_tok)

    conn.close()

    audit = {
        "total_decisions_24h": total,
        "risk_skips": risk_skips,
        "buys": buys,
        "risk_skip_rate": round(risk_skips / max(1, total), 4),
        "top_skip_reasons": [(r[0][:100], r[1]) for r in top_reasons],
        "false_positives": false_positives,
        "true_positives": true_positives,
    }

    proposals = []
    if risk_skips > 0 and false_positives > true_positives * 2:
        proposals.append(Proposal(
            key="max_daily_loss_fraction",
            current=0.05,
            proposed=0.07,
            reason=(
                f"过去24h风控熔断{risk_skips}次，其中{false_positives}次阻止了盈利交易"
                f"（假阳性），仅{true_positives}次避免亏损。建议放宽日亏损熔断阈值。"
            ),
            source_agent="risk",
            confidence="low",
        ))

    if total > 0 and risk_skips / total > 0.5:
        proposals.append(Proposal(
            key="max_consecutive_losses",
            current=3,
            proposed=5,
            reason=(
                f"风控熔断率{risk_skips / total:.1%}过高，严重限制交易频率。"
                f"建议上调连败熔断阈值或检查其他风控参数。"
            ),
            source_agent="risk",
            confidence="medium",
        ))

    return {
        "audit": audit,
        "proposals": proposals,
        "n_proposals": len(proposals),
    }
