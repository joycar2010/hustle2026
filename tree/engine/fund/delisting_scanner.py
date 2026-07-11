import logging
import re

import httpx

from coincore.models import Symbol
from coincore.db import SessionLocal
from engine.notify.feishu_sender import FeishuSender

logger = logging.getLogger(__name__)

BINANCE_ANNOUNCE_URL = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
DELIST_KEYWORDS = re.compile(
    r"(delist|remove|下架|移除交易对|摘牌)", re.IGNORECASE,
)
SYMBOL_PATTERN = re.compile(r"\b([A-Z]{2,10})(?:USDT|/USDT)\b")

_feishu = FeishuSender()


async def scan_delisting_announcements() -> list[str]:
    """Check Binance announcements for delisting notices.
    Returns list of newly flagged symbols."""
    flagged: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(BINANCE_ANNOUNCE_URL, json={
                "type": 1,
                "catalogId": 48,
                "pageNo": 1,
                "pageSize": 20,
            })
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning(f"Delisting scan: failed to fetch announcements: {e}")
        return []

    articles = data.get("data", {}).get("catalogs", [{}])[0].get("articles", [])
    if not articles:
        articles = data.get("data", {}).get("articles", [])

    delist_articles = [a for a in articles if DELIST_KEYWORDS.search(a.get("title", ""))]
    if not delist_articles:
        return []

    mentioned_symbols: set[str] = set()
    for article in delist_articles:
        title = article.get("title", "")
        matches = SYMBOL_PATTERN.findall(title)
        for m in matches:
            sym = f"{m}USDT"
            mentioned_symbols.add(sym)

    if not mentioned_symbols:
        return []

    db = SessionLocal()
    try:
        for sym_name in mentioned_symbols:
            sym = db.query(Symbol).filter(
                Symbol.symbol == sym_name,
                Symbol.is_active == True,
            ).first()
            if sym and not sym.is_delisting:
                sym.is_delisting = True
                sym.allow_open = False
                flagged.append(sym_name)
                logger.warning(f"Delisting detected: {sym_name}")
        if flagged:
            db.commit()
    finally:
        db.close()

    if flagged:
        try:
            await _feishu.send(
                "下架币种检测",
                f"检测到 {len(flagged)} 个下架币种: {', '.join(flagged)}\n已自动禁止开仓",
            )
        except Exception:
            pass

    return flagged
