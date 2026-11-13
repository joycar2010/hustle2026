"""Main trading loop for Polymarket BTC 5-minute markets."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

from btc5m.book import fetch_book
from btc5m.config import Config
from btc5m.markets import LiveMarket, fetch_live_market, fmt_utc, next_window_eta
from btc5m.resolver import gamma_winner_side, paper_pnl
from btc5m.risk import RiskState, allowed_to_trade, note_fill, note_resolution
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
        self._last_market_slug: Optional[str] = None
        self._hydrate_risk()

        if self.live:
            if not cfg.live_trading_enabled:
                raise RuntimeError(
                    "Refusing live mode: set LIVE_TRADING_ENABLED=true in .env"
                )
            from btc5m.orders import build_client

            self.client = build_client(cfg)
            log.warning("LIVE TRADING ENABLED — real orders will be placed")
        else:
            log.info("Paper mode — decisions logged, no real orders")

    def _hydrate_risk(self) -> None:
        day_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()
        self.risk.roll_day()
        self.risk.realized_pnl_usd = self.store.day_realized_pnl(day_start)
        self.risk.open_positions = len(self.store.open_rows())

    def _resolve_open(self, market: Optional[LiveMarket] = None) -> None:
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
            if winner is None:
                # Soft paper fallback: use BTC delta after close if Gamma lags
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

            pnl = paper_pnl(row["side"], row["size"], row["entry_price"], winner)
            exit_price = 1.0 if row["side"].upper() == winner else 0.0
            self.store.close_position(row["id"], exit_price=exit_price, pnl_usd=pnl)
            note_resolution(self.risk, pnl)
            self.store.log(
                "resolve",
                {
                    "position_id": row["id"],
                    "winner": winner,
                    "pnl_usd": pnl,
                    "side": row["side"],
                    "entry": row["entry_price"],
                },
                market_slug=slug,
            )
            log.info(
                "RESOLVED %s side=%s winner=%s pnl=%+.2f day_pnl=%+.2f",
                slug,
                row["side"],
                winner,
                pnl,
                self.risk.realized_pnl_usd,
            )

    def _execute(self, market: LiveMarket, decision: Decision) -> None:
        assert decision.action == "BUY"
        assert decision.side and decision.token_id and decision.price and decision.size

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

        if self.live:
            from btc5m.orders import place_buy_fok

            assert self.client is not None
            result = place_buy_fok(
                self.client,
                token_id=decision.token_id,
                price=float(decision.price),
                size=float(decision.size),
                tick_size=market.tick_size,
                neg_risk=market.neg_risk,
            )
            self.store.log(
                "live_order",
                {
                    "status": result.status,
                    "order_id": result.order_id,
                    "filled": result.filled_size,
                    "error": result.error,
                    "raw": result.raw,
                },
                market.market_slug,
            )
            if result.error or result.filled_size <= 0:
                log.error(
                    "LIVE ORDER FAILED status=%s err=%s",
                    result.status,
                    result.error,
                )
                return
            order_id = result.order_id
            filled_size = result.filled_size
            avg_price = result.avg_price or decision.price
            status = result.status

        pos_id = self.store.open_position(
            market_slug=market.market_slug,
            condition_id=market.condition_id,
            side=decision.side,
            token_id=decision.token_id,
            size=float(filled_size),
            entry_price=float(avg_price),
            dry_run=not self.live,
            order_id=order_id,
        )
        note_fill(self.risk, float(filled_size) * float(avg_price))
        self.state.entered_markets.add(market.condition_id)
        self.store.log(
            "entry",
            {
                "position_id": pos_id,
                "side": decision.side,
                "price": avg_price,
                "size": filled_size,
                "edge": decision.net_edge,
                "status": status,
                "reason": decision.reason,
            },
            market.market_slug,
        )
        log.info(
            "%s ENTRY #%s %s %s@%.2f x%.0f edge=%.4f",
            "LIVE" if self.live else "PAPER",
            pos_id,
            market.market_slug,
            decision.side,
            avg_price,
            filled_size,
            decision.net_edge or 0.0,
        )

    def tick(self) -> None:
        self._resolve_open()
        market = fetch_live_market(self.cfg.gamma_host, self.cfg.series_slug)
        if market is None:
            eta = next_window_eta()
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
