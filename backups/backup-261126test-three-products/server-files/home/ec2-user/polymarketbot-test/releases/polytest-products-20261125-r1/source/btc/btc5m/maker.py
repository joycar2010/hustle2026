"""Bilateral maker paper engine for BTC 5m Up/Down.

Paper-only by default: posts virtual resting bids on both outcomes while
keeping projected pair cost under a cap, simulates maker fills from the
live CLOB top-of-book, and settles inventory at resolution.

Paper fills require fresh public opposing trades after the quote was placed.
The full visible queue ahead must be consumed first.  Public trades are facts;
queue priority is a conservative model, not an exchange order replay.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from btc5m.book import TopOfBook, fetch_book
from btc5m.config import Config
from btc5m.fees import paper_sell_execution, taker_fee_usd
from btc5m.heartbeat import write_heartbeat
from btc5m.markets import LiveMarket, fetch_live_market, fetch_market_by_slug, fmt_utc, next_window_eta
from btc5m.resolver import gamma_winner_side
from btc5m.paper_queue import PaperQueue, PublicTradeTape
from btc5m.risk import (
    RiskState,
    allowed_to_trade,
    beijing_day_start_ts,
    note_resolution,
)
from btc5m.store import Store

log = logging.getLogger("btc5m.maker")


@dataclass
class Quote:
    side: str
    token_id: str
    price: float
    size: float
    placed_ts: float
    at_touch_since: Optional[float] = None
    queue: Optional[PaperQueue] = None
    original_size: Optional[float] = None
    last_evidence_note: str = ""


@dataclass
class FillQuality:
    touch: int = 0
    crossed: int = 0
    skipped_imbalance: int = 0
    flatten: int = 0

    def as_dict(self) -> dict:
        total = self.touch + self.crossed
        return {
            "touch": self.touch,
            "crossed": self.crossed,
            "skipped_imbalance": self.skipped_imbalance,
            "flatten": self.flatten,
            "total_fills": total,
            "crossed_rate": (self.crossed / total) if total else 0.0,
        }


@dataclass
class MakerState:
    session_id: int
    market: LiveMarket
    up_shares: float = 0.0
    down_shares: float = 0.0
    up_cost: float = 0.0
    down_cost: float = 0.0
    up_fee: float = 0.0
    down_fee: float = 0.0
    flatten_pnl_usd: float = 0.0
    slippage_usd: float = 0.0
    up_proceeds_usd: float = 0.0
    down_proceeds_usd: float = 0.0
    quotes: dict[str, Quote] = field(default_factory=dict)
    quoting: bool = True
    flattened: bool = False
    fill_quality: FillQuality = field(default_factory=FillQuality)
    # P5b: pair-complete SLA tracking
    imbalance_since: Optional[float] = None
    first_fill_ts: Optional[float] = None
    killed_zero_fill: bool = False
    exiting: bool = False
    # High-water mark of paired inventory; prevents unpaired settlement gamble.
    paired_peak: float = 0.0
    closed: bool = False

    def note_inventory(self) -> None:
        self.paired_peak = max(self.paired_peak, min(self.up_shares, self.down_shares))


def _round_tick(price: float, tick: float) -> float:
    if tick <= 0:
        return round(price, 2)
    steps = round(price / tick)
    return max(tick, min(1.0 - tick, steps * tick))


def _avg(cost: float, shares: float) -> float:
    return cost / shares if shares > 0 else 0.0


def settle_maker_pnl(
    *,
    up_shares: float,
    down_shares: float,
    up_cost: float,
    down_cost: float,
    up_fee: float,
    down_fee: float,
    winner: str,
    rebate_est: float = 0.0,
    flatten_pnl_usd: float = 0.0,
    slippage_usd: float = 0.0,
) -> dict:
    """Resolution PnL for bilateral inventory (+ any early residual flatten)."""
    if (up_shares > 1e-9 or down_shares > 1e-9) and winner not in {"UP", "DOWN"}:
        raise ValueError("Inventory settlement requires an official UP/DOWN outcome")
    total_cost = up_cost + down_cost
    fees = up_fee + down_fee
    payout = (up_shares if winner == "UP" else 0.0) + (
        down_shares if winner == "DOWN" else 0.0
    )
    # payout is $1 per winning share
    gross = payout - total_cost + float(flatten_pnl_usd)
    paired = min(up_shares, down_shares)
    if paired > 0:
        up_avg = _avg(up_cost, up_shares)
        down_avg = _avg(down_cost, down_shares)
        pair_cost = up_avg + down_avg
    else:
        pair_cost = None
    residual = abs(up_shares - down_shares)
    residual_side = None
    if up_shares > down_shares:
        residual_side = "UP"
    elif down_shares > up_shares:
        residual_side = "DOWN"
    # Gross already uses execution prices, hence includes adverse slippage.
    # Modelled rebates remain an estimate and are never realized Paper cash.
    net = gross - fees
    return {
        "paired_shares": paired,
        "pair_cost": pair_cost,
        "residual_side": residual_side,
        "residual_shares": residual,
        "gross_pnl_usd": gross,
        "fee_usd": fees,
        "rebate_est_usd": rebate_est,
        "net_pnl_usd": net,
        "payout": payout,
        "total_cost": total_cost,
        "flatten_pnl_usd": float(flatten_pnl_usd),
        "slippage_usd": float(slippage_usd),
        "gross_before_slippage_usd": gross + float(slippage_usd),
    }


class MakerEngine:
    """Paper bilateral market-maker loop."""

    def __init__(self, cfg: Config, *, live: bool = False) -> None:
        if live:
            raise RuntimeError(
                "Maker engine is paper-only in this release. "
                "Run without --live (strategy MODE=maker)."
            )
        self.cfg = cfg
        db_name = getattr(cfg, "maker_db_name", None) or "maker_paper.db"
        self.store = Store(cfg.data_dir / db_name)
        self.risk = RiskState()
        self._state: Optional[MakerState] = None
        self._last_slug: Optional[str] = None
        self.trade_tape = PublicTradeTape(
            host=getattr(cfg, "maker_trade_api_host", "https://data-api.polymarket.com/v2"),
            poll_sec=float(getattr(cfg, "maker_trade_poll_sec", 1.0)),
            freshness_sec=float(getattr(cfg, "maker_trade_freshness_sec", 10.0)),
        )
        self._hydrate_risk()
        log.info(
            "Maker paper engine | series=%s db=%s pair_max=%.3f min_bid=%.2f "
            "complete_sla=%.0fs zero_kill=%.0fs size=%.0f",
            cfg.series_slug,
            db_name,
            self._effective_pair_max(),
            cfg.maker_min_bid_price,
            cfg.maker_pair_complete_sec,
            cfg.maker_zero_fill_kill_sec,
            cfg.maker_quote_shares,
        )

    def _hydrate_risk(self) -> None:
        day_start = beijing_day_start_ts()
        self.risk.roll_day()
        self.risk.realized_pnl_usd = self.store.day_realized_pnl(day_start)
        self.risk.open_positions = len(self.store.open_maker_sessions())

    def _state_from_row(self, row, market: LiveMarket) -> MakerState:
        """Restore realized cash/fees as well as remaining inventory on restart."""
        values = dict(row)

        def number(key: str) -> float:
            return float(values.get(key) or 0.0)

        sid = int(values["id"])
        fills = self.store.conn.execute(
            "SELECT ts, note, execution_side FROM fills WHERE session_id=? ORDER BY ts",
            (sid,),
        ).fetchall()
        first = float(fills[0]["ts"]) if fills else None
        exiting = any(
            str(fill["execution_side"] or "").upper() == "SELL"
            or str(fill["note"] or "").startswith("flatten_residual")
            for fill in fills
        )
        imbalance = abs(number("up_shares") - number("down_shares")) > 1e-9
        return MakerState(
            session_id=sid, market=market,
            up_shares=number("up_shares"), down_shares=number("down_shares"),
            up_cost=number("up_cost_usd"), down_cost=number("down_cost_usd"),
            up_fee=number("up_fee_usd"), down_fee=number("down_fee_usd"),
            flatten_pnl_usd=number("flatten_pnl_usd"),
            slippage_usd=number("slippage_usd"),
            up_proceeds_usd=number("up_proceeds_usd"),
            down_proceeds_usd=number("down_proceeds_usd"),
            first_fill_ts=first,
            imbalance_since=(first or float(values["opened_ts"])) if imbalance else None,
            exiting=exiting,
            quoting=not exiting,
            flattened=exiting and not imbalance,
            paired_peak=min(number("up_shares"), number("down_shares")),
        )

    def _effective_pair_max(self) -> float:
        """P1: pair-profit first — cap = min(config max, 1 - min_profit)."""
        by_profit = 1.0 - max(self.cfg.maker_pair_profit_min, 0.0)
        return min(self.cfg.maker_pair_cost_max, by_profit)

    def _target_bids(
        self, market: LiveMarket, up: TopOfBook, down: TopOfBook, state: MakerState
    ) -> tuple[Optional[float], Optional[float]]:
        """Choose resting buy prices with pair-cost and inventory constraints."""
        tick = market.tick_size
        max_pair = self._effective_pair_max()
        # Fair-ish anchors from book
        up_anchor = up.best_bid if up.best_bid is not None else 0.45
        down_anchor = down.best_bid if down.best_bid is not None else 0.45
        # Prefer joining/improving slightly inside without crossing ask
        up_q = up_anchor
        down_q = down_anchor
        if up.best_ask is not None:
            up_q = min(up_q, up.best_ask - tick)
        if down.best_ask is not None:
            down_q = min(down_q, down.best_ask - tick)

        up_sh, dn_sh = state.up_shares, state.down_shares
        min_bid = max(tick, float(self.cfg.maker_min_bid_price))
        up_q = _round_tick(max(min_bid, up_q), tick)
        down_q = _round_tick(max(min_bid, down_q), tick)

        # Enforce projected pair cost including existing averages
        up_avg = _avg(state.up_cost, state.up_shares) if state.up_shares else up_q
        dn_avg = _avg(state.down_cost, state.down_shares) if state.down_shares else down_q

        # P0/P1/P5b: once one side fills, ONLY quote the missing leg
        if up_sh > dn_sh:
            down_q = min(down_q, _round_tick(max_pair - up_avg, tick))
            down_q = _round_tick(max(min_bid, down_q), tick)
            if down_q < min_bid - 1e-12 or (up_avg + down_q) > max_pair + 1e-9:
                return None, None
            if down.best_ask is not None and down_q >= down.best_ask - 1e-12:
                return None, None
            return None, down_q
        if dn_sh > up_sh:
            up_q = min(up_q, _round_tick(max_pair - dn_avg, tick))
            up_q = _round_tick(max(min_bid, up_q), tick)
            if up_q < min_bid - 1e-12 or (dn_avg + up_q) > max_pair + 1e-9:
                return None, None
            if up.best_ask is not None and up_q >= up.best_ask - 1e-12:
                return None, None
            return up_q, None

        # Flat inventory: quote both under pair cap (pair profit priority)
        if up_q + down_q > max_pair:
            half = _round_tick(max_pair / 2.0, tick)
            up_q = min(up_q, half)
            down_q = min(down_q, _round_tick(max_pair - up_q, tick))
        up_q = _round_tick(max(min_bid, up_q), tick)
        down_q = _round_tick(max(min_bid, down_q), tick)

        if up_q < min_bid - 1e-12 or down_q < min_bid - 1e-12:
            return None, None
        if up_q + down_q > max_pair + 1e-9:
            return None, None
        # Applying the min-bid floor must not turn a resting order into a
        # marketable order.  Skip the pair rather than invent post-only fills.
        if (up.best_ask is not None and up_q >= up.best_ask - 1e-12) or (
            down.best_ask is not None and down_q >= down.best_ask - 1e-12
        ):
            return None, None
        return up_q, down_q

    def _fill_side(
        self,
        state: MakerState,
        side: str,
        book: TopOfBook,
        now: float,
    ) -> bool:
        q = state.quotes.get(side)
        if q is None or state.exiting:
            return False
        if q.price + 1e-12 < float(self.cfg.maker_min_bid_price):
            state.quotes.pop(side, None)
            return False
        if q.queue is None:
            q.queue = PaperQueue(q.token_id, q.price, "BUY", q.placed_ts)
            q.queue.observe_book(book, now)
        # Public tape reports actual taker prints.  Queue location is inferred
        # conservatively from the complete displayed depth, never touch-time.
        q.queue.observe_book(book, now)
        rows = self.trade_tape.fetch(state.market.condition_id, now)
        size, evidence = q.queue.consume(
            rows,
            now=now,
            freshness_sec=self.trade_tape.freshness_sec,
            max_size=q.size,
            condition_id=state.market.condition_id,
        )
        if size <= 1e-9:
            if q.last_evidence_note != evidence:
                q.last_evidence_note = evidence
                self.store.log(
                    "maker_fill_evidence_wait",
                    {"session_id": state.session_id, "side": side,
                     "reason": evidence, "queue_ahead": q.queue.queue_ahead,
                     "model": "public_trade_full_visible_queue_model"},
                    state.market.market_slug,
                )
            return False

        cap = max(float(self.cfg.maker_max_imbalance_shares), 0.0)
        # Clamp partial fills to the current allowed inventory.  A quote may
        # have become stale after the opposite leg filled in this same tick.
        difference = state.up_shares - state.down_shares
        room = cap - (difference if side == "UP" else -difference)
        capital = max(float(getattr(self.cfg, "maker_max_capital_usd", 30.0)), 0.0)
        capital_room = max(capital - state.up_cost - state.down_cost, 0.0)
        room = min(room, capital_room / q.price if q.price > 0 else 0.0)
        size = min(size, max(room, 0.0))
        if size <= 1e-9:
            state.quotes.pop(side, None)
            state.fill_quality.skipped_imbalance += 1
            return False
        price = q.price  # A resting maker cannot execute above its buy limit.
        notional = size * price
        inventory = {
            "up_shares": state.up_shares + (size if side == "UP" else 0.0),
            "down_shares": state.down_shares + (size if side == "DOWN" else 0.0),
            "up_cost_usd": state.up_cost + (notional if side == "UP" else 0.0),
            "down_cost_usd": state.down_cost + (notional if side == "DOWN" else 0.0),
            "up_fee_usd": state.up_fee, "down_fee_usd": state.down_fee,
        }
        self.store.record_maker_execution(
            state.session_id,
            fill=dict(
                market_slug=state.market.market_slug,
                condition_id=state.market.condition_id,
                side=side, token_id=q.token_id, size=size, price=price,
                fee_usd=0.0, slippage_usd=0.0, liquidity="maker",
                strategy="maker_mm", dry_run=True, execution_side="BUY",
                fee_source="paper_maker_zero",
                slippage_source="maker_limit_no_price_slippage",
                note=evidence,
            ),
            inventory=inventory,
            accounting={},
        )
        state.up_shares = inventory["up_shares"]
        state.down_shares = inventory["down_shares"]
        state.up_cost = inventory["up_cost_usd"]
        state.down_cost = inventory["down_cost_usd"]
        if state.first_fill_ts is None:
            state.first_fill_ts = now
        state.note_inventory()
        if abs(state.up_shares - state.down_shares) > 1e-9:
            if state.imbalance_since is None:
                state.imbalance_since = now
        else:
            state.imbalance_since = None
        state.fill_quality.touch += 1
        q.size -= size
        if q.size <= 1e-9:
            state.quotes.pop(side, None)
        self.store.log(
            "maker_fill_quality",
            {"session_id": state.session_id, "kind": "public_trade_queue",
             "size": size, "queue_ahead": q.queue.queue_ahead,
             "model": evidence, **state.fill_quality.as_dict()},
            state.market.market_slug,
        )
        log.info(
            "MAKER FILL %s %s@%.2f x%.4f | queue_model=%s inv=%.4f/%.4f",
            state.market.market_slug, side, price, size, evidence,
            state.up_shares, state.down_shares,
        )
        return True

    def _refresh_quotes(
        self, state: MakerState, up: TopOfBook, down: TopOfBook, now: float
    ) -> None:
        if not state.quoting or state.exiting:
            state.quotes.clear()
            return
        up_px, dn_px = self._target_bids(state.market, up, down, state)
        size = float(self.cfg.maker_quote_shares)

        def place(side: str, token: str, px: Optional[float], book: TopOfBook) -> None:
            if px is None:
                state.quotes.pop(side, None)
                return
            old = state.quotes.get(side)
            missing = abs(state.up_shares - state.down_shares)
            quote_size = min(size, missing) if missing > 1e-9 else size
            if quote_size + 1e-9 < state.market.min_size:
                state.quotes.pop(side, None)
                return
            if old and abs(old.price - px) < 1e-12 and old.size <= quote_size:
                # Preserve queue priority and consumed public trade IDs.
                return
            at_touch = None
            if book.best_bid is not None and book.best_bid <= px + 1e-12:
                at_touch = now
            queue = PaperQueue(token, px, "BUY", now)
            queue.observe_book(book, now)
            state.quotes[side] = Quote(
                side=side,
                token_id=token,
                price=px,
                size=quote_size,
                placed_ts=now,
                at_touch_since=at_touch,
                queue=queue,
                original_size=quote_size,
            )

        place("UP", state.market.up_token, up_px, up)
        place("DOWN", state.market.down_token, dn_px, down)
        self.store.log(
            "maker_quotes",
            {
                "up": up_px,
                "down": dn_px,
                "pair": (up_px or 0) + (dn_px or 0) if up_px and dn_px else None,
                "inv_up": state.up_shares,
                "inv_dn": state.down_shares,
            },
            state.market.market_slug,
        )

    def _ensure_session(self, market: LiveMarket) -> Optional[MakerState]:
        if self._state and self._state.market.condition_id == market.condition_id:
            return self._state

        # New window — previous should already be resolved
        row = self.store.get_open_maker_session(market.condition_id)
        if row:
            self._state = self._state_from_row(row, market)
            return self._state

        block = allowed_to_trade(
            daily_loss_limit_usd=self.cfg.daily_loss_limit_usd,
            max_open_positions=self.cfg.max_open_positions,
            risk=self.risk,
        )
        if block:
            log.warning("risk block new maker session: %s", block)
            write_heartbeat(
                self.cfg.data_dir,
                mode="maker",
                market_slug=market.market_slug,
                detail=f"risk_block={block} open_positions={self.risk.open_positions}",
                pnl_usd=self.risk.realized_pnl_usd,
                open_positions=self.risk.open_positions,
            )
            return None

        sid = self.store.open_maker_session(
            market_slug=market.market_slug,
            condition_id=market.condition_id,
            up_token=market.up_token,
            down_token=market.down_token,
            dry_run=True,
        )
        self.risk.open_positions += 1
        self._state = MakerState(session_id=sid, market=market)
        log.info(
            "MAKER SESSION #%s %s | %s→%s",
            sid,
            market.market_slug,
            fmt_utc(market.start_ts),
            fmt_utc(market.end_ts),
        )
        return self._state

    def _flatten_residual(
        self, state: MakerState, up: TopOfBook, down: TopOfBook
    ) -> None:
        """Sell only displayed available residual depth; retry partial exits."""
        if state.flattened:
            return
        state.exiting = True
        state.quoting = False
        state.quotes.clear()
        residual = abs(state.up_shares - state.down_shares)
        if residual <= 1e-9:
            state.flattened = True
            state.imbalance_since = None
            return
        if residual + 1e-9 < state.market.min_size:
            self.store.log(
                "maker_exit_dust_below_min_order",
                {"session_id": state.session_id, "residual": residual,
                 "min_size": state.market.min_size, "action": "wait_official_settlement"},
                state.market.market_slug,
            )
            return
        if state.up_shares > state.down_shares:
            side, book, avg = "UP", up, _avg(state.up_cost, state.up_shares)
        else:
            side, book, avg = "DOWN", down, _avg(state.down_cost, state.down_shares)
        execution = paper_sell_execution(
            book, residual, tick_size=state.market.tick_size,
            ticks=getattr(self.cfg, "paper_slippage_ticks", 1.0),
            pct=getattr(self.cfg, "paper_slippage_pct", 0.0),
        )
        size = float(execution["size"])
        if size <= 1e-9:
            self.store.log(
                "maker_exit_no_depth",
                {"session_id": state.session_id, "side": side, "residual": residual},
                state.market.market_slug,
            )
            return
        price = float(execution["price"])
        slip = float(execution["slippage_usd"])
        fee = taker_fee_usd(price, size, self.cfg.taker_fee_rate)
        pnl = size * (price - avg)  # Includes adverse slippage exactly once.
        inventory = {
            "up_shares": max(state.up_shares - (size if side == "UP" else 0.0), 0.0),
            "down_shares": max(state.down_shares - (size if side == "DOWN" else 0.0), 0.0),
            "up_cost_usd": max(state.up_cost - (size * avg if side == "UP" else 0.0), 0.0),
            "down_cost_usd": max(state.down_cost - (size * avg if side == "DOWN" else 0.0), 0.0),
            "up_fee_usd": state.up_fee + (fee if side == "UP" else 0.0),
            "down_fee_usd": state.down_fee + (fee if side == "DOWN" else 0.0),
        }
        accounting = {
            "flatten_pnl_usd": state.flatten_pnl_usd + pnl,
            "slippage_usd": state.slippage_usd + slip,
            "up_proceeds_usd": state.up_proceeds_usd + (size * price if side == "UP" else 0.0),
            "down_proceeds_usd": state.down_proceeds_usd + (size * price if side == "DOWN" else 0.0),
        }
        self.store.record_maker_execution(
            state.session_id,
            fill=dict(
                market_slug=state.market.market_slug,
                condition_id=state.market.condition_id, side=side,
                token_id=state.market.up_token if side == "UP" else state.market.down_token,
                size=size, price=price, fee_usd=fee, slippage_usd=slip,
                liquidity="taker", strategy="maker_flatten_taker", dry_run=True,
                execution_side="SELL", fee_source="paper_model_v1",
                slippage_source="paper_adverse_model",
                note=(f"flatten_residual bid={execution['raw_price']:.6f} "
                      f"avg={avg:.6f} pnl={pnl:+.8f} fee={fee:.8f} slip={slip:.8f}"),
            ),
            inventory=inventory,
            accounting=accounting,
        )
        # Update memory only after the fill and inventory have committed together.
        state.up_shares, state.down_shares = inventory["up_shares"], inventory["down_shares"]
        state.up_cost, state.down_cost = inventory["up_cost_usd"], inventory["down_cost_usd"]
        state.up_fee, state.down_fee = inventory["up_fee_usd"], inventory["down_fee_usd"]
        state.flatten_pnl_usd = accounting["flatten_pnl_usd"]
        state.slippage_usd = accounting["slippage_usd"]
        state.up_proceeds_usd = accounting["up_proceeds_usd"]
        state.down_proceeds_usd = accounting["down_proceeds_usd"]
        state.flattened = abs(state.up_shares - state.down_shares) <= 1e-9
        if state.flattened:
            state.imbalance_since = None
        state.fill_quality.flatten += 1
        self.store.log(
            "maker_flatten",
            {"session_id": state.session_id, "side": side, "size": size,
             "price": price, "raw_price": execution["raw_price"], "avg": avg,
             "pnl": pnl, "fee_usd": fee, "slippage_usd": slip,
             "remaining": abs(state.up_shares - state.down_shares),
             "execution_side": "SELL", "liquidity": "taker"},
            state.market.market_slug,
        )
        log.info(
            "MAKER FLATTEN %s %s x%.4f @%.4f pnl=%+.4f fee=%.6f slip=%.4f remaining=%.4f",
            state.market.market_slug, side, size, price, pnl, fee, slip,
            abs(state.up_shares - state.down_shares),
        )

    def _abort_unpaired(self, state: MakerState, *, reason: str) -> bool:
        """Close a never-paired session after flattening, without directional settlement."""
        if state.closed or not getattr(self.cfg, "maker_close_on_unpaired_flatten", True):
            return bool(state.closed)
        if state.paired_peak > 1e-9:
            return False
        if not state.flattened or abs(state.up_shares) > 1e-9 or abs(state.down_shares) > 1e-9:
            return False
        state.quoting = False
        state.quotes.clear()
        net = float(state.flatten_pnl_usd)
        self.store.update_maker_inventory(
            state.session_id, up_shares=0.0, down_shares=0.0,
            up_cost_usd=0.0, down_cost_usd=0.0,
            up_fee_usd=state.up_fee, down_fee_usd=state.down_fee,
            flatten_pnl_usd=state.flatten_pnl_usd,
        )
        self.store.close_maker_session(
            state.session_id, paired_shares=0.0, pair_cost=None,
            residual_side=None, residual_shares=0.0, winner="UNPAIRED_ABORT",
            gross_pnl_usd=net, fee_usd=state.up_fee + state.down_fee,
            rebate_est_usd=0.0, net_pnl_usd=net - state.up_fee - state.down_fee,
            slippage_usd=state.slippage_usd, resolution_source="unpaired_abort",
        )
        realized = net - state.up_fee - state.down_fee
        note_resolution(self.risk, realized)
        self.store.log("maker_unpaired_abort", {
            "session_id": state.session_id, "reason": reason,
            "flatten_pnl_usd": net, "paired_peak": state.paired_peak,
        }, state.market.market_slug)
        state.closed = True
        self._state = None if self._state and self._state.session_id == state.session_id else self._state
        log.info("MAKER UNPAIRED ABORT #%s %s reason=%s net=%+.4f", state.session_id, state.market.market_slug, reason, realized)
        return True

    def _resolve_session(
        self, state: MakerState, winner: str, *, resolution_source: str = "official_gamma"
    ) -> None:
        if state.closed:
            return
        if (getattr(self.cfg, "maker_close_on_unpaired_flatten", True)
                and state.paired_peak <= 1e-9 and state.flattened
                and self._abort_unpaired(state, reason="resolve_unpaired")):
            return
        rebate = 0.0  # No confirmed rebate attribution exists for Paper fills.
        result = settle_maker_pnl(
            up_shares=state.up_shares,
            down_shares=state.down_shares,
            up_cost=state.up_cost,
            down_cost=state.down_cost,
            up_fee=state.up_fee,
            down_fee=state.down_fee,
            winner=winner,
            rebate_est=rebate,
            flatten_pnl_usd=state.flatten_pnl_usd,
            slippage_usd=state.slippage_usd,
        )
        self.store.close_maker_session(
            state.session_id,
            paired_shares=result["paired_shares"],
            pair_cost=result["pair_cost"],
            residual_side=result["residual_side"],
            residual_shares=result["residual_shares"],
            winner=winner,
            gross_pnl_usd=result["gross_pnl_usd"],
            fee_usd=result["fee_usd"],
            rebate_est_usd=result["rebate_est_usd"],
            net_pnl_usd=result["net_pnl_usd"],
            slippage_usd=result["slippage_usd"],
            resolution_source=resolution_source,
        )
        note_resolution(self.risk, result["net_pnl_usd"])
        state.closed = True
        self.store.log(
            "maker_resolve",
            {"session_id": state.session_id, "winner": winner,
             "resolution_source": resolution_source, **result},
            state.market.market_slug,
        )
        log.info(
            "MAKER RESOLVED #%s %s winner=%s paired=%.0f pair_cost=%s "
            "resid=%s/%.0f gross=%+.2f net=%+.2f day=%+.2f",
            state.session_id,
            state.market.market_slug,
            winner,
            result["paired_shares"],
            f"{result['pair_cost']:.3f}" if result["pair_cost"] is not None else "n/a",
            result["residual_side"],
            result["residual_shares"],
            result["gross_pnl_usd"],
            result["net_pnl_usd"],
            self.risk.realized_pnl_usd,
        )
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
            state = self._state_from_row(row, market)
            # An empty session has no outcome exposure, but may contain a
            # real flatten loss/fee.  Close it without inventing a BTC winner.
            if state.up_shares <= 1e-9 and state.down_shares <= 1e-9:
                self._resolve_session(
                    state, "FLAT_NO_EXPOSURE", resolution_source="flat_no_exposure"
                )
                continue
            winner = gamma_winner_side(self.cfg.gamma_host, market)
            if winner not in {"UP", "DOWN"}:
                self.store.log(
                    "maker_resolution_wait",
                    {"session_id": state.session_id, "reason": "official_result_pending",
                     "up_shares": state.up_shares, "down_shares": state.down_shares},
                    slug,
                )
                continue
            state.quoting = False
            self._resolve_session(state, winner, resolution_source="official_gamma")

    def tick(self) -> None:
        self._hydrate_risk()
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
            write_heartbeat(
                self.cfg.data_dir,
                mode="maker",
                market_slug="",
                detail="no_live_market",
                pnl_usd=self.risk.realized_pnl_usd,
                open_positions=self.risk.open_positions,
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
        elapsed = market.t_elapsed(now)
        t_left = market.t_remaining(now)

        # Time gates
        if elapsed < self.cfg.maker_start_delay_sec:
            log.info(
                "maker wait start_delay %.0fs (elapsed=%.1f)",
                self.cfg.maker_start_delay_sec,
                elapsed,
            )
            write_heartbeat(
                self.cfg.data_dir,
                mode="maker",
                market_slug=market.market_slug,
                detail=f"start_delay elapsed={elapsed:.1f}s",
                pnl_usd=self.risk.realized_pnl_usd,
                open_positions=self.risk.open_positions,
            )
            return
        up = fetch_book(self.cfg.clob_host, market.up_token)
        down = fetch_book(self.cfg.clob_host, market.down_token)

        # Keep imbalance timer accurate even after restart
        if abs(state.up_shares - state.down_shares) > 1e-9:
            if state.imbalance_since is None:
                state.imbalance_since = now
        else:
            state.imbalance_since = None

        if t_left <= self.cfg.maker_stop_before_end_sec:
            if state.quoting:
                log.info(
                    "maker stop quoting t_left=%.1f <= %.0f",
                    t_left,
                    self.cfg.maker_stop_before_end_sec,
                )
            state.quoting = False
            state.quotes.clear()
            # P0-B / P5b: flatten unpaired residual instead of gambling to resolution
            if self.cfg.maker_flatten_residual:
                self._flatten_residual(state, up, down)
                if self._abort_unpaired(state, reason="stop_before_end_unpaired"):
                    write_heartbeat(self.cfg.data_dir, mode="maker", market_slug=market.market_slug,
                                    detail=f"unpaired_abort t_left={t_left:.0f}s",
                                    pnl_usd=self.risk.realized_pnl_usd, open_positions=self.risk.open_positions)
                    return
            write_heartbeat(
                self.cfg.data_dir,
                mode="maker",
                market_slug=market.market_slug,
                detail=f"stopped quoting t_left={t_left:.0f}s flatten={state.flatten_pnl_usd:+.2f}",
                pnl_usd=self.risk.realized_pnl_usd,
                open_positions=self.risk.open_positions,
            )
            return

        # P5b: kill zero-fill sessions by T−N (default 90s)
        if (
            state.first_fill_ts is None
            and not state.killed_zero_fill
            and t_left <= self.cfg.maker_zero_fill_kill_sec
        ):
            state.killed_zero_fill = True
            state.quoting = False
            state.quotes.clear()
            log.info(
                "MAKER ZERO-FILL KILL %s t_left=%.1f <= %.0f — stop quoting",
                market.market_slug,
                t_left,
                self.cfg.maker_zero_fill_kill_sec,
            )
            write_heartbeat(
                self.cfg.data_dir,
                mode="maker",
                market_slug=market.market_slug,
                detail=f"zero_fill_kill t_left={t_left:.0f}s",
                pnl_usd=self.risk.realized_pnl_usd,
                open_positions=self.risk.open_positions,
            )
            return

        if state.exiting and not state.flattened:
            self._flatten_residual(state, up, down)
            if self._abort_unpaired(state, reason="pair_complete_unpaired"):
                write_heartbeat(self.cfg.data_dir, mode="maker", market_slug=market.market_slug,
                                detail=f"unpaired_abort pair_sla flatten={state.flatten_pnl_usd:+.2f}",
                                pnl_usd=self.risk.realized_pnl_usd, open_positions=self.risk.open_positions)
                return
            write_heartbeat(
                self.cfg.data_dir, mode="maker", market_slug=market.market_slug,
                detail=f"exit_pending inv={state.up_shares:.4f}/{state.down_shares:.4f}",
                pnl_usd=self.risk.realized_pnl_usd, open_positions=self.risk.open_positions,
            )
            return

        if state.flattened or state.killed_zero_fill:
            state.quoting = False
            state.quotes.clear()
            write_heartbeat(
                self.cfg.data_dir,
                mode="maker",
                market_slug=market.market_slug,
                detail=(
                    f"idle flattened={state.flattened} "
                    f"zero_kill={state.killed_zero_fill} "
                    f"inv={state.up_shares:.0f}/{state.down_shares:.0f}"
                ),
                pnl_usd=self.risk.realized_pnl_usd,
                open_positions=self.risk.open_positions,
            )
            return

        # Detect fills on resting quotes first
        self._fill_side(state, "UP", up, now)
        self._fill_side(state, "DOWN", down, now)

        # P5b: pair-complete SLA — if missing leg unfilled > N sec, early flatten
        if (
            self.cfg.maker_early_flatten
            and self.cfg.maker_flatten_residual
            and state.imbalance_since is not None
            and (now - state.imbalance_since) >= self.cfg.maker_pair_complete_sec
        ):
            log.info(
                "MAKER PAIR-COMPLETE SLA %s imbalance=%.1fs ≥ %.0fs — flatten",
                market.market_slug,
                now - state.imbalance_since,
                self.cfg.maker_pair_complete_sec,
            )
            state.quoting = False
            state.quotes.clear()
            self._flatten_residual(state, up, down)
            write_heartbeat(
                self.cfg.data_dir,
                mode="maker",
                market_slug=market.market_slug,
                detail=(
                    f"pair_complete_sla flatten={state.flatten_pnl_usd:+.2f} "
                    f"inv={state.up_shares:.0f}/{state.down_shares:.0f}"
                ),
                pnl_usd=self.risk.realized_pnl_usd,
                open_positions=self.risk.open_positions,
            )
            return

        # Refresh quotes
        self._refresh_quotes(state, up, down, now)

        uq = state.quotes.get("UP")
        dq = state.quotes.get("DOWN")
        fq = state.fill_quality.as_dict()
        imb_age = (
            (now - state.imbalance_since) if state.imbalance_since is not None else 0.0
        )
        write_heartbeat(
            self.cfg.data_dir,
            mode="maker",
            market_slug=market.market_slug,
            detail=(
                f"inv={state.up_shares:.0f}/{state.down_shares:.0f} "
                f"fills touch={fq['touch']} crossed={fq['crossed']} "
                f"imb_age={imb_age:.0f}s"
            ),
            pnl_usd=self.risk.realized_pnl_usd,
            open_positions=self.risk.open_positions,
        )
        log.info(
            "MAKER %s t_left=%.0fs quotes up=%s dn=%s pair=%s | "
            "book up %s/%s dn %s/%s | inv %.0f/%.0f | fill_q touch=%d crossed=%d | imb=%.0fs",
            market.market_slug,
            t_left,
            f"{uq.price:.2f}" if uq else "-",
            f"{dq.price:.2f}" if dq else "-",
            f"{(uq.price + dq.price):.2f}" if uq and dq else "-",
            up.best_bid,
            up.best_ask,
            down.best_bid,
            down.best_ask,
            state.up_shares,
            state.down_shares,
            fq["touch"],
            fq["crossed"],
            imb_age,
        )

    def run(self, *, once: bool = False) -> None:
        log.info("starting maker paper mode (bilateral MM)")
        while True:
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                log.exception("maker tick failed")
            if once:
                return
            time.sleep(self.cfg.poll_interval_sec)
