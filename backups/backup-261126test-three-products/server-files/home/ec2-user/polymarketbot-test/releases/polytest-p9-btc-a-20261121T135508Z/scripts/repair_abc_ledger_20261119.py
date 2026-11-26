#!/usr/bin/env python3
"""Audited, repeatable repair of *Paper* B/C ledgers; dry-run is the default.

No production path is implicit. Every invocation first takes a consistent SQLite
backup, including WAL contents, and validates it. --apply uses one transaction per
database; stop the corresponding worker before applying. This script never
imports Store/Engine, deletes history, infers a settlement winner from BTC prices,
or invents historical slippage. Fees added to B are explicitly Paper estimates.

Examples:
  python scripts/repair_abc_ledger_20261119.py --c-db copy.db --official-json audit.json
  python scripts/repair_abc_ledger_20261119.py --b-db copy.db --apply
  python scripts/repair_abc_ledger_20261119.py --c-db copy.db --fetch-official --apply
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import math
import sqlite3
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

REVISION = "paper-ledger-20261119-v1"
EPSILON = 1e-7
FILL_COLUMNS = {
    "execution_side": "TEXT",
    "fee_source": "TEXT",
    "slippage_source": "TEXT",
}
SESSION_COLUMNS = {
    "resolution_source": "TEXT",
    "accounting_original_gross_pnl_usd": "REAL",
    "accounting_original_net_pnl_usd": "REAL",
    "accounting_corrected_ts": "REAL",
}


def number(value: Any) -> float:
    result = float(value or 0.0)
    if not math.isfinite(result):
        raise ValueError("non-finite ledger amount")
    return result


def equivalent(a: Any, b: Any) -> bool:
    if isinstance(a, (float, int)) and isinstance(b, (float, int)):
        return math.isclose(float(a), float(b), abs_tol=1e-10, rel_tol=1e-12)
    return a == b


def connect(path: Path, *, writable: bool = False) -> sqlite3.Connection:
    # mode=rw must not silently create a database at a misspelled path.
    conn = sqlite3.connect(path.resolve().as_uri() + ("?mode=rw" if writable else "?mode=ro"), uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def validate_database(conn: sqlite3.Connection) -> None:
    result = conn.execute("PRAGMA quick_check").fetchone()[0]
    if result != "ok":
        raise ValueError(f"SQLite validation failed: {result}")
    required = {"maker_sessions", "fills", "events"}
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not required <= tables:
        raise ValueError("database lacks the expected Paper tables")


def snapshot(path: Path, directory: Path | None = None) -> Path:
    directory = directory or path.parent / "ledger-repair-backups"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    target = directory / f"{path.stem}.{stamp}.{uuid.uuid4().hex[:8]}.sqlite3"
    with closing(connect(path)) as source, closing(sqlite3.connect(target)) as dest:
        source.backup(dest)
        validate_database(dest)
    target.chmod(0o600)
    return target


def _decoded(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def official_result(data: dict[str, Any]) -> str:
    """Accept finalized binary outcomes only, never a high market quote."""
    if data.get("closed") is not True:
        raise ValueError("official result is not closed")
    if str(data.get("umaResolutionStatus", "")).lower() != "resolved":
        raise ValueError("official result is not resolved")
    outcomes = [str(v).upper() for v in _decoded(data.get("outcomes", []))]
    prices = [number(v) for v in _decoded(data.get("outcomePrices", []))]
    if set(outcomes) != {"UP", "DOWN"} or len(prices) != 2 or len(outcomes) != 2:
        raise ValueError("unsupported official outcome structure")
    if not (math.isclose(max(prices), 1, abs_tol=1e-8) and math.isclose(min(prices), 0, abs_tol=1e-8)):
        raise ValueError("official outcome prices are not finalized 1/0")
    winner = outcomes[prices.index(max(prices))]
    if data.get("official") and str(data["official"]).upper() != winner:
        raise ValueError("official evidence contradicts its outcome prices")
    return winner


def load_evidence(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    rows = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(rows, dict):
        rows = rows.get("records", rows.get("rows"))
    if not isinstance(rows, list):
        raise ValueError("official JSON must contain an array of evidence records")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        slug = row.get("slug") or row.get("market_slug")
        if not slug or slug in result:
            raise ValueError("missing or duplicate market slug in official evidence")
        official_result(row)
        result[slug] = row
    return result


def fetch_evidence(slug: str, host: str) -> dict[str, Any]:
    url = host.rstrip("/") + "/events/slug/" + urllib.parse.quote(slug, safe="")
    with urllib.request.urlopen(url, timeout=15) as response:
        event = json.load(response)
    markets = event.get("markets") or []
    matches = [m for m in markets if m.get("slug") == slug]
    if len(matches) != 1:
        raise ValueError("official response lacks exactly one matching market")
    data = dict(matches[0], slug=slug, evidence_url=url, fetched_at=time.time())
    official_result(data)
    return data


def _change(table: str, row: dict[str, Any], values: dict[str, Any], reason: str, **context: Any) -> dict[str, Any] | None:
    after = {k: v for k, v in values.items() if not equivalent(row.get(k), v)}
    if not after:
        return None
    return {"table": table, "id": row["id"], "market_slug": row["market_slug"],
            "before": row, "after": after, "reason": reason, "context": context}


def _annotate_fill(fill: dict[str, Any], mode: str, fee_rate: float) -> dict[str, Any]:
    note = str(fill.get("note") or "")
    action = fill.get("execution_side")
    if str(action or "").upper() == "UNKNOWN":
        action = None
    flatten = note.startswith("flatten_residual") or fill.get("strategy") == "maker_flatten_taker"
    unknown_fee_source = fill.get("fee_source") in {None, "", "historical_unknown"}
    if mode == "C":
        action = "SELL"  # split_sell mints inventory and every CLOB fill sells it.
    elif flatten:
        action = "SELL"
    elif not action:
        action = "BUY"
    if action not in {"BUY", "SELL"}:
        raise ValueError(f"unsupported execution side on fill {fill['id']}")
    values: dict[str, Any] = {"execution_side": action}
    if not fill.get("slippage_source"):
        values["slippage_source"] = "historical_unknown"
    if mode == "B" and flatten:
        values["liquidity"] = "taker"
        old_fee = number(fill["fee_usd"])
        if old_fee == 0 and not (fill.get("fee_source") or "").startswith("paper_model"):
            p = number(fill["price"])
            values["fee_usd"] = fee_rate * p * (1 - p) * number(fill["size"])
            values["fee_source"] = "paper_model_v1"
        elif unknown_fee_source:
            values["fee_source"] = "historical_recorded_paper"
    elif unknown_fee_source:
        values["fee_source"] = ("paper_maker_zero" if fill["liquidity"] == "maker" and number(fill["fee_usd"]) == 0
                                else "historical_recorded_paper")
    return values


def build_plan(conn: sqlite3.Connection, mode: str, evidence: dict[str, dict[str, Any]], *, fee_rate: float = 0.07) -> dict[str, Any]:
    validate_database(conn)
    sessions = [dict(r) for r in conn.execute("SELECT * FROM maker_sessions ORDER BY id")]
    changes: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    summary = {"closed": 0, "open_skipped": 0, "winner_changes": 0, "redeem_delta": 0.0,
               "net_delta": 0.0, "fee_delta": 0.0, "gross_delta": 0.0,
               "estimated_rebate_excluded": 0.0, "official_verified": 0}
    for row in sessions:
        if row["status"] != "closed":
            summary["open_skipped"] += 1
            continue
        if int(row["dry_run"]) != 1:
            raise ValueError("refusing a ledger containing non-Paper closed sessions")
        summary["closed"] += 1
        fills = [dict(f) for f in conn.execute("SELECT * FROM fills WHERE session_id=? ORDER BY id", (row["id"],))]
        expected_strategies = {"split_sell"} if mode == "C" else {"maker_mm", "maker_flatten_taker"}
        updated_fills: list[dict[str, Any]] = []
        for fill in fills:
            if int(fill["dry_run"]) != 1 or fill["strategy"] not in expected_strategies or fill["market_slug"] != row["market_slug"]:
                raise ValueError(f"unexpected fill belongs to session {row['id']}")
            if fill["side"] not in {"UP", "DOWN"} or not 0 <= number(fill["price"]) <= 1 or number(fill["size"]) <= 0:
                raise ValueError(f"invalid fill values: {fill['id']}")
            if abs(number(fill["notional_usd"]) - number(fill["size"]) * number(fill["price"])) > EPSILON:
                raise ValueError(f"fill notional disagrees with price/size: {fill['id']}")
            values = _annotate_fill(fill, mode, fee_rate)
            change = _change("fills", fill, values, "classify Paper execution and historical fee provenance", fee_rate=fee_rate)
            if change:
                changes.append(change)
            updated_fills.append(dict(fill, **values))
        gross = number(row["gross_pnl_usd"])
        old_fee = number(row["fee_usd"])
        fee = old_fee
        values = {}
        context: dict[str, Any] = {"net_policy": "gross_minus_fees_excludes_estimated_rebate",
                                  "slippage_policy": "embedded_in_fill_price_if_recorded_otherwise_unknown"}
        if mode == "C":
            proof = evidence.get(row["market_slug"])
            if proof is not None:
                if proof.get("id") is not None and int(proof["id"]) != int(row["id"]):
                    raise ValueError("official evidence session ID disagrees with matching slug")
                winner = official_result(proof)
                mint = number(row["up_cost_usd"]) + number(row["down_cost_usd"])
                sold = {side: sum(number(f["size"]) for f in updated_fills if f["side"] == side) for side in ("UP", "DOWN")}
                proceeds = {side: sum(number(f["notional_usd"]) for f in updated_fills if f["side"] == side) for side in ("UP", "DOWN")}
                merged = number(row["merged_shares"])
                merge_proceeds = number(row["merge_proceeds_usd"])
                if abs(merged - merge_proceeds) > EPSILON:
                    raise ValueError(f"session {row['id']} has inconsistent persisted merge cashflow; do not guess")
                for side, field in (("UP", "up_proceeds_usd"), ("DOWN", "down_proceeds_usd")):
                    if abs(number(row[field]) - proceeds[side]) > EPSILON:
                        raise ValueError(f"session {row['id']} has inconsistent persisted sell cashflow")
                remaining = {side: mint - sold[side] - merged for side in ("UP", "DOWN")}
                if any(n < -EPSILON for n in remaining.values()):
                    raise ValueError(f"session {row['id']} overconsumed minted inventory")
                for field, actual in (("sold_up", sold["UP"]), ("sold_down", sold["DOWN"]), ("merged", merged),
                                      ("up_proceeds", proceeds["UP"]), ("dn_proceeds", proceeds["DOWN"])):
                    if field in proof and abs(number(proof[field]) - actual) > EPSILON:
                        raise ValueError(f"session {row['id']} has stale evidence cashflow {field}")
                redeem = max(remaining[winner], 0.0)
                # Split proceeds already include flatten sales. Do NOT add flatten_pnl again.
                gross = proceeds["UP"] + proceeds["DOWN"] + merge_proceeds + redeem - mint
                summary["official_verified"] += 1
                summary["winner_changes"] += int(row.get("winner") != winner)
                summary["redeem_delta"] += redeem - number(row["redeem_proceeds_usd"])
                values.update(winner=winner, redeem_proceeds_usd=redeem, gross_pnl_usd=gross,
                              resolution_source="official_gamma_verified")
                context["official_evidence"] = proof
                context["official_evidence_sha256"] = hashlib.sha256(json.dumps(proof, sort_keys=True).encode()).hexdigest()
            elif fills:
                warnings.append({"session_id": row["id"], "slug": row["market_slug"],
                                 "reason": "official evidence missing; winner/redeem/gross preserved"})
            # C historical recorded fees remain recorded; do not manufacture old slippage.
            if abs(sum(number(f["fee_usd"]) for f in updated_fills) - old_fee) > EPSILON:
                raise ValueError(f"session {row['id']} fill/session fees disagree")
        else:
            # Gross already includes the earlier -$6 flatten correction. Never add it again.
            fill_fee_before = sum(number(f["fee_usd"]) for f in fills)
            if abs(fill_fee_before - old_fee) > EPSILON:
                raise ValueError(f"B session {row['id']} has unmatched preexisting session fees")
            fee = sum(number(f["fee_usd"]) for f in updated_fills)
            values.update(fee_usd=fee,
                          up_fee_usd=sum(number(f["fee_usd"]) for f in updated_fills if f["side"] == "UP"),
                          down_fee_usd=sum(number(f["fee_usd"]) for f in updated_fills if f["side"] == "DOWN"))
            context["gross_policy"] = "preserve_existing_flatten_accounting_correction"
        net = gross - fee
        values["net_pnl_usd"] = net
        # Estimated rebates are retained in their own field, never treated as received cash.
        context["net_including_estimated_rebate_for_comparison"] = net + number(row.get("rebate_est_usd"))
        financial_change = any(not equivalent(row.get(k), v) for k, v in values.items()
                               if k in {"gross_pnl_usd", "net_pnl_usd", "fee_usd", "redeem_proceeds_usd"})
        if financial_change:
            values["accounting_original_gross_pnl_usd"] = row.get("accounting_original_gross_pnl_usd") if row.get("accounting_original_gross_pnl_usd") is not None else row.get("gross_pnl_usd")
            values["accounting_original_net_pnl_usd"] = row.get("accounting_original_net_pnl_usd") if row.get("accounting_original_net_pnl_usd") is not None else row.get("net_pnl_usd")
            values["accounting_corrected_ts"] = time.time()
        summary["net_delta"] += net - number(row["net_pnl_usd"])
        summary["fee_delta"] += fee - old_fee
        summary["gross_delta"] += gross - number(row["gross_pnl_usd"])
        summary["estimated_rebate_excluded"] += number(row.get("rebate_est_usd"))
        change = _change("maker_sessions", row, values, "official settlement and cash-only Paper net PnL", **context)
        if change:
            changes.append(change)
    return {"revision": REVISION, "mode": mode, "summary": summary, "warnings": warnings, "changes": changes}


def ensure_columns(conn: sqlite3.Connection) -> None:
    for table, declarations in (("fills", FILL_COLUMNS), ("maker_sessions", SESSION_COLUMNS)):
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, declaration in declarations.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


def apply_plan(conn: sqlite3.Connection, plan: dict[str, Any]) -> None:
    ensure_columns(conn)
    for change in plan["changes"]:
        table = change["table"]
        current = dict(conn.execute(f"SELECT * FROM {table} WHERE id=?", (change["id"],)).fetchone())
        if any(not equivalent(current[k], v) for k, v in change["before"].items()):
            raise ValueError("ledger changed after plan creation; rebuild from a fresh snapshot")
        values = change["after"]
        assignments = ", ".join(k + "=?" for k in values)
        conn.execute(f"UPDATE {table} SET {assignments} WHERE id=?", (*values.values(), change["id"]))
        event = dict(change, revision=REVISION, source="scripts/repair_abc_ledger_20261119.py")
        conn.execute("INSERT INTO events(ts,kind,market_slug,payload) VALUES(?,?,?,?)",
                     (time.time(), "paper_ledger_repair", change["market_slug"], json.dumps(event, ensure_ascii=False)))


def repair_database(path: Path, mode: str, evidence: dict[str, dict[str, Any]] | None = None, *,
                    apply: bool = False, backup_dir: Path | None = None, fee_rate: float = 0.07,
                    fetch_official: bool = False, gamma_host: str = "https://gamma-api.polymarket.com") -> dict[str, Any]:
    if mode not in {"B", "C"} or not math.isfinite(fee_rate) or fee_rate < 0:
        raise ValueError("invalid mode or fee rate")
    evidence = dict(evidence or {})
    # Resolve remote evidence before taking an apply lock. Only finalized sessions are fetched.
    if mode == "C" and fetch_official:
        with closing(connect(path)) as read:
            slugs = [r[0] for r in read.execute("SELECT DISTINCT s.market_slug FROM maker_sessions s JOIN fills f ON f.session_id=s.id WHERE s.status='closed' AND s.dry_run=1")]
        for slug in slugs:
            evidence[slug] = fetch_evidence(slug, gamma_host)
    with closing(connect(path, writable=apply)) as conn:
        if apply:
            conn.execute("BEGIN IMMEDIATE")
        try:
            # A separate reader can back up while our reserved write lock prevents worker writes.
            backup = snapshot(path, backup_dir)
            if apply:
                plan = build_plan(conn, mode, evidence, fee_rate=fee_rate)
            else:
                with closing(connect(backup)) as read:
                    plan = build_plan(read, mode, evidence, fee_rate=fee_rate)
            if apply:
                counts_before = {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("fills", "maker_sessions")}
                apply_plan(conn, plan)
                for t, n in counts_before.items():
                    if conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] != n:
                        raise ValueError("repair unexpectedly changed the number of ledger rows")
                validate_database(conn)
                # A second plan must be empty, which catches incomplete fee/session synchronization.
                recheck = build_plan(conn, mode, evidence, fee_rate=fee_rate)
                if recheck["changes"]:
                    raise ValueError("repair is not idempotent; transaction rolled back")
                conn.commit()
            return dict(plan, applied=apply, backup=str(backup), database=str(path.resolve()))
        except BaseException:
            if apply:
                conn.rollback()
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--c-db", type=Path)
    parser.add_argument("--b-db", type=Path)
    parser.add_argument("--official-json", type=Path)
    parser.add_argument("--fetch-official", action="store_true")
    parser.add_argument("--gamma-host", default="https://gamma-api.polymarket.com")
    parser.add_argument("--fee-rate", type=float, default=0.07, help="Paper model coefficient; not a claim of actual historical exchange fees")
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--apply", action="store_true", help="Explicitly apply; otherwise only a backup and dry-run report are produced")
    parser.add_argument("--report", type=Path, help="Write the complete per-row original/changed values and evidence")
    args = parser.parse_args()
    if not args.c_db and not args.b_db:
        parser.error("at least one explicit --c-db or --b-db is required")
    evidence = load_evidence(args.official_json)
    results = []
    for mode, path in (("C", args.c_db), ("B", args.b_db)):
        if path:
            results.append(repair_database(path, mode, evidence, apply=args.apply, backup_dir=args.backup_dir,
                                           fee_rate=args.fee_rate, fetch_official=args.fetch_official, gamma_host=args.gamma_host))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        args.report.chmod(0o600)
    print(json.dumps([{k: v for k, v in r.items() if k != "changes"} | {"changed_rows": len(r["changes"])} for r in results], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
