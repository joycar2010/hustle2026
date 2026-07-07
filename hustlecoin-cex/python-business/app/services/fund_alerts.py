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
# 净敞口对账:主账户合约净仓 vs DB 在管对冲量,差额名义超此值 → 裸多/裸空告警(实测 50 FIL≈40U 裸多躺 6h 才被发现)
HEDGE_MISMATCH_NOTIONAL = 5.0   # 单币净敞口差额名义(USDT)超此 → 告警
HEDGE_MISMATCH_MIN_QTY = 1e-6   # 差额绝对量地板(过滤取整残差/浮点噪音)


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


def run_hedge_reconcile_checks(db: Session, master_pos_by_user: dict[int, dict],
                               prices: dict[str, float]) -> None:
    """净敞口对账:主账户每个币的合约净仓 vs DB 在管对冲量(该 user 该币非终态、hedge_account='master'
    的 futures_long_qty 合计)。差额名义 > HEDGE_MISMATCH_NOTIONAL → 裸多/裸空告警。
    数据全部现成(master_pos 由 balance_pusher 本轮采集,prices 用 spot_bids),零额外 REST。
    master_pos_by_user: {uid: {SYMBOL: positionAmt}}; prices: {SYMBOL: spot_bid}。"""
    if not master_pos_by_user:
        return
    unames = {u.id: u.username for u in db.query(User.id, User.username).all()}
    for uid, pos in master_pos_by_user.items():
        if not pos:
            continue
        uname = unames.get(uid, f"#{uid}")
        # 该 user 各币在管对冲量(master 腿),一次 SQL 聚合
        rows = (db.query(Position.symbol, func.coalesce(func.sum(Position.futures_long_qty), 0))
                .filter(Position.user_id == uid,
                        Position.status.notin_(["CLOSED", "FAILED"]),
                        Position.hedge_account == "master")
                .group_by(Position.symbol).all())
        hedged = {sym: float(q or 0) for sym, q in rows}
        # 对账口径取并集:主账户有仓但 DB 无对冲(裸露) 或 DB 有对冲但主账户仓不足,都要覆盖
        for sym in set(pos) | set(hedged):
            actual = float(pos.get(sym, 0) or 0)      # 主账户合约净仓(多为正)
            managed = hedged.get(sym, 0.0)            # DB 在管对冲量
            diff = actual - managed                   # >0 裸多(实仓多于对冲) / <0 裸空(对冲多于实仓)
            if abs(diff) < HEDGE_MISMATCH_MIN_QTY:
                continue
            px = prices.get(sym, 0.0)
            notional = abs(diff) * px if px > 0 else 0.0
            # 拿不到价时用绝对量兜底(名义 0 会漏报),阈值退化为 1 个币
            if (px > 0 and notional < HEDGE_MISMATCH_NOTIONAL) or (px <= 0 and abs(diff) < 1.0):
                continue
            kind = "裸多(实仓>对冲)" if diff > 0 else "裸空(对冲>实仓)"
            _fire(db, f"hedge:{sym}", uid, "资金告警·净敞口",
                  f"⚠ 用户 {uname} {sym} {kind} 差额 {diff:+.4f}(实仓 {actual:.4f} vs 在管对冲 {managed:.4f}"
                  f"{f',名义≈{notional:.1f}U' if notional > 0 else ''}),请核对合约仓")
