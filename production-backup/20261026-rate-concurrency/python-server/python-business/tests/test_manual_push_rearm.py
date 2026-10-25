"""COIN-REG-20260918-PUSH-VANISH regression tests.

A manual push must re-arm 禁移禁还 protection: leftover explicit
``allow_remove/allow_repay=True`` values from an earlier single-symbol rule
save must not let the Worker delete the freshly pushed slot milliseconds
after the「已推送」toast (production sequence: PUT symbol-rules then POST
push-symbol; Worker logged ``Auto-removed FILUSDT: remove_spread`` 187ms
later).  The Worker additionally confirms the persisted opt-in from the
database before removing a manual-marked symbol, so a stale in-memory rule
snapshot cannot bypass the reset.
"""

import asyncio
from types import SimpleNamespace

from app.services.manual_push_policy import (
    explicit_rule_optin_persisted,
    rearm_manual_push_protection,
)


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _DB:
    def __init__(self, symbol_rules=(), account_rules=()):
        self.symbol_rules = list(symbol_rules)
        self.account_rules = list(account_rules)

    def query(self, model):
        name = getattr(model, "__name__", "")
        if name == "SymbolRule":
            return _Query(self.symbol_rules)
        return _Query(self.account_rules)


def _symbol_rule(**kw):
    base = dict(symbol="FILUSDT", source="custom", allow_remove=None, allow_repay=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _account_rule(**kw):
    base = dict(symbol="FILUSDT", sub_account_id=1, allow_remove=None, allow_repay=None)
    base.update(kw)
    return SimpleNamespace(**base)


# --- rearm_manual_push_protection -------------------------------------------

def test_rearm_resets_true_flags_on_both_layers():
    rule = _symbol_rule(allow_remove=True, allow_repay=True)
    acct = _account_rule(allow_remove=True, allow_repay=None)
    db = _DB([rule], [acct])
    assert rearm_manual_push_protection(db, 2, "FILUSDT") is True
    assert rule.allow_remove is False and rule.allow_repay is False
    assert acct.allow_remove is False
    # NULL (inherit) stays untouched: the opt-in policy already blocks it.
    assert acct.allow_repay is None


def test_rearm_leaves_protected_rows_unchanged():
    rule = _symbol_rule(allow_remove=False, allow_repay=False)
    acct = _account_rule()
    db = _DB([rule], [acct])
    assert rearm_manual_push_protection(db, 2, "FILUSDT") is False
    assert rule.allow_remove is False and rule.allow_repay is False
    assert acct.allow_remove is None and acct.allow_repay is None


def test_rearm_without_any_rule_rows_is_a_noop():
    assert rearm_manual_push_protection(_DB(), 2, "SLPUSDT") is False


# --- explicit_rule_optin_persisted ------------------------------------------

def test_optin_requires_custom_rule_with_explicit_true():
    db = _DB([_symbol_rule(allow_remove=True)])
    assert explicit_rule_optin_persisted(db, 2, "FILUSDT", "remove") is True

    db = _DB([_symbol_rule(allow_remove=False)])
    assert explicit_rule_optin_persisted(db, 2, "FILUSDT", "remove") is False

    db = _DB([_symbol_rule(allow_remove=None)])
    assert explicit_rule_optin_persisted(db, 2, "FILUSDT", "remove") is False

    # A non-custom placeholder row is not an explicit opt-in.
    db = _DB([_symbol_rule(source="global", allow_remove=True)])
    assert explicit_rule_optin_persisted(db, 2, "FILUSDT", "remove") is False


def test_optin_after_rearm_is_blocked():
    rule = _symbol_rule(allow_remove=True, allow_repay=True)
    db = _DB([rule])
    assert explicit_rule_optin_persisted(db, 2, "FILUSDT", "remove") is True
    rearm_manual_push_protection(db, 2, "FILUSDT")
    assert explicit_rule_optin_persisted(db, 2, "FILUSDT", "remove") is False
    assert explicit_rule_optin_persisted(db, 2, "FILUSDT", "repay") is False


def test_optin_accepts_account_level_explicit_true():
    db = _DB([], [_account_rule(allow_remove=True)])
    assert explicit_rule_optin_persisted(db, 2, "FILUSDT", "remove") is True


# --- Worker removal bypass confirms the persisted value ----------------------

class _FakeAsyncRedis:
    def __init__(self, marker_exists=True):
        self._marker_exists = marker_exists

    async def exists(self, key):
        return 1 if self._marker_exists else 0

    async def hget(self, key, field):
        return None


def _bare_worker(monkeypatch, *, snapshot_rule, persisted_optin):
    from engine import worker as worker_mod

    w = worker_mod.Worker.__new__(worker_mod.Worker)
    w._redis = _FakeAsyncRedis(marker_exists=True)
    w._user_id = 2
    w._manual_pushed_symbols = set()
    w._symbol_rule_for_execution = lambda symbol: dict(snapshot_rule)

    calls = {"locked": 0}

    async def _no_lock(symbol, ttl_sec=None):
        calls["locked"] += 1
        return "token"

    w._acquire_borrow_lock = _no_lock

    async def _release(symbol, token):
        return None

    w._release_borrow_lock = _release
    w._rules_are_current = lambda expected: True

    monkeypatch.setattr(
        "app.services.manual_push_policy.explicit_rule_optin_persisted",
        lambda db, user_id, symbol, operation, sub_account_id=None: persisted_optin,
    )
    monkeypatch.setattr(
        worker_mod, "SessionLocal", lambda: SimpleNamespace(close=lambda: None)
    )
    return w, calls


def test_worker_keeps_manual_symbol_when_db_optin_is_gone(monkeypatch):
    # Snapshot still claims custom+allow_remove=True (stale, pre-rearm), but
    # the persisted value was reset by the push endpoint: must NOT remove.
    w, calls = _bare_worker(
        monkeypatch,
        snapshot_rule={"source": "custom", "allow_remove": True},
        persisted_optin=False,
    )
    removed = asyncio.run(w._maybe_auto_remove("FILUSDT", reason="remove_spread"))
    assert removed is False
    # Protection must short-circuit before taking the borrow transition lock.
    assert calls["locked"] == 0


def test_worker_keeps_manual_symbol_when_db_check_fails(monkeypatch):
    def _boom(db, user_id, symbol, operation, sub_account_id=None):
        raise RuntimeError("db down")

    w, calls = _bare_worker(
        monkeypatch,
        snapshot_rule={"source": "custom", "allow_remove": True},
        persisted_optin=False,
    )
    monkeypatch.setattr(
        "app.services.manual_push_policy.explicit_rule_optin_persisted", _boom
    )
    removed = asyncio.run(w._maybe_auto_remove("FILUSDT", reason="remove_spread"))
    assert removed is False
    assert calls["locked"] == 0


def test_worker_protects_manual_symbol_without_custom_rule(monkeypatch):
    w, calls = _bare_worker(
        monkeypatch,
        snapshot_rule={"source": "", "allow_remove": True},
        persisted_optin=True,
    )
    removed = asyncio.run(w._maybe_auto_remove("FILUSDT", reason="remove_spread"))
    assert removed is False
    assert calls["locked"] == 0
