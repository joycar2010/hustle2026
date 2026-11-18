"""P4/P6 split-sell paper engine: mint → bilateral asks → residual flatten → merge/redeem.

Paper-only. Live mint/merge/redeem on CTF is intentionally not wired until
WS cancel/replace and wallet approvals are verified.

Economics (per window):
1. Mint N USDC → N Up + N Down (cost = N)
2. Post-only asks both sides — **join touch** for fillability (P6)
3. Lean clamp: pull ahead side; lagging side improves into touch faster
4. Residual SLA: sell excess inventory at best bid to re-balance
5. Near close: merge remaining pairs @ $1, redeem unpaired winner
6. Rebate estimate = sold_notional * rebate_bps / 10000
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
    catchup: bool = False


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
    flatten_pnl_usd: float = 0.0
    quotes: dict[str, AskQuote] = field(default_factory=dict)
    quoting: bool = True
    closed: bool = False
    # P5a/P6: lean + residual closed loop
    lean_breach_since: Optional[float] = None
    lean_aborted: bool = False
    residual_since: Optional[float] = None
    residual_flattened: bool = False


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
    flatten_pnl_usd: float = 0.0,
) -> dict:
    # Flatten residual sells are already booked into up/down_proceeds;
    # flatten_pnl_usd is diagnostic (proceeds vs $0.50 mint basis).
    cash = up_proceeds + down_proceeds + merge_proceeds + redeem_proceeds + rebate_est
    net = cash - mint_cost
    residual = abs(up_inv - down_inv)
    return {
        "mint_cost": mint_cost,
        "sell_proceeds": up_proceeds + down_proceeds,
        "merge_proceeds": merge_proceeds,
        "redeem_proceeds": redeem_proceeds,
        "rebate_est_usd": rebate_est,
        "flatten_pnl_usd": float(flatten_pnl_usd),
        "gross_pnl_usd": cash - mint_cost - rebate_est,
        "net_pnl_usd": net,
        "residual_shares": residual,
        "up_inv": up_inv,
        "down_inv": down_inv,
    }


class SplitSellEngine:
    """Paper mint → ask both → residual flatten → merge/redeem loop."""

    def __init__(self, cfg: Config, *, live: bool = False) -> None:
        if live:
            raise RuntimeError(
                "split_sell is paper-only until CTF mint/merge + WS cancel are live-ready"
            )
        self.cfg = cfg
        db_name = getattr(cfg, "split_db_name", None) or "split_sell_paper.db"
        self.store = Store(cfg.data_dir / db_name)
        self.risk = RiskState()
        self._state: Optional[SplitState] = None
        self._last_slug: Optional[str] = None
        self._hydrate_risk()
        log.info(
            "Split-sell paper | series=%s db=%s mint=%.0f edge=%.2f lean≤%.0f "
            "min_pair_ask=%.2f join_touch=%s residual_sla=%.0fs",
            cfg.series_slug,
            db_name,
            cfg.split_size,
            cfg.split_fair_edge,
            cfg.split_max_lean_shares,
            cfg.split_min_pair_ask,
            cfg.split_join_touch,
            cfg.split_residual_sla_sec,
        )

    def _hb_mode(self) -> str:
        """P7.1: keep 5m and 15m heartbeats from overwriting each other."""
        key = getattr(self.cfg, "product_key", "") or ""
        db = getattr(self.cfg, "split_db_name", "") or ""
        if key == "btc15m" or "15m" in db:
            return "split_sell_15m"
        return "split_sell"

    def _hydrate_risk(self) -> None:
        from datetime import datetime, timezone

        day_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()
        self.risk.roll_day()
        self.risk.realized_pnl_usd = self.store.day_realized_pnl(day_start)
        self.risk.open_positions = len(self.store.open_maker_sessions())

    def _fair_probs(self, market: LiveMarket) -> tuple[float, float]:
        fair_up = 0.50
        try:
            sig = fetch_btc_signal(self.cfg, market)
            lead = sig.projected_lead_bp if sig.in_final_minute else sig.lead_bp
            lookup = hold_win_rate(elapsed_sec=market.t_elapsed(), lead_bp=lead)
            fair_up = fair_up_prob_from_lead(lookup.hold_wr, lead_bp_signed=lead)
        except Exception as exc:  # noqa: BLE001
            log.debug("fair value fallback: %s", exc)
        return fair_up, 1.0 - fair_up

    def _side_ask(
        self,
        fair: float,
        book: TopOfBook,
        tick: float,
        *,
        catchup: bool,
    ) -> Optional[float]:
        """Build a post-only ask; P6 joins touch so both legs can actually fill."""
        min_ask = max(
            tick,
            float(
                self.cfg.split_catchup_min_ask if catchup else self.cfg.split_min_ask_price
            ),
        )
        floor = tick
        if book.best_bid is not None:
            floor = max(floor, _round_tick(book.best_bid + tick, tick))

        fair_px = _round_tick(fair + self.cfg.split_fair_edge, tick)

        if self.cfg.split_join_touch and book.best_ask is not None:
            touch = _round_tick(book.best_ask, tick)
            if catchup and self.cfg.split_catchup_improve_ticks > 0:
                touch = _round_tick(
                    touch - self.cfg.split_catchup_improve_ticks * tick, tick
                )
            # Join (or improve) touch — never lift far above the book
            ask = max(floor, touch)
            # Keep a soft fair floor only when it does not destroy fillability
            # (fair within 2 ticks of touch)
            if fair_px <= touch + 2 * tick + 1e-12:
                ask = max(ask, min(fair_px, touch))
        else:
            ask = max(floor, fair_px)
            if book.best_ask is not None:
                ask = max(ask, book.best_ask)

        ask = max(ask, min_ask)
        ask = min(ask, 1.0 - tick)
        if ask + 1e-12 < min_ask:
            return None
        # If still far above touch, skip — unfillable lottery quote
        if (
            self.cfg.split_join_touch
            and book.best_ask is not None
            and ask > book.best_ask + 3 * tick + 1e-12
            and not catchup
        ):
            return None
        return ask

    def _lean(self, state: SplitState) -> float:
        return state.up_sold - state.down_sold

    def _inv_residual(self, state: SplitState) -> float:
        return abs(state.up_inv - state.down_inv)

    def _note_residual(self, state: SplitState, now: float) -> None:
        if self._inv_residual(state) > 1e-9:
            if state.residual_since is None:
                state.residual_since = now
        else:
            state.residual_since = None

    def _target_asks(
        self, state: SplitState, up: TopOfBook, down: TopOfBook
    ) -> tuple[Optional[float], Optional[float]]:
        if not state.quoting or state.lean_aborted or state.residual_flattened:
            return None, None
        if state.up_inv < self.cfg.split_clip_shares and state.down_inv < self.cfg.split_clip_shares:
            return None, None

        tick = state.market.tick_size
        fair_up, fair_dn = self._fair_probs(state.market)
        lean = self._lean(state)
        max_lean = float(self.cfg.split_max_lean_shares)

        up_catchup = lean <= -max_lean + 1e-9  # sold too much DOWN → catch UP
        dn_catchup = lean >= max_lean - 1e-9  # sold too much UP → catch DOWN

        up_px = self._side_ask(fair_up, up, tick, catchup=up_catchup)
        dn_px = self._side_ask(fair_dn, down, tick, catchup=dn_catchup)

        # Pull ahead side when lean exceeds clamp — only quote lagging leg
        if lean >= max_lean - 1e-9:
            up_px = None
        elif lean <= -max_lean + 1e-9:
            dn_px = None

        if state.up_inv < self.cfg.split_clip_shares:
            up_px = None
        if state.down_inv < self.cfg.split_clip_shares:
            dn_px = None

        # Dual-quote gate: both legs must clear min pair ask (mint edge / rebate path)
        if up_px is not None and dn_px is not None:
            if (up_px + dn_px) + 1e-12 < float(self.cfg.split_min_pair_ask):
                return None, None

        return up_px, dn_px

    def _note_lean(self, state: SplitState, now: float) -> None:
        lean = abs(self._lean(state))
        if lean >= self.cfg.split_max_lean_shares - 1e-9:
            if state.lean_breach_since is None:
                state.lean_breach_since = now
        else:
            state.lean_breach_since = None

    def _flatten_residual(
        self, state: SplitState, up: TopOfBook, down: TopOfBook, *, reason: str
    ) -> bool:
        """P6: sell excess inventory at best bid until up_inv == down_inv."""
        if not self.cfg.split_residual_flatten:
            return False
        residual = self._inv_residual(state)
        if residual <= 1e-9:
            state.residual_since = None
            return False
        if state.up_inv > state.down_inv:
            side, book = "UP", up
        else:
            side, book = "DOWN", down
        px = book.best_bid
        if px is None or px <= 0:
            log.warning(
                "SPLIT FLATTEN skip %s — no bid for residual %.0f (%s)",
                state.market.market_slug,
                residual,
                reason,
            )
            return False

        # Cost basis ≈ $0.50 per minted share; flatten PnL vs that basis
        basis = 0.5
        notional = residual * px
        pnl = residual * (px - basis)
        if side == "UP":
            state.up_inv -= residual
            state.up_sold += residual
            state.up_proceeds += notional
        else:
            state.down_inv -= residual
            state.down_sold += residual
            state.down_proceeds += notional
        state.flatten_pnl_usd += pnl
        state.residual_since = None
        state.quotes.clear()

        self.store.update_maker_inventory(
            state.session_id,
            up_shares=state.up_inv,
            down_shares=state.down_inv,
            up_cost_usd=state.mint_cost / 2.0,
            down_cost_usd=state.mint_cost / 2.0,
            flatten_pnl_usd=state.flatten_pnl_usd,
        )
        token = state.market.up_token if side == "UP" else state.market.down_token
        self.store.record_fill(
            market_slug=state.market.market_slug,
            condition_id=state.market.condition_id,
            side=side,
            token_id=token,
            size=residual,
            price=px,
            fee_usd=0.0,
            liquidity="taker",
            strategy="split_sell",
            dry_run=True,
            session_id=state.session_id,
            note=f"flatten_residual bid={px:.2f} basis={basis:.2f} pnl={pnl:+.2f} ({reason})",
        )
        self.store.log(
            "split_flatten",
            {
                "session_id": state.session_id,
                "side": side,
                "size": residual,
                "price": px,
                "pnl": pnl,
                "reason": reason,
            },
            state.market.market_slug,
        )
        log.info(
            "SPLIT FLATTEN %s %s x%.0f @%.2f pnl=%+.2f | inv %.0f/%.0f | %s",
            state.market.market_slug,
            side,
            residual,
            px,
            pnl,
            state.up_inv,
            state.down_inv,
            reason,
        )
        return True

    def _maybe_residual_sla(
        self, state: SplitState, up: TopOfBook, down: TopOfBook, now: float
    ) -> bool:
        if state.residual_flattened or state.residual_since is None:
            return False
        if (now - state.residual_since) < self.cfg.split_residual_sla_sec:
            return False
        did = self._flatten_residual(state, up, down, reason="residual_sla")
        if did:
            # After rebalance, merge pairs to lock capital; stop quoting this window
            self._merge_pairs(state)
            state.quoting = False
            state.residual_flattened = True
            state.quotes.clear()
        return did

    def _maybe_lean_abort(
        self, state: SplitState, up: TopOfBook, down: TopOfBook, now: float
    ) -> bool:
        """If lean clamp lasts too long: flatten residual, merge, stop asks."""
        if state.lean_aborted or state.lean_breach_since is None:
            return False
        if (now - state.lean_breach_since) < self.cfg.split_lean_abort_sec:
            return False
        state.lean_aborted = True
        state.quoting = False
        state.quotes.clear()
        self._flatten_residual(state, up, down, reason="lean_abort")
        self._merge_pairs(state)
        self.store.log(
            "split_lean_abort",
            {
                "session_id": state.session_id,
                "lean": self._lean(state),
                "breach_sec": now - state.lean_breach_since,
                "merged": state.merged,
                "flatten_pnl": state.flatten_pnl_usd,
            },
            state.market.market_slug,
        )
        log.info(
            "SPLIT LEAN ABORT #%s %s lean=%+.0f after %.0fs — flatten+merge",
            state.session_id,
            state.market.market_slug,
            self._lean(state),
            now - state.lean_breach_since,
        )
        return True

    def _fill_ask(self, state: SplitState, side: str, book: TopOfBook, now: float) -> bool:
        q = state.quotes.get(side)
        if q is None:
            return False
        filled = False
        reason = ""
        touch_need = (
            self.cfg.split_catchup_touch_fill_sec
            if q.catchup
            else self.cfg.split_touch_fill_sec
        )
        # Post-only sell fills when bid lifts into our ask (touch) for N seconds
        at_touch = book.best_bid is not None and book.best_bid + 1e-12 >= q.price
        if at_touch:
            if q.at_touch_since is None:
                q.at_touch_since = now
            elif now - q.at_touch_since >= touch_need:
                filled = True
                reason = (
                    f"ask_touch {now - q.at_touch_since:.1f}s "
                    f"bid={book.best_bid:.2f} ask={q.price:.2f}"
                    f"{' catchup' if q.catchup else ''}"
                )
        else:
            q.at_touch_since = None
        if not filled:
            return False

        min_ask = float(
            self.cfg.split_catchup_min_ask if q.catchup else self.cfg.split_min_ask_price
        )
        if q.price + 1e-12 < min_ask:
            state.quotes.pop(side, None)
            log.info(
                "SPLIT SKIP FILL %s %s@%.2f — below min_ask %.2f",
                state.market.market_slug,
                side,
                q.price,
                min_ask,
            )
            return False

        # Refuse fills that would push lean beyond clamp on the ahead side
        tentative_lean = self._lean(state) + (
            q.size if side == "UP" else -q.size
        )
        max_lean = float(self.cfg.split_max_lean_shares)
        if abs(tentative_lean) > max_lean + 1e-9 and abs(tentative_lean) > abs(
            self._lean(state)
        ):
            state.quotes.pop(side, None)
            log.info(
                "SPLIT SKIP FILL %s %s — lean would be %+.0f > ±%.0f",
                state.market.market_slug,
                side,
                tentative_lean,
                max_lean,
            )
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
        self.store.update_maker_inventory(
            state.session_id,
            up_shares=state.up_inv,
            down_shares=state.down_inv,
            up_cost_usd=state.mint_cost / 2.0,
            down_cost_usd=state.mint_cost / 2.0,
            flatten_pnl_usd=state.flatten_pnl_usd,
        )
        state.quotes.pop(side, None)
        self._note_residual(state, now)
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

    def _refresh_quotes(
        self, state: SplitState, up: TopOfBook, down: TopOfBook, now: float
    ) -> None:
        up_px, dn_px = self._target_asks(state, up, down)
        clip = float(self.cfg.split_clip_shares)
        lean = self._lean(state)
        max_lean = float(self.cfg.split_max_lean_shares)

        def place(
            side: str,
            token: str,
            px: Optional[float],
            book: TopOfBook,
            inv: float,
            catchup: bool,
        ) -> None:
            if px is None or inv < clip:
                state.quotes.pop(side, None)
                return
            size = min(clip, inv)
            old = state.quotes.get(side)
            if (
                old
                and abs(old.price - px) < 1e-12
                and old.size == size
                and old.catchup == catchup
            ):
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
                catchup=catchup,
            )

        place(
            "UP",
            state.market.up_token,
            up_px,
            up,
            state.up_inv,
            lean <= -max_lean + 1e-9,
        )
        place(
            "DOWN",
            state.market.down_token,
            dn_px,
            down,
            state.down_inv,
            lean >= max_lean - 1e-9,
        )
        self.store.log(
            "split_quotes",
            {
                "up": up_px,
                "down": dn_px,
                "pair_ask": (up_px or 0) + (dn_px or 0) if up_px and dn_px else None,
                "inv_up": state.up_inv,
                "inv_dn": state.down_inv,
                "lean": lean,
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
            flatten = 0.0
            try:
                flatten = float(row["flatten_pnl_usd"] or 0)
            except (KeyError, IndexError, TypeError):
                flatten = 0.0
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
                flatten_pnl_usd=flatten,
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
            flatten_pnl_usd=state.flatten_pnl_usd,
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
        state.up_inv = 0.0
        state.down_inv = 0.0

    def _close_session(self, state: SplitState, winner: str) -> None:
        if state.closed:
            return
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
            flatten_pnl_usd=state.flatten_pnl_usd,
        )
        self.store.close_maker_session(
            state.session_id,
            paired_shares=state.merged,
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
            "flatten=%+.2f rebate≈$%.2f net=%+.2f day=%+.2f",
            state.session_id,
            state.market.market_slug,
            winner,
            sold_notional,
            state.merge_proceeds,
            state.redeem_proceeds,
            state.flatten_pnl_usd,
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
                self.store.log(
                    "split_unresolved",
                    {"session_id": int(row["id"]), "reason": "gamma_result_pending"},
                    slug,
                )
                continue
            mint = float(self.cfg.split_size)
            stats = self.store.session_sell_stats(int(row["id"]))
            flatten = 0.0
            try:
                flatten = float(row["flatten_pnl_usd"] or 0)
            except (KeyError, IndexError, TypeError):
                flatten = 0.0
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
                flatten_pnl_usd=flatten,
                quoting=False,
            )
            self._close_session(state, winner)

    def tick(self) -> None:
        self._resolve_open()
        market = fetch_live_market(
            self.cfg.gamma_host,
            self.cfg.series_slug,
            window_sec=int(getattr(self.cfg, "window_sec", 300) or 300),
            slug_prefix=str(
                getattr(self.cfg, "market_slug_prefix", None) or "btc-updown-5m"
            ),
        )
        if market is None:
            log.info(
                "no live market; next window in %.0fs",
                next_window_eta(
                    window_sec=int(getattr(self.cfg, "window_sec", 300) or 300)
                ),
            )
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
        self._note_residual(state, now)

        # Near close: flatten residual → merge pairs
        if t_left <= self.cfg.split_merge_before_end_sec:
            state.quoting = False
            state.quotes.clear()
            self._flatten_residual(state, up, down, reason="merge_window")
            self._merge_pairs(state)
            write_heartbeat(
                self.cfg.data_dir,
                mode=self._hb_mode(),
                market_slug=market.market_slug,
                detail=(
                    f"merged early t_left={t_left:.0f}s "
                    f"sold={state.up_sold:.0f}/{state.down_sold:.0f} "
                    f"merge={state.merged:.0f} flat={state.flatten_pnl_usd:+.2f}"
                ),
                pnl_usd=self.risk.realized_pnl_usd,
                open_positions=self.risk.open_positions,
            )
            return

        if t_left <= self.cfg.split_stop_before_end_sec:
            state.quoting = False
            state.quotes.clear()

        if not state.lean_aborted and not state.residual_flattened:
            self._fill_ask(state, "UP", up, now)
            self._fill_ask(state, "DOWN", down, now)
            self._note_lean(state, now)
            self._note_residual(state, now)

            if self._maybe_residual_sla(state, up, down, now):
                write_heartbeat(
                    self.cfg.data_dir,
                    mode=self._hb_mode(),
                    market_slug=market.market_slug,
                    detail=(
                        f"residual_sla flat={state.flatten_pnl_usd:+.2f} "
                        f"merge={state.merged:.0f} inv={state.up_inv:.0f}/{state.down_inv:.0f}"
                    ),
                    pnl_usd=self.risk.realized_pnl_usd,
                    open_positions=self.risk.open_positions,
                )
                return

            if self._maybe_lean_abort(state, up, down, now):
                write_heartbeat(
                    self.cfg.data_dir,
                    mode=self._hb_mode(),
                    market_slug=market.market_slug,
                    detail=(
                        f"lean_abort lean={self._lean(state):+.0f} "
                        f"flat={state.flatten_pnl_usd:+.2f} merge={state.merged:.0f} "
                        f"inv={state.up_inv:.0f}/{state.down_inv:.0f}"
                    ),
                    pnl_usd=self.risk.realized_pnl_usd,
                    open_positions=self.risk.open_positions,
                )
                return

        if state.quoting and not state.lean_aborted and not state.residual_flattened:
            self._refresh_quotes(state, up, down, now)

        lean = self._lean(state)
        lean_age = (
            (now - state.lean_breach_since)
            if state.lean_breach_since is not None
            else 0.0
        )
        resid_age = (
            (now - state.residual_since) if state.residual_since is not None else 0.0
        )
        write_heartbeat(
            self.cfg.data_dir,
            mode=self._hb_mode(),
            market_slug=market.market_slug,
            detail=(
                f"inv={state.up_inv:.0f}/{state.down_inv:.0f} "
                f"sold={state.up_sold:.0f}/{state.down_sold:.0f} "
                f"lean={lean:+.0f} lean_age={lean_age:.0f}s "
                f"resid_age={resid_age:.0f}s merge={state.merged:.0f}"
            ),
            pnl_usd=self.risk.realized_pnl_usd,
            open_positions=self.risk.open_positions,
        )
        uq = state.quotes.get("UP")
        dq = state.quotes.get("DOWN")
        log.info(
            "SPLIT %s t_left=%.0fs asks up=%s dn=%s pair=%s | "
            "inv %.0f/%.0f lean=%+.0f resid_age=%.0fs merge=%.0f",
            market.market_slug,
            t_left,
            f"{uq.price:.2f}" if uq else "-",
            f"{dq.price:.2f}" if dq else "-",
            f"{(uq.price + dq.price):.2f}" if uq and dq else "-",
            state.up_inv,
            state.down_inv,
            lean,
            resid_age,
            state.merged,
        )

    def run(self, *, once: bool = False) -> None:
        log.info("starting split_sell paper mode (mint→ask→flatten→merge/redeem)")
        while True:
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                log.exception("split_sell tick failed")
            if once:
                return
            time.sleep(self.cfg.poll_interval_sec)
