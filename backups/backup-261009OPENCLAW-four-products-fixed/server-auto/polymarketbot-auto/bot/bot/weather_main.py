"""Weather probability scanner and optional Polymarket CLOB executor."""
from __future__ import annotations

import argparse
import logging
import time

from bot import config, store
from bot.book import fetch_book
from bot.resolver import resolve_pending
from bot.risk import (
    allowed_to_trade,
    account_equity_usd,
    market_buy_amount_and_shares,
    target_order_size,
)
from bot.weather_data import configured_city_keys, fetch_ensemble_forecast
from bot.weather_markets import fetch_weather_markets
from bot.weather_strategy import build_signal, signal_is_allowed

log = logging.getLogger("bot.weather")


def _weather_risk_config(cfg: config.Config) -> config.Config:
    """Use the shared sizing engine with the weather-specific risk fraction."""
    from dataclasses import replace

    return replace(cfg, order_risk_fraction=cfg.weather_order_risk_fraction)


def run_cycle(cfg: config.Config, *, live: bool, client=None) -> int:
    dry_run = not live
    resolved = resolve_pending(cfg, dry_run)
    if resolved:
        log.info(
            "weather settlement sync resolved=%d mode=%s",
            resolved,
            "live" if live else "paper",
        )
    markets = fetch_weather_markets(cfg)
    forecasts = {}
    signals = []
    for market in markets:
        key = (market.city_key, market.target_date)
        try:
            if key not in forecasts:
                forecasts[key] = fetch_ensemble_forecast(
                    cfg,
                    market.city_key,
                    market.target_date,
                )
            signal = build_signal(cfg, market, forecasts[key])
        except Exception as exc:
            log.warning(
                "weather signal failed market=%s error=%s",
                market.slug or market.market_id,
                exc,
            )
            continue
        signals.append(signal)

    signals.sort(key=lambda item: item.edge, reverse=True)
    weather_cfg = _weather_risk_config(cfg)
    traded = 0

    for signal in signals:
        market = signal.market
        if store.has_order_attempt(market.condition_id, dry_run):
            continue

        try:
            book = fetch_book(cfg.clob_host, signal.token_id)
        except Exception as exc:
            log.warning("weather book failed %s: %s", market.slug, exc)
            continue
        ask = book.best_ask
        if ask is None or book.ask_size <= 0:
            continue

        model_probability = (
            signal.model_yes_probability
            if signal.side == "UP"
            else signal.model_no_probability
        )
        live_edge = model_probability - ask
        ok, why = signal_is_allowed(
            cfg,
            signal,
            entry_price=ask,
            edge=live_edge,
        )
        if not ok:
            store.log_decision(
                asset="WEATHER",
                market_slug=market.slug,
                condition_id=market.condition_id,
                token_id=signal.token_id,
                side=signal.side,
                t_remaining=max(market.end_ts - time.time(), 0.0),
                ask_price=ask,
                ask_size=book.ask_size,
                action="SKIP_WEATHER",
                reason=f"{signal.reason}; {why}",
                dry_run=dry_run,
            )
            continue

        equity = account_equity_usd(weather_cfg, dry_run)
        order_size = target_order_size(
            weather_cfg,
            ask_price=ask,
            ask_size=book.ask_size,
            equity_usd=equity,
            risk_fraction=cfg.weather_order_risk_fraction,
        )
        amount_usd, order_size = market_buy_amount_and_shares(
            ask,
            order_size,
            tick_size=market.tick_size,
            min_notional_usd=cfg.effective_min_order_notional_usd,
        )
        if amount_usd <= 0 or order_size <= 0:
            continue

        allowed, risk_reason = allowed_to_trade(
            weather_cfg,
            dry_run,
            equity_usd=equity,
            order_cost_usd=amount_usd,
            risk_fraction=cfg.weather_order_risk_fraction,
        )
        if not allowed:
            store.log_decision(
                asset="WEATHER",
                market_slug=market.slug,
                condition_id=market.condition_id,
                token_id=signal.token_id,
                side=signal.side,
                t_remaining=max(market.end_ts - time.time(), 0.0),
                ask_price=ask,
                ask_size=book.ask_size,
                action="SKIP_RISK",
                reason=f"{signal.reason}; {risk_reason}",
                dry_run=dry_run,
            )
            continue

        reason = f"{signal.reason}; live_ask={ask:.3f}; amount=${amount_usd:.2f}"
        store.log_decision(
            asset="WEATHER",
            market_slug=market.slug,
            condition_id=market.condition_id,
            token_id=signal.token_id,
            side=signal.side,
            t_remaining=max(market.end_ts - time.time(), 0.0),
            ask_price=ask,
            ask_size=book.ask_size,
            action="BUY",
            reason=reason,
            dry_run=dry_run,
        )

        if dry_run:
            store.log_order(
                asset="WEATHER",
                market_slug=market.slug,
                condition_id=market.condition_id,
                token_id=signal.token_id,
                side=signal.side,
                size=order_size,
                price=ask,
                order_id=None,
                status="dry_run",
                filled_size=0.0,
                entry_rule="weather_ensemble",
                dry_run=True,
            )
            traded += 1
        else:
            from bot.orders import place_buy_market_fok

            result = place_buy_market_fok(
                client,
                token_id=signal.token_id,
                price=ask,
                amount_usd=amount_usd,
                tick_size=market.tick_size,
                neg_risk=market.neg_risk,
            )
            store.log_order(
                asset="WEATHER",
                market_slug=market.slug,
                condition_id=market.condition_id,
                token_id=signal.token_id,
                side=signal.side,
                size=order_size,
                price=ask,
                order_id=result.order_id,
                status=(
                    "filled"
                    if result.filled_size and result.filled_size > 0
                    else result.status
                ),
                filled_size=result.filled_size,
                error=result.error,
                entry_rule="weather_ensemble",
                dry_run=False,
            )
            if result.filled_size and result.filled_size > 0:
                traded += 1
            log.info(
                "weather order result market=%s side=%s status=%s filled=%s error=%s",
                market.slug,
                signal.side,
                result.status,
                result.filled_size,
                result.error,
            )

        if (
            cfg.weather_max_markets_per_cycle > 0
            and traded >= cfg.weather_max_markets_per_cycle
        ):
            break
    return traded


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    cfg = config.load()
    if not cfg.weather_enabled:
        raise SystemExit("WEATHER_ENABLED=false; weather bot is disabled")
    if args.live and not cfg.weather_live_trading_enabled:
        raise SystemExit(
            "WEATHER_LIVE_TRADING_ENABLED=false; refusing weather live orders"
        )
    configured_city_keys(cfg)
    if args.live:
        from bot.orders import build_client

        client = build_client(cfg)
    else:
        client = None

    while True:
        try:
            traded = run_cycle(cfg, live=args.live, client=client)
            log.info(
                "weather cycle complete mode=%s trades=%d next_scan=%.0fs",
                "live" if args.live else "paper",
                traded,
                cfg.weather_scan_interval_sec,
            )
        except KeyboardInterrupt:
            raise
        except Exception:
            log.exception("weather cycle failed")
        if args.once:
            return
        time.sleep(max(cfg.weather_scan_interval_sec, 5.0))


if __name__ == "__main__":
    main()
