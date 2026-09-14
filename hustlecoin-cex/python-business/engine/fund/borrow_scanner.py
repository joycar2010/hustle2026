import logging
from datetime import datetime, timezone
from decimal import Decimal

from app.db.models import SymbolRule
from app.db.session import SessionLocal
from engine.trading.binance_trading import BinanceTradingClient

logger = logging.getLogger(__name__)


async def scan_manual_borrows(
    client: BinanceTradingClient,
    sub_account_id: int,
    user_id: int | None,
    pushed_symbols: set[str],
) -> list[str]:
    """Scan margin account for manually borrowed assets not in pushed list.
    Returns list of newly detected symbols."""
    try:
        margin_info = await client.get_margin_account()
    except Exception as e:
        logger.warning(f"Borrow scan failed for account {sub_account_id}: {e}")
        return []

    new_symbols = []
    for asset_info in margin_info.get("userAssets", []):
        borrowed = Decimal(str(asset_info.get("borrowed", "0")))
        if borrowed <= 0:
            continue
        asset = asset_info["asset"]
        if asset in ("USDT", "BNB"):
            continue
        symbol = f"{asset}USDT"
        if symbol in pushed_symbols:
            continue

        new_symbols.append(symbol)
        logger.info(f"Detected manual borrow: {symbol} qty={borrowed} (account {sub_account_id})")

        db = SessionLocal()
        try:
            existing = db.query(SymbolRule).filter(
                SymbolRule.user_id == user_id,
                SymbolRule.symbol == symbol,
            ).first()
            if not existing:
                rule = SymbolRule(
                    user_id=user_id,
                    symbol=symbol,
                    allow_repay=False,
                    allow_remove=False,
                    source="scan",
                )
                db.add(rule)
            elif existing.source != "custom":
                existing.allow_repay = False
                existing.allow_remove = False
                existing.source = "scan"
            db.commit()
        finally:
            db.close()

    return new_symbols
