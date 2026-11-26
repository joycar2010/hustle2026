from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot.book import BookLevel, TopOfBook
from bot.execution_costs import ExecutionEstimate
from bot.paper_ai_roles import evaluate_roles


class PaperRoleGateTests(unittest.TestCase):
    def evidence(self):
        return {
            'candidate': {
                'token': 'up',
                'signal': {'available': True, 'source': 'chainlink_rtds_twap', 'window_sec': 60,
                           'source_ts': 100., 'anchor_verified': True},
                'book': TopOfBook(.84, 100., .85, 100., (BookLevel(.84, 100.),),
                                  (BookLevel(.85, 100.),), 100.),
            },
            'sized': {'quantity': 5., 'estimate': ExecutionEstimate(
                True, None, 'BUY', 5., 5., 4.25, .03, -4.28, .85, .85, True, 'TAKER')},
            'verdict': {'allow': True, 'net_edge_per_share': .02},
            'probability': {'available': True, 'markets': 40},
            'now': 100., 'daily_allowed': True, 'daily_reason': None,
            'stream_health': {'clob': {'market': {'connected': True},
                                     'books': {'up': {'snapshot_valid': True, 'resync_required': False}}}},
            'max_book_age_sec': 1.5, 'signal_max_age_sec': 5., 'min_order_size': 5.,
            'primary_model': 'Claude Code', 'secondary_model': 'Grok', 'policy_version': 'roles-v1',
        }

    def test_dataclass_execution_estimate_and_model_audit(self):
        result = evaluate_roles(**self.evidence())
        self.assertTrue(result['allow'])
        self.assertTrue(all(role['ok'] for role in result['roles'].values()))
        self.assertEqual(result['primary_model'], 'Claude Code')
        self.assertEqual(result['secondary_model'], 'Grok')
        self.assertEqual(result['roles']['trader']['entry_fee_usd'], .03)

    def test_dict_estimate_and_book_compatibility(self):
        evidence = self.evidence()
        evidence['sized']['estimate'] = asdict(evidence['sized']['estimate'])
        evidence['candidate']['book'] = asdict(evidence['candidate']['book'])
        self.assertTrue(evaluate_roles(**evidence)['allow'])

    def test_stale_or_future_source_and_book_are_rejected(self):
        for kind, stamp in [('source', 94.), ('source', 101.), ('book', 98.), ('book', 101.)]:
            with self.subTest(kind=kind, stamp=stamp):
                evidence = self.evidence()
                if kind == 'source': evidence['candidate']['signal']['source_ts'] = stamp
                else: evidence['candidate']['book'] = replace(evidence['candidate']['book'], fetched_at=stamp)
                result = evaluate_roles(**evidence)
                self.assertFalse(result['allow'])
                self.assertIn('AI_SCOUT_FRESHNESS', result['reasons'])

    def test_missing_or_unverified_settlement_evidence_is_rejected(self):
        for field in ['source_ts', 'anchor_verified', 'available', 'source', 'window_sec']:
            with self.subTest(field=field):
                evidence = self.evidence()
                evidence['candidate']['signal'].pop(field)
                self.assertFalse(evaluate_roles(**evidence)['roles']['scout']['ok'])

    def test_minimum_five_cannot_be_relaxed(self):
        evidence = self.evidence()
        evidence['sized']['quantity'] = 4.99
        evidence['min_order_size'] = 1.
        result = evaluate_roles(**evidence)
        self.assertFalse(result['roles']['trader']['ok'])
        self.assertFalse(result['roles']['auditor']['ok'])

    def test_unknown_negative_fees_and_nonpositive_edge_are_rejected(self):
        for field, value in [('fee_usd', None), ('fee_usd', -1.), ('fee_usd', float('nan')),
                             ('gross_amount_usd', 0.), ('available', False), ('complete', False),
                             ('filled_size', 4.)]:
            with self.subTest(field=field, value=value):
                evidence = self.evidence()
                evidence['sized']['estimate'] = {**asdict(evidence['sized']['estimate']), field: value}
                self.assertFalse(evaluate_roles(**evidence)['roles']['trader']['ok'])
        for edge in [None, 0., -.01, float('nan')]:
            evidence = self.evidence()
            evidence['verdict']['net_edge_per_share'] = edge
            self.assertFalse(evaluate_roles(**evidence)['roles']['trader']['ok'])

    def test_probability_or_filter_rejection_cannot_be_overridden(self):
        for field in ['probability', 'verdict']:
            evidence = self.evidence()
            evidence[field]['available' if field == 'probability' else 'allow'] = False
            self.assertFalse(evaluate_roles(**evidence)['roles']['trader']['ok'])

    def test_queue_depth_must_cover_order_and_conservative_buffer(self):
        evidence = self.evidence()
        evidence['candidate']['book'] = replace(evidence['candidate']['book'], asks=(BookLevel(.85, 6.),))
        result = evaluate_roles(**evidence)
        self.assertFalse(result['roles']['trader']['ok'])
        self.assertIn('AI_TRADER_QUEUE_CAPACITY', result['reasons'])

    def test_probability_warmup_is_reported_before_execution_cost(self):
        evidence = self.evidence()
        evidence['probability'] = {'available': False, 'reason': 'PROBABILITY_WARMUP', 'markets': 0}
        result = evaluate_roles(**evidence)
        self.assertFalse(result['roles']['trader']['ok'])
        self.assertIn('AI_TRADER_WAITING_PROBABILITY', result['reasons'])
        self.assertNotIn('AI_TRADER_EXECUTION_COST', result['reasons'])

    def test_nonpositive_net_edge_is_reported_separately(self):
        evidence = self.evidence()
        evidence['verdict']['net_edge_per_share'] = 0.0
        result = evaluate_roles(**evidence)
        self.assertFalse(result['roles']['trader']['ok'])
        self.assertIn('AI_TRADER_NET_EDGE', result['reasons'])
        self.assertNotIn('AI_TRADER_EXECUTION_COST', result['reasons'])

    def test_daily_loss_and_profit_block_entries(self):
        for reason in ['DAILY_LOSS_LIMIT', 'DAILY_PROFIT_LIMIT']:
            evidence = self.evidence()
            evidence.update(daily_allowed=False, daily_reason=reason)
            result = evaluate_roles(**evidence)
            self.assertFalse(result['allow'])
            self.assertIn('AI_AUDITOR_DAILY_RISK', result['reasons'])

    def test_missing_disconnected_or_invalid_stream_evidence_fails_closed(self):
        for health in [None, {}, {'clob': {'market': {'connected': True}}},
                       {'clob': {'market': {'connected': False}, 'books': {'up': {'snapshot_valid': True}}}},
                       {'clob': {'market': {'connected': True}, 'books': {'up': {'snapshot_valid': False}}}},
                       {'clob': {'market': {'connected': True}, 'books': {'up': {'snapshot_valid': True, 'resync_required': True}}}}]:
            with self.subTest(health=health):
                evidence = self.evidence()
                evidence['stream_health'] = health
                self.assertFalse(evaluate_roles(**evidence)['roles']['mechanic']['ok'])

    def test_gap_and_nested_runtime_health(self):
        evidence = self.evidence()
        evidence['stream_health'] = {'stream': deepcopy(evidence['stream_health'])}
        self.assertTrue(evaluate_roles(**evidence)['allow'])
        evidence['stream_health']['coverage_block'] = 'PUBLIC_EVENT_CURSOR_GAP'
        self.assertIn('AI_MECHANIC_STREAM_HEALTH', evaluate_roles(**evidence)['reasons'])


if __name__ == '__main__':
    unittest.main()
