"""Create one wallet without replacing strategy settings or printing secrets.

Run from the deployed virtualenv. This script never sends transactions or
registers a Polymarket account. A previous successful run is verified and reused.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from dotenv import dotenv_values
from eth_account import Account

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
KEY_DIR = Path.home() / ".polymarket-wallet"


def write_new(path: Path, contents: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(contents)
        handle.flush()
        os.fsync(handle.fileno())


def main() -> None:
    os.umask(0o077)
    if ENV_PATH.is_symlink() or not ENV_PATH.is_file():
        raise SystemExit("Expected a regular existing .env file.")
    original = ENV_PATH.read_text(encoding="utf-8")
    values = dotenv_values(ENV_PATH)
    KEY_DIR.mkdir(mode=0o700, exist_ok=True)
    if KEY_DIR.is_symlink() or KEY_DIR.stat().st_uid != os.getuid():
        raise SystemExit("Wallet folder must be owned by the current user.")
    KEY_DIR.chmod(0o700)
    private_path = KEY_DIR / "metamask-private-key.txt"
    existing = str(values.get("PRIVATE_KEY") or "").strip()
    if existing:
        if not private_path.is_file() or private_path.is_symlink():
            raise SystemExit("An existing wallet is configured; refusing replacement or export.")
        saved = private_path.read_text(encoding="utf-8").strip()
        if saved != existing:
            raise SystemExit("Saved import key differs from configured wallet; inspect manually.")
        account = Account.from_key(existing)
        if account.address.lower() != str(values.get("WALLET_ADDRESS") or "").lower():
            raise SystemExit("Configured public address does not match its key.")
        created = False
    else:
        for field in ("WALLET_ADDRESS", "FUNDER_ADDRESS", "DEPOSIT_WALLET_ADDRESS",
                      "CLOB_API_KEY", "CLOB_API_SECRET", "CLOB_API_PASSPHRASE"):
            if str(values.get(field) or "").strip():
                raise SystemExit(f"Existing {field} is populated; refusing to replace a wallet.")
        if private_path.exists():
            if private_path.is_symlink():
                raise SystemExit("Import key must be a regular file.")
            private_key = private_path.read_text(encoding="utf-8").strip()
            account = Account.from_key(private_key)
        else:
            account = Account.create()
            private_key = "0x" + account.key.hex().removeprefix("0x")
            write_new(private_path, private_key + "\n")

        backup = KEY_DIR / "env.before-wallet"
        if not backup.exists():
            write_new(backup, original)
        updates = {
            "PRIVATE_KEY": private_key,
            "WALLET_ADDRESS": account.address,
            "FUNDER_ADDRESS": account.address,
            "DEPOSIT_WALLET_ADDRESS": "",
            "SIGNATURE_TYPE": "0",
            "CHAIN_ID": "137",
        }
        output = []
        pending = dict(updates)
        for line in original.splitlines():
            match = re.match(r"^\s*([A-Z0-9_]+)\s*=", line)
            field = match.group(1) if match else None
            if field in updates:
                if field in pending:
                    output.append(f"{field}={pending.pop(field)}")
            else:
                output.append(line)
        output.extend(f"{field}={value}" for field, value in pending.items())
        fd, temporary = tempfile.mkstemp(prefix=".wallet-env-", dir=ROOT)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write("\n".join(output) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            if ENV_PATH.read_text(encoding="utf-8") != original:
                raise SystemExit("Configuration changed while preparing wallet; refusing overwrite.")
            os.replace(temporary, ENV_PATH)
            ENV_PATH.chmod(0o600)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        created = True

    private_path.chmod(0o600)
    address_path = KEY_DIR / "wallet-address.txt"
    if not address_path.exists():
        write_new(address_path, account.address + "\n")
    if address_path.read_text(encoding="utf-8").strip() != account.address:
        raise SystemExit("Saved address does not match the wallet.")
    print(json.dumps({"created": created, "address": account.address,
                      "network": "Polygon PoS", "chain_id": 137,
                      "private_key_file": str(private_path),
                      "configuration": str(ENV_PATH),
                      "polymarket_registered": False,
                      "trading_mode": "paper"}))


if __name__ == "__main__":
    main()
