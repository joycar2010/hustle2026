"""Safety checks required before launching real-money workers.

This command is intentionally read-only. It validates that the local .env has
the credentials and conservative controls needed by ``run_live.sh`` without
printing any secret values or placing an order.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parent.parent


def _configure_stdio() -> None:
    """Keep Chinese diagnostics usable on Windows and Linux consoles."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def main() -> int:
    _configure_stdio()
    env = {k: str(v or "").strip() for k, v in dotenv_values(ROOT / ".env").items()}
    failures: list[str] = []

    polyauto = env.get("POLYAUTO_INSTANCE", "").lower() in ("1", "true", "yes", "on", "auto") or env.get("INSTANCE_NAME", "").lower() == "polyauto"
    if polyauto:
        if env.get("BTC_LIVE_ENABLED", "false").lower() not in ("1", "true", "yes", "on"):
            failures.append("polyauto must explicitly enable BTC_LIVE_ENABLED before live start")
        # ETH live is explicitly enabled per-service in polyauto. Weather and
        # sports remain paper-only and are checked below.
        if env.get("WEATHER_LIVE_TRADING_ENABLED", "false").lower() in ("1", "true", "yes", "on"):
            failures.append("polyauto weather live path is locked")
        if env.get("SPORTS_LIVE_TRADING_ENABLED", "false").lower() in ("1", "true", "yes", "on"):
            failures.append("sports service is paper-only")

    # Optional deployment metadata proves the L2 key was provisioned with
    # minimum order/query scope. Existing deployments may omit this metadata.
    scope = env.get("CLOB_API_SCOPE", "").replace(" ", "").lower()
    if scope:
        allowed_scope = {"read", "trade", "order", "cancel", "query"}
        forbidden = {item for item in scope.split(",") if item} - allowed_scope
        if forbidden:
            failures.append("CLOB_API_SCOPE contains forbidden permissions")

    for key in ("PRIVATE_KEY", "WALLET_ADDRESS", "FUNDER_ADDRESS", "CLOB_API_KEY", "CLOB_API_SECRET", "CLOB_API_PASSPHRASE"):
        if not env.get(key):
            failures.append(f"缺少 {key}")

    if env.get("SIGNATURE_TYPE") != "3":
        failures.append("SIGNATURE_TYPE 必须为 3（Deposit Wallet）")
    if env.get("CHAIN_ID", "137") != "137":
        failures.append("CHAIN_ID 必须为 137（Polygon）")
    if env.get("ETH_TRADING_ENABLED", "false").lower() == "true" and not env.get("CHAIN_ID"):
        failures.append("ETH 实盘配置不完整")

    def number(name: str, default: float) -> float:
        try:
            return float(env.get(name, default))
        except (TypeError, ValueError):
            failures.append(f"{name} 不是有效数字")
            return default

    # A paper profile can be aggressive, but it must never be reused for live
    # money. These limits force an explicit, conservative reconfiguration.
    risk_fraction = number("ORDER_RISK_FRACTION", 0.0)
    fixed_notional = number("ORDER_FIXED_NOTIONAL_USD", 0.0)
    if risk_fraction > 0.05:
        failures.append("ORDER_RISK_FRACTION 必须 ≤ 0.05")
    if fixed_notional > 0 and fixed_notional > 10:
        failures.append("ORDER_FIXED_NOTIONAL_USD 必须 ≤ 10")
    if number("MIN_NET_EDGE", 0.0) <= 0:
        failures.append("MIN_NET_EDGE 必须大于 0")
    if number("CONFIRM_CHECKS", 0.0) < 1:
        failures.append("CONFIRM_CHECKS 必须至少为 1")
    if number("MIN_T_REMAINING_SEC", 0.0) <= 0:
        failures.append("MIN_T_REMAINING_SEC 必须大于 0")
    if number("MAX_DAILY_LOSS_FRACTION", 0.0) <= 0:
        failures.append("MAX_DAILY_LOSS_FRACTION 必须大于 0")
    if number("MAX_DAILY_REALIZED_PROFIT_USD", 0.0) <= 0:
        failures.append("MAX_DAILY_REALIZED_PROFIT_USD 必须大于 0")
    if number("MAX_ORDERS_PER_HOUR", 0.0) <= 0:
        failures.append("MAX_ORDERS_PER_HOUR 必须大于 0")
    if number("MAX_OPEN_POSITIONS", 0.0) <= 0:
        failures.append("MAX_OPEN_POSITIONS 必须大于 0")
    if env.get("BTC_DELTA_FILTER_ENABLED", "false").lower() != "true":
        failures.append("BTC_DELTA_FILTER_ENABLED 必须为 true")

    if failures:
        print("实盘预检失败，未启动任何进程：")
        for failure in failures:
            print(f"- {failure}")
        print("请先在 .env 中完成 Polygon Deposit Wallet、CLOB 凭据和保守风控配置。")
        return 1

    print("实盘预检通过：凭据已配置，风控参数满足安全上限。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
