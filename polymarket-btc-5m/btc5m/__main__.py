"""CLI entry: python -m btc5m [--mode late_edge|maker|split_sell] ..."""
from __future__ import annotations

import argparse
import json
import logging
import sys

from btc5m.config import load


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Polymarket BTC 5-minute Up/Down quant bot"
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=["run", "report", "dashboard", "heartbeat", "stress"],
        help="run trading loop (default), fee-aware report, dashboard, heartbeat, or stress",
    )
    parser.add_argument(
        "--mode",
        choices=["late_edge", "maker", "split_sell"],
        default=None,
        help="Strategy mode (overrides MODE env). maker/split_sell are paper-only.",
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

    cfg = load()
    mode = args.mode or cfg.mode

    if args.command == "report":
        from btc5m.audit import print_report

        if mode == "maker":
            db = cfg.data_dir / "maker_paper.db"
        elif mode == "split_sell":
            db = cfg.data_dir / "split_sell_paper.db"
        else:
            db = cfg.data_dir / ("live.db" if args.live else "paper.db")
        print_report(db, day=args.day, fee_rate=cfg.taker_fee_rate)
        for other_name in ("paper.db", "maker_paper.db", "split_sell_paper.db"):
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

    if mode == "maker":
        from btc5m.maker import MakerEngine

        MakerEngine(cfg, live=args.live).run(once=args.once)
        return 0

    if mode == "split_sell":
        from btc5m.split_sell import SplitSellEngine

        SplitSellEngine(cfg, live=args.live).run(once=args.once)
        return 0

    from btc5m.engine import Engine

    Engine(cfg, live=args.live).run(once=args.once)
    return 0


if __name__ == "__main__":
    sys.exit(main())
