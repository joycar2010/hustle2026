import copy
import json
from pathlib import Path
import unittest
from server.trade_fee_evidence import ORDER_FILLED_V2, receipt_fee_evidence, activity_fee_evidence

WALLET = "0x76080d5de1eba3c09564b589948a20bc770d3aad"
EXCHANGE = "0xe111180000d2663c0091e4f400237545b87b996b"
TX = "0xaeb769cfbd2d136df2fcf3877a3ebb4579b55f44974c087db2410fdaaab9060f"
TOKEN = "98101340637552944711966197973677652778067820053221204989653267750185067123217"
ORDER = "0x3dc984d7762fba30c501a7944e6883324381d69ca5cb3193f35f760bed057416"


def event(size=6_160_000, fee=80_850, side=0, order=ORDER, index=0):
    # Official receipt of the screenshot's 6.16-share BUY at 0.75.
    words = [side, int(TOKEN), 4_620_000 if side == 0 else size, size if side == 0 else 4_620_000, fee, 0, 0]
    return {"address": EXCHANGE, "topics": [ORDER_FILLED_V2, order, "0x" + WALLET[2:].zfill(64), "0x" + EXCHANGE[2:].zfill(64)],
            "data": "0x" + "".join(f"{word:064x}" for word in words), "logIndex": hex(index)}


def receipt(logs=None):
    return {"transactionHash": TX, "status": "0x1", "logs": logs if logs is not None else [event()]}


def activity(size=6.16, **values):
    return {"type": "TRADE", "transaction_hash": TX, "token_id": TOKEN, "side": "BUY", "size": size, **values}


class ReceiptFeeEvidenceTests(unittest.TestCase):
    def test_public_confirmed_receipt_fixture(self):
        actual = json.loads(Path(__file__).with_name("fixture_receipt_aeb769cf.json").read_text())
        fills = receipt_fee_evidence(actual, WALLET, [EXCHANGE])
        self.assertEqual(len(fills), 1)
        self.assertEqual(fills[0]["fee_raw"], 80850)
        self.assertEqual(fills[0]["order_hash"], ORDER)
        row = activity_fee_evidence(activity(), fills, [], WALLET)
        self.assertEqual(row["fee_usd"], -.08085)

    def test_actual_receipt_fee_not_cashflow_formula(self):
        fills = receipt_fee_evidence(receipt(), WALLET, [EXCHANGE])
        self.assertEqual(fills[0]["fee_raw"], 80850)
        self.assertAlmostEqual(fills[0]["fee_usd"], -.08085)
        self.assertEqual(fills[0]["size"], 6.16)
        row = activity_fee_evidence(activity(usdc_size=4.70085), fills, [], WALLET)
        self.assertEqual(row["fee_status"], "confirmed")
        self.assertEqual(row["fee_usd"], -.08085)
        self.assertIsNone(row["liquidity_role"])

    def test_no_fee_on_failed_or_foreign_receipt(self):
        bad = receipt(); bad["status"] = "0x0"
        self.assertEqual(receipt_fee_evidence(bad, WALLET), [])
        self.assertEqual(receipt_fee_evidence(receipt(), WALLET, []), [])
        self.assertEqual(receipt_fee_evidence(receipt(), "0x" + "1" * 40), [])

    def test_unknown_abi_and_bad_payload_do_not_claim_zero(self):
        bad = receipt(); bad["logs"][0]["data"] = "0x00"
        self.assertEqual(receipt_fee_evidence(bad, WALLET), [])
        self.assertEqual(activity_fee_evidence(activity(), [], [], WALLET)["fee_status"], "pending")

    def test_duplicate_logs_not_double_charged(self):
        fills = receipt_fee_evidence(receipt([event(), event()]), WALLET)
        self.assertEqual(len(fills), 1)
        self.assertEqual(activity_fee_evidence(activity(), fills, [], WALLET)["fee_raw"], 80850)

    def test_taker_from_authenticated_own_order(self):
        trades = [{"status": "CONFIRMED", "trader_side": "TAKER", "transaction_hash": TX, "taker_order_id": ORDER}]
        fills = receipt_fee_evidence(receipt(), WALLET)
        self.assertEqual(activity_fee_evidence(activity(), fills, trades, WALLET)["liquidity_role"], "TAKER")

    def test_maker_role_not_inferred_from_event_maker(self):
        trades = [{"status": "CONFIRMED", "trader_side": "MAKER", "transaction_hash": TX,
                   "maker_orders": [{"maker_address": WALLET, "order_id": ORDER}]}]
        fills = receipt_fee_evidence(receipt([event(fee=0)]), WALLET)
        row = activity_fee_evidence(activity(), fills, trades, WALLET)
        self.assertEqual(row["liquidity_role"], "MAKER")
        self.assertEqual(row["fee_raw"], 0)

    def test_sell_amount_is_maker_shares(self):
        fills = receipt_fee_evidence(receipt([event(side=1)]), WALLET)
        self.assertEqual(fills[0]["side"], "SELL")
        self.assertEqual(fills[0]["size"], 6.16)

    def test_many_fills_aggregate_only_with_exact_shares(self):
        fills = receipt_fee_evidence(receipt([event(3_000_000, 10_000), event(3_160_000, 20_000, index=1)]), WALLET)
        row = activity_fee_evidence(activity(), fills, [], WALLET)
        self.assertEqual(row["fee_raw"], 30000)
        self.assertEqual(activity_fee_evidence(activity(size=6.15), fills, [], WALLET)["fee_status"], "ambiguous")

    def test_same_tx_rows_partition_without_copying_transaction_fee(self):
        fills = receipt_fee_evidence(receipt([event(3_000_000, 10_000), event(3_160_000, 20_000, index=1)]), WALLET)
        peers = [activity(size=3, timestamp=1), activity(size=3.16, timestamp=2)]
        rows = [activity_fee_evidence(peer, fills, [], WALLET, peer_activity=peers) for peer in peers]
        self.assertEqual([row["fee_raw"] for row in rows], [10000, 20000])
        self.assertEqual(sum(row["fee_raw"] for row in rows), 30000)

    def test_ambiguous_same_size_different_fees_not_allocated(self):
        fills = receipt_fee_evidence(receipt([event(3_000_000, 10_000), event(3_000_000, 20_000, index=1)]), WALLET)
        peers = [activity(size=3, timestamp=1), activity(size=3, timestamp=2)]
        self.assertEqual(activity_fee_evidence(peers[0], fills, [], WALLET, peer_activity=peers)["fee_status"], "ambiguous")

    def test_identical_size_equal_actual_fees_are_confirmed(self):
        fills = receipt_fee_evidence(receipt([event(3_000_000, 10_000), event(3_000_000, 10_000, index=1)]), WALLET)
        peers = [activity(size=3, timestamp=1), activity(size=3, timestamp=2)]
        self.assertEqual(activity_fee_evidence(peers[0], fills, [], WALLET, peer_activity=peers)["fee_raw"], 10000)

    def test_redemption_not_charged_trade_or_gas_fee(self):
        row = activity_fee_evidence({"type": "REDEEM"}, [], [], WALLET)
        self.assertEqual(row["fee_usd"], 0)
        self.assertEqual(row["fee_status"], "not_applicable")


if __name__ == "__main__":
    unittest.main()
