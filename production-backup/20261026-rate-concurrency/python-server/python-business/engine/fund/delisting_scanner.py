"""Unified Binance/Telegram delisting monitor.

The monitor is deliberately fail-closed: a source outage does not clear an
existing delisting gate, and only messages that satisfy the required keyword
combination can disable new opens.  Existing positions are untouched.
"""

from __future__ import annotations

import logging
import re
import asyncio
from datetime import datetime, timezone
from typing import Any

from app.db.models import Blacklist, DelistingMonitorConfig, PendingBlacklist, Symbol
from app.db.session import SessionLocal
from app.services.binance_cms import BinanceCmsError, fetch_articles
from engine.notify.feishu_sender import FeishuSender

logger = logging.getLogger(__name__)

# The Chinese rule is intentionally AND/OR rather than a broad "delist"
# substring: all three required terms must be present, plus one market leg.
REQUIRED_TERMS = ("下线", "币", "USDT")
LEG_TERMS = ("合约", "现货", "杠杆", "全仓", "逐仓")
_EN_REQUIRED = ("delist", "usdt")
_EN_LEGS = ("futures", "spot", "margin", "cross", "isolated", "contract")

# Accept pair spellings seen in CMS titles and Telegram messages.  A bare
# "币 USDT" without a base symbol is intentionally not converted to a pair.
SYMBOL_PATTERN = re.compile(
    r"(?<![A-Z0-9])([A-Z][A-Z0-9]{1,19})(?:[-_/\s]?USDT)(?![A-Z0-9])",
    re.IGNORECASE,
)

_SYMBOL_STOPWORDS = {
    "THE", "AND", "FOR", "ALL", "NEW", "WILL", "COIN", "TO", "OF",
    "FROM", "THIS", "THAT", "WITH", "USDT",
}

_feishu = FeishuSender()
_scan_lock = asyncio.Lock()


def announcement_text(article: dict[str, Any]) -> str:
    """Combine all text fields available from CMS/Telegram adapters."""

    return " ".join(
        str(article.get(key) or "")
        for key in ("title", "content", "description", "summary", "text")
    ).strip()


def matches_delisting_keywords(text: str) -> bool:
    """Apply the required Chinese keyword rule (with English CMS alias).

    Chinese announcements require ``下线`` + ``币`` + ``USDT`` and at least
    one of the five market-leg terms.  English Binance mirrors commonly use
    ``delist``; they receive the equivalent ``delist`` + ``USDT`` + one leg
    rule so an English-only CMS feed remains useful without broad matching.
    """

    raw = str(text or "")
    upper = raw.upper()
    if (
        "下线" in raw
        and "币" in raw
        and "USDT" in upper
        and any(term in raw for term in LEG_TERMS)
    ):
        return True
    lower = raw.lower()
    return all(term in lower for term in _EN_REQUIRED) and any(term in lower for term in _EN_LEGS)


def extract_symbols(text: str) -> set[str]:
    """Extract canonical USDT symbols from a source message."""

    found: set[str] = set()
    for match in SYMBOL_PATTERN.finditer(str(text or "").upper()):
        base = match.group(1).upper()
        if base in _SYMBOL_STOPWORDS:
            continue
        # A compact match can start at the beginning of an already-normalized
        # ``BTCUSDT`` token.  Keep only the base asset so a secondary Chinese
        # extraction pass cannot turn it into ``BTCUSDTUSDT``.
        if base.endswith("USDT"):
            base = base[:-4]
        if not base or base in _SYMBOL_STOPWORDS:
            continue
        found.add(f"{base}USDT")
    # Chinese group posts often write "下线币：ONT（USDT 合约）" rather
    # than the compact ONTUSDT spelling.  Accept that form only when the
    # message explicitly contains USDT; never infer a quote asset otherwise.
    upper_text = str(text or "").upper()
    if "USDT" in upper_text:
        # ``下线币：ONT（USDT 合约）`` / ``SYMBOL: ONT USDT``.
        for match in re.finditer(
            r"(?:币|SYMBOL)\s*[:：]?\s*([A-Z][A-Z0-9]{1,19})\b",
            upper_text,
        ):
            base = match.group(1)
            if base.endswith("USDT"):
                base = base[:-4]
            if base and base not in _SYMBOL_STOPWORDS:
                found.add(f"{base}USDT")
        # Some notices place the ticker before the Chinese classifier:
        # ``下线 BTC 币 USDT 合约``.  Require the explicit classifier and quote
        # asset; do not infer a pair from a bare English ``to USDT`` phrase.
        for match in re.finditer(
            r"\b([A-Z][A-Z0-9]{1,19})\b\s*币(?=[^\n]{0,32}\bUSDT\b)",
            upper_text,
        ):
            base = match.group(1)
            if base.endswith("USDT"):
                base = base[:-4]
            if base and base not in _SYMBOL_STOPWORDS:
                found.add(f"{base}USDT")
    return found


def _article_event(article: dict[str, Any], source: str) -> list[dict[str, Any]]:
    text = announcement_text(article)
    if not matches_delisting_keywords(text):
        return []
    code = str(article.get("code") or article.get("id") or "")
    url = str(article.get("url") or (
        f"https://www.binance.com/zh-CN/support/announcement/{code}" if code else ""
    ))
    return [
        {
            "symbol": symbol,
            "source": source,
            "event_id": code or text[:120],
            "reason": f"{source} delisting signal: {text[:400]}",
            "title": str(article.get("title") or text[:400]),
            "url": url,
        }
        for symbol in sorted(extract_symbols(text))
    ]


async def _fetch_telegram_events(config: DelistingMonitorConfig) -> list[dict[str, Any]]:
    """Read an already-authorized Telegram StringSession, if configured.

    Telethon is optional at runtime.  ``connect`` is used instead of
    ``start`` so the service can never prompt for or persist an account
    password/2FA secret.  Operators must provision a StringSession out of
    band and paste only that encrypted session into the admin form.
    """

    # EncryptedString decrypts on attribute access. A rotated/missing key
    # must not abort the Binance source scan or leak decryption details into
    # the worker response; disable this optional source until it is repaired.
    try:
        telegram_enabled = bool(config.telegram_enabled)
        telegram_api_id = config.telegram_api_id
        telegram_api_hash = config.telegram_api_hash
        telegram_session = config.telegram_session
        telegram_chat = config.telegram_chat
    except Exception as exc:
        logger.warning("Telegram delisting config unavailable (%s)", type(exc).__name__)
        return []
    if not (
        telegram_enabled
        and telegram_api_id
        and telegram_api_hash
        and telegram_session
        and telegram_chat
    ):
        return []
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        logger.warning("Telegram delisting source enabled but telethon is not installed")
        return []

    client = None
    try:
        client = TelegramClient(
            StringSession(telegram_session),
            int(telegram_api_id),
            telegram_api_hash,
        )
        await client.connect()
        if not await client.is_user_authorized():
            logger.warning("Telegram delisting session is not authorized; refusing interactive login")
            await client.disconnect()
            return []
        events: list[dict[str, Any]] = []
        async for message in client.iter_messages(telegram_chat, limit=100):
            text = str(getattr(message, "message", "") or "")
            if not matches_delisting_keywords(text):
                continue
            for symbol in sorted(extract_symbols(text)):
                message_id = str(getattr(message, "id", ""))
                events.append({
                    "symbol": symbol,
                    "source": "telegram",
                    "event_id": f"{telegram_chat}:{message_id}",
                    "reason": f"Telegram delisting signal: {text[:400]}",
                    "title": text[:500],
                    "url": "",
                })
        await client.disconnect()
        return events
    except Exception as exc:
        # Do not include exception payloads: Telegram libraries can echo
        # request/session material in verbose errors.
        logger.warning("Telegram delisting scan failed (%s)", type(exc).__name__)
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass
        return []


def _upsert_event(db, event: dict[str, Any]) -> bool:
    """Atomically gate a symbol and retain an auditable pending event."""

    symbol_name = str(event["symbol"]).upper()
    symbol = db.query(Symbol).filter(Symbol.symbol == symbol_name).first()
    was_new = False
    if symbol is None:
        # Keep a discovered pair visible in admin coin management even when
        # exchangeInfo has already removed it.  It is never execution-eligible.
        symbol = Symbol(
            symbol=symbol_name,
            base_asset=symbol_name[:-4],
            quote_asset="USDT",
            margin_tradable=False,
            futures_tradable=False,
            is_active=True,
            is_delisting=True,
            allow_open=False,
        )
        db.add(symbol)
        was_new = True
    else:
        was_new = not bool(symbol.is_delisting)
    symbol.is_delisting = True
    symbol.allow_open = False

    global_blacklist = db.query(Blacklist).filter(
        Blacklist.symbol == symbol_name,
        Blacklist.user_id.is_(None),
    ).first()
    if global_blacklist is None:
        db.add(Blacklist(
            symbol=symbol_name,
            reason=f"Confirmed delisting ({event['source']})",
            user_id=None,
        ))

    pending = db.query(PendingBlacklist).filter(
        PendingBlacklist.symbol == symbol_name,
        PendingBlacklist.is_confirmed.is_(False),
    ).first()
    if pending is None:
        db.add(PendingBlacklist(
            symbol=symbol_name,
            reason=event["reason"],
            source=event["source"],
            announcement_title=event.get("title"),
            announcement_url=event.get("url"),
            source_event_id=event.get("event_id"),
        ))
    else:
        # Keep the newest evidence while retaining the existing review row.
        pending.reason = event["reason"]
        pending.source = event["source"]
        pending.announcement_title = event.get("title")
        pending.announcement_url = event.get("url")
        pending.source_event_id = event.get("event_id")
    return was_new


def _persist_events(events: list[dict[str, Any]]) -> list[str]:
    if not events:
        return []
    db = SessionLocal()
    flagged: list[str] = []
    try:
        for event in events:
            if _upsert_event(db, event):
                flagged.append(event["symbol"])
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return sorted(set(flagged))


async def _scan_delisting_sources() -> list[str]:
    """Scan CMS and optional Telegram, then immediately block new actions."""

    # A single global switch controls both sources.  Missing configuration is
    # treated as enabled so older installations keep their CMS protection.
    config_db = SessionLocal()
    try:
        initial_config = config_db.query(DelistingMonitorConfig).filter(
            DelistingMonitorConfig.id == 1
        ).first()
        if initial_config is not None and not initial_config.enabled:
            return []
    finally:
        config_db.close()

    events: list[dict[str, Any]] = []
    cms_error: str | None = None
    try:
        articles = await fetch_articles(page_size=100)
        for article in articles:
            events.extend(_article_event(article, "binance_announcement"))
    except BinanceCmsError as exc:
        cms_error = str(exc)
        logger.warning("Delisting scan: Binance CMS unavailable: %s", exc)

    db = SessionLocal()
    try:
        config = db.query(DelistingMonitorConfig).filter(DelistingMonitorConfig.id == 1).first()
        if config is None:
            config = DelistingMonitorConfig(id=1)
            db.add(config)
            db.commit()
            db.refresh(config)
        telegram_events = await _fetch_telegram_events(config)
        # Do not store credentials in logs or exception text.
        config.last_scan_at = datetime.now(timezone.utc)
        config.last_error = cms_error
        db.commit()
    finally:
        db.close()
    events.extend(telegram_events)

    flagged = _persist_events(events)
    if flagged:
        try:
            await _feishu.send(
                "下架币种检测",
                f"检测到 {len(flagged)} 个下架币种: {', '.join(flagged)}\n已禁止新借币/开仓；已有仓位不自动强平",
            )
        except Exception:
            logger.debug("delisting Feishu notification failed", exc_info=True)
    return flagged


async def scan_delisting_sources() -> list[str]:
    """Run at most one source scan per engine process.

    One Worker engine hosts an orchestrator per tenant.  A non-blocking
    process lock prevents those orchestrators from multiplying CMS/Telegram
    requests every 30 seconds; the database gates remain idempotent for a
    second process or an administrator-triggered scan.
    """
    if _scan_lock.locked():
        return []
    async with _scan_lock:
        return await _scan_delisting_sources()


async def scan_delisting_announcements() -> list[str]:
    """Backward-compatible alias used by older Worker images."""

    return await scan_delisting_sources()
