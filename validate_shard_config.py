#!/usr/bin/env python3
"""
Shard Configuration Validator

Validates that shard_config in sub_accounts table:
1. Has no overlapping symbols between workers (exclusivity)
2. Covers all tradable symbols (completeness)
"""

import asyncio
import asyncpg
import fnmatch
import os
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple


async def load_env():
    """Load PG_DSN from .env file"""
    # Try multiple possible locations
    possible_paths = [
        Path("/data/hustle2026/backend/.env"),
        Path.home() / "testgo" / ".env",
        Path.home() / "hustle2026" / "backend" / ".env",
    ]

    env_vars = {}
    for env_path in possible_paths:
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        key, _, value = line.partition("=")
                        env_vars[key.strip()] = value.strip().strip('"').strip("'")
            break

    return env_vars.get("DATABASE_URL") or env_vars.get("PG_DSN") or os.getenv("DATABASE_URL") or os.getenv("PG_DSN")


async def get_active_accounts(conn) -> List[Dict]:
    """Get all active accounts with their shard_config"""
    # Check if shard_config column exists
    has_shard_config = await conn.fetchval("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'accounts' AND column_name = 'shard_config'
        )
    """)

    if has_shard_config:
        rows = await conn.fetch("""
            SELECT account_id as id, account_name, shard_config
            FROM accounts
            WHERE is_active = true
              AND account_role IN ('primary', 'worker')
            ORDER BY account_id
        """)
    else:
        # If column doesn't exist, return accounts with NULL config
        rows = await conn.fetch("""
            SELECT account_id as id, account_name, NULL as shard_config
            FROM accounts
            WHERE is_active = true
              AND account_role IN ('primary', 'worker')
            ORDER BY account_id
        """)

    return [dict(row) for row in rows]


async def get_tradable_symbols(conn) -> List[str]:
    """Get all tradable symbols (is_active=true)"""
    # Check if allow_open column exists
    has_allow_open = await conn.fetchval("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'platform_symbols' AND column_name = 'allow_open'
        )
    """)

    if has_allow_open:
        rows = await conn.fetch("""
            SELECT DISTINCT symbol
            FROM platform_symbols
            WHERE is_active = true AND allow_open = true
            ORDER BY symbol
        """)
    else:
        # If allow_open doesn't exist, just filter by is_active
        rows = await conn.fetch("""
            SELECT DISTINCT symbol
            FROM platform_symbols
            WHERE is_active = true
            ORDER BY symbol
        """)

    return [row["symbol"] for row in rows]


def expand_patterns(patterns: List[str], all_symbols: List[str]) -> Set[str]:
    """Expand wildcard patterns into actual symbol list"""
    expanded = set()
    for pattern in patterns:
        if "*" in pattern or "?" in pattern:
            matches = fnmatch.filter(all_symbols, pattern)
            expanded.update(matches)
        else:
            expanded.add(pattern)
    return expanded


def parse_shard_config(shard_config: dict, all_symbols: List[str]) -> Set[str]:
    """
    Parse shard_config and return the set of symbols this worker handles.

    Format:
    - {"mode": "include", "patterns": ["A*", "B*"]} → only these patterns
    - {"mode": "exclude", "patterns": ["FIL*"]} → all except these patterns
    - null/empty → all symbols
    """
    if not shard_config:
        return set(all_symbols)

    mode = shard_config.get("mode", "include")
    patterns = shard_config.get("patterns", [])

    if not patterns:
        return set(all_symbols)

    expanded = expand_patterns(patterns, all_symbols)

    if mode == "include":
        return expanded
    elif mode == "exclude":
        return set(all_symbols) - expanded
    else:
        raise ValueError(f"Unknown mode: {mode}")


def analyze_coverage(
    accounts: List[Dict],
    all_symbols: List[str]
) -> Tuple[Dict[str, Set[str]], Dict[str, List[str]], Set[str]]:
    """
    Analyze which symbols are covered by which workers.

    Returns:
        - worker_symbols: {account_name: set of symbols}
        - symbol_workers: {symbol: list of workers}
        - uncovered: set of symbols with no worker
    """
    worker_symbols = {}
    symbol_workers = {}

    for account in accounts:
        name = account["account_name"]
        config = account["shard_config"]
        symbols = parse_shard_config(config, all_symbols)
        worker_symbols[name] = symbols

        for symbol in symbols:
            if symbol not in symbol_workers:
                symbol_workers[symbol] = []
            symbol_workers[symbol].append(name)

    all_symbols_set = set(all_symbols)
    covered = set(symbol_workers.keys())
    uncovered = all_symbols_set - covered

    return worker_symbols, symbol_workers, uncovered


def print_report(
    accounts: List[Dict],
    all_symbols: List[str],
    worker_symbols: Dict[str, Set[str]],
    symbol_workers: Dict[str, List[str]],
    uncovered: Set[str]
) -> int:
    """Print validation report and return exit code"""

    print("=== Shard Config Validation ===")
    print(f"Active workers: {len(accounts)}")
    print(f"Tradable symbols: {len(all_symbols)}")
    print()

    print("Worker coverage:")
    for account in accounts:
        name = account["account_name"]
        account_id = account["id"]
        config = account["shard_config"]
        symbols = worker_symbols[name]

        if not config:
            mode_desc = "all symbols (no config)"
        else:
            mode = config.get("mode", "include")
            patterns = config.get("patterns", [])
            mode_desc = f"{mode} mode: {patterns}"

        print(f"  {name} (id={account_id}): {len(symbols)} symbols ({mode_desc})")
    print()

    # Check for overlaps
    overlapping = {sym: workers for sym, workers in symbol_workers.items() if len(workers) > 1}

    if overlapping:
        print(f"❌ ERROR: {len(overlapping)} symbols processed by multiple workers")
        for symbol in sorted(overlapping.keys()):
            workers = overlapping[symbol]
            print(f"  {symbol}: {workers}")
        print()
        exit_code = 1
    else:
        print("✅ No overlapping symbols (all exclusive)")
        exit_code = 0

    # Check for uncovered symbols
    if uncovered:
        print(f"⚠️  WARNING: {len(uncovered)} symbols not covered by any worker")
        uncovered_list = sorted(uncovered)
        if len(uncovered_list) <= 10:
            print(f"  {', '.join(uncovered_list)}")
        else:
            print(f"  {', '.join(uncovered_list[:10])}, ... ({len(uncovered_list) - 10} more)")
        print()
        if exit_code == 0:
            exit_code = 2
    else:
        print(f"✅ All {len(all_symbols)} symbols covered")

    return exit_code


async def main():
    dsn = await load_env()
    if not dsn:
        print("ERROR: DATABASE_URL or PG_DSN not found in .env or environment", file=sys.stderr)
        return 1

    try:
        conn = await asyncpg.connect(dsn)

        accounts = await get_active_accounts(conn)
        all_symbols = await get_tradable_symbols(conn)

        await conn.close()

        if not accounts:
            print("ERROR: No active sub_accounts found", file=sys.stderr)
            return 1

        if not all_symbols:
            print("ERROR: No tradable symbols found", file=sys.stderr)
            return 1

        worker_symbols, symbol_workers, uncovered = analyze_coverage(accounts, all_symbols)
        exit_code = print_report(accounts, all_symbols, worker_symbols, symbol_workers, uncovered)

        return exit_code

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
