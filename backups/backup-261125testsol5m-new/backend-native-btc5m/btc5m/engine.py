"""Main trading loop for Polymarket BTC 5-minute markets."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

from btc5m.book import fetch_book
from btc5m.config import Config
from btc5m.fees import paper_slipped_price, taker_fee_usd
from btc5m.heartbeat import write_heartbeat
from btc5m.markets import LiveMarket, fetch_live_market, fmt_utc, next_window_eta
from btc5m.resolver import gamma_winner_side, paper_pnl
from btc5m.risk import (
    RiskState,
    allowed_to_trade,
    beijing_day_start_ts,
    note_fill,
    note_resolution,
)
from btc5m.signal import fetch_btc_signal
from btc5m.store import Store
from btc5m.strategy import Decision, StrategyState, decide

log = logging.getLogger("btc5m")


class Engine:
    def __init__(self, cfg: Config, *, live: bool = False) -> None:
        self.cfg = cfg
        self.live = bool(live)
        self.state = StrategyState()
        self.risk = RiskState()
        self.store = Store(cfg.data_dir / ("live.db" if live else "paper.db"))
        self.client = None
        self.execution = None
        # A live order with unknown/partial/unverified accounting evidence is
        # quarantined for this market.  Never retry it on the next tick and
        # risk duplicating a wallet fill.
        self._live_blocked_markets: set[str] = set()
        self._last_market_slug: Optional[str] = None
        self._hydrate_risk()

        if self.live:
            if not cfg.live_trading_enabled:
                raise RuntimeError(
                    "Refusing live mode: set LIVE_TRADING_ENABLED=true in .env"
                )
            if not getattr(cfg, "live_execution_ready", False):
                raise RuntimeError(
                    "Refusing live mode: LIVE_EXECUTION_READY is false; "
                    "Paper remains the only enabled execution path"
                )
            from btc5m.orders import build_client
            from btc5m.live_execution import CapabilityManifest, LiveExecutionAdapter

            self.client = build_client(cfg)
            manifest = CapabilityManifest.from_path(cfg.live_capabilities_manifest) if cfg.live_capabilities_manifest else CapabilityManifest()
            self.execution = LiveExecutionAdapter(self.client, cfg, manifest=manifest, event_sink=self.store.log)
            # LIVE_TRADING_ENABLED alone must never enable an incomplete
            # buy-only executor.
            self.execution.preflight()
            log.warning("LIVE TRADING ENABLED — real orders will be placed")
        else:
            log.info("Paper mode — decisions logged, no real orders")

    def _hydrate_risk(self) -> None:
        day_start = beijing_day_start_ts()
        self.risk.roll_day()
        self.risk.realized_pnl_usd = self.store.day_realized_pnl(day_start)
        self.risk.open_positions = len(self.store.open_rows())

    def _resolve_open(self, market: Optional[LiveMarket] = None) -> None:
        if self.live:
            # Gamma's closed/outcomePrices response is not proof of a CTF
            # payout or redemption. Keep the real position open until the
            # chain settlement/redeem adapter is wired and reconciled.
            self.store.log(
                "live_resolution_blocked",
                {"reason": "chain payout/redeem adapter not wired; local close forbidden"},
            )
            return
        for row in self.store.open_rows():
            # Build a minimal market handle from stored fields when needed
            slug = row["market_slug"]
            if market and market.market_slug == slug and market.t_remaining() > 0:
                continue
            # Only resolve after window end
            try:
                from btc5m.markets import fetch_market_by_slug

                closed = fetch_market_by_slug(self.cfg.gamma_host, slug)
            except Exception as exc:  # noqa: BLE001
                log.debug("resolve fetch failed %s: %s", slug, exc)
                continue
            if closed is None:
                continue
            if closed.t_remaining() > 0:
                continue
            winner = gamma_winner_side(self.cfg.gamma_host, closed)
            if winner is None and self.cfg.allow_spot_resolution_fallback:
                # Explicit opt-in only: spot is never the settlement oracle.: use BTC delta after close if Gamma lags
                if not self.live and closed.t_remaining() < -30:
                    try:
                        from btc5m.signal import fetch_btc_signal as _sig

                        sig = _sig(self.cfg, closed)
                        winner = "UP" if sig.delta_usd >= 0 else "DOWN"
                        log.info(
                            "paper resolve fallback %s winner=%s via spot Δ=%+.2f",
                            slug,
                            winner,
                            sig.delta_usd,
                        )
                    except Exception as exc:  # noqa: BLE001
                        log.debug("fallback resolve failed: %s", exc)
                        continue
                else:
                    continue

            fee = float(row["fee_usd"] or 0.0)
            pnl = paper_pnl(row["side"], row["size"], row["entry_price"], winner)
            net = pnl - fee
            exit_price = 1.0 if row["side"].upper() == winner else 0.0
            self.store.close_position(
                row["id"],
                exit_price=exit_price,
                pnl_usd=pnl,
                fee_usd=fee,
                pnl_net_usd=net,
            )
            note_resolution(self.risk, net)
            self.store.log(
                "resolve",
                {
                    "position_id": row["id"],
                    "winner": winner,
                    "pnl_usd": pnl,
                    "fee_usd": fee,
                    "pnl_net_usd": net,
                    "side": row["side"],
                    "entry": row["entry_price"],
                    "liquidity": row["liquidity"] if "liquidity" in row.keys() else "taker",
                    "strategy": row["strategy"] if "strategy" in row.keys() else "late_edge",
                },
                market_slug=slug,
            )
            log.info(
                "RESOLVED %s side=%s winner=%s gross=%+.2f fee=%.2f net=%+.2f day=%+.2f",
                slug,
                row["side"],
                winner,
                pnl,
                fee,
                net,
                self.risk.realized_pnl_usd,
            )

    def _execute(self, market: LiveMarket, decision: Decision) -> None:
        assert decision.action == "BUY"
        assert decision.side and decision.token_id and decision.price and decision.size

        if self.live and market.market_slug in self._live_blocked_markets:
            self.store.log(
                "live_order_blocked",
                {"reason": "market quarantined pending fill reconciliation"},
                market.market_slug,
            )
            return

        block = allowed_to_trade(
            daily_loss_limit_usd=self.cfg.daily_loss_limit_usd,
            max_open_positions=self.cfg.max_open_positions,
            risk=self.risk,
        )
        if block:
            log.warning("risk block: %s", block)
            self.store.log("risk_block", {"reason": block}, market.market_slug)
            return

        order_id = None
        filled_size = decision.size
        avg_price = decision.price
        status = "paper_fill"
        liquidity = "taker"
        actual_fee = None

        if self.live:
            if self.execution is None:
                raise RuntimeError("live execution adapter is not initialized")
            receipt = self.execution.buy(
                token_id=decision.token_id,
                price=float(decision.price),
                size=float(decision.size),
                tick_size=market.tick_size,
                neg_risk=market.neg_risk,
            )
            result = receipt.order
            self.store.log(
                "live_order",
                {
                    "status": result.status,
                    "order_id": result.order_id,
                    "filled": result.filled_size,
                    "fill_source": result.fill_source,
                    "notional_usd": result.notional_usd,
                    "fee_usd": result.fee_usd,
                    "error": result.error,
                    "raw": result.raw,
                },
                market.market_slug,
            )
            if result.error or result.status != "filled" or result.filled_size <= 0:
                log.error(
                    "LIVE ORDER FAILED status=%s err=%s",
                    result.status,
                    result.error,
                )
                if result.status in {"unknown", "partial"} or result.order_id:
                    self._live_blocked_markets.add(market.market_slug)
                return
            if result.fill_source != "authenticated_fills":
                self._live_blocked_markets.add(market.market_slug)
                self.store.log(
                    "live_order_blocked",
                    {"order_id": result.order_id, "reason": "authenticated fill evidence unavailable", "fill_source": result.fill_source},
                    market.market_slug,
                )
                return
            if result.fee_usd is None:
                self._live_blocked_markets.add(market.market_slug)
                log.error("LIVE ORDER BLOCKED: authenticated fee unavailable; refusing local ledger fill")
                self.store.log(
                    "live_order_blocked",
                    {"order_id": result.order_id, "reason": "actual fee unavailable"},
                    market.market_slug,
                )
                return
            order_id = result.order_id
            filled_size = result.filled_size
            avg_price = result.avg_price or decision.price
            status = result.status
            actual_fee = result.fee_usd

        if not self.live:
            raw_price = float(avg_price)
            avg_price = paper_slipped_price(
                raw_price,
                tick_size=market.tick_size,
                ticks=self.cfg.paper_slippage_ticks,
                pct=self.cfg.paper_slippage_pct,
            )
            if avg_price > raw_price + 1e-12:
                log.info(
                    "PAPER slippage %.4f -> %.4f (ticks=%.2f pct=%.3f%%)",
                    raw_price,
                    avg_price,
                    self.cfg.paper_slippage_ticks,
                    self.cfg.paper_slippage_pct * 100.0,
                )

        fee = float(actual_fee) if self.live and actual_fee is not None else taker_fee_usd(
            float(avg_price), float(filled_size), self.cfg.taker_fee_rate
        )
        pos_id = self.store.open_position(
            market_slug=market.market_slug,
            condition_id=market.condition_id,
            side=decision.side,
            token_id=decision.token_id,
            size=float(filled_size),
            entry_price=float(avg_price),
            dry_run=not self.live,
            order_id=order_id,
            fee_usd=fee,
            liquidity=liquidity,
            strategy="late_edge",
        )
        self.store.record_fill(
            market_slug=market.market_slug,
            condition_id=market.condition_id,
            side=decision.side,
            token_id=decision.token_id,
            size=float(filled_size),
            price=float(avg_price),
            fee_usd=fee,
            liquidity=liquidity,
            strategy="late_edge",
            dry_run=not self.live,
            order_id=order_id,
            note=decision.reason,
        )
        note_fill(self.risk, float(filled_size) * float(avg_price))
        self.state.entered_markets.add(market.condition_id)
        self.store.log(
            "entry",
            {
                "position_id": pos_id,
                "side": decision.side,
                "price": avg_price,
                "quoted_price": decision.price,
                "paper_slippage": max(float(avg_price) - float(decision.price), 0.0),
                "size": filled_size,
                "fee_usd": fee,
                "edge": decision.net_edge,
                "status": status,
                "reason": decision.reason,
            },
            market.market_slug,
        )
        log.info(
            "%s ENTRY #%s %s %s@%.2f x%.0f fee=%.4f edge=%.4f",
            "LIVE" if self.live else "PAPER",
            pos_id,
            market.market_slug,
            decision.side,
            avg_price,
            filled_size,
            fee,
            decision.net_edge or 0.0,
        )

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
            eta = next_window_eta(
                window_sec=int(getattr(self.cfg, "window_sec", 300) or 300)
            )
            log.info("no live market; next window in %.0fs", eta)
            return

        if market.market_slug != self._last_market_slug:
            self._last_market_slug = market.market_slug
            log.info(
                "market %s | %s → %s | t_left=%.1fs",
                market.market_slug,
                fmt_utc(market.start_ts),
                fmt_utc(market.end_ts),
                market.t_remaining(),
            )

        up = fetch_book(self.cfg.clob_host, market.up_token)
        down = fetch_book(self.cfg.clob_host, market.down_token)

        signal = None
        try:
            signal = fetch_btc_signal(self.cfg, market)
        except Exception as exc:  # noqa: BLE001
            log.warning("btc signal error: %s", exc)

        already = any(
            r["condition_id"] == market.condition_id for r in self.store.open_rows()
        )
        decision = decide(
            self.cfg,
            market,
            up,
            down,
            signal,
            self.state,
            already_in_market=already,
            db_path=self.store.path,
        )
        self.store.log(
            "decision",
            {
                "action": decision.action,
                "side": decision.side,
                "price": decision.price,
                "size": decision.size,
                "edge": decision.net_edge,
                "reason": decision.reason,
                "up_ask": up.best_ask,
                "down_ask": down.best_ask,
                "signal": signal.describe() if signal else None,
                "t_left": market.t_remaining(),
            },
            market.market_slug,
        )

        write_heartbeat(
            self.cfg.data_dir,
            mode="late_edge",
            market_slug=market.market_slug,
            detail=decision.reason[:200],
            pnl_usd=self.risk.realized_pnl_usd,
            open_positions=self.risk.open_positions,
        )

        if decision.action == "BUY":
            self._execute(market, decision)
        elif decision.action == "HOLD":
            log.debug("%s", decision.reason)
        else:
            log.info(
                "SKIP %s | up=%s dn=%s | %s",
                market.market_slug,
                up.best_ask,
                down.best_ask,
                decision.reason,
            )

    def run(self, *, once: bool = False) -> None:
        log.info(
            "starting btc5m v%s mode=%s entry_window=%.0f-%.0fs edge>=%.3f",
            __import__("btc5m").__version__,
            "LIVE" if self.live else "PAPER",
            self.cfg.min_t_remaining_sec,
            self.cfg.entry_window_sec,
            self.cfg.min_net_edge,
        )
        while True:
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                log.exception("tick failed")
            if once:
                return
            time.sleep(self.cfg.poll_interval_sec)
