"""Read dashboard helpers via AST; never start the app or touch a worker DB."""
from __future__ import annotations

import ast
from contextlib import nullcontext
import json
import math
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

from dotenv import dotenv_values
import pytest


@pytest.fixture
def helpers(tmp_path):
    source = Path(os.environ.get("PNL_DASHBOARD_SOURCE") or Path(__file__).parents[1] / "server" / "dashboard.py")
    names = {
        "_valid_daily_loss_fraction", "_paper_worker_daily_loss", "_daily_loss_limit_fields",
        "_production_daily_loss_limit", "_pnl_for_asset", "_risk_state", "_risk_snapshot",
        "_paper_lane_file", "_paper_shadow_metadata",
    }
    tree = ast.parse(source.read_text(encoding="utf-8-sig"))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in nodes} == names
    root = tmp_path / "worker"
    root.mkdir()
    proc = root / "proc" / "123"
    (proc / "cwd").mkdir(parents=True)
    (proc / "cmdline").write_bytes(b"python\0-m\0bot.main\0--asset\0BTC\0")
    db_path = root / "trades-auto.db"
    env = ("MAX_DAILY_LOSS_FRACTION=0.01\0BTC_LIVE_ENABLED=false\0"
           f"TRADES_DB_PATH={db_path}\0PRIVATE_KEY=do-not-expose-this\0")
    (proc / "environ").write_bytes(env.encode())
    systemctl = Mock(return_value=SimpleNamespace(
        stdout=f"MainPID=123\nActiveState=active\nWorkingDirectory={root}\n"))
    connection = Mock()
    connection.execute.return_value.fetchall.return_value = []
    connection.execute.return_value.fetchone.return_value = (0, 0)
    clock = SimpleNamespace(now=100.0)
    namespace = {
        "Path": lambda p: root / "proc" if p == "/proc" else Path(p),
        "math": math, "os": os, "json": json, "dotenv_values": dotenv_values,
        "time": SimpleNamespace(monotonic=lambda: clock.now, time=lambda: clock.now),
        "subprocess": SimpleNamespace(run=systemctl, SubprocessError=subprocess.SubprocessError),
        "_paper_worker_loss_cache": {}, "_RISK_WORKER_FIELDS": {"max_daily_loss_fraction": "MAX_DAILY_LOSS_FRACTION"}, "ROOT": root, "DB_PATH": db_path,
        "_PAPER_SHADOW_GROUPS": tuple("ABCDEFGH"), "_PAPER_PROTECTION_LABELS": {},
        "_state": {"bot_mode": "paper", "positions": [], "balance_pusd": None},
        "cfg": SimpleNamespace(max_daily_loss_fraction=.03, paper_equity_usd=100.,
                               max_daily_realized_profit_fraction=.12, consecutive_loss_kill=0,
                               max_open_positions=1),
        "_is_polyauto_instance": lambda: True,
        "_control_env_values": lambda: {"MAX_DAILY_LOSS_FRACTION": ".03"},
        "active_entry_pause": lambda *a, **kw: None,
        "active_paper_profit_stop": lambda *a, **kw: None,
        "_filter_active_positions": lambda p: p,
        "_paper_open_stats": lambda: (0, 0.), "db": lambda: nullcontext(connection),
        "_test_proc": proc, "_test_systemctl": systemctl, "_test_clock": clock,
    }
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *nodes], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(source), "exec"), namespace)
    return namespace


def pnl(realized=-1.1):
    return {"realized_usd": realized, "by_asset": {"BTC": {"realized_usd": realized}}}


def runtime(helpers):
    return helpers["_paper_worker_daily_loss"](
        "polymarket-auto-btc-paper.service", helpers["ROOT"], helpers["DB_PATH"])


def set_runtime_loss(helpers, value):
    path = helpers["_test_proc"] / "environ"
    content = path.read_text().replace("MAX_DAILY_LOSS_FRACTION=0.01", f"MAX_DAILY_LOSS_FRACTION={value}")
    path.write_text(content)


def test_saved_three_percent_runtime_one_percent_blocks_at_minus_one_point_one(helpers):
    snapshot = helpers["_risk_snapshot"](pnl())
    assert snapshot["state"] == "LOSS_CAP"
    assert snapshot["new_entries_blocked"] is True
    assert snapshot["configured_max_daily_loss_fraction"] == .03
    assert snapshot["effective_max_daily_loss_fraction"] == snapshot["max_daily_loss_fraction"] == .01
    assert snapshot["daily_loss_limit_mismatch"] is True
    assert snapshot["daily_loss_limit_source"] == "worker_environment"
    assert snapshot["worker_state"] == "LOSS_CAP_LOCKED"  # preserve the existing UI contract
    assert snapshot["worker_service_state"] == "RUNNING"  # process is alive while entries are blocked
    assert snapshot["resume_policy"] == "ASIA_SHANGHAI_MIDNIGHT"
    assert "do-not-expose-this" not in json.dumps(snapshot)


def test_matching_three_percent_does_not_block_minus_one_point_one(helpers):
    set_runtime_loss(helpers, ".03")
    snapshot = helpers["_risk_snapshot"](pnl())
    assert snapshot["state"] == "OK"
    assert snapshot["new_entries_blocked"] is False
    assert snapshot["daily_loss_limit_mismatch"] is False


def test_zero_runtime_threshold_disables_loss_gate(helpers):
    set_runtime_loss(helpers, "0")
    snapshot = helpers["_risk_snapshot"](pnl(-100.))
    assert snapshot["state"] == "OK"
    assert snapshot["effective_max_daily_loss_fraction"] == 0


def test_unreadable_running_process_is_unknown_not_ok(helpers):
    (helpers["_test_proc"] / "environ").unlink()
    snapshot = helpers["_risk_snapshot"](pnl())
    assert snapshot["state"] == "UNKNOWN"
    assert snapshot["new_entries_blocked"] is True
    assert snapshot["effective_max_daily_loss_fraction"] is None
    assert snapshot["daily_loss_limit_mismatch"] is None
    assert snapshot["worker_state"] == "UNKNOWN"


@pytest.mark.parametrize("value", ["", "nan", "inf", "-0.01", "not-a-number"])
def test_invalid_runtime_fraction_stays_unknown(helpers, value):
    set_runtime_loss(helpers, value)
    snapshot = helpers["_risk_snapshot"](pnl())
    assert snapshot["state"] == "UNKNOWN"
    assert snapshot["effective_max_daily_loss_fraction"] is None


def test_missing_runtime_fraction_does_not_fall_back_to_saved_setting(helpers):
    path = helpers["_test_proc"] / "environ"
    path.write_bytes(path.read_bytes().replace(b"MAX_DAILY_LOSS_FRACTION=0.01\0", b""))
    assert helpers["_risk_state"](pnl()) == "UNKNOWN"


@pytest.mark.parametrize("failure", ["live", "database", "command", "directory", "asset"])
def test_wrong_process_identity_is_not_trusted(helpers, failure):
    proc = helpers["_test_proc"]
    if failure == "live":
        path = proc / "environ"
        path.write_bytes(path.read_bytes().replace(b"BTC_LIVE_ENABLED=false", b"BTC_LIVE_ENABLED=true"))
    elif failure == "database":
        helpers["DB_PATH"] = helpers["ROOT"] / "other.db"
    elif failure == "command":
        (proc / "cmdline").write_bytes(b"python\0-m\0server.dashboard\0")
    elif failure == "asset":
        (proc / "cmdline").write_bytes(b"python\0-m\0bot.main\0--asset\0ETH\0")
    else:
        helpers["_test_systemctl"].return_value.stdout = "MainPID=123\nActiveState=active\nWorkingDirectory=/unrelated\n"
    assert runtime(helpers)["effective_max_daily_loss_fraction"] is None


def test_observation_cache_expires_after_five_seconds(helpers):
    assert runtime(helpers)["effective_max_daily_loss_fraction"] == .01
    set_runtime_loss(helpers, ".03")
    helpers["_test_clock"].now += 1
    assert runtime(helpers)["effective_max_daily_loss_fraction"] == .01
    helpers["_test_clock"].now += 5
    assert runtime(helpers)["effective_max_daily_loss_fraction"] == .03
    assert helpers["_test_systemctl"].call_count == 2


def test_stopped_service_does_not_claim_running_or_known_limit(helpers):
    helpers["_test_systemctl"].return_value.stdout = "MainPID=0\nActiveState=inactive\n"
    snapshot = helpers["_risk_snapshot"](pnl())
    assert snapshot["state"] == "UNKNOWN"
    assert snapshot["worker_running"] is False
    assert snapshot["worker_state"] == "STOPPED"


def test_systemctl_timeout_stays_unknown(helpers):
    helpers["_test_systemctl"].side_effect = subprocess.TimeoutExpired("systemctl", 1.5)
    assert helpers["_risk_snapshot"](pnl())["state"] == "UNKNOWN"


def test_protection_module_is_verified_against_its_own_service(helpers):
    (helpers["_test_proc"] / "cmdline").write_bytes(b"python\0-m\0bot.protection_runner\0")
    observation = helpers["_paper_worker_daily_loss"](
        "polymarket-auto-paper-protection-e.service", helpers["ROOT"], helpers["DB_PATH"])
    assert observation["worker_running"] is True
    assert observation["effective_max_daily_loss_fraction"] == .01


def test_live_path_keeps_configured_limit_without_inspecting_paper_worker(helpers):
    helpers["_state"].update(bot_mode="live", balance_pusd=100., value_usd=0.)
    snapshot = helpers["_risk_snapshot"](pnl())
    assert snapshot["state"] == "OK"
    assert snapshot["max_daily_loss_fraction"] == .03
    helpers["_test_systemctl"].assert_not_called()


@pytest.mark.parametrize("group", ["A", "E"])
@pytest.mark.parametrize("configured", [".03", "nan", "-1"])
def test_shadow_metadata_reports_configured_and_effective_thresholds(helpers, tmp_path, group, configured):
    lane = tmp_path / group
    lane.mkdir()
    (lane / ".env").write_text(f"MAX_DAILY_LOSS_FRACTION={configured}\n")
    observer = Mock(return_value={"effective_max_daily_loss_fraction": .01,
                                 "daily_loss_limit_source": "worker_environment",
                                 "worker_running": True, "worker_service_state": "RUNNING"})
    helpers["_paper_worker_daily_loss"] = observer
    metadata = helpers["_paper_shadow_metadata"](tmp_path, group, 100.)
    assert metadata["effective_max_daily_loss_fraction"] == .01
    assert metadata["configured_max_daily_loss_fraction"] == (.03 if configured == ".03" else None)
    assert metadata["daily_loss_limit_mismatch"] is (True if configured == ".03" else None)
    assert metadata["status"] == "RUNNING"
    assert observer.call_args.args[1] == lane
    assert observer.call_args.args[2] == lane / ("ab.db" if group == "A" else "trades.db")


@pytest.mark.parametrize("value", [True, False, None, float("nan"), float("inf"), -.01])
def test_invalid_configured_fraction_is_not_normalized_to_zero(helpers, value):
    assert helpers["_valid_daily_loss_fraction"](value) is None
