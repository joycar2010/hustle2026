"""P7 phase-2 paper sports mainline MM (ATP / CS).

Does not touch BTC 5m/15m crypto engines. Edge = external fair − Poly ask
(fee-aware). Paper fills when ask is cheap vs fair for TOUCH_SEC seconds.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

from btc5m.book import TopOfBook
from btc5m.config import Config
from btc5m.event_state import MatchPhase
from btc5m.heartbeat import write_heartbeat
from btc5m.odds_bus import OddsBus, build_odds_bus_from_env
from btc5m.risk import (
    RiskState,
    allowed_to_trade,
    beijing_day_start_ts,
    note_resolution,
)
from btc5m.sports_discover import MainlineMarket, fetch_mainline_events
from btc5m.store import Store
from btc5m.ws_book import get_book

log = logging.getLogger("btc5m.sports_mm")


def _truthy_flag(value: object) -> bool:
    """Parse Gamma boolean fields without treating the string ``"false"`` as true."""
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


@dataclass
class SportsQuote:
    side: str  # HOME | AWAY
    token_id: str
    price: float
    size: float
    placed_ts: float
    at_touch_since: Optional[float] = None


@dataclass
class SportsSession:
    session_id: int
    market: MainlineMarket
    home_shares: float = 0.0
    away_shares: float = 0.0
    home_cost: float = 0.0
    away_cost: float = 0.0
    quotes: dict[str, SportsQuote] = field(default_factory=dict)
    quoting: bool = True
    closed: bool = False


class SportsMmEngine:
    """Paper cross-book fair MM on match-winner mainlines."""

    def __init__(self, cfg: Config, *, live: bool = False, odds: Optional[OddsBus] = None) -> None:
        if live:
            raise RuntimeError("sports_mm is paper-only in this release")
        self.cfg = cfg
        self._heartbeat_mode = f"sports_mm_{getattr(cfg, 'product_key', 'sports')}"
        self.odds = odds or build_odds_bus_from_env()
        self.store = Store(cfg.data_dir / f"sports_mm_{cfg.product_key}_paper.db")
        self.risk = RiskState()
        self._sessions: dict[str, SportsSession] = {}
        self.min_edge = float(getattr(cfg, "sports_min_edge", 0.04) or 0.04)
        self.quote_shares = max(float(cfg.order_shares), 5.0)
        # Paper inventory guard: P7 does not yet have a settlement adapter, so
        # do not let repeated fills grow an unbounded session position.
        self.max_position_shares = max(self.quote_shares * 5.0, 50.0)
        self.touch_fill_sec = 5.0
        self.pre_game_open_sec = float(
            getattr(cfg, "sports_pre_game_open_sec", 6 * 3600.0) or 6 * 3600.0
        )
        self.daily_loss_limit = float(
            getattr(cfg, "sports_daily_loss_limit_usd", None)
            or cfg.daily_loss_limit_usd
            or 40.0
        )
        self.quote_on_mock = bool(getattr(cfg, "sports_quote_on_mock", False))
        self.discover_limit = int(getattr(cfg, "sports_discover_limit", 60) or 60)
        log.info(
            "Sports MM paper | series=%s product=%s min_edge=%.3f size=%.0f",
            cfg.series_slug,
            cfg.product_key,
            self.min_edge,
            self.quote_shares,
        )

    def _hydrate_risk(self) -> None:
        day_start = beijing_day_start_ts()
        self.risk.roll_day()
        self.risk.realized_pnl_usd = self.store.day_realized_pnl(day_start)
        self.risk.open_positions = len(self.store.open_maker_sessions())

    def _fetch_resolution(self, row) -> Optional[tuple[float, float, str]]:
        """Read one resolved sports market from Gamma.

        Sports sessions are stored independently from discovery.  A market
        can disappear from the pre-game feed as soon as it starts, so the
        settlement pass must query each open condition directly.  Prices are
        accepted only when Gamma has a decisive 0/1 outcome; unresolved or
        stale markets stay open for the next pass.
        """
        try:
            response = requests.get(
                f"{self.cfg.gamma_host}/events/slug/{row['market_slug']}",
                timeout=8,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            event = response.json()
        except Exception as exc:  # noqa: BLE001
            log.debug("sports resolve fetch %s: %s", row["market_slug"], exc)
            return None
        markets = event.get("markets") or []
        market = next(
            (
                item
                for item in markets
                if str(item.get("conditionId") or "").lower()
                == str(row["condition_id"] or "").lower()
            ),
            None,
        )
        if market is None:
            market = next(
                (item for item in markets if str(item.get("slug") or "") == str(row["market_slug"])),
                None,
            )
        if market is None or not _truthy_flag(market.get("closed")):
            return None
        raw_tokens = market.get("clobTokenIds")
        raw_prices = market.get("outcomePrices")
        try:
            tokens = json.loads(raw_tokens) if isinstance(raw_tokens, str) else raw_tokens
            prices = json.loads(raw_prices) if isinstance(raw_prices, str) else raw_prices
            prices = [float(value) for value in prices]
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(tokens, list) or len(tokens) != 2 or len(prices) != 2:
            return None
        if max(prices) < 0.95 or min(prices) > 0.05:
            return None
        try:
            up_idx = [str(token) for token in tokens].index(str(row["up_token"]))
            down_idx = [str(token) for token in tokens].index(str(row["down_token"]))
        except ValueError:
            return None
        up_price, down_price = prices[up_idx], prices[down_idx]
        winner = "HOME" if up_price >= down_price else "AWAY"
        return up_price, down_price, winner

    def _resolve_open_sessions(self) -> None:
        """Settle all resolved sessions and release their risk slots."""
        for row in self.store.open_maker_sessions():
            result = self._fetch_resolution(row)
            if result is None:
                continue
            up_price, down_price, winner = result
            up_shares = float(row["up_shares"] or 0.0)
            down_shares = float(row["down_shares"] or 0.0)
            up_cost = float(row["up_cost_usd"] or 0.0)
            down_cost = float(row["down_cost_usd"] or 0.0)
            fees = float(row["up_fee_usd"] or 0.0) + float(row["down_fee_usd"] or 0.0)
            rebate = float(row["rebate_est_usd"] or 0.0)
            payout = up_shares * up_price + down_shares * down_price
            gross = payout - up_cost - down_cost
            net = gross - fees + rebate
            sid = int(row["id"])
            self.store.close_maker_session(
                sid,
                paired_shares=min(up_shares, down_shares),
                pair_cost=None,
                residual_side=None,
                residual_shares=abs(up_shares - down_shares),
                winner=winner,
                gross_pnl_usd=gross,
                fee_usd=fees,
                rebate_est_usd=rebate,
                net_pnl_usd=net,
            )
            note_resolution(self.risk, net)
            self._sessions.pop(str(row["condition_id"]), None)
            self.store.log(
                "sports_resolve",
                {
                    "session_id": sid,
                    "winner": winner,
                    "up_price": up_price,
                    "down_price": down_price,
                    "payout": payout,
                    "gross_pnl_usd": gross,
                    "fee_usd": fees,
                    "rebate_est_usd": rebate,
                    "net_pnl_usd": net,
                },
                str(row["market_slug"]),
            )
            log.info(
                "SPORTS RESOLVED #%s %s winner=%s payout=%.2f gross=%+.2f net=%+.2f",
                sid,
                row["market_slug"],
                winner,
                payout,
                gross,
                net,
            )

    def _ensure(self, m: MainlineMarket) -> Optional[SportsSession]:
        if m.condition_id in self._sessions:
            return self._sessions[m.condition_id]
        row = self.store.get_open_maker_session(m.condition_id)
        if row:
            st = SportsSession(
                session_id=int(row["id"]),
                market=m,
                home_shares=float(row["up_shares"] or 0),
                away_shares=float(row["down_shares"] or 0),
                home_cost=float(row["up_cost_usd"] or 0),
                away_cost=float(row["down_cost_usd"] or 0),
            )
            self._sessions[m.condition_id] = st
            return st
        block = allowed_to_trade(
            daily_loss_limit_usd=self.daily_loss_limit,
            max_open_positions=max(self.cfg.max_open_positions, 5),
            risk=self.risk,
        )
        if block:
            log.debug("risk block sports session: %s", block)
            return None
        sid = self.store.open_maker_session(
            market_slug=m.market_slug,
            condition_id=m.condition_id,
            up_token=m.home_token,
            down_token=m.away_token,
            dry_run=True,
        )
        self.risk.open_positions += 1
        st = SportsSession(session_id=sid, market=m)
        self._sessions[m.condition_id] = st
        self.store.log(
            "sports_session_open",
            {
                "session_id": sid,
                "event": m.event_slug,
                "home": m.home,
                "away": m.away,
                "phase": m.state.phase.value,
            },
            m.market_slug,
        )
        return st

    def _target_buys(
        self, m: MainlineMarket, home_book: TopOfBook, away_book: TopOfBook
    ) -> tuple[Optional[float], Optional[float]]:
        fair = self.odds.fair_match(m.event_slug, m.home, m.away)
        if fair is None:
            return None, None
        if getattr(fair, "is_mock", False) and not self.quote_on_mock:
            return None, None
        home_ask = home_book.best_ask
        away_ask = away_book.best_ask
        home_px = away_px = None
        # Buy side that is cheap vs fair (maker: join bid if edge vs ask fair)
        # Paper simplification: rest a bid at max(best_bid, fair - edge) when ask underprices fair
        tick = m.tick_size
        if home_ask is not None and (fair.p_home - home_ask) >= self.min_edge:
            bid = home_book.best_bid if home_book.best_bid is not None else home_ask - tick
            home_px = min(bid, home_ask - tick)
            home_px = max(tick, round(home_px / tick) * tick)
        if away_ask is not None and (fair.p_away - away_ask) >= self.min_edge:
            bid = away_book.best_bid if away_book.best_bid is not None else away_ask - tick
            away_px = min(bid, away_ask - tick)
            away_px = max(tick, round(away_px / tick) * tick)
        return home_px, away_px

    def _fill(
        self, st: SportsSession, side: str, book: TopOfBook, now: float
    ) -> bool:
        q = st.quotes.get(side)
        if q is None:
            return False
        at_touch = book.best_bid is not None and abs(book.best_bid - q.price) <= 1e-12
        if not at_touch:
            # also allow crossed ask into our bid
            if book.best_ask is not None and book.best_ask <= q.price + 1e-12:
                at_touch = True
        if at_touch:
            if q.at_touch_since is None:
                q.at_touch_since = now
            elif now - q.at_touch_since >= self.touch_fill_sec:
                size = q.size
                px = q.price
                if side == "HOME":
                    st.home_shares += size
                    st.home_cost += size * px
                else:
                    st.away_shares += size
                    st.away_cost += size * px
                self.store.record_fill(
                    market_slug=st.market.market_slug,
                    condition_id=st.market.condition_id,
                    side="UP" if side == "HOME" else "DOWN",
                    token_id=q.token_id,
                    size=size,
                    price=px,
                    fee_usd=0.0,
                    liquidity="maker",
                    strategy="sports_mm",
                    dry_run=True,
                    session_id=st.session_id,
                    note=f"sports_touch {side}@{px:.2f}",
                )
                self.store.update_maker_inventory(
                    st.session_id,
                    up_shares=st.home_shares,
                    down_shares=st.away_shares,
                    up_cost_usd=st.home_cost,
                    down_cost_usd=st.away_cost,
                )
                st.quotes.pop(side, None)
                log.info(
                    "SPORTS FILL %s %s@%.2f x%.0f | inv H=%.0f A=%.0f",
                    st.market.market_slug,
                    side,
                    px,
                    size,
                    st.home_shares,
                    st.away_shares,
                )
                return True
        else:
            q.at_touch_since = None
        return False

    def _refresh(self, st: SportsSession, home_book: TopOfBook, away_book: TopOfBook, now: float) -> None:
        if not st.quoting:
            st.quotes.clear()
            return
        if not st.market.state.may_quote_mainline(
            now=now, pre_game_open_sec=self.pre_game_open_sec
        ):
            st.quoting = False
            st.quotes.clear()
            return
        h_px, a_px = self._target_buys(st.market, home_book, away_book)

        def place(side: str, token: str, px: Optional[float], book: TopOfBook) -> None:
            current = st.home_shares if side == "HOME" else st.away_shares
            if px is None or current >= self.max_position_shares:
                st.quotes.pop(side, None)
                return
            old = st.quotes.get(side)
            if old and abs(old.price - px) < 1e-12:
                return
            at = None
            if book.best_bid is not None and abs(book.best_bid - px) <= 1e-12:
                at = now
            st.quotes[side] = SportsQuote(
                side=side,
                token_id=token,
                price=px,
                size=min(self.quote_shares, self.max_position_shares - current),
                placed_ts=now,
                at_touch_since=at,
            )

        place("HOME", st.market.home_token, h_px, home_book)
        place("AWAY", st.market.away_token, a_px, away_book)
        self.store.log(
            "sports_quotes",
            {
                "home": h_px,
                "away": a_px,
                "event": st.market.event_slug,
                "phase": st.market.state.phase.value,
            },
            st.market.market_slug,
        )

    def tick(self) -> None:
        self._hydrate_risk()
        # Resolve by stored market/condition before discovery.  Closed events
        # are intentionally absent from the pre-game feed.
        self._resolve_open_sessions()
        now = time.time()
        try:
            mains = fetch_mainline_events(
                self.cfg.gamma_host,
                self.cfg.series_slug,
                limit=self.discover_limit,
                now=now,
                include_live=False,
                pre_game_open_sec=self.pre_game_open_sec,
            )
        except Exception:  # noqa: BLE001
            log.exception("sports discover failed")
            write_heartbeat(
                self.cfg.data_dir,
                mode=self._heartbeat_mode,
                market_slug=self.cfg.series_slug,
                detail=f"product={self.cfg.product_key} status=discover_error",
                pnl_usd=self.risk.realized_pnl_usd,
                open_positions=self.risk.open_positions,
            )
            return

        risk_block = allowed_to_trade(
            daily_loss_limit_usd=self.daily_loss_limit,
            max_open_positions=max(self.cfg.max_open_positions, 5),
            risk=self.risk,
        )
        risk_reason = None
        if risk_block and "daily loss" in risk_block:
            risk_reason = "daily_loss"
        elif risk_block and "max open" in risk_block:
            risk_reason = "max_open"
        pre = [m for m in mains if m.state.phase == MatchPhase.PRE_GAME]
        quoteable = [
            m for m in pre
            if m.state.may_quote_mainline(now=now, pre_game_open_sec=self.pre_game_open_sec)
        ]
        allow_new = risk_reason is None and (
            self.quote_on_mock or not self.odds.using_mock
        )
        active = 0
        if allow_new:
            for m in quoteable:
                st = self._ensure(m)
                if st is None:
                    continue
                st.market = m  # refresh phase
                home_book = get_book(self.cfg.clob_host, m.home_token)
                away_book = get_book(self.cfg.clob_host, m.away_token)
                self._fill(st, "HOME", home_book, now)
                self._fill(st, "AWAY", away_book, now)
                self._refresh(st, home_book, away_book, now)
                active += 1

        if risk_reason:
            detail = f"status=risk_blocked reason={risk_reason}"
        elif self.odds.using_mock and not self.quote_on_mock:
            detail = f"status=mock_odds_quote_disabled discover_pre={len(pre)} quoteable={len(quoteable)}"
        elif not pre:
            detail = "status=discover_empty"
        elif not quoteable:
            detail = f"status=outside_window discover_pre={len(pre)}"
        else:
            detail = f"status=running active_mainlines={active} quoteable={len(quoteable)}"

        write_heartbeat(
            self.cfg.data_dir,
            mode=self._heartbeat_mode,
            market_slug=self.cfg.series_slug,
            detail=f"product={self.cfg.product_key} {detail}",
            pnl_usd=self.risk.realized_pnl_usd,
            open_positions=self.risk.open_positions,
        )
        log.info(
            "SPORTS MM %s %s open_sessions=%d day=%+.2f",
            self.cfg.series_slug,
            detail,
            self.risk.open_positions,
            self.risk.realized_pnl_usd,
        )

    def run(self, *, once: bool = False) -> None:
        log.info("starting sports_mm paper (%s)", self.cfg.series_slug)
        while True:
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                log.exception("sports_mm tick failed")
            if once:
                return
            time.sleep(self.cfg.poll_interval_sec)
