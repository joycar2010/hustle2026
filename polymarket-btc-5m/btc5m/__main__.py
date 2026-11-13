"""CLI entry: python -m btc5m [--live] [--once] [-v]."""
from __future__ import annotations

import argparse
import logging
import sys

from btc5m.config import load
from btc5m.engine import Engine


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Polymarket BTC 5-minute Up/Down quant bot"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Place real CLOB orders (also requires LIVE_TRADING_ENABLED=true)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single decision tick then exit",
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
    engine = Engine(cfg, live=args.live)
    engine.run(once=args.once)
    return 0


if __name__ == "__main__":
    sys.exit(main())
