import logging
from decimal import Decimal

from engine.config_loader import FundRulesSnapshot
from engine.trading.binance_trading import BinanceTradingClient
from engine.notify.feishu_sender import FeishuSender
from engine.fund.transfer_manager import TRANSFER_TYPES

logger = logging.getLogger(__name__)


async def auto_balance_check(
    client: BinanceTradingClient,
    rules: FundRulesSnapshot,
    notifier: FeishuSender,
    account_note: str,
):
    try:
        margin_info = await client.get_margin_account()
        margin_level = Decimal(str(margin_info.get("marginLevel", "999")))

        usdt_free = Decimal("0")
        for asset in margin_info.get("userAssets", []):
            if asset["asset"] == "USDT":
                usdt_free = Decimal(str(asset.get("free", "0")))
                break

        if margin_level < rules.risk_value_threshold:
            transfer_amount = rules.single_transfer_amount
            order = rules.transfer_order.split(",")
            for source in order:
                source = source.strip()
                if source == "margin":
                    continue
                key = (source, "margin")
                transfer_type = TRANSFER_TYPES.get(key)
                if not transfer_type:
                    continue
                try:
                    await client.transfer(transfer_type, "USDT", transfer_amount)
                    logger.info(f"Auto-balance: {transfer_amount} USDT from {source} to margin (level={margin_level})")
                    await notifier.send(
                        "自动划转",
                        f"账户: {account_note}\n风险值: {margin_level}\n划入: {transfer_amount} USDT ({source}→margin)",
                        throttle_key=f"autotransfer:{account_note}",
                    )
                    return
                except Exception as e:
                    logger.warning(f"Auto-balance transfer from {source} failed: {e}")
                    continue

        if margin_level > Decimal("2.0") and usdt_free > rules.base_margin_amount:
            excess = usdt_free - rules.base_margin_amount
            if excess > Decimal("10"):
                try:
                    await client.transfer("MARGIN_MAIN", "USDT", excess)
                    logger.info(f"Auto-balance: transferred {excess} USDT excess from margin to spot")
                    await notifier.send(
                        "余额划出",
                        f"账户: {account_note}\n风险值: {margin_level}\n划出: {excess} USDT (margin→spot)",
                        throttle_key=f"excessout:{account_note}",
                    )
                except Exception as e:
                    logger.warning(f"Auto-balance excess transfer failed: {e}")

    except Exception as e:
        logger.warning(f"Auto-balance check error: {e}")
