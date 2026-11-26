import importlib.util
from datetime import datetime, timezone, timedelta
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location('period_chain_statistics', Path(__file__).resolve().parents[1] / 'server' / 'chain_statistics.py')
chain = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(chain)
BJ = timezone(timedelta(hours=8))
START = datetime(2026, 11, 10, tzinfo=BJ).timestamp()
END = START + 86400


def event(ts, side='BUY', amount=4.671309, fee=-.06131, kind='TRADE', token='t', tx='tx'):
    return {'type': kind, 'activity_type': kind, 'timestamp': ts, 'ts': ts,
            'condition_id': 'c', 'token_id': token, 'transaction_hash': tx,
            'side': side, 'size': 5.691357, 'usdc_size': amount,
            'cashflow_usd': -amount if side == 'BUY' else amount,
            'fee_usd': fee, 'fee_status': 'confirmed' if kind == 'TRADE' else 'not_applicable'}


def point(ts, economic, trade=None, fees=-1., block=1):
    return {'timestamp': ts, 'economic_pnl': economic, 'trade_pnl': trade if trade is not None else economic - fees,
            'fees': fees, 'maker_rebate': 0., 'source_block': block}


class PeriodSummaryTests(unittest.TestCase):
    def test_cashflow_already_contains_real_fees(self):
        # The 01:03 matched sample from the public audit. The fee is a
        # disclosure and must not be deducted a second time.
        buy = event(START + 10)
        sell = event(START + 20, 'SELL', 5.14528, -.03262, tx='sell')
        summary = chain.summarize_activity_period([buy, sell], START, END, now=END)
        self.assertEqual(summary['net_cashflow_usd'], .473971)
        self.assertEqual(summary['fees_usd'], -.09393)
        self.assertTrue(summary['cashflow_fee_inclusive'])
        self.assertEqual(summary['buy_cash_paid_usd'], 4.671309)
        self.assertEqual(summary['sell_cash_received_usd'], 5.14528)

    def test_whole_interval_does_not_use_page_length(self):
        rows = [event(START + 10 + index, amount=1., fee=0., tx=str(index)) for index in range(45)]
        summary = chain.summarize_activity_period(rows, START, END, now=END)
        self.assertEqual(summary['trades'], 45)
        self.assertEqual(summary['net_cashflow_usd'], -45.)
        self.assertEqual(summary['fee_confirmed'], 45)

    def test_beijing_boundaries_are_start_inclusive_end_exclusive(self):
        rows = [event(START - 1, tx='before'), event(START, tx='at-start'),
                event(END - 1, tx='last'), event(END, tx='at-end')]
        summary = chain.summarize_activity_period(rows, START, END, now=END)
        self.assertEqual(summary['records'], 2)

    def test_fees_pending_is_not_reported_as_zero(self):
        row = event(START + 1)
        row.update(fee_status='pending', fee_usd=None)
        summary = chain.summarize_activity_period([row], START, END, now=END)
        self.assertIsNone(summary['fees_usd'])
        self.assertEqual(summary['fee_pending'], 1)
        self.assertFalse(summary['fees_complete'])

    def test_partial_fee_total_is_labelled_incomplete(self):
        good = event(START + 1, tx='good')
        pending = event(START + 2, tx='pending')
        pending.update(fee_status='pending', fee_usd=None)
        summary = chain.summarize_activity_period([good, pending], START, END, now=END)
        self.assertEqual(summary['fees_usd'], -.06131)
        self.assertEqual(summary['fee_confirmed'], 1)
        self.assertFalse(summary['fees_complete'])

    def test_redemption_not_trading_fee(self):
        redeem = event(START + 1, 'REDEEM', 5.38, None, kind='REDEEM')
        summary = chain.summarize_activity_period([redeem], START, END, now=END)
        self.assertEqual(summary['redemptions'], 1)
        self.assertEqual(summary['redeem_cash_received_usd'], 5.38)
        self.assertEqual(summary['fees_usd'], 0.)
        self.assertEqual(summary['fee_total_trades'], 0)

    def test_failed_events_and_duplicate_payloads_are_excluded(self):
        row = event(START + 1)
        failed = dict(event(START + 2, tx='failed'), status='FAILED')
        summary = chain.summarize_activity_period([row, dict(row), failed], START, END, now=END)
        self.assertEqual(summary['records'], 1)

    def test_unknown_baseline_never_implies_zero(self):
        points = [point(START + 3600, -100.)]
        summary = chain.summarize_activity_period([event(START + 1)], START, END, points=points, now=END)
        self.assertIsNone(summary['official_economic_pnl_usd'])
        self.assertEqual(summary['official_coverage'], 'unavailable')
        self.assertIsNone(summary['official_baseline_ts'])

    def test_no_financial_sample_in_requested_day_does_not_invent_zero(self):
        summary = chain.summarize_activity_period([event(START + 1)], START, END,
            points=[point(START - 3600, -100.)], now=END)
        self.assertIsNone(summary['official_economic_pnl_usd'])
        self.assertEqual(summary['official_coverage'], 'unavailable')

    def test_partial_financial_snapshot_reports_true_as_of_and_baseline(self):
        points = [point(START, -14., block=7), point(START + 3600, -15.9, block=8)]
        summary = chain.summarize_activity_period([], START, END, points=points, now=END)
        self.assertEqual(summary['official_economic_pnl_usd'], -1.9)
        self.assertEqual(summary['official_data_as_of'], START + 3600)
        self.assertEqual(summary['official_baseline_source_block'], 7)
        self.assertEqual(summary['official_data_source_block'], 8)
        self.assertEqual(summary['official_coverage'], 'partial')

    def test_complete_requires_both_exact_financial_boundaries(self):
        points = [point(START, 1.), point(END, 2.)]
        summary = chain.summarize_activity_period([], START, END, points=points, now=END)
        self.assertEqual(summary['official_coverage'], 'complete')
        self.assertEqual(summary['official_economic_pnl_usd'], 1.)

    def test_forward_filled_midnight_is_not_a_new_source_sample(self):
        points = [point(START - 3600, 1., block=8), point(START, 1., block=8),
                  point(END - 3600, 2., block=9), point(END, 2., block=9)]
        summary = chain.summarize_activity_period([], START, END, points=points, now=END)
        self.assertEqual(summary['official_economic_pnl_usd'], 1.)
        self.assertEqual(summary['official_coverage'], 'partial')
        self.assertEqual(summary['official_baseline_source_ts'], START - 3600)
        self.assertEqual(summary['official_data_source_ts'], END - 3600)

    def test_future_requested_end_is_clamped_to_query_time(self):
        summary = chain.summarize_activity_period([], START, END, now=START + 100)
        self.assertEqual(summary['end_ts'], START + 100)
        self.assertEqual(summary['requested_end_ts'], END)

    def test_closed_results_are_distinct_from_interval_equity(self):
        positions = [{'condition_id': 'c', 'token_id': 't', 'last_event_at': START + 50,
                      'status': 'CLOSED', 'total_pnl': .4753}]
        summary = chain.summarize_activity_period([event(START + 1)], START, END,
                                                  positions=positions, now=END)
        self.assertEqual(summary['quick_closed_pnl_usd'], .4753)
        self.assertIsNone(summary['official_economic_pnl_usd'])
        self.assertEqual(summary['quick_closed_scope'], 'market_lifetime_grouped_by_close_time')

    def test_no_position_source_does_not_invent_closed_zero(self):
        summary = chain.summarize_activity_period([], START, END, now=END)
        self.assertIsNone(summary['quick_closed_pnl_usd'])
        self.assertIsNone(summary['quick_closed_markets'])

    def test_invalid_interval_is_rejected(self):
        with self.assertRaises(ValueError):
            chain.summarize_activity_period([], END, START, now=END)


class DailyBoundaryTests(unittest.TestCase):
    def test_truncated_first_day_is_unknown_instead_of_lifetime_loss(self):
        rows = chain.daily_financials([point(START + 3600, -100.)], [], START + 7200)
        first = next(row for row in rows if row['day'] == '2026-11-10')
        self.assertIsNone(first['economic_pnl_usd'])
        self.assertEqual(first['coverage'], 'unavailable')
        self.assertEqual(first['baseline_kind'], 'unknown')

    def test_exact_midnight_point_is_used_instead_of_prior_day_last(self):
        points = [point(START - 3600, -20.), point(START, -19.), point(START + 3600, -18.)]
        first = next(row for row in chain.daily_financials(points, [], START + 7200) if row['day'] == '2026-11-10')
        self.assertEqual(first['economic_pnl_usd'], 1.)
        self.assertEqual(first['baseline_ts'], START)
        self.assertTrue(first['baseline_exact'])

    def test_unknown_first_history_stats_not_assumed_account_inception(self):
        summary = chain.live_statistics([], point(START + 100, -100.), [], START + 200)
        self.assertIsNone(summary['today_economic_pnl_usd'])

    def test_explicit_zero_baseline_is_opt_in(self):
        rows = chain.daily_financials([point(START + 3600, 1.)], [], START + 7200,
                                      initial_baseline_known=True)
        row = next(item for item in rows if item['day'] == '2026-11-10')
        self.assertEqual(row['economic_pnl_usd'], 1.)
        self.assertEqual(row['baseline_kind'], 'explicit_zero')


if __name__ == '__main__':
    unittest.main()
