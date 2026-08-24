#!/usr/bin/env python3
"""Pure-local schema, hash, baseline, and deployer check for MT5 .4."""

import hashlib
import json
import pathlib


STAGE = pathlib.Path(__file__).resolve().parent
PREVIOUS = STAGE.parent / "mt5-tick-isolation-20260817.3-local"
MANIFEST = STAGE / "release-manifest.json"
FILES = {
    "main.py": STAGE / "app" / "main.py",
    "runtime.py": STAGE / "app" / "runtime.py",
    "cell.py": STAGE / "cell.py",
    "deploy.ps1": STAGE / "deploy.ps1",
}
PREVIOUS_FILES = {
    "main.py": PREVIOUS / "app" / "main.py",
    "runtime.py": PREVIOUS / "app" / "runtime.py",
    "cell.py": PREVIOUS / "cell.py",
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def main():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    previous = json.loads(
        (PREVIOUS / "release-manifest.json").read_text(encoding="utf-8"),
    )
    release = "mt5-trade-wake-priority-20260817.4"

    require(manifest["schema"] == 1, "schema must remain 1")
    require(manifest["release"] == manifest["build_id"] == release,
            "release identity mismatch")
    require(manifest["deployment_status"] == "candidate_sealed_not_deployed",
            "candidate must remain not deployed")
    require(manifest["production_mutated"] is False,
            "production mutation recorded")
    require(manifest["real_orders_sent"] is False, "real order recorded")
    require(manifest["validation"]["real_orders_sent"] is False,
            "validation records a real order")
    require(
        manifest["rollback_policy"]["automatic_order_submission"] is False,
        "rollback policy permits automatic order submission",
    )

    require(set(manifest["candidate"]) == set(FILES),
            "candidate file set mismatch")
    for name, path in FILES.items():
        require(sha256(path) == manifest["candidate"][name],
                "candidate hash mismatch: %s" % name)

    before = manifest["production_before"]
    require(before["build_id"] == previous["release"] ==
            "mt5-tick-isolation-20260817.3",
            "production-before release mismatch")
    for name, path in PREVIOUS_FILES.items():
        require(before[name] == previous["candidate"][name],
                "production-before manifest mismatch: %s" % name)
        require(sha256(path) == previous["candidate"][name],
                "sealed .3 source hash mismatch: %s" % name)

    required_env = manifest["required_env"]
    require(required_env["MT5_BRIDGE_BUILD_ID"] == release,
            "build environment mismatch")
    require(required_env["MT5_WAL_FALLBACK_POLL_MS"] == "50",
            "WAL fallback interval mismatch")
    require(required_env["ACCOUNT_IDLE_REFRESH_SEC"] == "5",
            "account refresh interval mismatch")

    main_source = FILES["main.py"].read_text(encoding="utf-8")
    runtime_source = FILES["runtime.py"].read_text(encoding="utf-8")
    cell_source = FILES["cell.py"].read_text(encoding="utf-8")
    deployer = FILES["deploy.ps1"].read_text(encoding="utf-8")
    for source, name in (
        (main_source, "main.py"),
        (runtime_source, "runtime.py"),
        (cell_source, "cell.py"),
    ):
        compile(source, name, "exec")

    markers = (
        '$Release = "mt5-trade-wake-priority-20260817.4"',
        '[int]$Manifest.schema -ne 1',
        'Assert-FileHash $ManifestPath $ManifestSha256',
        'Set-EnvValue $envPath "MT5_WAL_FALLBACK_POLL_MS" "50"',
        'Set-EnvValue $envPath "ACCOUNT_IDLE_REFRESH_SEC" "5"',
        'Restore-BackupFiles',
        'Code rollback must not roll durable broker evidence back in time.',
        'real_orders_sent = $false',
    )
    for marker in markers:
        require(marker in deployer, "deployer marker missing: %s" % marker)
    require('Invoke-Bridge $instance "/mt5/order"' not in deployer,
            "deployer contains an order-submission call")
    require("order_send" not in deployer,
            "deployer contains a native order-submission call")

    require("generation_pipe_with_durable_poll_fallback" in runtime_source,
            "durable wakeup policy marker missing")
    require("execution_probe" in main_source,
            "execution identity probe marker missing")
    require("MT5_WAL_FALLBACK_POLL_MS=50" in cell_source,
            "cell WAL fallback environment marker missing")

    print(json.dumps({
        "ok": True,
        "release": release,
        "manifest_sha256": sha256(MANIFEST),
        "candidate": manifest["candidate"],
        "production_before": before["build_id"],
        "real_orders_sent": False,
    }, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
