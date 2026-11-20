#!/usr/bin/env python3
"""Derive Polymarket CLOB API credentials from PRIVATE_KEY in .env."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
import os

load_dotenv(ROOT / ".env")


def main() -> int:
    key = os.getenv("PRIVATE_KEY", "").strip()
    if not key:
        print("PRIVATE_KEY missing in .env", file=sys.stderr)
        return 1

    from py_clob_client_v2.client import ClobClient

    host = os.getenv("CLOB_HOST", "https://clob.polymarket.com").rstrip("/")
    chain_id = int(os.getenv("CHAIN_ID", "137"))
    sig = int(os.getenv("SIGNATURE_TYPE", "3"))
    funder = os.getenv("FUNDER_ADDRESS", "").strip() or None

    client = ClobClient(
        host,
        chain_id=chain_id,
        key=key,
        signature_type=sig,
        funder=funder,
    )
    creds = client.create_or_derive_api_creds()
    print("Add these to your .env:\n")
    print(f"API_KEY={creds.api_key}")
    print(f"API_SECRET={creds.api_secret}")
    print(f"API_PASSPHRASE={creds.api_passphrase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
