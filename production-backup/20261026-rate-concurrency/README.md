Coin production source snapshot
Date label: 20261026查库速率优化并发借币版
Sources: 18.176.76.127 (Python business + frontend) and 57.181.214.206 (Rust engine + frontend)
Included: frontend/frontend-admin source, Python backend source, Rust source, migrations, tests, current static/spa/admin-spa build outputs, current systemd service metadata, and the Rust release binary.
Excluded: .git, secrets (.env/.pem/.key), caches, node_modules, Python bytecode, historical backup/release trees, and Rust build intermediates.
C3 host 57.181.130.126 was intentionally excluded and not contacted.
Archive SHA-256: python 72964ab6e5b33fd33f06966e2c4529fa8df65f2756389a635d66e8066001ef79; rust 812430652a2b39af6bf4479ad4c6e99bb4395169cef1f6a92af2e8dd691d79f9.
The Python snapshot includes the corrected cex-worker.service entrypoint and engine/main.py heartbeat implementation used by production at snapshot time.
