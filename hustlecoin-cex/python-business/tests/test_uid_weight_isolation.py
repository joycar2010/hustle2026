import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.api.engine_api import _scoped_uid_snapshot


def test_uid_snapshot_does_not_leak_other_user_metrics():
    raw = json.dumps({
        "1": {"used_uid_weight_1m": 2750, "uid_limit": 180000, "uid_weight_time": 1000},
        "9": {"used_uid_weight_1m": 9100, "uid_limit": 180000, "uid_weight_time": 1000},
    })
    assert _scoped_uid_snapshot(raw, [], 1010) == (0, 0, False)
    assert _scoped_uid_snapshot(raw, ["9"], 1010) == (9100, 180000, True)
    assert _scoped_uid_snapshot(raw, ["2"], 1010) == (0, 180000, True)


def test_uid_snapshot_uses_only_owned_account_with_fresh_window():
    raw = json.dumps({
        "1": {"used_uid_weight_1m": 2750, "uid_limit": 180000, "uid_weight_time": 1000},
        "2": {"used_uid_weight_1m": 6400, "uid_limit": 180000, "uid_weight_time": 1000},
    })
    assert _scoped_uid_snapshot(raw, ["1", "2"], 1010) == (6400, 180000, True)
    assert _scoped_uid_snapshot(raw, ["1"], 1061) == (0, 180000, True)


def test_uid_snapshot_malformed_payload_is_safe():
    assert _scoped_uid_snapshot("not-json", ["1"], 1010) == (0, 180000, True)
