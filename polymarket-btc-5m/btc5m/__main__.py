"""CLI entry: python -m btc5m [--mode late_edge|maker] [--live] [--once] [report] [-v]."""
from __future__ import annotations

import argparse
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
        choices=["run", "report"],
        help="run trading loop (default) or print fee-aware audit report",
    )
    parser.add_argument(
        "--mode",
        choices=["late_edge", "maker"],
        default=None,
        help="Strategy mode (overrides MODE env). maker is paper-only.",
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

        db = cfg.data_dir / (
            "maker_paper.db" if mode == "maker" else ("live.db" if args.live else "paper.db")
        )
        # Also show both DBs if present
        print_report(db, day=args.day)
        other = cfg.data_dir / ("paper.db" if mode == "maker" else "maker_paper.db")
        if other.exists() and other != db:
            print()
            print_report(other, day=args.day)
        return 0

    if mode == "maker":
        from btc5m.maker import MakerEngine

        engine = MakerEngine(cfg, live=args.live)
        engine.run(once=args.once)
        return 0

    from btc5m.engine import Engine

    engine = Engine(cfg, live=args.live)
    engine.run(once=args.once)
    return 0


if __name__ == "__main__":
    sys.exit(main())
