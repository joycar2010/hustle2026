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
import math
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from btc5m.book import TopOfBook
from btc5m.config import Config, validate_split_parameters
from btc5m.fees import paper_slipped_sell_price, taker_fee_usd
from btc5m.heartbeat import write_heartbeat
from btc5m.lead_table import hold_win_rate
from btc5m.markets import LiveMarket, fetch_live_market, fetch_market_by_slug, fmt_utc, next_window_eta
from btc5m.resolver import gamma_winner_side
from btc5m.paper_queue import PaperQueue, PublicTradeTape
from btc5m.risk import RiskState, allowed_to_trade, beijing_day_start_ts
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
    queue: Optional[PaperQueue] = None
    original_size: Optional[float] = None
    last_evidence_note: str = ""


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
    up_fee: float = 0.0
    down_fee: float = 0.0
    up_slippage: float = 0.0
    down_slippage: float = 0.0
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
    fee_usd: float = 0.0,
    slippage_usd: float = 0.0,
) -> dict:
    # Flatten residual sells are already booked into up/down_proceeds;
    # flatten_pnl_usd is diagnostic (proceeds vs $0.50 mint basis).
    # An estimated maker rebate is not a received cash flow.  Keep it in the
    # separate audit field, never in realized PnL or the daily loss circuit.
    cash = up_proceeds + down_proceeds + merge_proceeds + redeem_proceeds
    # Slippage is already reflected in effective sell proceeds.  Fees are
    # explicit cash costs and are deducted exactly once here.
    net = cash - mint_cost - float(fee_usd)
    residual = abs(up_inv - down_inv)
    return {
        "mint_cost": mint_cost,
        "sell_proceeds": up_proceeds + down_proceeds,
        "merge_proceeds": merge_proceeds,
        "redeem_proceeds": redeem_proceeds,
        "rebate_est_usd": rebate_est,
        "fee_usd": float(fee_usd),
        "slippage_usd": float(slippage_usd),
        "flatten_pnl_usd": float(flatten_pnl_usd),
        "gross_pnl_usd": cash - mint_cost,
        "net_pnl_usd": net,
        "residual_shares": residual,
        "up_inv": up_inv,
        "down_inv": down_inv,
    }


def repair_split_merge_accounting(db_path: Path, *, dry_run: bool = False) -> dict:
    """Fix closed sessions where full merge cash was dropped (net ≈ −mint).

    Symptom seen live: mint=$50, merged_shares=50, merge_proceeds=$50, sells=$0,
    but net_pnl=−$50 (merge cash not credited in settle after restart).
    """
    import sqlite3
    import time as _time

    out = {"path": str(db_path), "scanned": 0, "repaired": 0, "ids": [], "dry_run": dry_run}
    if not db_path.exists():
        return out
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(maker_sessions)")}
        need = {
            "merge_proceeds_usd",
            "merged_shares",
            "up_proceeds_usd",
            "down_proceeds_usd",
            "redeem_proceeds_usd",
            "up_cost_usd",
            "down_cost_usd",
        }
        if not need.issubset(cols):
            out["error"] = "missing split cash columns"
            return out
        rows = conn.execute(
            """
            SELECT id, status, up_cost_usd, down_cost_usd,
                   COALESCE(up_proceeds_usd,0) AS up_p,
                   COALESCE(down_proceeds_usd,0) AS dn_p,
                   COALESCE(merge_proceeds_usd,0) AS merge_p,
                   COALESCE(redeem_proceeds_usd,0) AS redeem_p,
                   COALESCE(merged_shares,0) AS merged,
                   COALESCE(rebate_est_usd,0) AS rebate,
                   COALESCE(gross_pnl_usd,0) AS gross,
                   COALESCE(net_pnl_usd,0) AS net
            FROM maker_sessions
            WHERE status='closed'
            """
        ).fetchall()
        out["scanned"] = len(rows)
        for row in rows:
            mint = float(row["up_cost_usd"] or 0) + float(row["down_cost_usd"] or 0)
            if mint <= 1e-9:
                continue
            merge_p = float(row["merge_p"] or 0)
            merged = float(row["merged"] or 0)
            sells = float(row["up_p"] or 0) + float(row["dn_p"] or 0)
            redeem = float(row["redeem_p"] or 0)
            rebate = float(row["rebate"] or 0)
            net = float(row["net"] or 0)
            # Case A: merge cash present in columns but net ignored it (≈ −mint)
            cash = sells + merge_p + redeem + rebate
            correct = cash - mint
            looks_dropped = (
                merge_p + 1e-6 >= mint * 0.95
                and sells <= 1e-6
                and abs(net + mint) <= 1e-3
            )
            # Case B: inventory fully cleared via merge (merged≈mint) but merge_p=0
            looks_unbooked_merge = (
                merged + 1e-6 >= mint * 0.95
                and merge_p <= 1e-6
                and sells <= 1e-6
                and abs(net + mint) <= 1e-3
            )
            if not (looks_dropped or looks_unbooked_merge):
                # Also catch: merge_p booked, net wrong by ~mint
                if abs(correct - net) <= 0.01 or abs(net - correct) < 1e-6:
                    continue
                if abs(net - correct) < mint * 0.5:
                    continue
                if not (merge_p > 0 and abs(net + mint) <= 1e-3 and abs(correct) <= 1e-3):
                    continue
            if looks_unbooked_merge:
                merge_p = mint
                cash = sells + merge_p + redeem + rebate
                correct = cash - mint
            out["ids"].append(int(row["id"]))
            out["repaired"] += 1
            if dry_run:
                continue
            conn.execute(
                """
                UPDATE maker_sessions
                SET accounting_original_gross_pnl_usd=?,
                    accounting_original_net_pnl_usd=?,
                    accounting_corrected_ts=?,
                    merge_proceeds_usd=?,
                    merged_shares=?,
                    gross_pnl_usd=?,
                    net_pnl_usd=?
                WHERE id=?
                """,
                (
                    float(row["gross"]),
                    float(row["net"]),
                    _time.time(),
                    merge_p,
                    max(merged, mint if looks_unbooked_merge else merged),
                    correct - rebate,  # gross excludes rebate in settle_split_sell
                    correct,
                    int(row["id"]),
                ),
            )
        if not dry_run and out["repaired"]:
            conn.commit()
    finally:
        conn.close()
    return out




class SplitSellEngine:
    """Paper mint → ask both → residual flatten → merge/redeem loop."""

    def __init__(self, cfg: Config, *, live: bool = False) -> None:
        if live:
            raise RuntimeError(
                "split_sell is paper-only until CTF mint/merge + WS cancel are live-ready"
            )
        validate_split_parameters(cfg)
        self.cfg = cfg
        db_name = getattr(cfg, "split_db_name", None) or "split_sell_paper.db"
        self.store = Store(cfg.data_dir / db_name)
        self.risk = RiskState()
        self._state: Optional[SplitState] = None
        self._last_slug: Optional[str] = None
        self._resolution_retry_at: dict[int, float] = {}
        self._resolution_attempts: dict[int, int] = {}
        self._trade_tape = PublicTradeTape(
            host=getattr(cfg, "maker_trade_api_host", "https://data-api.polymarket.com/v2"),
            poll_sec=float(getattr(cfg, "maker_trade_poll_sec", 1.0)),
            freshness_sec=float(getattr(cfg, "maker_trade_freshness_sec", 10.0)),
        )
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
        self.risk.roll_day()
        self.risk.realized_pnl_usd = self.store.day_realized_pnl(beijing_day_start_ts())
        # Fully merged inventory has no remaining market exposure.  It can
        # await the official winner without occupying every new window's slot.
        # A genuinely unredeemed residual still consumes a risk slot.
        self.risk.open_positions = sum(
            float(row["up_shares"] or 0) > 1e-9
            or float(row["down_shares"] or 0) > 1e-9
            for row in self.store.open_maker_sessions()
        )

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

    def _record_sell_execution(
        self, state: SplitState, *, side: str, token: str, size: float,
        price: float, fee: float, slippage: float, liquidity: str, note: str,
        flatten_pnl_delta: float = 0.0,
    ) -> None:
        """Commit fill + resulting inventory/cash in one SQLite transaction."""
        prefix = "up" if side == "UP" else "down"
        updates = {
            f"{prefix}_inv": getattr(state, f"{prefix}_inv") - size,
            f"{prefix}_sold": getattr(state, f"{prefix}_sold") + size,
            f"{prefix}_proceeds": getattr(state, f"{prefix}_proceeds") + size * price,
            f"{prefix}_fee": getattr(state, f"{prefix}_fee") + fee,
            f"{prefix}_slippage": getattr(state, f"{prefix}_slippage") + slippage,
            "flatten_pnl_usd": state.flatten_pnl_usd + flatten_pnl_delta,
        }
        value = lambda name: updates.get(name, getattr(state, name))
        self.store.record_maker_execution(
            state.session_id,
            fill={
                "market_slug": state.market.market_slug,
                "condition_id": state.market.condition_id,
                "side": side, "token_id": token, "size": size, "price": price,
                "fee_usd": fee, "slippage_usd": slippage,
                "liquidity": liquidity, "strategy": "split_sell", "dry_run": True,
                "execution_side": "SELL",
                "fee_source": "maker_zero_fee" if liquidity == "maker" else "paper_model_v1",
                "slippage_source": (
                    "maker_limit_no_price_slippage" if liquidity == "maker"
                    else "paper_adverse_model"
                ),
                "note": note,
            },
            inventory={
                "up_shares": value("up_inv"), "down_shares": value("down_inv"),
                "up_cost_usd": state.mint_cost / 2,
                "down_cost_usd": state.mint_cost / 2,
                "up_fee_usd": value("up_fee"), "down_fee_usd": value("down_fee"),
                "flatten_pnl_usd": value("flatten_pnl_usd"),
                "slippage_usd": value("up_slippage") + value("down_slippage"),
            },
            accounting={
                "up_proceeds_usd": value("up_proceeds"),
                "down_proceeds_usd": value("down_proceeds"),
            },
        )
        for name, updated in updates.items():
            setattr(state, name, updated)

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
        if residual + 1e-9 < state.market.min_size:
            # This would be a new taker order, so exchange minimum order size
            # applies.  A partial fill of an existing >= minimum maker/FAK
            # order remains valid; its smaller leftover must await redemption.
            self.store.log(
                "split_flatten_unfilled",
                {
                    "session_id": state.session_id,
                    "reason": "dust_below_min_order",
                    "requested_size": residual,
                    "min_order_size": state.market.min_size,
                },
                state.market.market_slug,
            )
            return False
        if state.up_inv > state.down_inv:
            side, book = "UP", up
        else:
            side, book = "DOWN", down
        px = book.best_bid
        if px is None or not math.isfinite(px) or px <= 0:
            log.warning(
                "SPLIT FLATTEN skip %s — no bid for residual %.0f (%s)",
                state.market.market_slug,
                residual,
                reason,
            )
            return False

        # We only have top-of-book depth, so do not simulate the whole
        # residual at a price with insufficient displayed liquidity.  A FAK
        # order meeting the market minimum may receive a smaller partial fill.
        available = float(book.bid_size)
        if (
            not math.isfinite(available)
            or available <= 0
        ):
            self.store.log(
                "split_flatten_unfilled",
                {
                    "session_id": state.session_id,
                    "reason": "insufficient_executable_bid_depth",
                    "requested_size": residual,
                    "bid_size": available,
                },
                state.market.market_slug,
            )
            return False
        size = min(residual, available)

        # Cost basis ≈ $0.50 per minted share; flatten PnL vs that basis.
        # Flattening crosses the book, so model taker fee and adverse Paper
        # slippage.  The effective price is what is booked as proceeds.
        basis = 0.5
        raw_px = float(px)
        effective_px = paper_slipped_sell_price(
            raw_px,
            tick_size=state.market.tick_size,
            ticks=getattr(self.cfg, "paper_slippage_ticks", 1.0),
            pct=getattr(self.cfg, "paper_slippage_pct", 0.0),
        )
        fee = taker_fee_usd(
            effective_px, size, getattr(self.cfg, "taker_fee_rate", 0.07)
        )
        slip = size * max(raw_px - effective_px, 0.0)
        pnl = size * (effective_px - basis)
        token = state.market.up_token if side == "UP" else state.market.down_token
        self._record_sell_execution(
            state, side=side, token=token, size=size, price=effective_px,
            fee=fee, slippage=slip, liquidity="taker", flatten_pnl_delta=pnl,
            note=(
                f"flatten_residual bid={raw_px:.2f} exec={effective_px:.2f} "
                f"slippage={slip:.4f} fee={fee:.4f} basis={basis:.2f} "
                f"pnl={pnl:+.2f} ({reason})"
            ),
        )
        state.residual_since = None if size + 1e-9 >= residual else state.residual_since
        state.quotes.clear()
        self.store.log(
            "split_flatten",
            {
                "session_id": state.session_id,
                "side": side,
                "size": size,
                "requested_size": residual,
                "bid_size": available,
                "price": effective_px,
                "quoted_price": raw_px,
                "slippage_usd": slip,
                "fee_usd": fee,
                "pnl": pnl,
                "reason": reason,
            },
            state.market.market_slug,
        )
        log.info(
            "SPLIT FLATTEN %s %s x%.0f @%.2f pnl=%+.2f | inv %.0f/%.0f | %s",
            state.market.market_slug,
            side,
            size,
            effective_px,
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
        touch_need = (
            self.cfg.split_catchup_touch_fill_sec
            if q.catchup
            else self.cfg.split_touch_fill_sec
        )
        if q.queue is None:
            q.queue = PaperQueue(q.token_id, q.price, "SELL", q.placed_ts)
        q.queue.observe_book(book, now)
        # This remains a minimum quote residence time, not fill evidence.
        # Only fresh public opposing trades can consume the visible queue.
        if now - q.placed_ts < touch_need:
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

        order_size = q.original_size if q.original_size is not None else q.size
        if order_size + 1e-9 < state.market.min_size:
            state.quotes.pop(side, None)
            return False
        inventory = state.up_inv if side == "UP" else state.down_inv
        size, reason = q.queue.consume(
            self._trade_tape.fetch(state.market.condition_id, now),
            now=now,
            freshness_sec=self._trade_tape.freshness_sec,
            max_size=min(q.size, inventory),
            condition_id=state.market.condition_id,
        )
        if size <= 1e-9:
            if reason != q.last_evidence_note:
                self.store.log(
                    "split_fill_wait",
                    {"session_id": state.session_id, "side": side,
                     "reason": reason, "queue_ahead": q.queue.queue_ahead,
                     "fill_model": "public_trade_full_visible_queue_model"},
                    state.market.market_slug,
                )
                q.last_evidence_note = reason
            return False

        # Refuse fills that would push lean beyond clamp on the ahead side
        tentative_lean = self._lean(state) + (
            size if side == "UP" else -size
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

        raw_px = float(q.price)
        # A resting sell limit never executes below its limit.  Adverse
        # selection is represented by waiting for touch and by subsequent
        # inventory risk; applying taker price impact here violates the order.
        px = raw_px
        slip = 0.0
        fee = 0.0
        self._record_sell_execution(
            state, side=side, token=q.token_id, size=size, price=px,
            fee=fee, slippage=slip, liquidity="maker",
            note=f"{reason} quote={raw_px:.2f} exec={px:.2f} slippage={slip:.4f}",
        )
        q.original_size = order_size
        q.size -= size
        if q.size <= 1e-9:
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
                and (old.original_size if old.original_size is not None else old.size) == size
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
                queue=PaperQueue(token, px, "SELL", now),
                original_size=size,
            )
            state.quotes[side].queue.observe_book(book, now)

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
            mint = float(row["up_cost_usd"] or 0) + float(row["down_cost_usd"] or 0)
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
                up_fee=stats.get("up_fee", 0.0),
                down_fee=stats.get("down_fee", 0.0),
                up_slippage=stats.get("up_slippage", 0.0),
                down_slippage=stats.get("down_slippage", 0.0),
                merged=float(row["merged_shares"] or 0.0),
                merge_proceeds=float(row["merge_proceeds_usd"] or 0.0),
                redeem_proceeds=float(row["redeem_proceeds_usd"] or 0.0),
                flatten_pnl_usd=flatten,
            )
            return self._state

        self._hydrate_risk()
        block = allowed_to_trade(
            daily_loss_limit_usd=self.cfg.daily_loss_limit_usd,
            max_open_positions=self.cfg.max_open_positions,
            risk=self.risk,
        )
        if block:
            log.warning("risk block new split session: %s", block)
            # Keep the worker heartbeat fresh while risk controls intentionally
            # block new entries.  Without this, the dashboard reports a
            # running Paper worker as stale even though the loop is healthy.
            write_heartbeat(
                self.cfg.data_dir,
                mode=self._hb_mode(),
                market_slug=market.market_slug,
                detail=f"risk_block={block} open_positions={self.risk.open_positions}",
                pnl_usd=self.risk.realized_pnl_usd,
                open_positions=self.risk.open_positions,
            )
            return None

        mint = float(self.cfg.split_size)
        sid = self.store.open_maker_session(
            market_slug=market.market_slug,
            condition_id=market.condition_id,
            up_token=market.up_token,
            down_token=market.down_token,
            dry_run=True,
            initial_state={
                "up_shares": mint, "down_shares": mint,
                "up_cost_usd": mint / 2.0, "down_cost_usd": mint / 2.0,
            },
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
        self.store.update_maker_state(
            state.session_id,
            up_shares=state.up_inv - paired,
            down_shares=state.down_inv - paired,
            up_cost_usd=state.mint_cost / 2.0,
            down_cost_usd=state.mint_cost / 2.0,
            up_fee_usd=state.up_fee,
            down_fee_usd=state.down_fee,
            flatten_pnl_usd=state.flatten_pnl_usd,
            merged_shares=state.merged + paired,
            merge_proceeds_usd=state.merge_proceeds + paired,
        )
        state.up_inv -= paired
        state.down_inv -= paired
        state.merged += paired
        state.merge_proceeds += paired  # $1 per pair
        self.store.log(
            "split_merge",
            {"session_id": state.session_id, "pairs": paired, "proceeds": paired},
            state.market.market_slug,
        )
        self._hydrate_risk()
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
        proceeds = state.redeem_proceeds
        if winner == "UP" and state.up_inv > 0:
            proceeds += state.up_inv
        elif winner == "DOWN" and state.down_inv > 0:
            proceeds += state.down_inv
        self.store.update_maker_state(
            state.session_id,
            up_shares=0.0,
            down_shares=0.0,
            up_cost_usd=state.mint_cost / 2.0,
            down_cost_usd=state.mint_cost / 2.0,
            up_fee_usd=state.up_fee,
            down_fee_usd=state.down_fee,
            flatten_pnl_usd=state.flatten_pnl_usd,
            redeem_proceeds_usd=proceeds,
        )
        state.redeem_proceeds = proceeds
        state.up_inv = state.down_inv = 0.0

    def _close_session(self, state: SplitState, winner: str) -> None:
        if state.closed:
            return
        if winner not in {"UP", "DOWN"}:
            raise ValueError("split session requires an official UP/DOWN outcome")
        self._merge_pairs(state)
        self._redeem(state, winner)
        sold_notional = state.up_proceeds + state.down_proceeds
        maker_notional = self.store.conn.execute(
            "SELECT COALESCE(SUM(notional_usd),0) FROM fills "
            "WHERE session_id=? AND strategy='split_sell' AND liquidity='maker'",
            (state.session_id,),
        ).fetchone()[0]
        state.rebate_est = float(maker_notional) * (self.cfg.split_rebate_bps / 10_000.0)
        total_fee = state.up_fee + state.down_fee
        total_slippage = state.up_slippage + state.down_slippage
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
            fee_usd=total_fee,
            slippage_usd=total_slippage,
        )
        self.store.close_maker_session(
            state.session_id,
            paired_shares=state.merged,
            pair_cost=None,
            residual_side=None,
            residual_shares=result["residual_shares"],
            winner=winner,
            gross_pnl_usd=result["gross_pnl_usd"],
            fee_usd=total_fee,
            rebate_est_usd=result["rebate_est_usd"],
            net_pnl_usd=result["net_pnl_usd"],
            slippage_usd=total_slippage,
            resolution_source="official_gamma",
        )
        self._hydrate_risk()
        self.store.log(
            "split_resolve",
            {
                "session_id": state.session_id,
                "winner": winner,
                "resolution_source": "official_gamma",
                "rebate_status": "estimate_unpaid",
                **result,
            },
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
        self._resolution_retry_at.pop(state.session_id, None)
        self._resolution_attempts.pop(state.session_id, None)
        if self._state and self._state.session_id == state.session_id:
            self._state = None

    def _pending_resolution(self, row, reason: str, *, error: str = "") -> None:
        sid = int(row["id"])
        self._resolution_attempts[sid] = self._resolution_attempts.get(sid, 0) + 1
        self.store.log(
            "split_unresolved",
            {
                "session_id": sid,
                "reason": reason,
                "resolution_source": "official_gamma",
                "attempt": self._resolution_attempts[sid],
                "retry_after_sec": 15,
                "error": error,
            },
            row["market_slug"],
        )

    def _resolve_open(self) -> None:
        now = time.time()
        rows = sorted(
            self.store.open_maker_sessions(),
            key=lambda row: (self._resolution_retry_at.get(int(row["id"]), 0), int(row["id"])),
        )
        attempted = 0
        for row in rows:
            sid = int(row["id"])
            if now < self._resolution_retry_at.get(sid, 0):
                continue
            if (
                self._state is not None and self._state.session_id == sid
                and self._state.market.t_remaining(now) > 0
            ):
                continue
            # Bound resolver I/O per tick instead of N pending sessions each
            # performing two HTTP calls before the execution loop can run.
            if attempted >= 2:
                break
            attempted += 1
            # Pending official resolutions are retried independently, not
            # replaced by a current spot price after an arbitrary timeout.
            self._resolution_retry_at[sid] = now + 15.0
            slug = row["market_slug"]
            try:
                market = fetch_market_by_slug(self.cfg.gamma_host, slug)
            except Exception as exc:  # noqa: BLE001
                self._pending_resolution(row, "official_market_fetch_error", error=str(exc))
                continue
            if market is None:
                self._pending_resolution(row, "official_market_pending")
                continue
            if market.t_remaining(now) > 0:
                continue
            try:
                winner = gamma_winner_side(self.cfg.gamma_host, market)
            except Exception as exc:  # noqa: BLE001
                self._pending_resolution(row, "official_result_fetch_error", error=str(exc))
                continue
            if winner not in {"UP", "DOWN"}:
                self._pending_resolution(row, "gamma_result_pending")
                continue
            mint = float(row["up_cost_usd"] or 0) + float(row["down_cost_usd"] or 0)
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
                up_fee=stats.get("up_fee", 0.0),
                down_fee=stats.get("down_fee", 0.0),
                up_slippage=stats.get("up_slippage", 0.0),
                down_slippage=stats.get("down_slippage", 0.0),
                merged=float(row["merged_shares"] or 0.0),
                merge_proceeds=float(row["merge_proceeds_usd"] or 0.0),
                redeem_proceeds=float(row["redeem_proceeds_usd"] or 0.0),
                flatten_pnl_usd=flatten,
                quoting=False,
            )
            self._close_session(state, winner)

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
