import logging
from decimal import Decimal

from engine.config_loader import FundRulesSnapshot
from engine.trading.binance_trading import BinanceTradingClient
from engine.notify.feishu_sender import FeishuSender

logger = logging.getLogger(__name__)


async def check_margin_risk(
    client: BinanceTradingClient,
    rules: FundRulesSnapshot,
    notifier: FeishuSender,
    account_note: str,
) -> bool:
    """Returns True if safe to trade, False if risk level is critical."""
    try:
        margin_info = await client.get_margin_account()
        margin_level = Decimal(str(margin_info.get("marginLevel", "999")))

        if margin_level < Decimal("1.3"):
            logger.critical(f"CRITICAL margin level: {margin_level}")
            await notifier.notify_risk(account_note, margin_level)
            return False

        if margin_level < rules.risk_value_threshold:
            logger.warning(f"Low margin level: {margin_level}")
            await notifier.notify_risk(account_note, margin_level)
            return False

        return True
    except Exception as e:
        logger.warning(f"Risk monitor error: {e}")
        return True
