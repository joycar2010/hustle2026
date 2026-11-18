"""P7/P7.1 paper sports mainline MM (ATP / CS).

Does not touch BTC 5m/15m crypto engines. Edge = external fair − Poly ask
(fee-aware). Paper fills when ask is cheap vs fair for TOUCH_SEC seconds.

P7.1: discover future-first, close LIVE zombies, separate sports daily loss,
refuse quotes on mock odds unless SPORTS_QUOTE_ON_MOCK=1, emit parseable
heartbeat status (risk_blocked / outside_window / discover_empty / running).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from btc5m.book import TopOfBook
from btc5m.config import Config
from btc5m.event_state import MatchPhase, MatchState
from btc5m.heartbeat import write_heartbeat
from btc5m.odds_bus import OddsBus, build_odds_bus_from_env
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
        self.odds = odds or build_odds_bus_from_env()
        self.store = Store(cfg.data_dir / f"sports_mm_{cfg.product_key}_paper.db")
        self.risk = RiskState()
        self._sessions: dict[str, SportsSession] = {}
        self.min_edge = float(getattr(cfg, "sports_min_edge", 0.04) or 0.04)
        self.quote_shares = max(float(cfg.order_shares), 5.0)
        self.touch_fill_sec = 5.0
        self.pre_game_open_sec = float(
            getattr(cfg, "sports_pre_game_open_sec", 6 * 3600) or 6 * 3600
        )
        self.daily_loss_limit = float(
            getattr(cfg, "sports_daily_loss_limit_usd", None)
            or cfg.daily_loss_limit_usd
            or 40.0
        )
        self.quote_on_mock = bool(getattr(cfg, "sports_quote_on_mock", False))
        self.discover_limit = int(getattr(cfg, "sports_discover_limit", 60) or 60)
        log.info(
            "Sports MM paper | series=%s product=%s min_edge=%.3f size=%.0f "
            "loss_limit=%.0f quote_on_mock=%s odds=%s",
            cfg.series_slug,
            cfg.product_key,
            self.min_edge,
            self.quote_shares,
            self.daily_loss_limit,
            self.quote_on_mock,
            self.odds.primary_source,
        )

    def _hydrate_risk(self) -> None:
        from datetime import datetime, timezone

        day_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()
        self.risk.roll_day()
        self.risk.realized_pnl_usd = self.store.day_realized_pnl(day_start)
        self.risk.open_positions = len(self.store.open_maker_sessions())

    def _close_session(
        self,
        st: SportsSession,
        *,
        winner: str,
        gross: float = 0.0,
        net: float = 0.0,
    ) -> None:
        if st.closed:
            return
        paired = min(st.home_shares, st.away_shares)
        residual = abs(st.home_shares - st.away_shares)
        residual_side = None
        if st.home_shares > st.away_shares:
            residual_side = "HOME"
        elif st.away_shares > st.home_shares:
            residual_side = "AWAY"
        self.store.close_maker_session(
            st.session_id,
            paired_shares=paired,
            pair_cost=None,
            residual_side=residual_side,
            residual_shares=residual,
            winner=winner,
            gross_pnl_usd=gross,
            fee_usd=0.0,
            rebate_est_usd=0.0,
            net_pnl_usd=net,
        )
        st.closed = True
        st.quoting = False
        st.quotes.clear()
        self._sessions.pop(st.market.condition_id, None)
        self.risk.open_positions = max(self.risk.open_positions - 1, 0)
        self.store.log(
            "sports_session_close",
            {
                "session_id": st.session_id,
                "winner": winner,
                "net": net,
                "event": st.market.event_slug,
            },
            st.market.market_slug,
        )

    def _sweep_stale_sessions(self, mains: list[MainlineMarket], now: float) -> int:
        """Close open sessions that are LIVE / missing from discover / past start."""
        live_ids = {m.condition_id: m for m in mains}
        closed = 0
        # DB open rows not in memory
        for row in self.store.open_maker_sessions():
            cid = str(row["condition_id"] or "")
            if cid in self._sessions:
                continue
            slug = str(row["market_slug"] or "")
            st = SportsSession(
                session_id=int(row["id"]),
                market=MainlineMarket(
                    event_slug=slug,
                    event_title="",
                    market_slug=slug,
                    condition_id=cid,
                    question="",
                    home="HOME",
                    away="AWAY",
                    home_token=str(row["up_token"] or ""),
                    away_token=str(row["down_token"] or ""),
                    start_ts=0.0,
                    tick_size=0.01,
                    min_size=5,
                    state=MatchState(
                        event_slug=slug,
                        home="HOME",
                        away="AWAY",
                        phase=MatchPhase.LIVE,
                        start_ts=0.0,
                    ),
                ),
                home_shares=float(row["up_shares"] or 0),
                away_shares=float(row["down_shares"] or 0),
                home_cost=float(row["up_cost_usd"] or 0),
                away_cost=float(row["down_cost_usd"] or 0),
            )
            self._sessions[cid] = st

        for cid, st in list(self._sessions.items()):
            m = live_ids.get(cid)
            if m is not None:
                st.market = m
                if m.state.phase == MatchPhase.PRE_GAME and m.state.may_quote_mainline(
                    now=now, pre_game_open_sec=self.pre_game_open_sec
                ):
                    continue
                # Past pre-game window or LIVE → close empty or mark abort
                inv = st.home_shares + st.away_shares
                self._close_session(
                    st,
                    winner="LIVE_ABORT" if inv > 0 else "EXPIRED_EMPTY",
                    gross=0.0,
                    net=0.0,
                )
                closed += 1
                continue
            # Not in discover set → expire
            inv = st.home_shares + st.away_shares
            self._close_session(
                st,
                winner="DISCOVER_DROP" if inv > 0 else "EXPIRED_EMPTY",
                gross=0.0,
                net=0.0,
            )
            closed += 1
        return closed

    def _ensure(self, m: MainlineMarket) -> Optional[SportsSession]:
        if m.condition_id in self._sessions:
            st = self._sessions[m.condition_id]
            return None if st.closed else st
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
        if fair.is_mock and not self.quote_on_mock:
            return None, None
        home_ask = home_book.best_ask
        away_ask = away_book.best_ask
        home_px = away_px = None
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

    def _status_detail(
        self,
        *,
        active: int,
        discover_pre: int,
        quoteable: int,
        nearest_h: Optional[float],
        risk_block: Optional[str],
        closed_stale: int,
    ) -> str:
        odds = "mock" if self.odds.using_mock else self.odds.primary_source
        if risk_block:
            return (
                f"status=risk_blocked reason={risk_block} "
                f"pnl={self.risk.realized_pnl_usd:.2f} limit={self.daily_loss_limit:.0f} "
                f"odds={odds} closed_stale={closed_stale}"
            )
        if self.odds.using_mock and not self.quote_on_mock:
            return (
                f"status=mock_odds_quote_disabled discover_pre={discover_pre} "
                f"quoteable={quoteable} odds={odds} closed_stale={closed_stale}"
            )
        if discover_pre == 0:
            return f"status=discover_empty odds={odds} closed_stale={closed_stale}"
        if quoteable == 0:
            nearest = f"{nearest_h:.2f}" if nearest_h is not None else "na"
            return (
                f"status=outside_window discover_pre={discover_pre} "
                f"nearest_h={nearest} odds={odds} closed_stale={closed_stale}"
            )
        return (
            f"status=running active_mainlines={active} quoteable={quoteable} "
            f"odds={odds} closed_stale={closed_stale}"
        )

    def tick(self) -> None:
        self._hydrate_risk()
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
                mode=f"sports_mm_{self.cfg.product_key}",
                market_slug=self.cfg.series_slug,
                detail="status=discover_error",
                pnl_usd=self.risk.realized_pnl_usd,
                open_positions=self.risk.open_positions,
            )
            return

        closed_stale = self._sweep_stale_sessions(mains, now)
        self._hydrate_risk()

        pre = [m for m in mains if m.state.phase == MatchPhase.PRE_GAME]
        quoteable_list = [
            m
            for m in pre
            if m.state.may_quote_mainline(now=now, pre_game_open_sec=self.pre_game_open_sec)
        ]
        nearest_h = None
        if pre:
            nearest_h = max(0.0, (min(m.start_ts for m in pre) - now) / 3600.0)

        risk_block = allowed_to_trade(
            daily_loss_limit_usd=self.daily_loss_limit,
            max_open_positions=max(self.cfg.max_open_positions, 5),
            risk=self.risk,
        )
        # Only treat daily-loss / max-open as hard block for status when no room
        if risk_block and "daily loss" in risk_block:
            risk_reason = "daily_loss"
        elif risk_block and "max open" in risk_block:
            risk_reason = "max_open"
        else:
            risk_reason = None

        allow_new = risk_reason is None and (
            self.quote_on_mock or not self.odds.using_mock
        )

        active = 0
        if allow_new:
            for m in quoteable_list:
                st = self._ensure(m)
                if st is None:
                    # risk blocked mid-loop
                    if risk_reason is None:
                        mid = allowed_to_trade(
                            daily_loss_limit_usd=self.daily_loss_limit,
                            max_open_positions=max(self.cfg.max_open_positions, 5),
                            risk=self.risk,
                        )
                        if mid and "daily loss" in mid:
                            risk_reason = "daily_loss"
                        elif mid and "max open" in mid:
                            risk_reason = "max_open"
                    continue
                st.market = m
                home_book = get_book(self.cfg.clob_host, m.home_token)
                away_book = get_book(self.cfg.clob_host, m.away_token)
                self._fill(st, "HOME", home_book, now)
                self._fill(st, "AWAY", away_book, now)
                self._refresh(st, home_book, away_book, now)
                active += 1

        detail = self._status_detail(
            active=active,
            discover_pre=len(pre),
            quoteable=len(quoteable_list),
            nearest_h=nearest_h,
            risk_block=risk_reason,
            closed_stale=closed_stale,
        )
        write_heartbeat(
            self.cfg.data_dir,
            mode=f"sports_mm_{self.cfg.product_key}",
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
