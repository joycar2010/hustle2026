"""P7 phase-2 paper sports mainline MM (ATP / CS).

Does not touch BTC 5m/15m crypto engines. Edge = external fair − Poly ask
(fee-aware). Paper fills when ask is cheap vs fair for TOUCH_SEC seconds.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from btc5m.book import TopOfBook
from btc5m.config import Config
from btc5m.event_state import MatchPhase
from btc5m.heartbeat import write_heartbeat
from btc5m.odds_bus import OddsBus
from btc5m.risk import RiskState, allowed_to_trade
from btc5m.sports_discover import MainlineMarket, fetch_mainline_events
from btc5m.store import Store
from btc5m.ws_book import get_book

log = logging.getLogger("btc5m.sports_mm")


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
        self.odds = odds or OddsBus()
        self.store = Store(cfg.data_dir / f"sports_mm_{cfg.product_key}_paper.db")
        self.risk = RiskState()
        self._sessions: dict[str, SportsSession] = {}
        self.min_edge = float(getattr(cfg, "sports_min_edge", 0.04) or 0.04)
        self.quote_shares = max(float(cfg.order_shares), 5.0)
        self.touch_fill_sec = 5.0
        self.pre_game_open_sec = 6 * 3600.0
        log.info(
            "Sports MM paper | series=%s product=%s min_edge=%.3f size=%.0f",
            cfg.series_slug,
            cfg.product_key,
            self.min_edge,
            self.quote_shares,
        )

    def _hydrate_risk(self) -> None:
        from datetime import datetime, timezone

        day_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()
        self.risk.roll_day()
        self.risk.realized_pnl_usd = self.store.day_realized_pnl(day_start)
        self.risk.open_positions = len(self.store.open_maker_sessions())

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
            daily_loss_limit_usd=self.cfg.daily_loss_limit_usd,
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
            if px is None:
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
                size=self.quote_shares,
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
        now = time.time()
        try:
            mains = fetch_mainline_events(
                self.cfg.gamma_host,
                self.cfg.series_slug,
                limit=20,
                now=now,
                include_live=False,
            )
        except Exception:  # noqa: BLE001
            log.exception("sports discover failed")
            return

        active = 0
        for m in mains:
            if m.state.phase != MatchPhase.PRE_GAME:
                continue
            if not m.state.may_quote_mainline(now=now, pre_game_open_sec=self.pre_game_open_sec):
                continue
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

        write_heartbeat(
            self.cfg.data_dir,
            mode="sports_mm",
            market_slug=self.cfg.series_slug,
            detail=f"product={self.cfg.product_key} active_mainlines={active}",
            pnl_usd=self.risk.realized_pnl_usd,
            open_positions=self.risk.open_positions,
        )
        log.info(
            "SPORTS MM %s active=%d open_sessions=%d day=%+.2f",
            self.cfg.series_slug,
            active,
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
