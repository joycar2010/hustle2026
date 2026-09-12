"""Bind the bot signer to the owner of the configured Deposit Wallet.

The private key is collected with a hidden terminal prompt and is never
printed, logged, or accepted as a command-line argument.  The script refuses
to edit .env unless the derived EOA matches the Deposit Wallet's on-chain
owner().  Existing L2 credentials are cleared because they belong to the old
signer and must be derived again after this change.
"""
from __future__ import annotations

import getpass
import os
import re
import shutil
import sys
import time
from pathlib import Path

from dotenv import dotenv_values
from eth_account import Account
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware


ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
OWNER_SELECTOR = "0x8da5cb5b"


def _owner(w3: Web3, address: str) -> str:
    code = w3.eth.get_code(Web3.to_checksum_address(address))
    if not code:
        raise RuntimeError(f"Deposit Wallet {address} has no contract code")
    raw = w3.eth.call(
        {"to": Web3.to_checksum_address(address), "data": OWNER_SELECTOR}
    )
    if not raw or len(raw) < 20:
        raise RuntimeError("Deposit Wallet owner() returned no address")
    return Web3.to_checksum_address("0x" + bytes(raw)[-20:].hex())


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _rewrite_env(updates: dict[str, str]) -> Path:
    original = ENV_PATH.read_text(encoding="utf-8")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = ENV_PATH.with_name(f".env.before-owner-bind.{stamp}")
    shutil.copy2(ENV_PATH, backup)
    backup.chmod(0o600)

    seen: set[str] = set()
    out: list[str] = []
    key_re = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
    for line in original.splitlines():
        match = key_re.match(line)
        key = match.group(1) if match else ""
        if key in updates:
            out.append(f"{key}={_quote(updates[key])}")
            seen.add(key)
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={_quote(value)}")

    temporary = ENV_PATH.with_suffix(".env.owner-bind.tmp")
    temporary.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, ENV_PATH)
    ENV_PATH.chmod(0o600)
    return backup


def main() -> int:
    if not ENV_PATH.exists():
        print(".env not found", file=sys.stderr)
        return 1

    env = dotenv_values(ENV_PATH)
    target = str(env.get("DEPOSIT_WALLET_ADDRESS") or env.get("FUNDER_ADDRESS") or "").strip()
    rpc_url = str(env.get("POLYGON_RPC_URL") or "").strip()
    if not target or not rpc_url:
        print(".env must contain DEPOSIT_WALLET_ADDRESS/FUNDER_ADDRESS and POLYGON_RPC_URL", file=sys.stderr)
        return 1

    try:
        target = Web3.to_checksum_address(target)
    except Exception as exc:
        print(f"invalid Deposit Wallet address: {exc}", file=sys.stderr)
        return 1

    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 15}))
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        owner = _owner(w3, target)
    except Exception as exc:
        print(f"unable to verify Deposit Wallet owner: {exc}", file=sys.stderr)
        return 1

    first = getpass.getpass("MetaMask owner EOA private key (hidden): ").strip()
    if not first:
        print("no private key entered", file=sys.stderr)
        return 1
    second = getpass.getpass("Repeat private key (hidden): ").strip()
    if first != second:
        print("private key entries do not match", file=sys.stderr)
        return 1
    try:
        account = Account.from_key(first)
    except Exception as exc:
        print(f"invalid private key: {exc}", file=sys.stderr)
        return 1

    if account.address.lower() != owner.lower():
        print("private key does not belong to the Deposit Wallet owner; .env unchanged", file=sys.stderr)
        print(f"expected owner: {owner}", file=sys.stderr)
        print(f"derived address: {account.address}", file=sys.stderr)
        return 1

    print(f"verified owner: {owner}")
    print(f"Deposit Wallet: {target}")
    if input("Type BIND to update the bot signer and clear old L2 credentials: ").strip() != "BIND":
        print("cancelled; .env unchanged")
        return 1

    backup = _rewrite_env(
        {
            "PRIVATE_KEY": first,
            "WALLET_ADDRESS": account.address,
            "FUNDER_ADDRESS": target,
            "DEPOSIT_WALLET_ADDRESS": target,
            "SIGNATURE_TYPE": "3",
            "CHAIN_ID": "137",
            "CLOB_API_KEY": "",
            "CLOB_API_SECRET": "",
            "CLOB_API_PASSPHRASE": "",
        }
    )
    print("signer updated and old CLOB credentials cleared")
    print(f"backup: {backup}")
    print("next: .venv/bin/python scripts/derive_api_creds.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
