import logging

from sqlalchemy.orm import Session

from app.db.models import Symbol
from app.services import binance_client

logger = logging.getLogger(__name__)


async def sync_symbols(db: Session) -> dict:
    try:
        spot_data = await binance_client.fetch_spot_exchange_info()
    except Exception as e:
        raise RuntimeError(f"现货交易对获取失败: {e}")
    try:
        futures_data = await binance_client.fetch_futures_exchange_info()
    except Exception as e:
        raise RuntimeError(f"合约交易对获取失败: {e}")

    futures_set = {s["symbol"] for s in futures_data}
    spot_map = {s["symbol"]: s for s in spot_data}

    all_symbols = set(spot_map.keys()) | futures_set

    existing = {s.symbol: s for s in db.query(Symbol).all()}

    new_added = 0
    updated = 0
    deactivated = 0

    for sym_name in all_symbols:
        spot_info = spot_map.get(sym_name)
        base_asset = spot_info["base_asset"] if spot_info else sym_name.replace("USDT", "")
        quote_asset = "USDT"
        margin = spot_info["is_margin"] if spot_info else False
        futures = sym_name in futures_set

        if sym_name in existing:
            row = existing[sym_name]
            changed = False
            if row.margin_tradable != margin:
                row.margin_tradable = margin
                changed = True
            if row.futures_tradable != futures:
                row.futures_tradable = futures
                changed = True
            if not row.is_active:
                row.is_active = True
                changed = True
            if changed:
                updated += 1
            existing.pop(sym_name)
        else:
            db.add(Symbol(
                symbol=sym_name,
                base_asset=base_asset,
                quote_asset=quote_asset,
                margin_tradable=margin,
                futures_tradable=futures,
                is_active=True,
            ))
            new_added += 1

    for row in existing.values():
        if row.is_active:
            row.is_active = False
            deactivated += 1

    db.commit()

    total = len(all_symbols)
    logger.info(f"Symbol sync: {total} fetched, {new_added} new, {updated} updated, {deactivated} deactivated")
    return {
        "total_fetched": total,
        "new_added": new_added,
        "updated": updated,
        "deactivated": deactivated,
    }
