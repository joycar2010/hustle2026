"""Exercise the real main loop with local ledgers and mocked market transport.

The Paper guard and accounting are real. Only market I/O, resolution transport,
exit execution, config loading, and sleeps are mocked. No service is launched.
"""
from __future__ import annotations

import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from bot import main, paper_profit, store
from bot.book import TopOfBook
from bot.config import Config
from bot.markets import LiveMarket


class LoopStopped(BaseException):
    """A deliberate test stop which cannot be swallowed by network handlers."""


class EntryDecisionReached(BaseException):
    """Marks the next-day entry decision without placing a simulated order."""


class PaperProfitMainLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="paper-profit-loop-")
        self.addCleanup(self.tmp.cleanup)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.now = datetime(
            2026, 10, 24, 12, 0, tzinfo=timezone(timedelta(hours=8)),
        ).timestamp()
        self.start_now = self.now
        self.stack.enter_context(patch.object(
            store, "DB_PATH", Path(self.tmp.name) / "isolated-loop.db",
        ))
        self.stack.enter_context(patch.object(store, "TRADING_DAY_UTC_OFFSET_HOURS", 8.0))
        self.stack.enter_context(patch("bot.main.time.time", side_effect=lambda: self.now))
        paper_profit.invalidate_paper_profit_cache()
        self.addCleanup(paper_profit.invalidate_paper_profit_cache)
        self.cfg = Config(
            private_key="", wallet_address="", funder_address="",
            signature_type=0, chain_id=137, clob_host="", gamma_host="",
            polygon_rpc="", api_key="", api_secret="", api_passphrase="",
            instance_name="polyauto", btc_live_enabled=False,
            paper_equity_usd=100.0, max_daily_realized_profit_fraction=0.12,
            max_daily_realized_profit_usd=0.0, max_orders_per_hour=0,
            max_open_positions=0, max_daily_loss_fraction=0.0,
            consecutive_loss_kill=0, price_signal_source="test",
            seconds_before_close=180, min_t_remaining_sec=120,
            reversal_exit_enabled=True, reversal_exit_window_sec=90,
            reversal_exit_min_t_remaining_sec=0,
            reversal_exit_require_btc_reversal=False,
            early_reversal_exit_enabled=False,
            early_strong_delta_entry_enabled=False,
            early_strong_delta_entry_hedge_enabled=False,
            strong_delta_entry_enabled=False, late_edge_entry_enabled=False,
            stable_delta_entry_enabled=False, early_entry_enabled=False,
            mid_entry_enabled=False, tail_entry_enabled=False,
            scale_in_after_early_enabled=False, strong_normal_reverse_enabled=False,
        )
        self.stack.enter_context(patch.object(main.config, "load", return_value=self.cfg))
        self.resolve = self.stack.enter_context(patch.object(main, "resolve_pending"))
        self.exit_check = self.stack.enter_context(patch.object(
            main, "maybe_reversal_exit", return_value=False,
        ))
        self.fetch_market = self.stack.enter_context(patch.object(
            main, "fetch_live_market", side_effect=self.market,
        ))
        self.fetch_book = self.stack.enter_context(patch.object(
            main, "fetch_book", return_value=TopOfBook(0.85, 100.0, 0.86, 100.0),
        ))
        self.stack.enter_context(patch.object(main, "fetch_btc_signal", return_value=None))
        self.decide = self.stack.enter_context(patch.object(
            main, "decide", side_effect=EntryDecisionReached,
        ))
        self.buy = self.stack.enter_context(patch.object(
            main, "place_buy_market_fok", side_effect=AssertionError("BUY must not run"),
        ))
        self.build_client = self.stack.enter_context(patch.object(
            main, "build_client", side_effect=AssertionError("Paper created live client"),
        ))
        self.stack.enter_context(patch.object(
            main, "ensure_rtds_client", side_effect=AssertionError("network client started"),
        ))
        self.stack.enter_context(patch(
            "requests.sessions.Session.request",
            side_effect=AssertionError("test attempted a network request"),
        ))
        self.sleep = self.stack.enter_context(patch("bot.main.time.sleep", side_effect=LoopStopped))
        with store.db() as db:
            # $12 realized today, plus an unresolved current-market position.
            db.execute(
                "INSERT INTO orders (ts,asset,market_slug,condition_id,token_id,"
                "side,size,price,status,dry_run) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (self.now - 300, "BTC", "btc-past", "realized", "winner",
                 "UP", 24.0, 0.5, "dry_run", 1),
            )
            db.execute(
                "INSERT INTO resolutions (condition_id,winning_token,resolved_ts) "
                "VALUES (?,?,?)", ("realized", "winner", self.now - 200),
            )
            db.execute(
                "INSERT INTO orders (ts,asset,market_slug,condition_id,token_id,"
                "side,size,price,status,dry_run) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (self.now - 120, "BTC", "btc-current", "held", "up-held",
                 "UP", 2.0, 0.86, "dry_run", 1),
            )

    def market(self, *args):
        current_day = self.now == self.start_now
        return LiveMarket(
            condition_id="held" if current_day else "new-day",
            market_slug="btc-current" if current_day else "btc-new-day",
            up_token="up-held" if current_day else "up-new-day",
            down_token="down-held" if current_day else "down-new-day",
            start_ts=self.now - (240 if current_day else 150),
            end_ts=self.now + (60 if current_day else 150),
            tick_size=0.01, neg_risk=False,
        )

    def assert_no_order_or_live_client(self):
        self.buy.assert_not_called()
        self.build_client.assert_not_called()

    def test_profit_pause_keeps_settlement_and_exit_checks_running(self):
        with self.assertRaises(LoopStopped):
            main.loop(False, asset="BTC")
        self.assertGreaterEqual(self.resolve.call_count, 2)
        self.resolve.assert_called_with(self.cfg, True)
        self.exit_check.assert_called_once()
        exit_args = self.exit_check.call_args.args
        self.assertEqual(exit_args[2].condition_id, "held")
        self.assertTrue(exit_args[6])  # dry_run passed to existing-position exit check
        self.decide.assert_not_called()
        self.assert_no_order_or_live_client()
        self.assertIsNotNone(paper_profit.active_paper_profit_stop("BTC"))
        with store.db() as db:
            logged = db.execute(
                "SELECT action, reason FROM decisions ORDER BY id DESC LIMIT 1",
            ).fetchone()
        self.assertEqual(logged["action"], "SKIP_RISK")
        self.assertIn("12.0%", logged["reason"])

    def test_profit_pause_allows_successful_exit_branch(self):
        self.exit_check.return_value = True
        with self.assertRaises(LoopStopped):
            main.loop(False, asset="BTC")
        self.assertGreaterEqual(self.resolve.call_count, 2)
        self.exit_check.assert_called_once()
        self.decide.assert_not_called()
        self.assert_no_order_or_live_client()
        self.assertIsNotNone(paper_profit.active_paper_profit_stop("BTC"))

    def test_same_worker_resumes_entry_decision_after_beijing_midnight(self):
        def advance_to_next_day(_seconds):
            if self.now != self.start_now:
                raise AssertionError("next-day loop failed to reach entry decision")
            self.now = store.local_day_start_ts(self.now) + 86400 + 60

        self.sleep.side_effect = advance_to_next_day
        with self.assertRaises(EntryDecisionReached):
            main.loop(False, asset="BTC")
        self.assertGreaterEqual(self.resolve.call_count, 3)
        self.assertEqual(self.exit_check.call_count, 2)
        self.decide.assert_called_once()
        self.assertEqual(self.decide.call_args.args[1].condition_id, "new-day")
        self.assertIsNone(paper_profit.active_paper_profit_stop("BTC"))
        self.assertIsNone(main.daily_realized_profit_stop_reason(self.cfg, True, asset="BTC"))
        self.assert_no_order_or_live_client()


if __name__ == "__main__":
    unittest.main()
