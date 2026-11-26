"""Exercise the new local bridge without importing the live application."""
import ast
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import threading
import time
import unittest


class HTTPFailure(Exception):
    def __init__(self,status_code,detail):self.status_code=status_code;self.detail=detail


class PaperAdvisorEndpointTests(unittest.TestCase):
    def load(self):
        source=Path(__file__).resolve().parents[1]/'server/dashboard.py'
        node=next(n for n in ast.parse(source.read_text(encoding='utf-8')).body
            if isinstance(n,ast.FunctionDef) and n.name=='paper_model_advisor')
        node.decorator_list=[]
        self.calls=[]
        def call(slot,prompt):
            self.calls.append((slot,prompt))
            return {'slot':slot,'enabled':True,'model':slot,'usage':{'total_tokens':5},'text':'{}','error':None}
        env={'LlmAdvisorPayload':object,'Request':object,'HTTPException':HTTPFailure,
            '_paper_model_lock':threading.Lock(),'time':time,'ThreadPoolExecutor':ThreadPoolExecutor,
            '_llm_advisor_call':call}
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),env)
        return env['paper_model_advisor'],env

    def test_local_pair_returns_actual_usage_without_order_permission(self):
        endpoint,_=self.load()
        result=endpoint(SimpleNamespace(prompt='Public Paper context',lead_id='id'),
            SimpleNamespace(client=SimpleNamespace(host='127.0.0.1'),headers={}))
        self.assertFalse(result['trading_allowed'])
        self.assertEqual(result['lead_id'],'id')
        self.assertEqual({c[0] for c in self.calls},{'primary','secondary'})
        self.assertTrue(all('Public Paper context' in c[1] for c in self.calls))
        for slot in ('primary','secondary'):
            self.assertEqual(result[slot]['usage']['total_tokens'],5)
            self.assertGreaterEqual(result[slot]['latency_sec'],0)

    def test_external_forwarded_and_parallel_requests_are_rejected(self):
        endpoint,env=self.load();payload=SimpleNamespace(prompt='Paper',lead_id='id')
        for request in (SimpleNamespace(client=SimpleNamespace(host='1.2.3.4'),headers={}),
                SimpleNamespace(client=SimpleNamespace(host='127.0.0.1'),headers={'x-forwarded-for':'1.2.3.4'})):
            with self.assertRaises(HTTPFailure) as failure:endpoint(payload,request)
            self.assertEqual(failure.exception.status_code,403)
        env['_paper_model_lock'].acquire()
        with self.assertRaises(HTTPFailure) as failure:
            endpoint(payload,SimpleNamespace(client=SimpleNamespace(host='127.0.0.1'),headers={}))
        self.assertEqual(failure.exception.status_code,429)
        self.assertFalse(self.calls)


if __name__=='__main__':unittest.main()
