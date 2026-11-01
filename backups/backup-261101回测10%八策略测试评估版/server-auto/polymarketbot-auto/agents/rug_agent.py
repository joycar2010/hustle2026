"""P2 rug agent: 监控系统性风险，检测异常模式。

检测短时间大量SKIP、信号源失效、流动性枯竭等异常，
提议启用/禁用某些资产或市场。
"""
from __future__ import annotations

import sqlite3

from agents.schemas import Proposal


def run(db_path: str) -> dict:
    """Monitor for systemic risks and anomalies."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 检测最近1小时的异常SKIP率
    cursor.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN action LIKE 'SKIP%' THEN 1 ELSE 0 END) as skips
        FROM decisions
        WHERE asset IN ('BTC', 'ETH')
        AND ts > (strftime('%s', 'now') - 3600)
    """)
    row = cursor.fetchone()
    total_1h = row[0] if row else 0
    skips_1h = row[1] if row else 0

    # 检测信号反向错误（连续窗口outcome与side相反）
    cursor.execute("""
        SELECT
            d.asset,
            COUNT(*) as n_windows,
            SUM(CASE WHEN d.token_id != r.winning_token THEN 1 ELSE 0 END) as wrong_signals
        FROM decisions d
        JOIN resolutions r ON d.condition_id = r.condition_id
        WHERE d.action = 'BUY'
        AND d.ts > (strftime('%s', 'now') - 3600)
        GROUP BY d.asset
    """)
    signal_rows = cursor.fetchall()

    # 检测市场流动性问题（订单error频繁）
    cursor.execute("""
        SELECT market_slug, COUNT(*) as error_count
        FROM orders
        WHERE status IN ('error', 'pre_submit_error')
        AND ts > (strftime('%s', 'now') - 3600)
        GROUP BY market_slug
        HAVING error_count >= 3
        ORDER BY error_count DESC
        LIMIT 5
    """)
    error_markets = cursor.fetchall()

    conn.close()

    alerts = []
    anomalies = 0

    # 异常1：SKIP率过高
    if total_1h > 20 and skips_1h / total_1h > 0.7:
        alerts.append({
            "type": "high_skip_rate",
            "severity": "medium",
            "message": f"过去1小时SKIP率{skips_1h / total_1h:.1%}异常高（{skips_1h}/{total_1h}），可能系统卡顿或风控过严。"
        })
        anomalies += 1

    # 异常2：信号失效
    for asset, n_windows, wrong in signal_rows:
        if n_windows >= 5 and wrong / n_windows > 0.8:
            alerts.append({
                "type": "signal_failure",
                "asset": asset,
                "severity": "high",
                "message": f"{asset}信号过去1小时错误率{wrong / n_windows:.1%}（{wrong}/{n_windows}窗口），信号源可能失效。"
            })
            anomalies += 1

    # 异常3：流动性枯竭
    if error_markets:
        alerts.append({
            "type": "liquidity_issue",
            "severity": "medium",
            "markets": [m[0] for m in error_markets[:3]],
            "message": f"{len(error_markets)}个市场过去1小时订单error频繁，可能流动性不足。"
        })
        anomalies += 1

    proposals = []
    for alert in alerts:
        if alert["type"] == "signal_failure" and alert.get("severity") == "high":
            proposals.append(Proposal(
                key=f"{alert['asset']}_enabled",
                current=True,
                proposed=False,
                reason=alert["message"] + " 建议暂时禁用该资产交易。",
                source_agent="rug",
                confidence="medium",
            ))

    return {
        "alerts": alerts,
        "anomalies": anomalies,
        "total_1h": total_1h,
        "skips_1h": skips_1h,
        "proposals": proposals,
        "n_proposals": len(proposals),
    }
