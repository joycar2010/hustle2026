"""BTC KPI accounting regression tests; only a temporary SQLite DB is used.

Run from the application root with PYTHONPATH=. and optionally set
PNL_DASHBOARD_SOURCE to a staged dashboard.py. Dashboard functions are loaded
through AST, avoiding dashboard startup, network access and service changes.
"""
import ast
from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
from typing import Any
import unittest
from unittest import mock

from bot import store


NOW = datetime(2026, 10, 21, 6, 0, tzinfo=timezone.utc).timestamp()
DAY_START = store.local_day_start_ts(NOW)


def dashboard_source():
    override = os.environ.get("PNL_DASHBOARD_SOURCE")
    if override:
        return Path(override)
    adjacent = Path(__file__).with_name("dashboard.py")
    if adjacent.exists():
        return adjacent
    return Path(store.__file__).resolve().parent.parent / "server" / "dashboard.py"


def load_dashboard_accounting(clock):
    """Compile only the actual production KPI helpers, not their imports."""
    source = dashboard_source()
    parsed = ast.parse(source.read_text(encoding="utf-8-sig"), filename=str(source))
    names = {"_cumulative_lane_pnl", "_mode_split"}
    nodes = [node for node in parsed.body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             and node.name in names]
    found = {node.name for node in nodes}
    if found != names:
        raise AssertionError("Missing staged dashboard helpers: " + ", ".join(sorted(names - found)))
    module = ast.Module(body=nodes, type_ignores=[])
    namespace = {
        "Any": Any,
        "time": clock,
        "threading": threading,
        "store": store,
        "realized_pnl_summary_today": store.realized_pnl_summary_today,
        "_cumulative_pnl_cache": {"ts": 0.0, "value": {}},
        "_cumulative_pnl_lock": threading.Lock(),
        "_paper_open_stats": lambda: (0, 0.0),
        "_filter_active_positions": lambda positions: positions,
        "_state": {"balance_pusd": 50.0, "positions": []},
        "cfg": SimpleNamespace(paper_equity_usd=100.0),
    }
    exec(compile(module, str(source), "exec"), namespace)
    return namespace


class BtcPnlContractTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="btc-kpi-contract-")
        self.addCleanup(self.directory.cleanup)
        self.database_path = Path(self.directory.name) / "test-ledger.sqlite"
        with sqlite3.connect(str(self.database_path)) as connection:
            connection.executescript(store.SCHEMA)
        self.monotonic = 100.0
        self.now = NOW
        self.clock = SimpleNamespace(
            time=lambda: self.now,
            monotonic=lambda: self.monotonic,
        )
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(store, "db", self.temporary_db).start()
        mock.patch.object(store, "local_day_start_ts", return_value=DAY_START).start()
        self.helpers = load_dashboard_accounting(self.clock)

    @contextmanager
    def temporary_db(self):
        connection = sqlite3.connect(str(self.database_path))
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def order(self, condition, size, price, ts, asset="BTC", dry=True,
              side="UP", status=None):
        if status is None:
            status = ("exit_dry_run" if dry else "exit_filled") if side.startswith("SELL_") else ("dry_run" if dry else "filled")
        with self.temporary_db() as connection:
            connection.execute(
                "INSERT INTO orders (ts, asset, market_slug, condition_id, token_id, "
                "side, size, price, status, filled_size, dry_run) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (ts, asset, asset.lower() + "-test", condition, condition + "-up",
                 side, size, price, status, size * price, int(dry)),
            )

    def resolve(self, condition, ts, won=True):
        with self.temporary_db() as connection:
            connection.execute(
                "INSERT INTO resolutions (condition_id, winning_token, resolved_ts) VALUES (?,?,?)",
                (condition, condition + ("-up" if won else "-down"), ts),
            )

    def cumulative(self, lane="paper"):
        return self.helpers["_cumulative_lane_pnl"]()[lane]

    def test_today_and_cumulative_keep_btc_and_sports_separate(self):
        self.order("btc-old", 10, .8, DAY_START - 600)
        self.resolve("btc-old", DAY_START - 300)
        self.order("btc-today", 10, .9, DAY_START + 100)
        self.resolve("btc-today", DAY_START + 200)
        self.order("sports-today", 10, .8, DAY_START + 100, asset="SPORTS")
        self.resolve("sports-today", DAY_START + 200)
        split = self.helpers["_mode_split"]()
        paper = split["paper"]
        self.assertAlmostEqual(paper["realized_usd"], 3.0)
        self.assertAlmostEqual(paper["by_asset"]["BTC"]["realized_usd"], 1.0)
        self.assertAlmostEqual(paper["cumulative_realized_usd"], 5.0)
        self.assertAlmostEqual(paper["cumulative_by_asset"]["BTC"]["realized_usd"], 3.0)
        self.assertAlmostEqual(paper["cumulative_by_asset"]["SPORTS"]["realized_usd"], 2.0)
        self.assertEqual(paper["cumulative_by_asset"]["BTC"]["wins"], 2)
        self.assertEqual(paper["cumulative_wins"], 3)
        self.assertEqual(paper["cumulative_losses"], 0)
        self.assertAlmostEqual(paper["capital_base_usd"], 100.0)
        self.assertAlmostEqual(paper["cumulative_asof_ts"], NOW)

    def test_same_market_paper_and_live_are_isolated(self):
        self.order("same", 10, .8, DAY_START + 100, dry=True)
        self.order("same", 20, .7, DAY_START + 100, dry=False)
        self.order("same", 10, .6, DAY_START + 200, dry=True, side="SELL_UP")
        self.resolve("same", DAY_START + 300)
        split = self.helpers["_mode_split"]()
        self.assertAlmostEqual(split["paper"]["cumulative_by_asset"]["BTC"]["realized_usd"], -2.0)
        self.assertAlmostEqual(split["live"]["cumulative_by_asset"]["BTC"]["realized_usd"], 6.0)
        self.assertEqual(split["paper"]["cumulative_losses"], 1)
        self.assertEqual(split["live"]["cumulative_wins"], 1)

    def test_partial_exit_settles_only_remaining_shares(self):
        self.order("partial", 10, .8, DAY_START + 100)
        self.order("partial", 4, .6, DAY_START + 200, side="SELL_UP")
        self.resolve("partial", DAY_START + 300)
        paper = self.cumulative()
        self.assertAlmostEqual(paper["cumulative_realized_usd"], .4)
        self.assertAlmostEqual(paper["cumulative_by_asset"]["BTC"]["realized_usd"], .4)
        self.assertEqual(paper["cumulative_wins"], 1)
        self.assertEqual(paper["cumulative_losses"], 0)

    def test_fully_exited_position_is_not_settled_again(self):
        self.order("exited", 10, .8, DAY_START + 100)
        self.order("exited", 10, .6, DAY_START + 200, side="SELL_UP")
        self.resolve("exited", DAY_START + 300)
        paper = self.cumulative()
        self.assertAlmostEqual(paper["cumulative_realized_usd"], -2.0)
        self.assertEqual(paper["cumulative_wins"], 0)
        self.assertEqual(paper["cumulative_losses"], 1)

    def test_today_can_be_empty_while_cumulative_remains(self):
        self.order("historical", 10, .8, DAY_START - 600)
        self.resolve("historical", DAY_START - 300)
        paper = self.helpers["_mode_split"]()["paper"]
        self.assertEqual(paper["realized_usd"], 0)
        self.assertNotIn("BTC", paper["by_asset"])
        self.assertAlmostEqual(paper["cumulative_by_asset"]["BTC"]["realized_usd"], 2.0)
        self.assertEqual(paper["cumulative_wins"], 1)

    def test_failed_entries_and_failed_exits_do_not_change_pnl(self):
        self.order("failed-entry", 100, .8, DAY_START + 100, status="error")
        self.resolve("failed-entry", DAY_START + 300)
        self.order("failed-exit", 10, .8, DAY_START + 100)
        self.order("failed-exit", 10, .1, DAY_START + 200,
                   side="SELL_UP", status="exit_error")
        self.resolve("failed-exit", DAY_START + 300)
        paper = self.cumulative()
        self.assertAlmostEqual(paper["cumulative_realized_usd"], 2.0)
        self.assertEqual(paper["cumulative_wins"], 1)

    def test_cumulative_snapshot_is_bounded_by_current_time(self):
        self.order("future-resolution", 10, .8, DAY_START + 100)
        self.resolve("future-resolution", NOW + 600)
        paper = self.cumulative()
        self.assertEqual(paper["cumulative_realized_usd"], 0)
        self.assertEqual(paper["cumulative_wins"], 0)

    def test_cache_refreshes_after_five_seconds(self):
        self.order("first", 10, .8, DAY_START + 100)
        self.resolve("first", DAY_START + 200)
        self.assertAlmostEqual(self.cumulative()["cumulative_realized_usd"], 2.0)
        self.order("second", 10, .9, DAY_START + 300)
        self.resolve("second", DAY_START + 400)
        self.monotonic += 1.0
        self.assertAlmostEqual(self.cumulative()["cumulative_realized_usd"], 2.0)
        self.monotonic += 5.0
        self.now += 6.0
        self.assertAlmostEqual(self.cumulative()["cumulative_realized_usd"], 3.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
