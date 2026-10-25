import asyncio
import logging
from decimal import Decimal

from app.db.models import SubAccount
from app.db.session import SessionLocal
from engine.config_loader import FundRulesSnapshot
from engine.trading.binance_trading import BinanceTradingClient
from engine.notify.feishu_sender import FeishuSender

logger = logging.getLogger(__name__)


def _sub_risk_threshold(sub_account_id: int) -> Decimal | None:
    """子账户 risk_threshold(风控阈)—— 有值则覆盖全局 risk_value_threshold。无值/异常返回 None。"""
    db = SessionLocal()
    try:
        sa = db.query(SubAccount).get(sub_account_id)
        if sa and getattr(sa, "risk_threshold", None) is not None:
            return Decimal(str(sa.risk_threshold))
        return None
    except Exception:
        return None
    finally:
        db.close()


async def check_margin_risk(
    client: BinanceTradingClient,
    rules: FundRulesSnapshot,
    notifier: FeishuSender,
    account_note: str,
    sub_account_id: int = None,
) -> bool:
    """Returns True if safe to trade, False if risk level is critical."""
    try:
        margin_info = await client.get_margin_account()
        margin_level = Decimal(str(margin_info.get("marginLevel", "999")))

        # 临界阈值取绿框 leverage_risk_alert(FeishuConfig,可在 /rules 配),缺省 1.3
        notifier._ensure_config()
        crit = notifier.leverage_risk_alert or Decimal("1.3")

        # 预警阈值: 子账户 risk_threshold(风控阈)覆盖全局 risk_value_threshold(有值才覆盖)
        warn = rules.risk_value_threshold
        if sub_account_id is not None:
            ov = await asyncio.to_thread(_sub_risk_threshold, sub_account_id)
            if ov is not None:
                warn = ov

        if margin_level < crit:
            logger.critical(f"CRITICAL margin level: {margin_level} (< {crit})")
            await notifier.notify_risk(account_note, margin_level)
            return False

        if margin_level < warn:
            logger.warning(f"Low margin level: {margin_level} (< {warn})")
            await notifier.notify_risk(account_note, margin_level)
            return False

        return True
    except Exception as e:
        logger.warning(f"Risk monitor error: {e}")
        return True
