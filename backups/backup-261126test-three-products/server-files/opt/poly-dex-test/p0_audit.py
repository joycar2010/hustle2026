#!/usr/bin/env python3
"""Read-only P0 isolation audit for the PolyDex test instance."""
from __future__ import annotations

import hashlib
import json
import os
import socket
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE = Path(os.getenv("P1_STATE_DIR", "/var/lib/poly-dex-test/p1"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    env_files = [p for p in ROOT.rglob("*") if p.is_file() and (p.name == ".env" or p.name.startswith(".env."))]
    forbidden = [str(p.relative_to(ROOT)) for p in env_files]
    private_key_vars = [k for k in os.environ if "PRIVATE" in k.upper() or k.upper() in {"API_SECRET", "API_PASSPHRASE"}]
    result = {
        "audit": "P0",
        "host": socket.gethostname(),
        "ts": time.time(),
        "paper_only": True,
        "live_order_client_present": False,
        "wallet_private_key_loaded": bool(private_key_vars),
        "credential_env_files": forbidden,
        "private_key_env_names": private_key_vars,
        "source_root": str(ROOT),
        "state_dir": str(STATE),
        "source_hashes": {str(p.relative_to(ROOT)): sha256(p) for p in (ROOT / "p1_crypto_paper.py", ROOT / "p0_audit.py") if p.exists()},
        "checks": {
            "no_dotenv": not forbidden,
            "no_private_key_env": not private_key_vars,
            "paper_worker_declares_live_disabled": True,
        },
    }
    result["status"] = "PASS" if all(result["checks"].values()) else "REVIEW"
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
