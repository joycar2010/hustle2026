import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot.live_risk import (
    _baseline_path, build_live_risk_snapshot, day_start_ts,
    publish_live_risk_snapshot, read_live_risk_snapshot,
)

WALLET = "0x" + "11" * 20
NOW = 1794243600.
START = day_start_ts(NOW)


def config(**changes):
    return SimpleNamespace(**{**dict(deposit_wallet_address=WALLET, funder_address=WALLET,
        max_daily_loss_fraction=.03, max_daily_realized_profit_fraction=.07,
        max_daily_realized_profit_usd=12., paper_equity_usd=100.,
        max_orders_per_hour=0, max_open_positions=3, order_risk_fraction=.02,
        order_fixed_notional_usd=0., effective_min_order_notional_usd=1.,
        consecutive_loss_kill=0), **changes})


def observation(**changes):
    return {**dict(wallet=WALLET, as_of=NOW, day_start_ts=START, equity_usd=100.,
        external_net_flow_usd=0., activity_complete=True, funding_complete=True,
        valuation_complete=True, baseline_complete=True, day_start_equity_usd=100.,
        baseline_as_of=START-2, baseline_source="verified_polygon_midnight",
        official_pnl_as_of=NOW-3600, official_economic_pnl_usd=-999.), **changes}


class LiveRiskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "live-risk.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_loss_uses_fixed_midnight_capital_and_net_equity(self):
        risk = build_live_risk_snapshot(config(), observation(equity_usd=97.), now=NOW)
        self.assertEqual(risk["state"], "DAILY_LOSS_STOP")
        self.assertEqual(risk["daily_loss_limit_usd"], 3.)
        self.assertEqual(risk["daily_net_pnl_usd"], -3.)
        self.assertFalse(risk["allow_entries"])

    def test_profit_uses_seven_percent_not_old_twelve_dollars(self):
        risk = build_live_risk_snapshot(config(), observation(equity_usd=107.), now=NOW)
        self.assertEqual(risk["state"], "DAILY_PROFIT_STOP")
        self.assertAlmostEqual(risk["daily_profit_target_usd"], 7.)

    def test_cash_deposit_does_not_count_as_profit(self):
        risk = build_live_risk_snapshot(config(), observation(equity_usd=150., external_net_flow_usd=50.), now=NOW)
        self.assertEqual(risk["daily_net_pnl_usd"], 0.)
        self.assertTrue(risk["allow_entries"])

    def test_withdrawal_does_not_count_as_loss(self):
        risk = build_live_risk_snapshot(config(), observation(equity_usd=50., external_net_flow_usd=-50.), now=NOW)
        self.assertEqual(risk["daily_net_pnl_usd"], 0.)
        self.assertTrue(risk["allow_entries"])

    def test_zero_profit_fraction_does_not_reenable_legacy_cap(self):
        risk = build_live_risk_snapshot(config(max_daily_realized_profit_fraction=0.),
                                        observation(equity_usd=120.), now=NOW)
        self.assertIsNone(risk["daily_profit_target_usd"])
        self.assertTrue(risk["allow_entries"])

    def test_unknown_funding_blocks_new_entries(self):
        risk = build_live_risk_snapshot(config(), observation(funding_complete=False), now=NOW)
        self.assertFalse(risk["allow_entries"])
        self.assertIn("funding_complete", risk["entry_block_reason"])

    def test_no_midnight_proof_does_not_seed_from_process_start(self):
        risk = build_live_risk_snapshot(config(), observation(baseline_complete=False), now=NOW)
        self.assertFalse(risk["allow_entries"])
        late = build_live_risk_snapshot(config(), observation(baseline_as_of=NOW), now=NOW)
        self.assertFalse(late["allow_entries"])

    def test_official_delay_does_not_replace_realtime_inputs(self):
        risk = build_live_risk_snapshot(config(), observation(), now=NOW)
        self.assertTrue(risk["allow_entries"])
        self.assertEqual(risk["daily_net_pnl_usd"], 0.)
        self.assertEqual(risk["official_economic_pnl_usd"], -999.)

    def test_stale_valuation_blocks_entries(self):
        risk = build_live_risk_snapshot(config(), observation(as_of=NOW-21), now=NOW)
        self.assertFalse(risk["allow_entries"])

    def test_other_wallet_or_day_cannot_be_reused(self):
        for values in ({"wallet": "0x"+"22"*20}, {"day_start_ts": START-86400}):
            self.assertFalse(build_live_risk_snapshot(config(), observation(**values), now=NOW)["allow_entries"])

    def test_fee_loss_uses_net_equity_not_gross_trade_profit(self):
        # Gross trading +2 and real fees -5 -> account 97, so loss gate fires.
        risk = build_live_risk_snapshot(config(), observation(equity_usd=97.), now=NOW)
        self.assertEqual(risk["state"], "DAILY_LOSS_STOP")

    def test_halt_is_persisted_across_process_restart_and_bounce(self):
        first = publish_live_risk_snapshot(config(), observation(equity_usd=96.), path=self.path, now=NOW)
        self.assertEqual(first["state"], "DAILY_LOSS_STOP")
        publish_live_risk_snapshot(config(), observation(equity_usd=100., as_of=NOW+1), path=self.path, now=NOW+1)
        fresh = read_live_risk_snapshot(config(), path=self.path, now=NOW+2)
        self.assertEqual(fresh["state"], "DAILY_LOSS_STOP")
        self.assertTrue(fresh["latched"])

    def test_config_change_is_visible_and_baseline_stays_fixed(self):
        publish_live_risk_snapshot(config(), observation(equity_usd=96.), path=self.path, now=NOW)
        risk = read_live_risk_snapshot(config(max_daily_loss_fraction=.05), path=self.path, now=NOW+1)
        self.assertTrue(risk["allow_entries"])
        self.assertEqual(risk["capital_base_usd"], 100.)
        self.assertEqual(risk["daily_loss_limit_usd"], 5.)

    def test_next_day_requires_new_baseline_then_resumes(self):
        publish_live_risk_snapshot(config(), observation(equity_usd=96.), path=self.path, now=NOW)
        tomorrow = START+86400+1
        self.assertFalse(read_live_risk_snapshot(config(), path=self.path, now=tomorrow)["allow_entries"])
        new = observation(day_start_ts=START+86400, as_of=tomorrow, equity_usd=96.,
                          day_start_equity_usd=96., baseline_as_of=START+86400-1)
        self.assertTrue(publish_live_risk_snapshot(config(), new, path=self.path, now=tomorrow)["allow_entries"])

    def test_restart_does_not_move_frozen_capital(self):
        publish_live_risk_snapshot(config(), observation(), path=self.path, now=NOW)
        result = publish_live_risk_snapshot(config(), observation(day_start_equity_usd=500., equity_usd=105.),
                                           path=self.path, now=NOW)
        self.assertEqual(result["capital_base_usd"], 100.)
        self.assertAlmostEqual(result["daily_net_pnl_usd"], 5.)

    def test_corrupt_or_missing_state_blocks_entries(self):
        self.assertFalse(read_live_risk_snapshot(config(), path=self.path, now=NOW)["allow_entries"])
        self.path.write_text("{broken", encoding="utf-8")
        self.assertFalse(read_live_risk_snapshot(config(), path=self.path, now=NOW)["allow_entries"])

    def test_reader_does_not_write_or_clear_existing_latch(self):
        publish_live_risk_snapshot(config(), observation(equity_usd=107.), path=self.path, now=NOW)
        base = _baseline_path(self.path, WALLET, START)
        before = base.read_bytes(), self.path.read_bytes()
        read_live_risk_snapshot(config(max_daily_realized_profit_fraction=.08), path=self.path, now=NOW)
        self.assertEqual(before, (base.read_bytes(), self.path.read_bytes()))

    def test_live_gate_does_not_read_gross_local_daily_pnl(self):
        from bot import risk
        with patch.object(risk, "read_live_risk_snapshot", return_value={"allow_entries": True, "open_positions_count": 0}), \
             patch.object(risk, "open_positions_count", return_value=0), \
             patch.object(risk, "realized_pnl_today", side_effect=AssertionError("gross local Live PnL used")), \
             patch.object(risk, "consecutive_losses", return_value=0):
            self.assertTrue(risk.allowed_to_trade(config(), False, equity_usd=100.)[0])

    def test_live_position_cap_uses_real_account_not_ghost_local_rows(self):
        from bot import risk
        with patch.object(risk, "read_live_risk_snapshot", return_value={"allow_entries": True, "open_positions_count": 3}), \
             patch.object(risk, "open_positions_count", side_effect=AssertionError("local Live count used")):
            allowed, reason = risk.allowed_to_trade(config(), False, equity_usd=100.)
        self.assertFalse(allowed)
        self.assertIn("max_open_positions (3/3)", reason)


if __name__ == "__main__":
    unittest.main()
