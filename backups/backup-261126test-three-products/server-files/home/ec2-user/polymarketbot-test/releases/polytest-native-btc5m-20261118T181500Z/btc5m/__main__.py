"""CLI entry: python -m btc5m [--series ...] [--mode ...] ..."""
from __future__ import annotations

import argparse
import json
import logging
import sys

from btc5m.config import load
from btc5m.products import list_products


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Polymarket multi-series paper quant bot (BTC 5m baseline preserved)"
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=["run", "report", "dashboard", "heartbeat", "stress", "products", "preflight"],
        help="run trading loop (default), report, dashboard, heartbeat, stress, or list products",
    )
    parser.add_argument(
        "--series",
        default=None,
        help="Product / series slug or key (btc5m, btc-up-or-down-15m, atp, cs, ...). "
        "Default SERIES_SLUG / btc-up-or-down-5m.",
    )
    parser.add_argument(
        "--mode",
        choices=["late_edge", "maker", "split_sell", "sports_mm"],
        default=None,
        help="Strategy mode (overrides MODE env / product preferred mode).",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Place real CLOB orders (late_edge only; requires LIVE_TRADING_ENABLED=true)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single decision tick then exit",
    )
    parser.add_argument(
        "--day",
        default=None,
        help="For report: UTC day YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--slip-ticks",
        type=float,
        default=1.0,
        help="For stress: adverse entry slip in ticks (default 1)",
    )
    parser.add_argument(
        "--fee-mult",
        type=float,
        default=1.0,
        help="For stress: fee multiplier (default 1.0)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Debug logging",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.command == "products":
        rows = []
        for p in list_products():
            rows.append(
                {
                    "key": p.key,
                    "series_slug": p.series_slug,
                    "phase": p.phase,
                    "enabled": p.enabled,
                    "family": p.family,
                    "preferred_mode": p.preferred_mode,
                    "description": p.description,
                }
            )
        print(json.dumps(rows, indent=2))
        return 0

    try:
        cfg = load(series=args.series)
    except Exception as exc:  # noqa: BLE001
        logging.error("%s", exc)
        return 2

    if args.command == "preflight":
        if cfg.mode != "late_edge":
            logging.error("live preflight only supports late_edge")
            return 2
        try:
            from btc5m.live_execution import CapabilityManifest, LiveExecutionAdapter
            from btc5m.orders import build_client

            client = build_client(cfg)
            manifest = CapabilityManifest.from_path(cfg.live_capabilities_manifest) if cfg.live_capabilities_manifest else CapabilityManifest()
            LiveExecutionAdapter(client, cfg, manifest=manifest).preflight()
        except Exception as exc:  # noqa: BLE001
            logging.error("live preflight failed: %s", exc)
            return 2
        print(json.dumps({"ready": True, "mode": "late_edge"}))
        return 0

    mode = args.mode or cfg.mode

    # Sports profiles are paper-only and must never fall through to the BTC
    # directional engine, even if a caller supplies an overriding mode/live flag.
    if cfg.product_key in {"atp", "cs"}:
        if args.live or mode != "sports_mm":
            logging.error("%s is Paper-only and requires --mode sports_mm", cfg.product_key)
            return 2

    if args.command == "report":
        from btc5m.audit import print_report

        if mode == "maker":
            db = cfg.data_dir / cfg.maker_db_name
        elif mode == "split_sell":
            db = cfg.data_dir / cfg.split_db_name
        elif mode == "sports_mm":
            db = cfg.data_dir / f"sports_mm_{cfg.product_key}_paper.db"
        else:
            db = cfg.data_dir / ("live.db" if args.live else "paper.db")
        print_report(db, day=args.day, fee_rate=cfg.taker_fee_rate)
        for other_name in (
            "paper.db",
            "maker_paper.db",
            "split_sell_paper.db",
            "split_sell_15m_paper.db",
            "maker_15m_paper.db",
            f"sports_mm_{cfg.product_key}_paper.db",
        ):
            other = cfg.data_dir / other_name
            if other.exists() and other != db:
                print()
                print_report(other, day=args.day, fee_rate=cfg.taker_fee_rate)
        return 0

    if args.command == "heartbeat":
        from btc5m.heartbeat import status_report

        report = status_report(
            cfg.data_dir,
            stale_sec=cfg.heartbeat_stale_sec,
        )
        print(json.dumps(report, indent=2))
        return 0 if report.get("ok") else 2

    if args.command == "stress":
        from btc5m.stress import format_stress, stress_late_edge_db

        db = cfg.data_dir / ("live.db" if args.live else "paper.db")
        result = stress_late_edge_db(
            db,
            slip_ticks=args.slip_ticks,
            fee_rate=cfg.taker_fee_rate,
            fee_mult=args.fee_mult,
        )
        print(format_stress(result))
        return 0

    if args.command == "dashboard":
        import uvicorn

        uvicorn.run(
            "btc5m.dashboard_api:app",
            host="0.0.0.0",
            port=int(__import__("os").getenv("DASHBOARD_PORT", "8088")),
            reload=False,
        )
        return 0

    # Guard: phase-3/4 products
    if cfg.product_key in {"nba", "nfl"}:
        from btc5m.phase_stubs import assert_nba_nfl_ready

        assert_nba_nfl_ready()
    if cfg.product_key in {"dota", "soccer_unl"}:
        from btc5m.phase_stubs import assert_dota_soccer_live_ready

        assert_dota_soccer_live_ready()

    if mode == "maker":
        from btc5m.maker import MakerEngine

        MakerEngine(cfg, live=args.live).run(once=args.once)
        return 0

    if mode == "split_sell":
        from btc5m.split_sell import SplitSellEngine

        SplitSellEngine(cfg, live=args.live).run(once=args.once)
        return 0

    if mode == "sports_mm":
        from btc5m.sports_mm import SportsMmEngine

        SportsMmEngine(cfg, live=args.live).run(once=args.once)
        return 0

    from btc5m.engine import Engine

    Engine(cfg, live=args.live).run(once=args.once)
    return 0


if __name__ == "__main__":
    sys.exit(main())
