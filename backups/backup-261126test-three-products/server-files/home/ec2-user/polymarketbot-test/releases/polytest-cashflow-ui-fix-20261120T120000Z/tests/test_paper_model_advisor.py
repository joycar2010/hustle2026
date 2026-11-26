from pathlib import Path
import json
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot.paper_model_advisor import ADVISOR_URL, AsyncPaperAdvisor


class Clock:
    def __init__(self): self.now = 1000.
    def __call__(self): return self.now


def answer(payload, *, primary=None, secondary=None):
    def slot(model):
        return {"enabled": True, "model": model, "error": None,
                "text": json.dumps({"allow": True, "confidence": .9, "reason": "public evidence agrees"}),
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}, "latency_ms": 2.}
    return {"ok": True, "lead_id": payload["lead_id"], "decision": "HOLD", "trading_allowed": False,
            "primary": primary or slot("claude-opus-4-8"), "secondary": secondary or slot("grok-4.7")}


class AdvisorTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.instances = []

    def tearDown(self):
        for advisor in self.instances: advisor.close()

    def make(self, transport, **kwargs):
        advisor = AsyncPaperAdvisor(transport=transport, clock=self.clock, **kwargs)
        self.instances.append(advisor)
        return advisor

    def done(self, advisor, handle):
        deadline = time.monotonic() + 2.
        while time.monotonic() < deadline:
            result = advisor.poll(handle["decision_id"])
            if result["status"] != "PENDING": return result
            threading.Event().wait(.005)
        self.fail("Advisor worker did not finish")

    def test_exact_context_is_deduplicated_and_real_pair_is_audited(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            def transport(url, payload, timeout):
                calls.append((url, payload, timeout))
                return answer(payload)
            audit = Path(directory) / "reviews.jsonl"
            advisor = self.make(transport, audit_path=audit)
            handle = advisor.request("market", "UP", {"observed_at": 1000., "delta": 20})
            again = advisor.request("market", "UP", {"delta": 20, "observed_at": 1000.})
            self.assertEqual(again["decision_id"], handle["decision_id"])
            result = self.done(advisor, handle)
            self.assertTrue(result["allow"])
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0], ADVISOR_URL)
            self.assertEqual(set(calls[0][1]), {"prompt", "lead_id"})
            self.assertLessEqual(len(calls[0][1]["prompt"]), 4000)
            self.assertEqual(result["primary"]["model"], "claude-opus-4-8")
            self.assertEqual(result["secondary"]["model"], "grok-4.7")
            self.assertEqual(result["primary"]["usage"]["total_tokens"], 15)
            self.assertGreaterEqual(result["latency_ms"], 0)
            records = [json.loads(line) for line in audit.read_text().splitlines()]
            self.assertEqual([row["event"] for row in records], ["requested", "completed"])
            self.assertEqual(records[-1]["evidence_sha256"], result["context_sha256"])
            self.assertNotIn("_context", records[-1])
            self.assertEqual(records[-1]["context"], {"observed_at": 1000., "delta": 20})
            self.assertEqual(records[-1]["schema_version"], 1)
            self.assertEqual(records[-1]["prompt_version"], "paper-dual-model-review-v1")
            summary = advisor.summary()
            self.assertEqual(summary["counts"]["requested"], 1)
            self.assertEqual(summary["counts"]["approved"], 1)
            self.assertEqual(summary["counts"]["deduplicated"], 1)
            self.assertEqual(summary["last_decision"]["primary"]["reason"], "AI_MODEL_APPROVED")
            self.assertEqual(summary["requests"], 1)
            self.assertEqual(summary["completed"], 1)
            self.assertEqual(summary["last_decision"]["primary"]["status"], "APPROVED")
            self.assertEqual(summary["last_decision"]["primary"]["latency_sec"], .002)
            self.assertEqual(summary["last_decision"]["models"]["primary"], summary["last_decision"]["primary"])
            self.assertEqual(summary["status"], "READY")
            self.assertEqual(advisor.health()["timeout_sec"], 40.)
            self.assertEqual(ADVISOR_URL, "http://127.0.0.1:8897/api/paper/model-advisor")

    def test_queue_and_worker_are_bounded_and_do_not_wait_for_provider(self):
        active = threading.Event(); release = threading.Event(); calls = []
        def transport(url, payload, timeout):
            calls.append(payload); active.set(); release.wait(2.)
            return answer(payload)
        advisor = self.make(transport)
        start = time.monotonic()
        first = advisor.request("one", "UP", {"delta": 20})
        self.assertTrue(active.wait(1.))
        second = advisor.request("two", "UP", {"delta": 20})
        third = advisor.request("three", "UP", {"delta": 20})
        self.assertEqual(second["status"], "PENDING")
        self.assertEqual(third["status"], "BUSY")
        self.assertFalse(advisor.poll(first["decision_id"])["allow"])
        self.assertLess(time.monotonic() - start, 1.)
        self.assertEqual(len(calls), 1)
        self.assertEqual(advisor.snapshot()["queue_size"], 1)
        advisor.close()
        self.assertFalse(advisor.poll(first["decision_id"])["allow"])
        self.assertTrue(advisor._thread.daemon)
        release.set()

    def test_readiness_response_never_authorizes_entry(self):
        advisor=self.make(lambda url,payload,timeout:answer(payload))
        handle=advisor.request('__paper_readiness__','UP',{'purpose':'STARTUP_READINESS','deterministic_allow':False})
        result=self.done(advisor,handle)
        self.assertFalse(result['allow'])
        self.assertEqual(result['reasons'],['AI_DIAGNOSTIC_ONLY'])
        self.assertEqual(result['purpose'],'STARTUP_READINESS')
        self.clock.now += 20
        self.assertEqual(advisor.snapshot()['status'], 'IDLE')
        self.assertEqual(advisor.snapshot()['last_decision']['status'], 'STALE')

    def test_changed_context_cooldown_ttl_and_identity_fail_closed(self):
        advisor = self.make(lambda url, payload, timeout: answer(payload), ttl_sec=5., cooldown_sec=10.)
        handle = advisor.request("m", "UP", {"delta": 20})
        self.assertTrue(self.done(advisor, handle)["allow"])
        changed = advisor.request("m", "UP", {"delta": 21})
        self.assertEqual(changed["status"], "COOLDOWN")
        self.assertFalse(changed["allow"])
        self.assertNotEqual(changed["context_sha256"], handle["context_sha256"])
        self.assertEqual(advisor.poll(handle["decision_id"], context_sha256="wrong")["reasons"], ["AI_CONTEXT_MISMATCH"])
        self.clock.now += 5
        self.assertEqual(advisor.poll(handle["decision_id"])["status"], "STALE")
        self.clock.now += 5
        renewed = advisor.request("m", "UP", {"delta": 21})
        self.assertNotEqual(renewed["decision_id"], handle["decision_id"])
        self.assertTrue(self.done(advisor, renewed)["allow"])

    def test_timeout_and_stale_original_evidence_cannot_become_approvals(self):
        active = threading.Event(); release = threading.Event()
        def transport(url, payload, timeout):
            active.set(); release.wait(2.)
            return answer(payload)
        advisor = self.make(transport, timeout_sec=5., max_context_age_sec=20.)
        handle = advisor.request("m", "UP", {"observed_at": 1000.})
        self.assertTrue(active.wait(1.))
        self.clock.now = 1006.
        self.assertEqual(advisor.poll(handle["decision_id"])["status"], "TIMEOUT")
        release.set()
        advisor._queue.join()
        self.assertFalse(advisor.poll(handle["decision_id"])["allow"])
        self.assertEqual(advisor.poll(handle["decision_id"])["status"], "TIMEOUT")
        stale = self.make(lambda url, payload, timeout: answer(payload), max_context_age_sec=2.)
        handle = stale.request("fresh", "UP", {"observed_at": self.clock.now})
        self.done(stale, handle)
        self.clock.now += 3
        self.assertEqual(stale.poll(handle["decision_id"])["reasons"], ["AI_CONTEXT_STALE"])
        self.assertEqual(stale.request("old", "UP", {"observed_at": 1.})["status"], "STALE")

    def test_missing_model_denial_low_confidence_and_invalid_json_all_reject(self):
        cases = [
            {"enabled": False, "model": "grok-4.7", "error": "disabled"},
            {"enabled": True, "model": "grok-4.7", "text": '{"allow":false,"confidence":0.9,"reason":"risk"}'},
            {"enabled": True, "model": "grok-4.7", "text": '{"allow":true,"confidence":0.7,"reason":"unclear"}'},
            {"enabled": True, "model": "grok-4.7", "text": 'analysis\n```json\n{"allow":true,"confidence":0.9,"reason":"ok"}\n```'},
            {"enabled": True, "model": "grok-4.7", "text": '{"allow":"true","confidence":0.9,"reason":"ok"}'},
            {"enabled": True, "model": "grok-4.7", "text": '{"allow":true,"confidence":NaN,"reason":"ok"}'},
            {"enabled": True, "model": "grok-4.7", "text": '{"allow":true,"confidence":0.9,"reason":"ok","extra":1}'},
            {"enabled": True, "model": "grok-4.7", "text": '{"allow":false,"allow":true,"confidence":0.9,"reason":"ok"}'},
            {"enabled": True, "model": "claude-opus-4-8", "text": '{"allow":true,"confidence":0.9,"reason":"ok"}'},
        ]
        for index, slot in enumerate(cases):
            with self.subTest(slot=slot):
                advisor = self.make(lambda url, payload, timeout, slot=slot: answer(payload, secondary=slot))
                result = self.done(advisor, advisor.request(str(index), "UP", {"delta": 20}))
                self.assertFalse(result["allow"])
                self.assertNotEqual(result["reasons"], ["AI_DUAL_MODEL_APPROVED"])

    def test_provider_failure_bad_identity_and_secret_never_leak(self):
        secret = "sk-THIS_IS_AN_EXAMPLE_PRIVATE_VALUE"
        def broken(url, payload, timeout): raise RuntimeError("Authorization Bearer " + secret)
        advisor = self.make(broken)
        result = self.done(advisor, advisor.request("m", "UP", {"delta": 20}))
        self.assertEqual(result["reasons"], ["AI_MODEL_CALL_FAILED"])
        self.assertNotIn(secret, json.dumps(result))
        self.assertEqual(advisor.request("bad", "UP", {"api_key": secret})["reasons"], ["AI_CONTEXT_INVALID"])
        self.assertEqual(advisor.request("bad", "UP", {"note": secret})["reasons"], ["AI_CONTEXT_INVALID"])
        def wrong(url, payload, timeout):
            result = answer(payload); result["lead_id"] = "other-request"; return result
        mismatch = self.make(wrong)
        self.assertFalse(self.done(mismatch, mismatch.request("m", "DOWN", {}))["allow"])

    def test_claude_exact_json_envelope_preserves_strict_schema(self):
        def fenced(url,payload,timeout):
            response=answer(payload)
            response['primary']['text']='```json\n'+response['primary']['text']+'\n```'
            return response
        advisor=self.make(fenced)
        result=self.done(advisor,advisor.request('wrapped','UP',{}))
        self.assertTrue(result['allow'])
        self.assertEqual(result['primary']['response_envelope'],'JSON_CODE_FENCE')
        for text in ('```json\n{"allow":false,"allow":true,"confidence":.9,"reason":"x"}\n```',
                '```json\n{"allow":true,"confidence":0.9,"reason":"x"}\n``` trailing',
                '```json\n{"allow":"true","confidence":0.9,"reason":"x"}\n```'):
            def invalid(url,payload,timeout,text=text):
                response=answer(payload);response['primary']['text']=text;return response
            blocked=self.make(invalid)
            self.assertFalse(self.done(blocked,blocked.request('bad','UP',{}))['allow'])

    def test_usage_absence_is_honest_and_audit_failure_rejects(self):
        def no_usage(url, payload, timeout):
            result = answer(payload)
            result["primary"].pop("usage"); result["secondary"].pop("usage")
            return result
        advisor = self.make(no_usage)
        result = self.done(advisor, advisor.request("m", "UP", {}))
        self.assertTrue(result["allow"])
        self.assertIsNone(result["primary"]["usage"])
        self.assertFalse(result["primary"]["usage_available"])
        with tempfile.TemporaryDirectory() as directory:
            blocked = self.make(no_usage, audit_path=Path(directory))
            result = self.done(blocked, blocked.request("m", "UP", {}))
            self.assertFalse(result["allow"])
            self.assertEqual(result["reasons"], ["AI_AUDIT_UNAVAILABLE"])


if __name__ == "__main__": unittest.main()
