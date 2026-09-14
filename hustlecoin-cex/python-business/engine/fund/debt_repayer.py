import logging
from decimal import Decimal

from engine.config_loader import FundRulesSnapshot
from engine.trading.binance_trading import BinanceTradingClient
from engine.notify.feishu_sender import FeishuSender

logger = logging.getLogger(__name__)


async def run_usdt_debt_check(
    client: BinanceTradingClient,
    rules: FundRulesSnapshot,
    notifier: FeishuSender,
    account_note: str,
):
    if not rules.usdt_debt_auto_repay:
        return

    try:
        margin_info = await client.get_margin_account()
        for asset in margin_info.get("userAssets", []):
            if asset["asset"] == "USDT":
                borrowed = Decimal(str(asset.get("borrowed", "0")))
                if borrowed > rules.usdt_debt_threshold:
                    free = Decimal(str(asset.get("free", "0")))
                    repay_amount = min(borrowed, free)
                    if repay_amount > 0:
                        await client.margin_repay("USDT", repay_amount)
                        logger.info(f"USDT debt repaid: {repay_amount}")
                        await notifier.send("USDT还款", f"账户: {account_note}\n还款: {repay_amount} USDT")
                break
    except Exception as e:
        logger.warning(f"USDT debt repayer error: {e}")
