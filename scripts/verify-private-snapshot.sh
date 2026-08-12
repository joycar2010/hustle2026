#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "$#" -ne 3 ]]; then
  echo "Usage: $0 ENCRYPTED_CMS PUBLIC_CERT PRIVATE_KEY" >&2
  exit 2
fi

ENCRYPTED_CMS="$1"
PUBLIC_CERT="$2"
PRIVATE_KEY="$3"
VERIFY_DIR="$(mktemp -d /var/tmp/qh-backup-verify.XXXXXX)"

cleanup() {
  rm -rf -- "${VERIFY_DIR}"
}
trap cleanup EXIT
umask 077

openssl cms -decrypt -binary -inform DER \
  -in "${ENCRYPTED_CMS}" \
  -recip "${PUBLIC_CERT}" \
  -inkey "${PRIVATE_KEY}" \
  | zstd -d -q -c \
  | tar -xf - -C "${VERIFY_DIR}"

(
  cd "${VERIFY_DIR}"
  sha256sum -c MANIFEST.sha256 > /dev/null
)

pg_restore --list \
  "${VERIFY_DIR}/databases/postgresql/quanthedge.dump" > /dev/null
pg_restore --list \
  "${VERIFY_DIR}/databases/postgresql/postgres.dump" > /dev/null
# Render every archived data block to SQL without connecting to a database.
# This catches truncated payload blocks that a TOC-only check would miss.
pg_restore --file=/dev/null \
  "${VERIFY_DIR}/databases/postgresql/quanthedge.dump"
pg_restore --file=/dev/null \
  "${VERIFY_DIR}/databases/postgresql/postgres.dump"
test -s "${VERIFY_DIR}/databases/postgresql/globals.sql"

if command -v redis-check-rdb > /dev/null; then
  redis-check-rdb "${VERIFY_DIR}/databases/redis/dump.rdb" > /dev/null
else
  test -s "${VERIFY_DIR}/databases/redis/dump.rdb"
fi

python3 - "${VERIFY_DIR}" <<'PY'
import pathlib
import sqlite3
import sys

root = pathlib.Path(sys.argv[1])
for name in ("goview-live.db", "goview-source-copy.db"):
    path = root / "databases" / "sqlite" / name
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        result = db.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise SystemExit(f"SQLite integrity check failed: {name}")
PY

echo "PRIVATE_SNAPSHOT_VERIFIED=1"
