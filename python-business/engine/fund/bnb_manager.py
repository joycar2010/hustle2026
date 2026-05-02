import asyncio
import logging
from decimal import Decimal

from engine.config_loader import FundRulesSnapshot
from engine.trading.binance_trading import BinanceTradingClient
from engine.notify.feishu_sender import FeishuSender

logger = logging.getLogger(__name__)


async def run_bnb_check(
    client: BinanceTradingClient,
    rules: FundRulesSnapshot,
    notifier: FeishuSender,
    account_note: str,
):
    try:
        balances = await client.get_bnb_balance()
        bnb_free = balances.get("margin", Decimal("0"))

        if bnb_free < rules.bnb_min_quantity:
            trigger = rules.bnb_min_quantity * rules.bnb_buy_trigger_pct / 100
            if bnb_free <= trigger:
                margin_usdt_free = Decimal("0")
                try:
                    margin_info = await client.get_margin_account()
                    for asset in margin_info.get("userAssets", []):
                        if asset["asset"] == "USDT":
                            margin_usdt_free = Decimal(str(asset.get("free", "0")))
                            break
                except Exception:
                    pass
                estimated_cost = rules.bnb_buy_amount * Decimal("700")
                if margin_usdt_free < estimated_cost:
                    logger.debug(f"BNB buy skipped: margin USDT free {margin_usdt_free} < estimated cost {estimated_cost}")
                else:
                    logger.info(f"BNB low ({bnb_free}), buying {rules.bnb_buy_amount}")
                    await client.spot_market_buy_qty("BNBUSDT", rules.bnb_buy_amount)
                    await notifier.send("BNB购买", f"账户: {account_note}\n购买: {rules.bnb_buy_amount} BNB")

        if rules.bnb_debt_auto_repay:
            margin_info = await client.get_margin_account()
            for asset in margin_info.get("userAssets", []):
                if asset["asset"] == "BNB":
                    borrowed = Decimal(str(asset.get("borrowed", "0")))
                    if borrowed > rules.bnb_debt_threshold:
                        free = Decimal(str(asset.get("free", "0")))
                        repay_amount = min(borrowed, free)
                        if repay_amount > 0:
                            await client.margin_repay("BNB", repay_amount)
                            logger.info(f"BNB debt repaid: {repay_amount}")
                    break
    except Exception as e:
        logger.warning(f"BNB manager error: {e}")
