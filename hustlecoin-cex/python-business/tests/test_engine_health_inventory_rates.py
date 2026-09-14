from types import SimpleNamespace

from app.api.engine_api import _inventory_probe_rates_by_account


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return list(self.rows)


class _DB:
    def __init__(self, rules, accounts):
        self.rules = rules
        self.accounts = accounts

    def query(self, model):
        name = getattr(model, "__name__", "")
        return _Query(self.rules if name == "GlobalRules" else self.accounts)


def test_inventory_probe_rate_uses_account_override_and_global_fallback():
    db = _DB(
        [SimpleNamespace(inventory_probe_rate_per_sec=3.8)],
        [
            SimpleNamespace(id=1, is_enabled=True, inventory_probe_rate_per_sec=None),
            SimpleNamespace(id=2, is_enabled=True, inventory_probe_rate_per_sec=2.5),
        ],
    )
    assert _inventory_probe_rates_by_account(db, 42) == {"1": 3.8, "2": 2.5}


def test_inventory_probe_rate_does_not_fall_back_to_borrow_rate():
    db = _DB(
        [SimpleNamespace(inventory_probe_rate_per_sec=None, borrow_rate_per_sec=2)],
        [SimpleNamespace(id=7, is_enabled=True, inventory_probe_rate_per_sec=None)],
    )
    assert _inventory_probe_rates_by_account(db, 42) == {"7": 3.8}
