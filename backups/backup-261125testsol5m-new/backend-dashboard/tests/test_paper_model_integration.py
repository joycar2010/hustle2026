from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bot.book import BookLevel,TopOfBook
from bot.markets import LiveMarket
from bot.paper_comparison import PaperComparison,PaperComparisonConfig


class FakeAdvisor:
    def __init__(self):
        self.calls=[];self.result={'status':'PENDING','allow':False,'reasons':['AI_MODEL_PENDING'],
            'decision_id':'one','context_sha256':'context'}
    def request(self,market_id,side,context,now=None):
        self.calls.append(context);return dict(self.result)
    def poll(self,decision_id,now=None,context_sha256=None):
        return dict(self.result)
    def health(self):return {'status':self.result['status'],'requests':len(self.calls)}


class PaperModelIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.advisor=FakeAdvisor()
        self.exp=PaperComparison(replace(PaperComparisonConfig(),confirm_checks=1),self.temp.name,
            now=900.,advisor=self.advisor)
        self.addCleanup(self.exp.close)
        m=LiveMarket('condition','btc-updown-5m-700','up','down',700.,1000.,.01,False)
        self.market=self.exp.add_market(m,{'feeSchedule':{'rate':.07,'exponent':1,'takerOnly':True},
            '_verified_twap_seconds':60},now=900.)
        self.health={'clob':{'market':{'connected':True},'books':{'up':{'snapshot_valid':True}}}}

    def candidate(self,now=900.,delta=20.,ask=.85):
        book=TopOfBook(.84,100.,ask,100.,(BookLevel(.84,100.),),(BookLevel(ask,100.),),now)
        self.exp.books['up']=book
        return {'side':'UP','token':'up','book':book,'remaining':1000.-now,'delta':delta,
            'signal':{'available':True,'source':'chainlink_rtds_twap','window_sec':60,'source_ts':now,
                'anchor_verified':True,'price':10000.+delta,'anchor':10000.}}

    def filtered(self,candidate,now=900.,**kw):
        sized,why=self.exp._budget_size('FILTERED',self.market,candidate,now)
        self.assertIsNone(why)
        with patch.object(self.exp.features,'features',return_value={}), \
                patch.object(self.exp.model,'estimate',return_value={'available':True}), \
                patch('bot.paper_comparison.evaluate_filters',return_value={
                    'allow':True,'reasons':[],'net_edge_per_share':.08}):
            return self.exp._filtered(self.market,candidate,sized,now,stream_health=self.health,**kw)

    def test_pending_and_veto_block_b_without_blocking_baseline(self):
        first=self.filtered(self.candidate())
        self.assertFalse(first['allow']);self.assertEqual(len(self.advisor.calls),1)
        self.advisor.result.update(status='READY',allow=False,reasons=['AI_MODEL_VETO'])
        second=self.filtered(self.candidate(901.),now=901.)
        self.assertFalse(second['allow']);self.assertEqual(len(self.advisor.calls),1)
        summary=self.exp.summary(901.)
        self.assertFalse(summary['groups']['BASELINE']['ai_shadow']['enabled'])
        self.assertTrue(summary['groups']['FILTERED']['ai_shadow']['enabled'])

    def test_approval_current_hard_risk_and_context_recheck(self):
        self.filtered(self.candidate())
        self.advisor.result.update(status='READY',allow=True,reasons=[])
        self.assertTrue(self.filtered(self.candidate(901.),now=901.)['allow'])
        blocked=self.filtered(self.candidate(902.),now=902.,daily_allowed=False,daily_reason='DAILY_LOSS_LIMIT')
        self.assertFalse(blocked['allow'])
        self.assertIn('AI_AUDITOR_DAILY_RISK',blocked['reasons'])
        self.advisor.result.update(status='PENDING',allow=False,reasons=['AI_MODEL_PENDING'])
        changed=self.filtered(self.candidate(903.,delta=11.),now=903.)
        self.assertFalse(changed['allow']);self.assertEqual(len(self.advisor.calls),2)

    def test_approval_audit_follows_submitted_paper_order(self):
        candidate=self.candidate()
        verdict=self.filtered(candidate)
        self.advisor.result.update(status='READY',allow=True,reasons=[])
        verdict=self.filtered(candidate)
        self.assertTrue(verdict['allow'])
        sized,_=self.exp._budget_size('FILTERED',self.market,candidate,900.)
        self.exp._submit_entry('FILTERED',self.market,candidate,sized,900.,verdict=verdict)
        payload=json.loads(self.exp.db.execute("SELECT payload FROM decisions WHERE action='PAPER_ENTRY_SUBMITTED'").fetchone()[0])
        self.assertTrue(payload['filter_audit']['ai_roles']['allow'])
        self.assertEqual(payload['filter_audit']['ai_model_decision']['decision_id'],'one')

    def test_missing_advisor_cannot_turn_rule_gates_into_model_approval(self):
        self.exp.advisor=None
        verdict=self.filtered(self.candidate())
        self.assertFalse(verdict['allow'])
        self.assertIn('AI_ADVISOR_UNAVAILABLE',verdict['reasons'])


if __name__=='__main__':unittest.main()
