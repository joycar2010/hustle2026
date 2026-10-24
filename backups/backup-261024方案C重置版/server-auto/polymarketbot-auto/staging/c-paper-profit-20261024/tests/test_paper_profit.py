"""Paper daily profit guard integration tests using isolated SQLite ledgers.

Run with the candidate code on PYTHONPATH:
    python -m unittest discover -s tests -p test_paper_profit.py -v
No production environment, network, wallet or database is used.
"""
from __future__ import annotations

import importlib
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from bot import paper_profit, risk, store
from bot.config import Config


BEIJING = timezone(timedelta(hours=8))


class PaperProfitGuardTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="paper-profit-tests-")
        self.addCleanup(self.tempdir.cleanup)
        self.db_path = Path(self.tempdir.name) / "isolated.db"
        self.db_patch = patch.object(store, "DB_PATH", self.db_path)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.zone_patch = patch.object(store, "TRADING_DAY_UTC_OFFSET_HOURS", 8.0)
        self.zone_patch.start()
        self.addCleanup(self.zone_patch.stop)
        self.now = datetime(2026, 10, 24, 12, 0, tzinfo=BEIJING).timestamp()
        self.clock = patch("bot.paper_profit.time.time", side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.midnight = store.local_day_start_ts(self.now)
        self.sequence = 0
        self.cfg = Config(
            private_key="", wallet_address="", funder_address="",
            signature_type=0, chain_id=137, clob_host="", gamma_host="",
            polygon_rpc="", api_key="", api_secret="", api_passphrase="",
            paper_equity_usd=100.0, max_daily_realized_profit_fraction=0.12,
            max_daily_realized_profit_usd=0.0, max_orders_per_hour=0,
            max_open_positions=0, max_daily_loss_fraction=0.0,
            consecutive_loss_kill=0,
        )
        with store.db():
            pass

    def add_resolution(self, pnl, *, asset="BTC", paper=True, buy_ts=None,
                       settle_ts=None):
        """At price 0.5 a 2*abs(pnl) share lot yields exactly +/- pnl."""
        self.sequence += 1
        condition = f"{asset}-{self.sequence}"
        token = f"token-{self.sequence}"
        buy_ts = self.now - 120 if buy_ts is None else buy_ts
        settle_ts = self.now - 60 if settle_ts is None else settle_ts
        with store.db() as db:
            db.execute(
                "INSERT INTO orders (ts,asset,market_slug,condition_id,token_id,"
                "side,size,price,status,dry_run) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (buy_ts, asset, f"{asset.lower()}-test-{self.sequence}",
                 condition, token, "UP", abs(pnl) * 2, 0.5,
                 "dry_run" if paper else "filled", int(paper)),
            )
            db.execute(
                "INSERT INTO resolutions (condition_id,winning_token,resolved_ts) "
                "VALUES (?,?,?)",
                (condition, token if pnl >= 0 else "other-token", settle_ts),
            )

    def stop_reason(self, cfg=None, asset="BTC"):
        return risk.daily_realized_profit_stop_reason(
            cfg or self.cfg, True, asset=asset,
        )

    def state_path(self, asset="BTC"):
        return paper_profit._state_path(asset)

    def test_below_twelve_percent_remains_allowed(self):
        self.add_resolution(11.999)
        self.assertIsNone(self.stop_reason())
        self.assertFalse(self.state_path().exists())
        allowed, reason = risk.allowed_to_trade(
            self.cfg, True, equity_usd=100.0, asset="BTC",
        )
        self.assertTrue(allowed, reason)

    def test_exact_twelve_percent_triggers_and_persists_metadata(self):
        self.add_resolution(12.0)
        reason = self.stop_reason()
        self.assertIn("12.0%", reason)
        self.assertIn("BTC Paper", reason)
        self.assertIn("2026-10-25 00:00:00 Beijing", reason)
        state = json.loads(self.state_path().read_text(encoding="utf-8"))
        self.assertEqual(state["mode"], "paper")
        self.assertEqual(state["asset"], "BTC")
        self.assertEqual(state["limit_usd"], 12.0)
        self.assertEqual(state["capital_usd"], 100.0)
        self.assertEqual(state["resume_ts"], self.midnight + 86400)

    def test_only_requested_asset_paper_pnl_counts(self):
        self.add_resolution(11.0)
        self.add_resolution(50.0, asset="ETH")
        self.add_resolution(100.0, paper=False)
        self.add_resolution(200.0, settle_ts=self.midnight - 1,
                            buy_ts=self.midnight - 120)
        self.assertIsNone(self.stop_reason())
        self.assertFalse(self.state_path().exists())
        self.add_resolution(1.0)
        self.assertIsNotNone(self.stop_reason())

    def test_prior_day_entry_settled_today_counts(self):
        self.add_resolution(12.0, buy_ts=self.midnight - 300,
                            settle_ts=self.midnight + 120)
        self.assertIsNotNone(self.stop_reason())

    def test_unresolved_and_future_settlements_do_not_count(self):
        self.add_resolution(12.0, settle_ts=self.now + 600)
        self.assertIsNone(self.stop_reason())
        with store.db() as db:
            db.execute("DELETE FROM resolutions")
        self.assertIsNone(self.stop_reason())

    def test_exit_today_counts_and_does_not_double_count_settlement(self):
        self.add_resolution(20.0, buy_ts=self.midnight - 100,
                            settle_ts=self.now - 10)
        # Forty shares bought at .5, sold at .8 today: realized profit is $12.
        with store.db() as db:
            db.execute(
                "INSERT INTO orders (ts,asset,market_slug,condition_id,token_id,"
                "side,size,price,status,dry_run) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (self.now - 60, "BTC", "btc-test-1", "BTC-1", "token-1",
                 "SELL_UP", 40.0, 0.8, "exit_dry_run", 1),
            )
        self.assertAlmostEqual(
            store.realized_pnl_summary_today(True)["by_asset"]["BTC"]["realized_usd"],
            12.0,
        )
        self.assertIsNotNone(self.stop_reason())

    def test_latch_remains_after_later_loss(self):
        self.add_resolution(12.0)
        initial_reason = self.stop_reason()
        self.add_resolution(-5.0)
        self.assertAlmostEqual(store.realized_pnl_today(True), 7.0)
        self.assertEqual(self.stop_reason(), initial_reason)

    def test_module_reload_preserves_stop(self):
        self.add_resolution(12.0)
        reason = self.stop_reason()
        self.add_resolution(-5.0)
        reloaded = importlib.reload(paper_profit)
        self.assertEqual(reloaded.paper_profit_stop_reason(self.cfg, "BTC"), reason)
        self.assertEqual(self.stop_reason(), reason)

    def test_beijing_midnight_resumes_then_new_day_can_trigger(self):
        self.add_resolution(12.0)
        self.assertIsNotNone(self.stop_reason())
        old_state = json.loads(self.state_path().read_text(encoding="utf-8"))
        self.now = self.midnight + 86400 - 0.001
        self.assertIsNotNone(self.stop_reason())
        self.now = self.midnight + 86400
        self.assertIsNone(self.stop_reason())
        self.assertIsNone(paper_profit.active_paper_profit_stop("BTC"))
        self.now += 600
        self.add_resolution(12.0)
        self.assertIsNotNone(self.stop_reason())
        new_state = json.loads(self.state_path().read_text(encoding="utf-8"))
        self.assertEqual(new_state["resume_ts"], old_state["resume_ts"] + 86400)

    def test_different_ledgers_have_independent_latches(self):
        self.add_resolution(12.0)
        initial_reason = self.stop_reason()
        second_db = Path(self.tempdir.name) / "independent-shadow.db"
        with patch.object(store, "DB_PATH", second_db):
            with store.db():
                pass
            self.assertIsNone(self.stop_reason())
            self.assertFalse(self.state_path().exists())
            self.add_resolution(12.0)
            self.assertIsNotNone(self.stop_reason())
            self.assertTrue(self.state_path().exists())
        self.assertEqual(self.stop_reason(), initial_reason)

    def test_invalid_capital_blocks_entries(self):
        for capital in (0.0, -1.0, float("nan"), float("inf")):
            with self.subTest(capital=capital):
                reason = self.stop_reason(replace(self.cfg, paper_equity_usd=capital))
                self.assertIn("unavailable", reason)
                self.assertIn("new entries blocked", reason)
                self.assertFalse(self.state_path().exists())

    def test_invalid_fraction_blocks_entries(self):
        for fraction in (-0.01, 1.01, float("nan"), float("inf")):
            with self.subTest(fraction=fraction):
                reason = self.stop_reason(replace(
                    self.cfg, max_daily_realized_profit_fraction=fraction,
                ))
                self.assertIn("new entries blocked", reason)

    def test_disabled_percentage_does_not_create_latch(self):
        self.add_resolution(100.0)
        cfg = replace(self.cfg, max_daily_realized_profit_fraction=0.0)
        self.assertIsNone(self.stop_reason(cfg))
        self.assertFalse(self.state_path().exists())

    def test_live_retains_usd_cap_without_reading_or_writing_paper_latch(self):
        self.add_resolution(500.0)
        self.add_resolution(4.0, paper=False)
        cfg = replace(self.cfg, max_daily_realized_profit_usd=5.0)
        with patch.object(risk, "paper_profit_stop_reason",
                          side_effect=AssertionError("live accessed Paper guard")):
            self.assertIsNone(risk.daily_realized_profit_stop_reason(cfg, False))
            self.add_resolution(1.0, paper=False)
            reason = risk.daily_realized_profit_stop_reason(cfg, False)
            self.assertIn("$5.00", reason)
            self.assertIsNone(risk.daily_realized_profit_stop_reason(
                replace(cfg, max_daily_realized_profit_usd=0.0), False,
            ))
        self.assertFalse(self.state_path().exists())

    def test_allowed_to_trade_blocks_new_paper_entry(self):
        self.add_resolution(12.0)
        with patch.object(risk, "order_attempts_since",
                          side_effect=AssertionError("should stop before other caps")):
            allowed, reason = risk.allowed_to_trade(
                replace(self.cfg, max_orders_per_hour=40), True,
                equity_usd=100.0, order_cost_usd=2.0, asset="BTC",
            )
        self.assertFalse(allowed)
        self.assertIn("Paper daily realized profit", reason)

    def test_corrupt_persisted_state_blocks_entries(self):
        self.state_path().write_text("{invalid", encoding="utf-8")
        self.assertIn("new entries blocked", self.stop_reason())

    def test_unavailable_accounting_blocks_entries(self):
        with patch.object(store, "realized_pnl_summary_today",
                          side_effect=RuntimeError("test ledger failure")):
            self.assertIn("new entries blocked", self.stop_reason())
        self.assertFalse(self.state_path().exists())

    def test_buy_gate_bypasses_background_pnl_cache(self):
        self.add_resolution(11.0)
        self.assertIsNone(paper_profit.paper_profit_stop_reason(
            self.cfg, cache_ttl_sec=10.0))
        self.add_resolution(1.0)
        self.assertIsNone(paper_profit.paper_profit_stop_reason(
            self.cfg, cache_ttl_sec=10.0))
        allowed, reason = risk.allowed_to_trade(self.cfg, True, asset="BTC")
        self.assertFalse(allowed)
        self.assertIn("12.0%", reason)

    def test_background_cache_invalidates_on_new_day_and_configuration(self):
        self.add_resolution(11.0)
        self.assertIsNone(paper_profit.paper_profit_stop_reason(
            self.cfg, cache_ttl_sec=10.0))
        self.assertIsNotNone(paper_profit.paper_profit_stop_reason(
            replace(self.cfg, max_daily_realized_profit_fraction=0.10),
            cache_ttl_sec=10.0))
        self.now = self.midnight + 86400
        self.assertIsNone(paper_profit.paper_profit_stop_reason(
            self.cfg, cache_ttl_sec=10.0))

    def test_exit_or_resolution_invalidates_background_cache(self):
        self.add_resolution(11.0)
        self.assertIsNone(paper_profit.paper_profit_stop_reason(
            self.cfg, cache_ttl_sec=10.0))
        self.add_resolution(1.0)
        paper_profit.invalidate_paper_profit_cache()
        self.assertIsNotNone(paper_profit.paper_profit_stop_reason(
            self.cfg, cache_ttl_sec=10.0))


if __name__ == "__main__":
    unittest.main()
