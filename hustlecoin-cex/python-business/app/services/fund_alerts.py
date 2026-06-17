"""资金风险告警(回撤 / 保证金水平 / 单用户日亏)。

balance_pusher 每快照周期(~10min)调一次。复用现有令牌桶 throttle_ok 节流(跨进程,fail-open),
命中即写 coinadmin 跑马灯(NotificationLog channel=marquee,与引擎关键告警同一展示面)。
阈值为模块常量,后续可迁到 FeishuConfig/GlobalRules 做可配。口径:净PnL = realized+funding−interest。
"""
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models_auth import User
from app.db.models_notify import NotificationLog
from app.services.notifier import throttle_ok
from engine.models import Position

logger = logging.getLogger(__name__)

# ── 阈值(可调)──
MARGIN_ALERT_LEVEL = 1.3      # 全仓保证金水平低于此 → 告警
DAILY_LOSS_ALERT = 50.0       # 单用户当日净亏(USDT)超过此 → 告警
DRAWDOWN_PCT = 0.20           # 24h 峰值回撤比例超过此 → 告警
DRAWDOWN_MIN_EQUITY = 20.0    # 峰值净值需 ≥ 此值才判回撤(避免小额噪音)
THROTTLE_SEC = 1800           # 同类同用户告警最小间隔(30min)


def _fire(db: Session, alert_type: str, uid: int, title: str, detail: str) -> None:
    # 节流:同 (类型,用户) 30min 至多一条,避免刷屏(与引擎告警共用 Redis 令牌桶)
    if not throttle_ok(f"fundalert:{alert_type}:{uid}", THROTTLE_SEC, 1):
        return
    try:
        db.add(NotificationLog(template_name=title, channel="marquee", status="sent", content=detail))
        db.commit()
        logger.info(f"fund alert [{alert_type}] u{uid}: {detail}")
    except Exception as e:
        db.rollback()
        logger.warning(f"fund alert marquee write failed: {e}")


def run_fund_alert_checks(db: Session, agg_by_user: dict[int, dict]) -> None:
    """agg_by_user: {user_id: {"equity": float, "margin_level_min": float|None}}"""
    if not agg_by_user:
        return
    unames = {u.id: u.username for u in db.query(User.id, User.username).all()}
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    since_24h = now - timedelta(hours=24)

    from app.db.models import BalanceSnapshot  # 延迟导入避免循环

    for uid, agg in agg_by_user.items():
        uname = unames.get(uid, f"#{uid}")
        equity = agg.get("equity")
        mlm = agg.get("margin_level_min")

        # 1) 保证金水平
        if mlm is not None and mlm < MARGIN_ALERT_LEVEL:
            _fire(db, "margin", uid, "资金告警·保证金",
                  f"⚠ 用户 {uname} 最低全仓保证金水平 {mlm:.2f} < {MARGIN_ALERT_LEVEL}(爆仓风险),请关注")

        # 2) 当日净亏
        row = (db.query(
                    func.coalesce(func.sum(Position.realized_pnl), 0),
                    func.coalesce(func.sum(Position.cumulative_funding_fee), 0),
                    func.coalesce(func.sum(Position.cumulative_interest), 0),
                )
               .filter(Position.user_id == uid, Position.status == "CLOSED",
                       Position.closed_at >= today_start).first())
        if row:
            net = float(row[0] or 0) + float(row[1] or 0) - float(row[2] or 0)
            if net < -DAILY_LOSS_ALERT:
                _fire(db, "dailyloss", uid, "资金告警·日亏",
                      f"⚠ 用户 {uname} 今日净亏 {net:.2f} USDT(阈值 -{DAILY_LOSS_ALERT}),请关注")

        # 3) 24h 净值回撤
        if equity is not None:
            peak = db.query(func.max(BalanceSnapshot.equity)).filter(
                BalanceSnapshot.user_id == uid, BalanceSnapshot.ts >= since_24h).scalar()
            peak = float(peak) if peak is not None else 0.0
            if peak >= DRAWDOWN_MIN_EQUITY and equity < peak:
                dd = (peak - equity) / peak
                if dd >= DRAWDOWN_PCT:
                    _fire(db, "drawdown", uid, "资金告警·回撤",
                          f"⚠ 用户 {uname} 24h 净值回撤 {dd * 100:.1f}%(峰值 {peak:.2f}→当前 {equity:.2f}),请关注")
