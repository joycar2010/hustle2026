from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot import live_accounting as accounting
from bot.live_risk import day_start_ts, publish_live_risk_snapshot, read_live_risk_snapshot

WALLET = "0x"+"11"*20
CONDITION = "0x"+"22"*32
NOW = 1794243600.
START = day_start_ts(NOW)


def config():
    return SimpleNamespace(deposit_wallet_address=WALLET, funder_address=WALLET,
                           max_daily_loss_fraction=.03, max_daily_realized_profit_fraction=.07,
                           polygon_rpc="https://rpc.invalid/secret-never-print", clob_host="https://clob.invalid")


class FakeReader:
    def __init__(self, extra_cash=0.):
        self.extra_cash = extra_cash
        self.baseline_calls = 0

    def block(self, number):
        number = 1900 if number == "latest" else number
        return {"number": number, "timestamp": START+(number-100)*2, "hash": "0xblock"}

    def calls(self, calls, block):
        values = []
        for address, data in calls:
            if data.startswith("0x70a08231"):
                values.append(int((100. if block < 100 else 95.7+self.extra_cash)*1e6))
                if block < 100:
                    self.baseline_calls += 1
            elif data.startswith("0x00fdd58e"):
                values.append(0 if block < 100 else 5_000_000)
            elif data.startswith("0xdd34de67") or data.startswith("0x0504c814"):
                values.append(1)
            else:
                raise AssertionError(data)
        return values


def rows():
    return ([dict(timestamp=START+100, type="TRADE", token_id="123", condition_id=CONDITION,
                  outcome_index=0, side="BUY", usdc_size=4.3, size=5., proxy_wallet=WALLET)],
            [dict(token_id="123", condition_id=CONDITION, current_size=5., outcome_index=0)])


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/"live-risk.json"
        accounting._settled_values.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def test_midnight_block_is_strictly_before_boundary(self):
        reader = FakeReader()
        block = accounting.block_before_midnight(reader, START, reader.block("latest"))
        self.assertEqual(block["number"], 99)
        self.assertEqual(block["timestamp"], START-2)

    def test_proven_contract_baseline_and_resolved_holdings(self):
        with patch.object(accounting, "read_account_inputs", return_value=rows()):
            value = accounting.collect_live_observation(config(), now=NOW, path=self.path, reader=FakeReader())
        self.assertEqual(value["day_start_equity_usd"], 100.)
        self.assertAlmostEqual(value["equity_usd"], 100.7)
        self.assertAlmostEqual(value["cash_reconciliation_difference_usd"], 0.)
        self.assertTrue(value["baseline_as_of"] < START)
        self.assertTrue(publish_live_risk_snapshot(config(), value, now=NOW, path=self.path)["allow_entries"])

    def test_unknown_cash_or_indexer_delay_blocks_instead_of_assuming_profit(self):
        with patch.object(accounting, "read_account_inputs", return_value=rows()):
            result = accounting.refresh_live_risk(config(), now=NOW, path=self.path, reader=FakeReader(extra_cash=5.))
        self.assertFalse(result["allow_entries"])
        self.assertIn("not synchronized", result["entry_block_reason"])

    def test_complete_external_deposit_is_neutral(self):
        activity, positions = rows()
        activity.append(dict(type="DEPOSIT", timestamp=START+200, usdc_size=5., proxy_wallet=WALLET))
        with patch.object(accounting, "read_account_inputs", return_value=(activity, positions)):
            result = accounting.refresh_live_risk(config(), now=NOW, path=self.path, reader=FakeReader(extra_cash=5.))
        self.assertTrue(result["allow_entries"])
        self.assertEqual(result["external_net_flow_usd"], 5.)
        self.assertAlmostEqual(result["daily_net_pnl_usd"], .7)

    def test_verified_midnight_baseline_survives_poller_restart(self):
        reader = FakeReader()
        with patch.object(accounting, "read_account_inputs", return_value=rows()):
            accounting.refresh_live_risk(config(), now=NOW, path=self.path, reader=reader)
            other_reader = FakeReader()
            accounting.refresh_live_risk(config(), now=NOW, path=self.path, reader=other_reader)
        self.assertEqual(reader.baseline_calls, 1)
        self.assertEqual(other_reader.baseline_calls, 0)

    def test_unknown_income_type_is_not_silently_classified_as_pnl(self):
        with self.assertRaises(accounting.AccountingCoverageError):
            accounting.period_flows([dict(type="REWARD", timestamp=NOW, usdc_size=1.)], WALLET, START, NOW)

    def test_deposit_with_pending_status_is_not_counted_as_confirmed(self):
        value = accounting.period_flows([dict(type="DEPOSIT", timestamp=NOW, usdc_size=1., status="PENDING")], WALLET, START, NOW)
        self.assertEqual(value, (0., 0., 0))

    def test_negative_amount_or_unidentified_trade_direction_is_invalid(self):
        for row in [dict(type="DEPOSIT", timestamp=NOW, usdc_size=-1.),
                    dict(type="TRADE", timestamp=NOW, usdc_size=1., side="unknown")]:
            with self.assertRaises((ValueError, accounting.AccountingCoverageError)):
                accounting.period_flows([row], WALLET, START, NOW)

    def test_public_pagination_must_finish(self):
        class Response:
            def raise_for_status(self): pass
            def json(self): return {"data":[{}], "pagination":{"has_more":True,"next_cursor":"same"}}
        with self.assertRaises(accounting.AccountingCoverageError):
            accounting._pages("activity", {}, get=lambda *a, **k:Response())

    def test_rpc_errors_do_not_expose_endpoint_or_credentials(self):
        def fail(*a, **k):
            raise RuntimeError("https://rpc.invalid/secret-never-print")
        reader = accounting.PolygonReader("https://rpc.invalid/secret-never-print", post=fail)
        with self.assertRaises(accounting.AccountingCoverageError) as caught:
            reader.rpc("eth_call", [])
        self.assertNotIn("secret-never-print", str(caught.exception))

    def test_closed_history_request_does_not_use_invalid_include_archived_flag(self):
        requested = []
        class Response:
            def raise_for_status(self): pass
            def json(self): return {"data":[], "pagination":{"has_more":False}}
        def get(url, params, timeout):
            requested.append((url, dict(params)))
            return Response()
        accounting.read_account_inputs(WALLET, get=get)
        closed = next(params for url, params in requested if params.get("status") == "CLOSED")
        self.assertNotIn("include_archived", closed)
        funding = next(params for url, params in requested if url.endswith("activity"))
        self.assertEqual(funding["exclude_deposits_withdrawals"], "false")

    def test_cross_midnight_unresolved_position_requires_historical_mark(self):
        class Reader(FakeReader):
            def calls(self, calls, block):
                return [5_000_000 if data.startswith("0x00fdd58e") else 0 for address, data in calls]
        class Response:
            def raise_for_status(self): pass
            def json(self): return {"history":[]}
        with self.assertRaises(accounting.AccountingCoverageError) as caught:
            accounting._marks(Reader(), WALLET,
                {"123":{"condition_id":CONDITION,"outcome_index":0}},
                dict(number=99,timestamp=START-2), historical=True, get=lambda *a,**k:Response())
        self.assertIn("historical valuation", str(caught.exception))

    def test_verified_fallback_requires_same_chain_and_block_hash(self):
        class Node:
            endpoint = "https://public.invalid"
            def __init__(self, *, fail=False, chain="0x89", hash_="0xcanonical"):
                self.fail, self.chain, self.hash = fail, chain, hash_
            def rpc(self, method, params):
                self.assert_method = method
                return self.chain
            def block(self, number):
                return dict(number=100, timestamp=START, hash=self.hash)
            def calls(self, calls, block):
                if self.fail:
                    raise accounting.AccountingCoverageError("archive not supported")
                return [123]
        nodes = [Node(fail=True), Node()]
        with patch.object(accounting, "PolygonReader", return_value=Node()):
            reader = accounting.VerifiedPolygonReader("https://polygon-bor-rpc.publicnode.com")
        # The configured URL matches the first fallback so there are 3 unique
        # endpoints; restrict injected nodes explicitly for this pure test.
        reader.readers = nodes
        reader.block(100)
        self.assertEqual(reader.calls([("0xcontract","0xdata")],100), [123])
        nodes[1].hash = "0xdifferent"
        reader.hash_verified.discard((1,100))
        reader.preferred = 0
        with self.assertRaises(accounting.AccountingCoverageError):
            reader.calls([("0xcontract","0xdata")],100)


if __name__ == "__main__":
    unittest.main()
