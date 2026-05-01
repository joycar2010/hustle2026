import logging
from decimal import Decimal

from engine.config_loader import FundRulesSnapshot
from engine.trading.binance_trading import BinanceTradingClient

logger = logging.getLogger(__name__)

TRANSFER_TYPES = {
    ("futures", "margin"): "UMFUTURE_MARGIN",
    ("spot", "margin"): "MAIN_MARGIN",
    ("margin", "spot"): "MARGIN_MAIN",
    ("margin", "futures"): "MARGIN_UMFUTURE",
    ("spot", "futures"): "MAIN_UMFUTURE",
    ("futures", "spot"): "UMFUTURE_MAIN",
}


async def ensure_margin_balance(
    client: BinanceTradingClient,
    rules: FundRulesSnapshot,
    required_amount: Decimal,
):
    margin_info = await client.get_margin_account()
    usdt_free = Decimal("0")
    for asset in margin_info.get("userAssets", []):
        if asset["asset"] == "USDT":
            usdt_free = Decimal(str(asset.get("free", "0")))
            break

    if usdt_free >= required_amount:
        return True

    deficit = required_amount - usdt_free
    transfer_amount = min(deficit, rules.single_transfer_amount)

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
            logger.info(f"Transferred {transfer_amount} USDT from {source} to margin")
            return True
        except Exception as e:
            logger.warning(f"Transfer from {source} failed: {e}")
            continue

    return False
