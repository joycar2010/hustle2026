"""Read-only Live risk observations from official activity and Polygon state.

No order/signing/withdrawal method is called. A current wallet balance is never
used as a substitute for midnight equity. Indexer lag or unknown cash movements
block new BUYs while the worker continues position reconciliation and exits.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
import re
import threading
import time
from typing import Any
from urllib.parse import urlsplit

import requests

from bot.live_risk import (
    _atomic_json, _baseline_path, _number, _read_json, _wallet, day_start_ts,
    publish_live_risk_snapshot, state_file,
)

API = "https://data-api.polymarket.com/v2/"
PUSD = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
CTF = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
KNOWN_ACTIVITIES = {"TRADE", "REDEEM", "MERGE", "SPLIT", "DEPOSIT", "WITHDRAWAL"}
_refresh_lock = threading.Lock()
_settled_values: dict[tuple[str, int], tuple[int, int, int]] = {}


class AccountingCoverageError(ValueError):
    pass


def _hex(value: Any, name: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]+", value):
        raise AccountingCoverageError(f"invalid Polygon {name}")
    return int(value, 16)


class PolygonReader:
    """Small bounded RPC reader; exception text never contains endpoint secrets."""
    def __init__(self, endpoint: str, *, post=None, timeout: float = 5.):
        if not endpoint:
            raise AccountingCoverageError("Polygon RPC is not configured")
        self.endpoint, self.post, self.timeout = endpoint, post or requests.post, timeout

    def rpc(self, method: str, params: list):
        try:
            response = self.post(self.endpoint, json={"jsonrpc": "2.0", "id": 1,
                                  "method": method, "params": params}, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise AccountingCoverageError(f"Polygon {method} read failed ({type(exc).__name__})") from None
        if not isinstance(payload, dict) or payload.get("error") or "result" not in payload:
            raise AccountingCoverageError(f"Polygon {method} returned no usable result")
        return payload["result"]

    def block(self, number: str | int) -> dict:
        value = self.rpc("eth_getBlockByNumber", [hex(number) if isinstance(number, int) else number, False])
        if not isinstance(value, dict):
            raise AccountingCoverageError("Polygon block is unavailable")
        return {"number": _hex(value.get("number"), "block number"),
                "timestamp": _hex(value.get("timestamp"), "block timestamp"),
                "hash": value.get("hash")}

    def calls(self, requests_: list[tuple[str, str]], block_number: int) -> list[int]:
        if not requests_:
            return []
        if len(requests_) == 1:
            address, data = requests_[0]
            return [_hex(self.rpc("eth_call", [{"to": address, "data": data}, hex(block_number)]), "contract value")]
        output = []
        for start in range(0, len(requests_), 100):
            chunk = requests_[start:start + 100]
            batch = [{"jsonrpc": "2.0", "id": i + 1, "method": "eth_call",
                      "params": [{"to": address, "data": data}, hex(block_number)]}
                     for i, (address, data) in enumerate(chunk)]
            unsupported_batch = False
            try:
                response = self.post(self.endpoint, json=batch, timeout=self.timeout)
                unsupported_batch = response.status_code in (400, 405, 413)
                response.raise_for_status()
                payload = response.json()
            except Exception as exc:
                if not unsupported_batch:
                    raise AccountingCoverageError(f"Polygon batch read failed ({type(exc).__name__})") from None
                payload = None
            if unsupported_batch:
                # Some configured public RPCs support plain eth_call but
                # reject JSON-RPC batch envelopes. Bound concurrency instead
                # of treating batch support as permission to bypass checks.
                def single(pair):
                    address, data = pair
                    return _hex(self.rpc("eth_call", [{"to": address, "data": data}, hex(block_number)]), "contract value")
                with ThreadPoolExecutor(max_workers=6) as pool:
                    output.extend(pool.map(single, chunk))
                continue
            if not isinstance(payload, list) or len(payload) != len(batch):
                raise AccountingCoverageError("Polygon batch read is incomplete")
            indexed = {row.get("id"): row for row in payload if isinstance(row, dict)}
            if len(indexed) != len(batch):
                raise AccountingCoverageError("Polygon batch read has duplicate/missing identities")
            for i in range(1, len(batch) + 1):
                row = indexed.get(i) or {}
                if row.get("error"):
                    raise AccountingCoverageError("Polygon historical contract state is unavailable")
                output.append(_hex(row.get("result"), "contract value"))
        return output


class VerifiedPolygonReader:
    """Use read-only fallback RPCs only after chain and block-hash agreement."""
    def __init__(self, endpoint: str):
        endpoints = list(dict.fromkeys([endpoint, "https://polygon-bor-rpc.publicnode.com",
            "https://polygon.drpc.org", "https://1rpc.io/matic"]))
        self.readers = [PolygonReader(url) for url in endpoints if url]
        self.verified = set()
        self.hashes = {}
        self.hash_verified = set()
        self.preferred = 0
        self.sources_used = set()

    def _verify_chain(self, index):
        if index not in self.verified:
            value = self.readers[index].rpc("eth_chainId", [])
            if _hex(value, "chain identity") != 137:
                raise AccountingCoverageError("RPC chain identity is not Polygon 137")
            self.verified.add(index)

    def _note(self, index):
        # Host only: private provider tokens often appear in paths/queries.
        self.sources_used.add(urlsplit(self.readers[index].endpoint).hostname or "configured_rpc")

    def block(self, number):
        for index in [self.preferred] + [i for i in range(len(self.readers)) if i != self.preferred]:
            try:
                self._verify_chain(index)
                block = self.readers[index].block(number)
                known = self.hashes.get(block["number"])
                if not block.get("hash") or (known is not None and block["hash"] != known):
                    raise AccountingCoverageError("Polygon RPC block-hash agreement failed")
                self.hashes[block["number"]] = block["hash"]
                self.hash_verified.add((index, block["number"]))
                self._note(index)
                return block
            except AccountingCoverageError:
                continue
        raise AccountingCoverageError("verified Polygon block state is unavailable from configured/read-only RPCs")

    def calls(self, requests_, block_number):
        if not requests_:
            return []
        if block_number not in self.hashes:
            self.block(block_number)
        expected_hash = self.hashes[block_number]
        for index in [self.preferred] + [i for i in range(len(self.readers)) if i != self.preferred]:
            try:
                self._verify_chain(index)
                if (index, block_number) not in self.hash_verified:
                    block = self.readers[index].block(block_number)
                    if block.get("hash") != expected_hash:
                        raise AccountingCoverageError("fallback Polygon RPC block-hash mismatch")
                    self.hash_verified.add((index, block_number))
                result = self.readers[index].calls(requests_, block_number)
                self.preferred = index
                self._note(index)
                return result
            except AccountingCoverageError:
                continue
        raise AccountingCoverageError("verified Polygon historical contract state is unavailable")


def block_before_midnight(reader: PolygonReader, start: float, latest: dict) -> dict:
    """Find the last block strictly before the Beijing day, not a later sample."""
    if latest["timestamp"] < start:
        raise AccountingCoverageError("Polygon latest block precedes the current Beijing day")
    high = latest["number"]
    distance = max(64, int((latest["timestamp"] - start) * 1.3) + 32)
    low = max(0, high - distance)
    low_block = reader.block(low)
    while low_block["timestamp"] >= start:
        if low == 0:
            raise AccountingCoverageError("could not bracket Beijing midnight block")
        distance *= 2
        low = max(0, high - distance)
        low_block = reader.block(low)
    while high - low > 1:
        middle = (low + high) // 2
        block = reader.block(middle)
        if block["timestamp"] < start:
            low, low_block = middle, block
        else:
            high = middle
    return low_block


def _pages(endpoint: str, params: dict, *, get=None, timeout=6., max_pages=50) -> list[dict]:
    fetch = get or requests.get
    rows, cursors = [], set()
    params = dict(params)
    for _ in range(max_pages):
        try:
            response = fetch(API + endpoint, params=params, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise AccountingCoverageError(f"official {endpoint} read failed ({type(exc).__name__})") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise AccountingCoverageError(f"official {endpoint} page is invalid")
        batch = payload["data"]
        if any(not isinstance(row, dict) for row in batch):
            raise AccountingCoverageError(f"official {endpoint} contains an invalid row")
        rows.extend(batch)
        pagination = payload.get("pagination") or {}
        if not isinstance(pagination, dict):
            raise AccountingCoverageError(f"official {endpoint} pagination is invalid")
        more = payload.get("has_more", pagination.get("has_more"))
        cursor = payload.get("next_cursor") or pagination.get("next_cursor")
        if more is False or (more is None and not cursor):
            return rows
        if not batch or not cursor or cursor in cursors:
            raise AccountingCoverageError(f"official {endpoint} history is incomplete")
        cursors.add(cursor)
        params["cursor"] = cursor
    raise AccountingCoverageError(f"official {endpoint} history exceeded pagination bound")


def read_account_inputs(wallet: str, *, get=None) -> tuple[list[dict], list[dict]]:
    """Retain CLOSED dust; no 0.1-share display filter is allowed in risk."""
    with ThreadPoolExecutor(max_workers=4) as pool:
        activity = pool.submit(_pages, "activity", {
            "user": wallet, "limit": 500, "exclude_deposits_withdrawals": "false",
            "sort_by": "TIMESTAMP", "sort_direction": "DESC"}, get=get)
        futures = [pool.submit(_pages, "positions", {
            "user": wallet, "status": status, "limit": 500,
            **({"include_archived": "true"} if status != "CLOSED" else {}),
            "sort_by": "TIMESTAMP", "sort_direction": "DESC"}, get=get)
            for status in ("OPEN", "REDEEMABLE", "CLOSED")]
        return activity.result(), [row for future in futures for row in future.result()]


def _cash_balance_call(wallet: str) -> tuple[str, str]:
    return PUSD, "0x70a08231" + wallet[2:].rjust(64, "0")


def _token_balance_call(wallet: str, token: str) -> tuple[str, str]:
    return CTF, "0x00fdd58e" + wallet[2:].rjust(64, "0") + format(int(token), "064x")


def _position_identity(row: dict) -> tuple[str, dict] | None:
    token = str(row.get("token_id") or row.get("tokenId") or "")
    condition = str(row.get("condition_id") or row.get("conditionId") or "")
    if not token.isdigit() or not re.fullmatch(r"0x[0-9a-fA-F]{64}", condition):
        return None
    index = row.get("outcome_index")
    return token, {"condition_id": condition.lower(), "outcome_index": index,
                   "slug": row.get("slug") or row.get("market_slug"), "source": row}


def candidate_tokens(positions: list[dict], activity: list[dict], start: float) -> dict[str, dict]:
    tokens = {}
    for row in positions:
        item = _position_identity(row)
        if item is None:
            raise AccountingCoverageError("official position identity is incomplete")
        size = _number(row.get("current_size", row.get("size")), "official current shares", minimum=0.)
        if size > 0:
            tokens[item[0]] = item[1]
    for row in activity:
        ts = _number(row.get("timestamp"), "official activity timestamp", minimum=0.)
        if ts >= start and str(row.get("type") or "").upper() in {"TRADE", "REDEEM", "MERGE", "SPLIT"}:
            item = _position_identity(row)
            if item is None:
                raise AccountingCoverageError("official activity token identity is incomplete")
            prior = tokens.get(item[0], {})
            tokens[item[0]] = {**prior, **item[1]}
    return tokens


def _marks(reader: PolygonReader, wallet: str, tokens: dict[str, dict], block: dict,
           *, historical=False, get=None, clob_host="https://clob.polymarket.com") -> tuple[float, dict]:
    """Value exact contract-held shares; confirmed payout is authoritative."""
    ids = list(tokens)
    amounts = reader.calls([_token_balance_call(wallet, token) for token in ids], block["number"])
    held = {token: amount for token, amount in zip(ids, amounts) if amount > 0}
    details, total = {}, 0.
    # Denominator/numerator values are queried in the *same* snapshot block.
    conditions = {}
    for token in held:
        meta = tokens[token]
        condition, index = meta["condition_id"], meta.get("outcome_index")
        if isinstance(index, bool) or index is None or int(index) < 0:
            raise AccountingCoverageError("held token has no verified outcome index")
        index = int(index)
        if index > 255:
            raise AccountingCoverageError("invalid held outcome index")
        conditions[(condition, index)] = None
    keys = [key for key in conditions if key not in _settled_values
            or _settled_values[key][0] > block["number"]]
    calls = []
    for condition, index in keys:
        calls.extend([(CTF, "0xdd34de67" + condition[2:]),
                      (CTF, "0x0504c814" + condition[2:] + format(index, "064x"))])
    payouts = reader.calls(calls, block["number"])
    fetched = {key: (payouts[i * 2], payouts[i * 2 + 1]) for i, key in enumerate(keys)}
    for key, (denominator, numerator) in fetched.items():
        if denominator > 0:
            _settled_values[key] = (block["number"], denominator, numerator)
    conditions = {key: fetched[key] if key in fetched else _settled_values[key][1:]
                  for key in conditions}
    fetch = get or requests.get
    for token, raw in held.items():
        meta = tokens[token]
        denominator, numerator = conditions[(meta["condition_id"], int(meta["outcome_index"]))]
        if denominator > 0:
            price = numerator / denominator
            source = "polygon_ctf_confirmed_payout"
            mark_as_of = block["timestamp"]
        elif historical:
            # A current mark may not be backdated to midnight. Require an
            # official observed historical price at/before the boundary.
            try:
                response = fetch(clob_host.rstrip("/") + "/prices-history", params={
                    "market": token, "startTs": block["timestamp"] - 120,
                    "endTs": block["timestamp"] + 1, "fidelity": 1}, timeout=5)
                response.raise_for_status()
                payload = response.json()
                points = [point for point in payload.get("history", []) if isinstance(point, dict)
                          and block["timestamp"] - 60 <= float(point.get("t", 0)) <= block["timestamp"]]
                point = max(points, key=lambda point: float(point["t"]))
                price = _number(point.get("p"), "historical position price", minimum=0.)
                mark_as_of = float(point["t"])
                source = "official_clob_last_observed_pre_midnight_price"
            except Exception:
                raise AccountingCoverageError("cross-midnight holding has no verified historical valuation") from None
        else:
            try:
                response = fetch(clob_host.rstrip("/") + "/book", params={"token_id": token}, timeout=5)
                response.raise_for_status()
                payload = response.json()
                bids = payload.get("bids")
                if not isinstance(bids, list):
                    raise ValueError("book bids absent")
                price = max((float(item["price"]) for item in bids if float(item.get("size", 0)) > 0), default=0.)
                book_ts = float(payload.get("timestamp") or 0.)
                book_ts = book_ts / 1000 if book_ts > 1e11 else book_ts
                if not book_ts or abs(book_ts - block["timestamp"]) > 20:
                    raise ValueError("book valuation timestamp missing or stale")
                mark_as_of, source = book_ts, "official_clob_current_best_bid"
            except Exception:
                raise AccountingCoverageError("unresolved holding has no fresh executable valuation") from None
        if not math.isfinite(price) or not 0 <= price <= 1:
            raise AccountingCoverageError("invalid position valuation")
        value = raw / 1e6 * price
        total += value
        details[token] = {"shares": raw / 1e6, "price": price, "value_usd": value,
                          "source": source, "mark_as_of": mark_as_of,
                          "condition_id": meta["condition_id"], "settled": denominator > 0}
    return total, details


def period_flows(activity: list[dict], wallet: str, start: float, end: float) -> tuple[float, float, int]:
    """Return fee-inclusive trading cashflow, net external funding and count."""
    trading, funding, count, seen = 0., 0., 0, set()
    for row in activity:
        ts = _number(row.get("timestamp"), "official activity timestamp", minimum=0.)
        if not start <= ts <= end:
            continue
        owner = str(row.get("proxy_wallet") or wallet).lower()
        if owner != wallet:
            raise AccountingCoverageError("official account history wallet mismatch")
        status = str(row.get("status") or "CONFIRMED").upper()
        if any(part in status for part in ("PENDING", "FAIL", "CANCEL", "REJECT", "UNCONFIRMED")):
            continue
        key = json.dumps(row, sort_keys=True, separators=(",", ":"))
        if key in seen:
            continue
        seen.add(key)
        kind = str(row.get("type") or "").upper()
        if kind not in KNOWN_ACTIVITIES:
            raise AccountingCoverageError(f"unknown account cash activity type: {kind[:32]}")
        amount = _number(row.get("usdc_size", row.get("usdcSize")), "actual activity cashflow", minimum=0.)
        count += 1
        if kind == "DEPOSIT":
            funding += amount
        elif kind == "WITHDRAWAL":
            funding -= amount
        elif kind in {"REDEEM", "MERGE"}:
            trading += amount
        elif kind == "SPLIT":
            trading -= amount
        else:
            side = str(row.get("side") or "").upper()
            if side not in {"BUY", "SELL"}:
                raise AccountingCoverageError("official trade cash direction is invalid")
            trading += amount if side == "SELL" else -amount
    return trading, funding, count


def collect_live_observation(cfg, *, now: float | None = None, path: str | Path | None = None,
                             reader: PolygonReader | None = None, get=None) -> dict:
    """Read complete account inputs and verify them against actual cash state."""
    now = time.time() if now is None else now
    wallet, start = _wallet(cfg), day_start_ts(now)
    target = state_file(path)
    polygon = reader or VerifiedPolygonReader(str(getattr(cfg, "polygon_rpc", "")))
    latest = polygon.block("latest")
    if not -3 <= now - latest["timestamp"] <= 20:
        raise AccountingCoverageError("Polygon latest block is stale")
    activity, positions = read_account_inputs(wallet, get=get)
    tokens = candidate_tokens(positions, activity, start)
    try:
        baseline = _read_json(_baseline_path(target, wallet, start))
    except FileNotFoundError:
        baseline = None
    evidence = (baseline or {}).get("baseline_evidence")
    if not isinstance(evidence, dict) or evidence.get("day_start_cash_usd") is None:
        midnight = block_before_midnight(polygon, start, latest)
        base_cash = polygon.calls([_cash_balance_call(wallet)], midnight["number"])[0] / 1e6
        base_positions, base_details = _marks(polygon, wallet, tokens, midnight,
            historical=True, get=get, clob_host=str(getattr(cfg, "clob_host", "https://clob.polymarket.com")))
        capital = base_cash + base_positions
        evidence = {"source": "polygon_pre_midnight_contract_state",
                    "block_number": midnight["number"], "block_hash": midnight.get("hash"),
                    "block_timestamp": midnight["timestamp"], "day_start_cash_usd": base_cash,
                    "day_start_position_value_usd": base_positions, "positions": base_details}
        if baseline is not None and abs(capital - float(baseline["day_start_equity_usd"])) > 1e-6:
            raise AccountingCoverageError("reconstructed midnight capital conflicts with frozen baseline")
        # Building historical proof can take longer than the live freshness
        # budget. Persist only this verified historical baseline now; the
        # independent current observation can remain blocked until the next
        # short refresh. Never substitute a newer wallet value on retry.
        if capital <= 0:
            raise AccountingCoverageError("verified midnight account equity is not positive")
        base_document = dict(baseline or {})
        base_document.update(schema_version=1, wallet=wallet, day_start_ts=start,
            day_start_equity_usd=capital, baseline_as_of=evidence["block_timestamp"],
            baseline_source="polygon_pre_midnight_cash_plus_verified_holdings",
            baseline_evidence=evidence)
        base_document.setdefault("frozen_at", time.time())
        _atomic_json(_baseline_path(target, wallet, start), base_document)
    else:
        capital = _number(baseline["day_start_equity_usd"], "persisted midnight equity", minimum=0.)
        base_cash = _number(evidence["day_start_cash_usd"], "persisted midnight cash", minimum=0.)
    cash = polygon.calls([_cash_balance_call(wallet)], latest["number"])[0] / 1e6
    trading, funding, activity_count = period_flows(activity, wallet, start, latest["timestamp"])
    cash_difference = cash - base_cash - trading - funding
    # USD fields carry six decimal precision. Do not paper over a missing fill,
    # stale indexer, pending activation or an unclassified external transfer.
    if abs(cash_difference) > 0.0001:
        raise AccountingCoverageError(f"official activity and Polygon cash are not synchronized (difference ${cash_difference:.6f})")
    position_value, current_details = _marks(polygon, wallet, tokens, latest, get=get,
        clob_host=str(getattr(cfg, "clob_host", "https://clob.polymarket.com")))
    completed = time.time() if now is None else now
    if completed - latest["timestamp"] > 20:
        raise AccountingCoverageError("accounting collection exceeded freshness window")
    return {
        "wallet": wallet, "day_start_ts": start, "as_of": latest["timestamp"],
        "equity_usd": cash + position_value, "cash_usd": cash,
        "position_value_usd": position_value, "external_net_flow_usd": funding,
        "activity_complete": True, "funding_complete": True, "valuation_complete": True,
        "baseline_complete": True, "day_start_equity_usd": capital,
        "baseline_as_of": evidence["block_timestamp"],
        "baseline_source": "polygon_pre_midnight_cash_plus_verified_holdings",
        "baseline_evidence": evidence,
        "open_positions_count": sum(not row["settled"] for row in current_details.values()),
        "current_positions": current_details,
        "cash_reconciliation_difference_usd": cash_difference,
        "period_trading_cashflow_usd": trading, "activity_count": activity_count,
        "snapshot_block": latest["number"], "snapshot_block_hash": latest.get("hash"),
        "rpc_sources": sorted(getattr(polygon, "sources_used", [])),
        "valuation_source": "Polygon balances and resolved payouts; fresh CLOB bid for unresolved",
    }


def refresh_live_risk(cfg, client=None, *, now: float | None = None,
                      path: str | Path | None = None, reader=None, get=None) -> dict:
    """Background worker API. ``client`` is accepted but never signs anything."""
    query_now = time.time() if now is None else now
    with _refresh_lock:
        try:
            observation = collect_live_observation(cfg, now=query_now, path=path, reader=reader, get=get)
        except Exception as exc:
            # No raw HTTP exception text: configured RPC URLs may contain keys.
            safe = str(exc) if isinstance(exc, AccountingCoverageError) else type(exc).__name__
            observation = {"wallet": _wallet(cfg), "day_start_ts": day_start_ts(query_now),
                           "as_of": query_now, "error": safe,
                           "activity_complete": False, "funding_complete": False,
                           "valuation_complete": False}
        # Publication time is actual completion in production, not an earlier
        # poll-start time that could make a lengthy RPC read appear fresh.
        publication_now = time.time() if now is None else now
        return publish_live_risk_snapshot(cfg, observation, now=publication_now, path=path)
