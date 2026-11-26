"""Cashflow, backup and rollback tests for the offline Paper ledger migration."""
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "repair_abc_ledger_20261119.py"
spec = importlib.util.spec_from_file_location("ledger_repair_20261119", SCRIPT)
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


@pytest.fixture
def ledger(tmp_path):
    path = tmp_path / "paper.db"
    with sqlite3.connect(path) as c:
        c.executescript("""
        CREATE TABLE maker_sessions (
          id INTEGER PRIMARY KEY, market_slug TEXT, status TEXT, dry_run INTEGER,
          up_cost_usd REAL DEFAULT 25, down_cost_usd REAL DEFAULT 25,
          gross_pnl_usd REAL DEFAULT 0, net_pnl_usd REAL DEFAULT 0,
          fee_usd REAL DEFAULT 0, rebate_est_usd REAL DEFAULT 0,
          up_fee_usd REAL DEFAULT 0, down_fee_usd REAL DEFAULT 0,
          up_proceeds_usd REAL DEFAULT 0, down_proceeds_usd REAL DEFAULT 0,
          merged_shares REAL DEFAULT 50, merge_proceeds_usd REAL DEFAULT 50,
          redeem_proceeds_usd REAL DEFAULT 0, winner TEXT DEFAULT 'DOWN',
          flatten_pnl_usd REAL DEFAULT 0, slippage_usd REAL DEFAULT 0,
          accounting_original_gross_pnl_usd REAL,
          accounting_original_net_pnl_usd REAL, accounting_corrected_ts REAL
        );
        CREATE TABLE fills (
          id INTEGER PRIMARY KEY, session_id INTEGER, market_slug TEXT,
          side TEXT, size REAL, price REAL, notional_usd REAL, fee_usd REAL,
          liquidity TEXT, strategy TEXT, dry_run INTEGER, note TEXT,
          slippage_usd REAL DEFAULT 0
        );
        CREATE TABLE events (
          id INTEGER PRIMARY KEY, ts REAL, kind TEXT, market_slug TEXT, payload TEXT
        );
        """)
    return path


def session(path, ident, **values):
    row = dict(id=ident, market_slug=f"btc-updown-5m-{ident}", status="closed", dry_run=1)
    row.update(values)
    with sqlite3.connect(path) as c:
        c.execute(f"INSERT INTO maker_sessions ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()))


def fill(path, ident, session_id, **values):
    row = dict(id=ident, session_id=session_id, market_slug=f"btc-updown-5m-{session_id}",
               side="UP", size=5, price=.99, notional_usd=4.95, fee_usd=0,
               liquidity="maker", strategy="split_sell", dry_run=1, note="ask_touch")
    row.update(values)
    with sqlite3.connect(path) as c:
        c.execute(f"INSERT INTO fills ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()))


def proof(ident, **values):
    row = dict(id=ident, slug=f"btc-updown-5m-{ident}", closed=True,
               umaResolutionStatus="resolved", outcomes=["Up", "Down"], outcomePrices=["1", "0"], official="UP")
    row.update(values)
    return row


def row(path, table, ident):
    with sqlite3.connect(path) as c:
        c.row_factory = sqlite3.Row
        return dict(c.execute(f"SELECT * FROM {table} WHERE id=?", (ident,)).fetchone())


def test_c_official_payout_estimate_exclusion_backup_and_idempotence(ledger):
    session(ledger, 14, up_proceeds_usd=4.95, merged_shares=45, merge_proceeds_usd=45,
            redeem_proceeds_usd=5, gross_pnl_usd=4.95, rebate_est_usd=.02079, net_pnl_usd=4.97079)
    fill(ledger, 1, 14)
    evidence = {proof(14)["slug"]: proof(14)}
    result = repair.repair_database(ledger, "C", evidence, apply=True)
    current = row(ledger, "maker_sessions", 14)
    assert current["winner"] == "UP"
    assert current["redeem_proceeds_usd"] == 0
    assert current["gross_pnl_usd"] == pytest.approx(-.05)
    assert current["net_pnl_usd"] == pytest.approx(-.05)
    assert current["rebate_est_usd"] == .02079
    assert current["resolution_source"] == "official_gamma_verified"
    assert result["summary"]["net_delta"] == pytest.approx(-5.02079)
    assert row(Path(result["backup"]), "maker_sessions", 14)["net_pnl_usd"] == 4.97079
    assert row(ledger, "fills", 1)["execution_side"] == "SELL"
    assert row(ledger, "fills", 1)["slippage_source"] == "historical_unknown"
    assert row(ledger, "fills", 1)["slippage_usd"] == 0
    second = repair.repair_database(ledger, "C", evidence, apply=True)
    assert second["changes"] == []
    with sqlite3.connect(ledger) as c:
        events = [json.loads(r[0]) for r in c.execute("SELECT payload FROM events")]
    before = next(e["before"] for e in events if e["table"] == "maker_sessions")
    assert before["winner"] == "DOWN"
    assert before["net_pnl_usd"] == 4.97079


def test_prior_100_merge_correction_and_current_open_are_untouched(ledger):
    for ident in [66, 67]:
        session(ledger, ident, accounting_original_gross_pnl_usd=-50,
                accounting_original_net_pnl_usd=-50, accounting_corrected_ts=1)
    session(ledger, 68, status="open", net_pnl_usd=None, gross_pnl_usd=None)
    before = {i: row(ledger, "maker_sessions", i) for i in [66, 67, 68]}
    result = repair.repair_database(ledger, "C", {}, apply=True)
    assert result["summary"]["open_skipped"] == 1
    assert result["summary"]["net_delta"] == 0
    for ident, original in before.items():
        current = row(ledger, "maker_sessions", ident)
        assert all(current[k] == v for k, v in original.items())


def test_b_fee_reclassification_does_not_repeat_flatten_loss(ledger):
    session(ledger, 1, up_cost_usd=0, down_cost_usd=0, gross_pnl_usd=-6, net_pnl_usd=-6,
            flatten_pnl_usd=-6, accounting_original_gross_pnl_usd=0,
            accounting_original_net_pnl_usd=0, accounting_corrected_ts=1)
    fill(ledger, 1, 1, strategy="maker_mm", price=.5, notional_usd=2.5, note="maker_touch")
    fill(ledger, 2, 1, strategy="maker_mm", price=.4, notional_usd=2,
         note="flatten_residual bid=0.4 avg=0.5 pnl=-0.5")
    result = repair.repair_database(ledger, "B", apply=True)
    expected_fee = .07 * .4 * .6 * 5
    current = row(ledger, "maker_sessions", 1)
    assert current["gross_pnl_usd"] == -6
    assert current["flatten_pnl_usd"] == -6
    assert current["net_pnl_usd"] == pytest.approx(-6 - expected_fee)
    assert current["accounting_original_net_pnl_usd"] == 0
    assert current["fee_usd"] == pytest.approx(expected_fee)
    assert current["up_fee_usd"] == pytest.approx(expected_fee)
    assert result["summary"]["gross_delta"] == 0
    sell = row(ledger, "fills", 2)
    assert sell["liquidity"] == "taker"
    assert sell["execution_side"] == "SELL"
    assert sell["fee_source"] == "paper_model_v1"
    assert sell["slippage_source"] == "historical_unknown"
    assert row(ledger, "fills", 1)["execution_side"] == "BUY"
    assert repair.repair_database(ledger, "B", apply=True)["changes"] == []


def test_default_dry_run_preserves_source_schema_and_data(ledger):
    session(ledger, 14, net_pnl_usd=.1, rebate_est_usd=.1)
    raw_before = ledger.read_bytes()
    result = repair.repair_database(ledger, "C")
    assert not result["applied"]
    assert Path(result["backup"]).exists()
    assert ledger.read_bytes() == raw_before
    assert row(ledger, "maker_sessions", 14)["net_pnl_usd"] == .1
    assert "resolution_source" not in row(ledger, "maker_sessions", 14)


@pytest.mark.parametrize("values", [dict(closed=False), dict(umaResolutionStatus="proposed"),
                                   dict(outcomePrices=[".96", ".04"]), dict(official="DOWN")])
def test_evidence_rejects_pending_or_non_final_quotes(values):
    with pytest.raises(ValueError):
        repair.official_result(proof(14, **values))


def test_evidence_is_bound_to_session_and_cashflow(ledger):
    session(ledger, 14, up_proceeds_usd=4.95, merged_shares=45, merge_proceeds_usd=45)
    fill(ledger, 1, 14)
    stale = proof(14, sold_up=10)
    before = ledger.read_bytes()
    with pytest.raises(ValueError, match="stale evidence cashflow"):
        repair.repair_database(ledger, "C", {stale["slug"]: stale}, apply=True)
    assert ledger.read_bytes() == before


def test_apply_rolls_back_every_row_and_schema_if_audit_event_fails(ledger):
    session(ledger, 14, rebate_est_usd=.1, net_pnl_usd=.1)
    with sqlite3.connect(ledger) as c:
        c.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END")
    before = ledger.read_bytes()
    with pytest.raises(sqlite3.IntegrityError, match="audit unavailable"):
        repair.repair_database(ledger, "C", apply=True)
    assert row(ledger, "maker_sessions", 14)["net_pnl_usd"] == .1
    assert "resolution_source" not in row(ledger, "maker_sessions", 14)
    assert ledger.read_bytes() == before
    assert list((ledger.parent / "ledger-repair-backups").glob("*.sqlite3"))


def test_unknown_closed_result_preserves_payout_and_reports_it(ledger):
    session(ledger, 14, up_proceeds_usd=4.95, merged_shares=45, merge_proceeds_usd=45,
            redeem_proceeds_usd=5, gross_pnl_usd=4.95, net_pnl_usd=4.97079, rebate_est_usd=.02079)
    fill(ledger, 1, 14)
    result = repair.repair_database(ledger, "C", apply=True)
    current = row(ledger, "maker_sessions", 14)
    assert current["winner"] == "DOWN"
    assert current["redeem_proceeds_usd"] == 5
    assert current["gross_pnl_usd"] == 4.95
    assert current["net_pnl_usd"] == 4.95
    assert result["warnings"][0]["session_id"] == 14


def test_non_paper_ledger_is_refused(ledger):
    session(ledger, 14, dry_run=0)
    with pytest.raises(ValueError, match="non-Paper"):
        repair.repair_database(ledger, "C", apply=True)


def test_store_unknown_defaults_and_new_taker_strategy_are_compatible(ledger):
    session(ledger, 1, up_cost_usd=0, down_cost_usd=0, gross_pnl_usd=-.5, net_pnl_usd=-.5)
    fill(ledger, 1, 1, strategy="maker_mm", note="maker_touch")
    fill(ledger, 2, 1, strategy="maker_flatten_taker", price=.4, notional_usd=2,
         note="flatten_residual bid=0.4")
    with sqlite3.connect(ledger) as c:
        c.execute("ALTER TABLE fills ADD COLUMN execution_side TEXT DEFAULT 'UNKNOWN'")
        c.execute("ALTER TABLE fills ADD COLUMN fee_source TEXT DEFAULT 'historical_unknown'")
        c.execute("ALTER TABLE fills ADD COLUMN slippage_source TEXT DEFAULT 'historical_unknown'")
    repair.repair_database(ledger, "B", apply=True)
    assert row(ledger, "fills", 1)["execution_side"] == "BUY"
    assert row(ledger, "fills", 2)["execution_side"] == "SELL"
    assert row(ledger, "fills", 2)["fee_source"] == "paper_model_v1"
    assert repair.repair_database(ledger, "B", apply=True)["changes"] == []
