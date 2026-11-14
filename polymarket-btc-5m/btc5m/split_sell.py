"""P4 split-sell paper engine: mint complete sets → post-only asks → merge/redeem.

Paper-only. Live mint/merge/redeem on CTF is intentionally not wired until
WS cancel/replace and wallet approvals are verified.

Economics (per window):
1. Mint N USDC → N Up + N Down (cost = N)
2. Rest post-only asks both sides at max(touch, fair + edge)
3. Lean clamp: pull ahead side when sold_up - sold_down exceeds lean
4. Near close: merge remaining pairs @ $1, redeem unpaired winner
5. Rebate estimate = sold_notional * rebate_bps / 10000
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from btc5m.book import TopOfBook
from btc5m.config import Config
from btc5m.heartbeat import write_heartbeat
from btc5m.lead_table import hold_win_rate
from btc5m.markets import LiveMarket, fetch_live_market, fetch_market_by_slug, fmt_utc, next_window_eta
from btc5m.resolver import gamma_winner_side
from btc5m.risk import RiskState, allowed_to_trade, note_resolution
from btc5m.signal import fetch_btc_signal
from btc5m.store import Store
from btc5m.twap import fair_up_prob_from_lead
from btc5m.ws_book import get_book

log = logging.getLogger("btc5m.split_sell")


@dataclass
class AskQuote:
    side: str
    token_id: str
    price: float
    size: float
    placed_ts: float
    at_touch_since: Optional[float] = None


@dataclass
class SplitState:
    session_id: int
    market: LiveMarket
    mint_shares: float
    up_inv: float
    down_inv: float
    mint_cost: float
    up_sold: float = 0.0
    down_sold: float = 0.0
    up_proceeds: float = 0.0
    down_proceeds: float = 0.0
    merged: float = 0.0
    merge_proceeds: float = 0.0
    redeem_proceeds: float = 0.0
    rebate_est: float = 0.0
    quotes: dict[str, AskQuote] = field(default_factory=dict)
    quoting: bool = True
    closed: bool = False


def _round_tick(price: float, tick: float) -> float:
    if tick <= 0:
        return round(price, 2)
    steps = round(price / tick)
    return max(tick, min(1.0 - tick, steps * tick))


def settle_split_sell(
    *,
    mint_cost: float,
    up_proceeds: float,
    down_proceeds: float,
    merge_proceeds: float,
    redeem_proceeds: float,
    rebate_est: float,
    up_inv: float,
    down_inv: float,
) -> dict:
    cash = up_proceeds + down_proceeds + merge_proceeds + redeem_proceeds + rebate_est
    net = cash - mint_cost
    residual = abs(up_inv - down_inv)
    return {
        "mint_cost": mint_cost,
        "sell_proceeds": up_proceeds + down_proceeds,
        "merge_proceeds": merge_proceeds,
        "redeem_proceeds": redeem_proceeds,
        "rebate_est_usd": rebate_est,
        "gross_pnl_usd": cash - mint_cost - rebate_est,
        "net_pnl_usd": net,
        "residual_shares": residual,
        "up_inv": up_inv,
        "down_inv": down_inv,
    }


class SplitSellEngine:
    """Paper mint → ask both → merge/redeem loop."""

    def __init__(self, cfg: Config, *, live: bool = False) -> None:
        if live:
            raise RuntimeError(
                "split_sell is paper-only until CTF mint/merge + WS cancel are live-ready"
            )
        self.cfg = cfg
        self.store = Store(cfg.data_dir / "split_sell_paper.db")
        self.risk = RiskState()
        self._state: Optional[SplitState] = None
        self._last_slug: Optional[str] = None
        self._hydrate_risk()
        log.info(
            "Split-sell paper | mint=%.0f edge=%.2f lean≤%.0f clip=%.0f",
            cfg.split_size,
            cfg.split_fair_edge,
            cfg.split_max_lean_shares,
            cfg.split_clip_shares,
        )

    def _hydrate_risk(self) -> None:
        from datetime import datetime, timezone

        day_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()
        self.risk.roll_day()
        self.risk.realized_pnl_usd = self.store.day_realized_pnl(day_start)
        self.risk.open_positions = len(self.store.open_maker_sessions())

    def _fair_asks(self, market: LiveMarket, up: TopOfBook, down: TopOfBook) -> tuple[float, float]:
        tick = market.tick_size
        fair_up = 0.50
        try:
            sig = fetch_btc_signal(self.cfg, market)
            lead = sig.projected_lead_bp if sig.in_final_minute else sig.lead_bp
            lookup = hold_win_rate(elapsed_sec=market.t_elapsed(), lead_bp=lead)
            fair_up = fair_up_prob_from_lead(lookup.hold_wr, lead_bp_signed=lead)
        except Exception as exc:  # noqa: BLE001
            log.debug("fair value fallback: %s", exc)

        fair_dn = 1.0 - fair_up
        up_ask = _round_tick(fair_up + self.cfg.split_fair_edge, tick)
        dn_ask = _round_tick(fair_dn + self.cfg.split_fair_edge, tick)
        # Post-only: never cross the bid; join/raise to sit on ask side
        if up.best_bid is not None:
            up_ask = max(up_ask, _round_tick(up.best_bid + tick, tick))
        if down.best_bid is not None:
            dn_ask = max(dn_ask, _round_tick(down.best_bid + tick, tick))
        if up.best_ask is not None:
            up_ask = max(up_ask, up.best_ask)  # join touch ask (sell)
        if down.best_ask is not None:
            dn_ask = max(dn_ask, down.best_ask)
        up_ask = min(up_ask, 1.0 - tick)
        dn_ask = min(dn_ask, 1.0 - tick)
        return up_ask, dn_ask

    def _lean(self, state: SplitState) -> float:
        return state.up_sold - state.down_sold

    def _target_asks(
        self, state: SplitState, up: TopOfBook, down: TopOfBook
    ) -> tuple[Optional[float], Optional[float]]:
        if not state.quoting:
            return None, None
        if state.up_inv < self.cfg.split_clip_shares and state.down_inv < self.cfg.split_clip_shares:
            return None, None
        up_px, dn_px = self._fair_asks(state.market, up, down)
        lean = self._lean(state)
        # Pull ahead side when lean exceeds clamp
        if lean >= self.cfg.split_max_lean_shares:
            up_px = None  # sold too much UP — wait for DOWN
        elif lean <= -self.cfg.split_max_lean_shares:
            dn_px = None
        if state.up_inv < self.cfg.split_clip_shares:
            up_px = None
        if state.down_inv < self.cfg.split_clip_shares:
            dn_px = None
        return up_px, dn_px

    def _fill_ask(self, state: SplitState, side: str, book: TopOfBook, now: float) -> bool:
        q = state.quotes.get(side)
        if q is None:
            return False
        filled = False
        reason = ""
        # Post-only sell fills when bid lifts into our ask (touch) for N seconds
        at_touch = book.best_bid is not None and book.best_bid + 1e-12 >= q.price
        if at_touch:
            if q.at_touch_since is None:
                q.at_touch_since = now
            elif now - q.at_touch_since >= self.cfg.split_touch_fill_sec:
                filled = True
                reason = f"ask_touch {now - q.at_touch_since:.1f}s bid={book.best_bid:.2f} ask={q.price:.2f}"
        else:
            q.at_touch_since = None
        if not filled:
            return False

        size = min(q.size, state.up_inv if side == "UP" else state.down_inv)
        if size < state.market.min_size:
            state.quotes.pop(side, None)
            return False
        px = q.price
        notional = size * px
        if side == "UP":
            state.up_inv -= size
            state.up_sold += size
            state.up_proceeds += notional
        else:
            state.down_inv -= size
            state.down_sold += size
            state.down_proceeds += notional

        self.store.record_fill(
            market_slug=state.market.market_slug,
            condition_id=state.market.condition_id,
            side=side,
            token_id=q.token_id,
            size=size,
            price=px,
            fee_usd=0.0,
            liquidity="maker",
            strategy="split_sell",
            dry_run=True,
            session_id=state.session_id,
            note=reason,
        )
        # Persist inventory as maker session fields (up/down shares = remaining)
        self.store.update_maker_inventory(
            state.session_id,
            up_shares=state.up_inv,
            down_shares=state.down_inv,
            up_cost_usd=state.mint_cost / 2.0,
            down_cost_usd=state.mint_cost / 2.0,
        )
        state.quotes.pop(side, None)
        log.info(
            "SPLIT FILL SELL %s %s@%.2f x%.0f | inv %.0f/%.0f sold %.0f/%.0f | %s",
            state.market.market_slug,
            side,
            px,
            size,
            state.up_inv,
            state.down_inv,
            state.up_sold,
            state.down_sold,
            reason,
        )
        return True

    def _refresh_quotes(self, state: SplitState, up: TopOfBook, down: TopOfBook, now: float) -> None:
        up_px, dn_px = self._target_asks(state, up, down)
        clip = float(self.cfg.split_clip_shares)

        def place(side: str, token: str, px: Optional[float], book: TopOfBook, inv: float) -> None:
            if px is None or inv < clip:
                state.quotes.pop(side, None)
                return
            size = min(clip, inv)
            old = state.quotes.get(side)
            if old and abs(old.price - px) < 1e-12 and old.size == size:
                return
            at_touch = None
            if book.best_bid is not None and book.best_bid + 1e-12 >= px:
                at_touch = now
            state.quotes[side] = AskQuote(
                side=side,
                token_id=token,
                price=px,
                size=size,
                placed_ts=now,
                at_touch_since=at_touch,
            )

        place("UP", state.market.up_token, up_px, up, state.up_inv)
        place("DOWN", state.market.down_token, dn_px, down, state.down_inv)
        self.store.log(
            "split_quotes",
            {
                "up": up_px,
                "down": dn_px,
                "pair_ask": (up_px or 0) + (dn_px or 0) if up_px and dn_px else None,
                "inv_up": state.up_inv,
                "inv_dn": state.down_inv,
                "lean": self._lean(state),
            },
            state.market.market_slug,
        )

    def _ensure_session(self, market: LiveMarket) -> Optional[SplitState]:
        if self._state and self._state.market.condition_id == market.condition_id:
            return self._state

        row = self.store.get_open_maker_session(market.condition_id)
        if row:
            mint = float(self.cfg.split_size)
            stats = self.store.session_sell_stats(int(row["id"]))
            self._state = SplitState(
                session_id=int(row["id"]),
                market=market,
                mint_shares=mint,
                up_inv=float(row["up_shares"] or 0),
                down_inv=float(row["down_shares"] or 0),
                mint_cost=mint,
                up_sold=stats["up_sold"],
                down_sold=stats["down_sold"],
                up_proceeds=stats["up_proceeds"],
                down_proceeds=stats["down_proceeds"],
            )
            return self._state

        block = allowed_to_trade(
            daily_loss_limit_usd=self.cfg.daily_loss_limit_usd,
            max_open_positions=self.cfg.max_open_positions,
            risk=self.risk,
        )
        if block:
            log.warning("risk block new split session: %s", block)
            return None

        mint = float(self.cfg.split_size)
        sid = self.store.open_maker_session(
            market_slug=market.market_slug,
            condition_id=market.condition_id,
            up_token=market.up_token,
            down_token=market.down_token,
            dry_run=True,
        )
        # Paper mint
        self.store.update_maker_inventory(
            sid,
            up_shares=mint,
            down_shares=mint,
            up_cost_usd=mint / 2.0,
            down_cost_usd=mint / 2.0,
        )
        self.store.log(
            "split_mint",
            {"session_id": sid, "shares": mint, "cost_usd": mint},
            market.market_slug,
        )
        self.risk.open_positions += 1
        self._state = SplitState(
            session_id=sid,
            market=market,
            mint_shares=mint,
            up_inv=mint,
            down_inv=mint,
            mint_cost=mint,
        )
        log.info(
            "SPLIT MINT #%s %s x%.0f | %s→%s",
            sid,
            market.market_slug,
            mint,
            fmt_utc(market.start_ts),
            fmt_utc(market.end_ts),
        )
        return self._state

    def _merge_pairs(self, state: SplitState) -> None:
        paired = min(state.up_inv, state.down_inv)
        if paired <= 0:
            return
        state.up_inv -= paired
        state.down_inv -= paired
        state.merged += paired
        state.merge_proceeds += paired  # $1 per pair
        self.store.update_maker_inventory(
            state.session_id,
            up_shares=state.up_inv,
            down_shares=state.down_inv,
            up_cost_usd=state.mint_cost / 2.0,
            down_cost_usd=state.mint_cost / 2.0,
        )
        self.store.log(
            "split_merge",
            {"session_id": state.session_id, "pairs": paired, "proceeds": paired},
            state.market.market_slug,
        )
        log.info(
            "SPLIT MERGE #%s %s pairs=%.0f → $%.2f | inv %.0f/%.0f",
            state.session_id,
            state.market.market_slug,
            paired,
            paired,
            state.up_inv,
            state.down_inv,
        )

    def _redeem(self, state: SplitState, winner: str) -> None:
        if winner == "UP" and state.up_inv > 0:
            state.redeem_proceeds += state.up_inv
            state.up_inv = 0.0
        elif winner == "DOWN" and state.down_inv > 0:
            state.redeem_proceeds += state.down_inv
            state.down_inv = 0.0
        # Losing residual → 0
        state.up_inv = 0.0
        state.down_inv = 0.0

    def _close_session(self, state: SplitState, winner: str) -> None:
        if state.closed:
            return
        # Merge any remaining pairs first, then redeem
        self._merge_pairs(state)
        self._redeem(state, winner)
        sold_notional = state.up_proceeds + state.down_proceeds
        state.rebate_est = sold_notional * (self.cfg.split_rebate_bps / 10_000.0)
        result = settle_split_sell(
            mint_cost=state.mint_cost,
            up_proceeds=state.up_proceeds,
            down_proceeds=state.down_proceeds,
            merge_proceeds=state.merge_proceeds,
            redeem_proceeds=state.redeem_proceeds,
            rebate_est=state.rebate_est,
            up_inv=state.up_inv,
            down_inv=state.down_inv,
        )
        paired = state.merged
        self.store.close_maker_session(
            state.session_id,
            paired_shares=paired,
            pair_cost=None,
            residual_side=None,
            residual_shares=result["residual_shares"],
            winner=winner,
            gross_pnl_usd=result["gross_pnl_usd"],
            fee_usd=0.0,
            rebate_est_usd=result["rebate_est_usd"],
            net_pnl_usd=result["net_pnl_usd"],
        )
        note_resolution(self.risk, result["net_pnl_usd"])
        self.store.log(
            "split_resolve",
            {"session_id": state.session_id, "winner": winner, **result},
            state.market.market_slug,
        )
        log.info(
            "SPLIT RESOLVED #%s %s winner=%s sold=$%.2f merge=$%.2f redeem=$%.2f "
            "rebate≈$%.2f net=%+.2f day=%+.2f",
            state.session_id,
            state.market.market_slug,
            winner,
            sold_notional,
            state.merge_proceeds,
            state.redeem_proceeds,
            state.rebate_est,
            result["net_pnl_usd"],
            self.risk.realized_pnl_usd,
        )
        state.closed = True
        if self._state and self._state.session_id == state.session_id:
            self._state = None

    def _resolve_open(self) -> None:
        for row in self.store.open_maker_sessions():
            slug = row["market_slug"]
            try:
                market = fetch_market_by_slug(self.cfg.gamma_host, slug)
            except Exception as exc:  # noqa: BLE001
                log.debug("resolve fetch %s: %s", slug, exc)
                continue
            if market is None or market.t_remaining() > 0:
                continue
            winner = gamma_winner_side(self.cfg.gamma_host, market)
            if winner is None and market.t_remaining() < -30:
                try:
                    sig = fetch_btc_signal(self.cfg, market)
                    winner = "UP" if sig.projected_delta_usd >= 0 else "DOWN"
                except Exception:  # noqa: BLE001
                    continue
            if winner is None:
                continue
            mint = float(self.cfg.split_size)
            stats = self.store.session_sell_stats(int(row["id"]))
            state = SplitState(
                session_id=int(row["id"]),
                market=market,
                mint_shares=mint,
                up_inv=float(row["up_shares"] or 0),
                down_inv=float(row["down_shares"] or 0),
                mint_cost=mint,
                up_sold=stats["up_sold"],
                down_sold=stats["down_sold"],
                up_proceeds=stats["up_proceeds"],
                down_proceeds=stats["down_proceeds"],
                quoting=False,
            )
            self._close_session(state, winner)

    def tick(self) -> None:
        self._resolve_open()
        market = fetch_live_market(self.cfg.gamma_host, self.cfg.series_slug)
        if market is None:
            log.info("no live market; next window in %.0fs", next_window_eta())
            return

        if market.market_slug != self._last_slug:
            self._last_slug = market.market_slug
            log.info(
                "market %s | %s→%s | t_left=%.1fs",
                market.market_slug,
                fmt_utc(market.start_ts),
                fmt_utc(market.end_ts),
                market.t_remaining(),
            )

        state = self._ensure_session(market)
        if state is None:
            return

        now = time.time()
        t_left = market.t_remaining(now)
        up = get_book(self.cfg.clob_host, market.up_token)
        down = get_book(self.cfg.clob_host, market.down_token)

        # Stop quoting / merge early
        if t_left <= self.cfg.split_merge_before_end_sec:
            state.quoting = False
            state.quotes.clear()
            self._merge_pairs(state)
            write_heartbeat(
                self.cfg.data_dir,
                mode="split_sell",
                market_slug=market.market_slug,
                detail=f"merged early t_left={t_left:.0f}s",
                pnl_usd=self.risk.realized_pnl_usd,
                open_positions=self.risk.open_positions,
            )
            return

        if t_left <= self.cfg.split_stop_before_end_sec:
            state.quoting = False
            state.quotes.clear()

        self._fill_ask(state, "UP", up, now)
        self._fill_ask(state, "DOWN", down, now)
        if state.quoting:
            self._refresh_quotes(state, up, down, now)

        write_heartbeat(
            self.cfg.data_dir,
            mode="split_sell",
            market_slug=market.market_slug,
            detail=(
                f"inv={state.up_inv:.0f}/{state.down_inv:.0f} "
                f"sold={state.up_sold:.0f}/{state.down_sold:.0f} lean={self._lean(state):+.0f}"
            ),
            pnl_usd=self.risk.realized_pnl_usd,
            open_positions=self.risk.open_positions,
        )
        uq = state.quotes.get("UP")
        dq = state.quotes.get("DOWN")
        log.info(
            "SPLIT %s t_left=%.0fs asks up=%s dn=%s | inv %.0f/%.0f lean=%+.0f",
            market.market_slug,
            t_left,
            f"{uq.price:.2f}" if uq else "-",
            f"{dq.price:.2f}" if dq else "-",
            state.up_inv,
            state.down_inv,
            self._lean(state),
        )

    def run(self, *, once: bool = False) -> None:
        log.info("starting split_sell paper mode (mint→ask→merge/redeem)")
        while True:
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                log.exception("split_sell tick failed")
            if once:
                return
            time.sleep(self.cfg.poll_interval_sec)
