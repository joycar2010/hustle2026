"""Shared, fee-inclusive Live daily entry gates; never stop exits/settlement.

Only the Live worker publishes observations. The dashboard reads the same
document and recomputes limits from the currently saved configuration. A
missing or stale observation blocks BUY admission, not position management.
No credential or signing information is stored in these files.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any

BEIJING = timezone(timedelta(hours=8))
DEFAULT_MAX_AGE_SEC = 20.0
SCHEMA_VERSION = 1


def day_start_ts(now: float) -> float:
    local = datetime.fromtimestamp(now, BEIJING)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def state_file(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    configured = os.environ.get("LIVE_RISK_STATE_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    # Avoid release-directory-local state when the ledger already lives in
    # the shared instance data directory.
    from bot import store
    return Path(store.DB_PATH).with_name("live-risk.json")


def _wallet(cfg) -> str:
    wallet = str(getattr(cfg, "deposit_wallet_address", "") or getattr(cfg, "funder_address", "")).lower()
    if not re.fullmatch(r"0x[0-9a-f]{40}", wallet):
        raise ValueError("Live account wallet is invalid")
    return wallet


def _number(value: Any, name: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"missing or invalid {name}")
    result = float(value)
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise ValueError(f"missing or invalid {name}")
    return result


def _limits(cfg) -> tuple[float, float, str]:
    loss = _number(getattr(cfg, "max_daily_loss_fraction", None), "daily loss fraction", minimum=0.)
    profit = _number(getattr(cfg, "max_daily_realized_profit_fraction", None), "daily profit fraction", minimum=0.)
    if loss > 1 or profit > 1:
        raise ValueError("daily fractions must be between 0 and 1")
    # The old $12 setting must not silently override or re-enable a disabled
    # percentage target. A deliberate configuration change is visible in the
    # policy fingerprint; a restart with unchanged config cannot clear a halt.
    policy = hashlib.sha256(json.dumps([loss, profit], separators=(",", ":")).encode()).hexdigest()[:16]
    return loss, profit, policy


def _baseline_path(path: Path, wallet: str, start: float) -> Path:
    day = datetime.fromtimestamp(start, BEIJING).strftime("%Y-%m-%d")
    return path.with_name(f"{path.stem}.{wallet}.{day}.baseline.json")


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Live accounting document is not an object")
    return value


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
            tmp = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def _unknown(cfg, now: float, reason: str) -> dict:
    try:
        loss, profit, policy = _limits(cfg)
    except (ValueError, TypeError):
        loss, profit, policy = None, None, None
    return {
        "schema_version": SCHEMA_VERSION, "mode": "live", "asset": "BTC",
        "available": False, "allow_entries": False, "state": "ACCOUNTING_UNAVAILABLE",
        "entry_block_reason": reason, "circuit_reason": reason,
        "day_start_ts": day_start_ts(now), "resume_ts": day_start_ts(now) + 86400,
        "max_daily_loss_fraction": loss, "max_daily_realized_profit_fraction": profit,
        "policy_fingerprint": policy, "capital_base_usd": None,
        "daily_net_pnl_usd": None, "daily_realized_usd": None,
        "daily_loss_limit_usd": None, "daily_profit_target_usd": None,
        "daily_profit_rate": None, "source": "live_account_equity",
        "updated_at": now, "requires_fresh_accounting": True,
    }


def build_live_risk_snapshot(cfg, observation: dict, *, now: float | None = None,
                             baseline: dict | None = None,
                             max_age_sec: float = DEFAULT_MAX_AGE_SEC) -> dict:
    """Evaluate trusted account inputs with a fixed Beijing day-start capital.

    Observation contract:
      wallet; as_of; day_start_ts; equity_usd (cash + *all* marked holdings);
      external_net_flow_usd (deposit minus withdrawal since Beijing midnight);
      activity_complete/funding_complete/valuation_complete booleans; and,
      when no persistent baseline is supplied, baseline_complete=true plus
      day_start_equity_usd, baseline_as_of, baseline_source.

    Baseline provenance and completeness are asserted by the collector, never
    inferred from "an official endpoint returned some data". A same-day process
    start equity is not a legitimate midnight baseline. Official delayed PnL may
    be included for disclosure but is not the real-time admission numerator.
    """
    now = time.time() if now is None else now
    try:
        wallet = _wallet(cfg)
        loss, profit, policy = _limits(cfg)
        if not isinstance(observation, dict):
            raise ValueError("Live account observation is missing")
        if str(observation.get("wallet") or "").lower() != wallet:
            raise ValueError("Live account observation wallet mismatch")
        start = day_start_ts(now)
        if _number(observation.get("day_start_ts"), "accounting day") != start:
            raise ValueError("Live account observation is from another Beijing day")
        as_of = _number(observation.get("as_of"), "account valuation timestamp", minimum=0.)
        if not -3. <= now - as_of <= max_age_sec:
            raise ValueError("Live account valuation is stale or from the future")
        if observation.get("error"):
            raise ValueError(str(observation["error"]))
        for key in ("activity_complete", "funding_complete", "valuation_complete"):
            if observation.get(key) is not True:
                raise ValueError(f"Live accounting coverage is incomplete: {key}")
        equity = _number(observation.get("equity_usd"), "current account equity", minimum=0.)
        flow = _number(observation.get("external_net_flow_usd"), "external net funding")
        if baseline is None:
            if observation.get("baseline_complete") is not True:
                raise ValueError("Beijing midnight equity baseline is unproven")
            capital = _number(observation.get("day_start_equity_usd"), "midnight account equity", minimum=0.)
            base_as_of = _number(observation.get("baseline_as_of"), "midnight baseline timestamp", minimum=0.)
            source = str(observation.get("baseline_source") or "").strip()
            if not source:
                raise ValueError("midnight equity baseline source is missing")
        else:
            if baseline.get("wallet") != wallet or baseline.get("day_start_ts") != start:
                raise ValueError("persistent midnight equity baseline identity mismatch")
            capital = _number(baseline.get("day_start_equity_usd"), "frozen midnight account equity", minimum=0.)
            base_as_of = _number(baseline.get("baseline_as_of"), "frozen baseline timestamp", minimum=0.)
            source = str(baseline.get("baseline_source") or "").strip()
            if not source:
                raise ValueError("persistent midnight baseline source is missing")
        if capital <= 0:
            raise ValueError("Beijing midnight account equity must be positive")
        if base_as_of > start + 1:
            raise ValueError("midnight baseline may not use a later process-start valuation")
        pnl = equity - capital - flow
        loss_limit, profit_target = capital * loss if loss > 0 else None, capital * profit if profit > 0 else None
        state, reason = "OK", None
        if loss_limit is not None and pnl <= -loss_limit + 1e-9:
            state = "DAILY_LOSS_STOP"
            reason = f"BTC 实盘日亏损熔断：含费净盈亏 ${pnl:.4f}，达到日初权益 {loss:.2%}（${loss_limit:.4f}）；仅暂停新开仓至北京时间次日零时"
        elif profit_target is not None and pnl >= profit_target - 1e-9:
            state = "DAILY_PROFIT_STOP"
            reason = f"BTC 实盘日止盈：含费净盈亏 ${pnl:.4f}，达到日初权益 {profit:.2%}（${profit_target:.4f}）；仅暂停新开仓至北京时间次日零时"
        return {
            "schema_version": SCHEMA_VERSION, "wallet": wallet, "mode": "live", "asset": "BTC",
            "available": True, "allow_entries": reason is None, "state": state,
            "entry_block_reason": reason, "circuit_reason": reason,
            "day_start_ts": start, "resume_ts": start + 86400,
            "capital_base_usd": capital, "day_start_equity_usd": capital,
            "equity_usd": equity, "external_net_flow_usd": flow,
            "daily_net_pnl_usd": round(pnl, 8), "daily_realized_usd": round(pnl, 8),
            "daily_profit_rate": pnl / capital,
            "max_daily_loss_fraction": loss, "max_daily_realized_profit_fraction": profit,
            "daily_loss_limit_usd": loss_limit, "daily_profit_target_usd": profit_target,
            "policy_fingerprint": policy, "source": "live_account_equity",
            "baseline_as_of": base_as_of, "baseline_source": source,
            "data_as_of": as_of, "updated_at": now, "latched": False,
            "open_positions_count": observation.get("open_positions_count"),
            "official_pnl_as_of": observation.get("official_pnl_as_of"),
            "official_economic_pnl_usd": observation.get("official_economic_pnl_usd"),
            "position_value_usd": observation.get("position_value_usd"),
            "cash_usd": observation.get("cash_usd"),
        }
    except (ValueError, TypeError, OverflowError) as exc:
        return _unknown(cfg, now, f"实盘日风控数据待核验：{exc}；暂停新开仓，持仓退出和兑换继续")


def _with_latch(snapshot: dict, baseline: dict | None) -> dict:
    """A restart cannot clear a same-day halt under unchanged thresholds."""
    latch = (baseline or {}).get("halt")
    if (snapshot.get("available") and isinstance(latch, dict)
            and latch.get("policy_fingerprint") == snapshot.get("policy_fingerprint")
            and latch.get("state") in {"DAILY_LOSS_STOP", "DAILY_PROFIT_STOP"}):
        return {**snapshot, "allow_entries": False, "state": latch["state"],
                "entry_block_reason": latch["reason"], "circuit_reason": latch["reason"],
                "triggered_at": latch["triggered_at"], "latched": True}
    return snapshot


def publish_live_risk_snapshot(cfg, observation: dict, *, now: float | None = None,
                               path: str | Path | None = None,
                               max_age_sec: float = DEFAULT_MAX_AGE_SEC) -> dict:
    """Worker-only: atomically freeze the day baseline and publish admission."""
    now = time.time() if now is None else now
    target = state_file(path)
    baseline = None
    try:
        wallet = _wallet(cfg)
        base_path = _baseline_path(target, wallet, day_start_ts(now))
        try:
            baseline = _read_json(base_path)
        except FileNotFoundError:
            pass
        snapshot = build_live_risk_snapshot(cfg, observation, now=now, baseline=baseline, max_age_sec=max_age_sec)
        if snapshot.get("available"):
            if baseline is None:
                baseline = {key: snapshot[key] for key in ("schema_version", "wallet", "day_start_ts",
                    "day_start_equity_usd", "baseline_as_of", "baseline_source")}
                baseline["frozen_at"] = now
                if isinstance(observation.get("baseline_evidence"), dict):
                    baseline["baseline_evidence"] = observation["baseline_evidence"]
            snapshot = _with_latch(snapshot, baseline)
            if snapshot["state"] in {"DAILY_LOSS_STOP", "DAILY_PROFIT_STOP"} and not snapshot.get("latched"):
                baseline["halt"] = {"state": snapshot["state"], "reason": snapshot["entry_block_reason"],
                                    "triggered_at": now, "policy_fingerprint": snapshot["policy_fingerprint"]}
                snapshot.update(triggered_at=now, latched=True)
            _atomic_json(base_path, baseline)
        _atomic_json(target, {"schema_version": SCHEMA_VERSION, "observation": observation,
                              "snapshot": snapshot, "published_at": now})
        return snapshot
    except (OSError, ValueError, TypeError, OverflowError) as exc:
        return _unknown(cfg, now, f"实盘日风控状态无法保存（{type(exc).__name__}）；暂停新开仓，持仓退出和兑换继续")


def read_live_risk_snapshot(cfg, *, now: float | None = None,
                            path: str | Path | None = None,
                            max_age_sec: float = DEFAULT_MAX_AGE_SEC) -> dict:
    """Read only, including threshold changes without mutating halt evidence."""
    now = time.time() if now is None else now
    try:
        target = state_file(path)
        document = _read_json(target)
        if document.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported Live accounting schema")
        if not -3 <= now - _number(document.get("published_at"), "risk publication timestamp") <= max_age_sec:
            raise ValueError("Live risk publication is stale")
        baseline = _read_json(_baseline_path(target, _wallet(cfg), day_start_ts(now)))
        snapshot = build_live_risk_snapshot(cfg, document.get("observation"), now=now,
                                            baseline=baseline, max_age_sec=max_age_sec)
        return _with_latch(snapshot, baseline)
    except (OSError, ValueError, TypeError, OverflowError) as exc:
        return _unknown(cfg, now, f"实盘日风控快照不可用（{type(exc).__name__}）；暂停新开仓，持仓退出和兑换继续")


def live_entry_stop_reason(cfg, **kwargs) -> str | None:
    snapshot = read_live_risk_snapshot(cfg, **kwargs)
    return None if snapshot.get("allow_entries") else str(snapshot["entry_block_reason"])


def refresh_live_risk(cfg, client=None, **kwargs) -> dict:
    """Convenience entry point for the worker's background accounting poller."""
    from bot.live_accounting import refresh_live_risk as refresh
    return refresh(cfg, client=client, **kwargs)
