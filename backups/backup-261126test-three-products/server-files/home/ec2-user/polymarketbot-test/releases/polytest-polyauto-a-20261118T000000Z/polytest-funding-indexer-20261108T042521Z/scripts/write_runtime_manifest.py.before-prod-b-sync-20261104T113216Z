#!/usr/bin/env python3
"""Write and validate a non-secret runtime configuration manifest."""
from __future__ import annotations
import hashlib, json, math, os, pathlib, sys, time

KEYS = (
    "CONFIG_PROFILE", "CONFIG_MANIFEST_VERSION", "SECONDS_BEFORE_CLOSE", "MIN_T_REMAINING_SEC",
    "REVERSAL_EXIT_WINDOW_SEC", "REVERSAL_NORMAL_MIN_T_REMAINING_SEC", "REVERSAL_HELD_BID_DRAWDOWN",
    "REVERSAL_CONFIRM_CHECKS", "CONFIRM_CHECKS", "BTC_MIN_ENTRY_PRICE", "BTC_MAX_ENTRY_PRICE",
    "BTC_UP_MIN_ENTRY_PRICE", "BTC_UP_MAX_ENTRY_PRICE", "BTC_DELTA_FILTER_ENABLED",
    "BTC_DELTA_THRESHOLD_USD", "BTC_UP_MIN_DELTA_USD", "BTC_DOWN_MAX_DELTA_USD",
    "REVERSAL_PARTIAL_EXIT_ENABLED", "REVERSAL_PARTIAL_EXIT_WINDOW_SEC",
    "REVERSAL_PARTIAL_EXIT_MIN_T_REMAINING_SEC", "REVERSAL_PARTIAL_HELD_BID_THRESHOLD",
    "REVERSAL_PARTIAL_HELD_BID_DRAWDOWN", "REVERSAL_PARTIAL_CONFIRM_CHECKS",
    "REVERSAL_PARTIAL_EXIT_FRACTION", "ORDER_RISK_FRACTION", "PAPER_EQUITY_USD",
    "MAX_DAILY_LOSS_FRACTION", "MAX_DAILY_REALIZED_PROFIT_FRACTION", "BTC_LIVE_ENABLED",
    "ETH_TRADING_ENABLED", "WEATHER_LIVE_TRADING_ENABLED", "SPORTS_LIVE_TRADING_ENABLED",
)

def expected_for(profile: str, values: dict[str, str]) -> dict[str, str]:
    p1 = values.get("CONFIG_MANIFEST_VERSION", "").startswith("P1-")
    common = {
        "CONFIG_PROFILE": profile,
        "CONFIG_MANIFEST_VERSION": "P1-20261031" if p1 else "P0-20261031",
        "SECONDS_BEFORE_CLOSE": "150", "MIN_T_REMAINING_SEC": "90",
        "REVERSAL_EXIT_WINDOW_SEC": "150", "REVERSAL_NORMAL_MIN_T_REMAINING_SEC": "0",
        "REVERSAL_HELD_BID_DRAWDOWN": "0.30", "REVERSAL_CONFIRM_CHECKS": "2",
        "BTC_MIN_ENTRY_PRICE": "0.84", "BTC_MAX_ENTRY_PRICE": "0.90",
        "BTC_UP_MIN_ENTRY_PRICE": "0.84", "BTC_UP_MAX_ENTRY_PRICE": "0.90",
        "BTC_DELTA_FILTER_ENABLED": "true", "REVERSAL_PARTIAL_EXIT_MIN_T_REMAINING_SEC": "30",
        "REVERSAL_PARTIAL_HELD_BID_THRESHOLD": "0", "REVERSAL_PARTIAL_CONFIRM_CHECKS": "2",
        "REVERSAL_PARTIAL_EXIT_FRACTION": "0.50", "ORDER_RISK_FRACTION": "0.02",
        "PAPER_EQUITY_USD": "100", "MAX_DAILY_LOSS_FRACTION": "0.03",
        "MAX_DAILY_REALIZED_PROFIT_FRACTION": "0.12", "BTC_LIVE_ENABLED": "false",
    }
    if profile == "A" and p1:
        common.update({"CONFIRM_CHECKS":"2", "BTC_DELTA_THRESHOLD_USD":"10", "BTC_UP_MIN_DELTA_USD":"10", "BTC_DOWN_MAX_DELTA_USD":"-10", "REVERSAL_PARTIAL_EXIT_ENABLED":"false", "REVERSAL_PARTIAL_EXIT_WINDOW_SEC":"60", "REVERSAL_PARTIAL_HELD_BID_DRAWDOWN":"0.25"})
    elif profile == "A":
        common.update({"CONFIRM_CHECKS":"3", "BTC_DELTA_THRESHOLD_USD":"20", "BTC_UP_MIN_DELTA_USD":"20", "BTC_DOWN_MAX_DELTA_USD":"-20", "REVERSAL_PARTIAL_EXIT_ENABLED":"false", "REVERSAL_PARTIAL_EXIT_WINDOW_SEC":"60", "REVERSAL_PARTIAL_HELD_BID_DRAWDOWN":"0.25"})
    elif profile == "B":
        common.update({"CONFIRM_CHECKS":"2", "BTC_DELTA_THRESHOLD_USD":"10", "BTC_UP_MIN_DELTA_USD":"10", "BTC_DOWN_MAX_DELTA_USD":"-10", "REVERSAL_PARTIAL_EXIT_ENABLED":"true", "REVERSAL_PARTIAL_EXIT_WINDOW_SEC":"150" if p1 else "60", "REVERSAL_PARTIAL_HELD_BID_DRAWDOWN":"0.25", "REVERSAL_EXIT_WINDOW_SEC":"150" if p1 else "120"})
    else:
        common.update({"CONFIRM_CHECKS":"2", "BTC_DELTA_THRESHOLD_USD":"10", "BTC_UP_MIN_DELTA_USD":"10", "BTC_DOWN_MAX_DELTA_USD":"-10", "REVERSAL_PARTIAL_EXIT_ENABLED":"false", "REVERSAL_PARTIAL_EXIT_WINDOW_SEC":"60", "REVERSAL_PARTIAL_HELD_BID_DRAWDOWN":"0.25"})
    if profile == "D-production":
        # D is the strategy identity; D-production is the manifest lane name.
        common["CONFIG_PROFILE"] = "D"
        # Operator-managed production values are range-checked below. A/B
        # experiment parameters remain fixed to preserve their comparison.
        for key in ("REVERSAL_HELD_BID_DRAWDOWN", "ORDER_RISK_FRACTION",
                    "PAPER_EQUITY_USD", "MAX_DAILY_LOSS_FRACTION",
                    "MAX_DAILY_REALIZED_PROFIT_FRACTION"):
            common.pop(key, None)
        # This unused default was absent in the original production env.
        if values.get("REVERSAL_PARTIAL_EXIT_ENABLED") == "false":
            common.pop("REVERSAL_PARTIAL_HELD_BID_DRAWDOWN", None)
    return common


def validate_production_values(values: dict[str, str]) -> None:
    bounds = {
        "REVERSAL_HELD_BID_DRAWDOWN": (0.0, 1.0, False),
        "ORDER_RISK_FRACTION": (0.0, 1.0, False),
        "PAPER_EQUITY_USD": (10.0, 100000.0, True),
        "MAX_DAILY_LOSS_FRACTION": (0.0, 0.5, True),
        "MAX_DAILY_REALIZED_PROFIT_FRACTION": (0.0, 1.0, True),
    }
    for key, (low, high, inclusive) in bounds.items():
        try:
            value = float(values.get(key, ""))
        except (TypeError, ValueError):
            raise SystemExit("invalid production configuration: " + key)
        if not math.isfinite(value) or value > high or (value < low if inclusive else value <= low):
            raise SystemExit("invalid production configuration: " + key)

def main() -> None:
    if len(sys.argv) != 3: raise SystemExit("usage: write_runtime_manifest.py OUTPUT PROFILE")
    output=pathlib.Path(sys.argv[1]); profile=sys.argv[2]
    values={key: os.environ.get(key, "") for key in KEYS}
    if profile == "D-production": validate_production_values(values)
    expected=expected_for(profile, values)
    mismatches={k:{"expected":v,"actual":values.get(k,"")} for k,v in expected.items() if values.get(k,"") != v}
    if mismatches: raise SystemExit("runtime configuration mismatch: "+json.dumps(mismatches,sort_keys=True))
    canonical=json.dumps(values,sort_keys=True,separators=(",",":")).encode()
    payload={"profile":profile,"pid":os.getppid(),"manifest_writer_pid":os.getpid(),"started_at":time.time(),"timezone":"Asia/Shanghai","config_hash":hashlib.sha256(canonical).hexdigest(),"values":values,"paper_run_id":os.environ.get("PAPER_RUN_ID",""),"paper_variant":os.environ.get("PAPER_VARIANT","")}
    output.parent.mkdir(parents=True,exist_ok=True)
    tmp=output.with_suffix(output.suffix+".tmp"); tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); os.replace(tmp,output)
if __name__ == "__main__": main()
