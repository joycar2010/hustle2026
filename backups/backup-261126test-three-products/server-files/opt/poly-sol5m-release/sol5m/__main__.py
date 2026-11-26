"""CLI for the isolated SOL5M Paper release."""
from __future__ import annotations

import argparse
import json
import logging
import sys

from sol5m.api import app
from sol5m.profile import SOL5M, env_defaults
from sol5m.runner import run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Isolated SOL Up/Down 5m Paper service")
    parser.add_argument("command", nargs="?", choices=("paper", "api", "profile"), default="paper")
    parser.add_argument("--once", action="store_true", help="Run one Paper tick and exit")
    parser.add_argument("--port", type=int, default=8095)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    if args.command == "profile":
        print(json.dumps({**env_defaults(), "description": SOL5M.description}, indent=2))
        return 0
    if args.command == "api":
        import uvicorn

        uvicorn.run(app, host="0.0.0.0", port=args.port, reload=False)
        return 0
    run(once=args.once)
    return 0


if __name__ == "__main__":
    sys.exit(main())

