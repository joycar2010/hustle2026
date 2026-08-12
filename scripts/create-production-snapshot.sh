#!/usr/bin/env bash
set -Eeuo pipefail

SNAPSHOT_DATE="20260812"
EXPECTED_HOST="ip-172-31-36-34"

if [[ "${EUID}" -ne 0 ]]; then
  echo "This script must run as root." >&2
  exit 1
fi

if [[ "$(hostname)" != "${EXPECTED_HOST}" ]]; then
  echo "Refusing to run on unexpected host: $(hostname)" >&2
  exit 1
fi

umask 077
STAGE="$(mktemp -d "/var/tmp/qh-backup-${SNAPSHOT_DATE}.XXXXXX")"
PUBLIC_TREE="${STAGE}/public-tree"
PRIVATE_TREE="${STAGE}/private-tree"
ARTIFACTS="${STAGE}/artifacts"

mkdir -p \
  "${PUBLIC_TREE}/backend" \
  "${PUBLIC_TREE}/qh_ws_hub/bin" \
  "${PUBLIC_TREE}/goview" \
  "${PUBLIC_TREE}/ops/nginx" \
  "${PUBLIC_TREE}/ops/systemd" \
  "${PUBLIC_TREE}/metadata" \
  "${PRIVATE_TREE}/databases/postgresql" \
  "${PRIVATE_TREE}/databases/redis" \
  "${PRIVATE_TREE}/databases/sqlite" \
  "${PRIVATE_TREE}/runtime-config/nginx" \
  "${PRIVATE_TREE}/runtime-config/systemd" \
  "${PRIVATE_TREE}/runtime-config/application" \
  "${ARTIFACTS}/frontend-dist"

copy_tree() {
  local source="$1"
  local destination="$2"
  mkdir -p "${destination}"
  rsync -a --exclude='.git/' --exclude='node_modules/' "${source}/" "${destination}/"
}

write_tree_manifest() {
  local tree="$1"
  local output="$2"
  (
    cd "${tree}"
    find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum
  ) > "${output}"
}

archive_tree() {
  local parent="$1"
  local name="$2"
  local output="$3"
  tar --acls --xattrs --numeric-owner --sort=name -C "${parent}" -cf - "${name}" \
    | zstd -T0 -10 -q -o "${output}"
}

sqlite_backup() {
  local source="$1"
  local destination="$2"
  python3 - "${source}" "${destination}" <<'PY'
import sqlite3
import sys

source, destination = sys.argv[1:]
with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src:
    with sqlite3.connect(destination) as dst:
        src.backup(dst)
PY
}

echo "Collecting exact live frontend trees..."
copy_tree /opt/quanthedge/web "${PUBLIC_TREE}/web"
copy_tree /opt/quanthedge/admin "${PUBLIC_TREE}/admin"
copy_tree /opt/qhwww "${PUBLIC_TREE}/qhwww"
copy_tree /opt/goview/web "${PUBLIC_TREE}/goview/web"

echo "Collecting frontend and application sources..."
copy_tree /opt/quanthedge/admin-src "${PUBLIC_TREE}/admin-src"
copy_tree /opt/quanthedge/client-src "${PUBLIC_TREE}/client-src"
copy_tree /opt/quanthedge/qhwww "${PUBLIC_TREE}/qhwww-source-copy"
rsync -a \
  --exclude='.git/' \
  --exclude='goview.db' \
  --exclude='config.ini' \
  /opt/goview/src/ "${PUBLIC_TREE}/goview/src/"

while IFS= read -r -d '' source_file; do
  cp -a "${source_file}" "${PUBLIC_TREE}/backend/"
done < <(
  find /opt/quanthedge -maxdepth 1 -type f -name '*.py' \
    ! -name '*.bak*' ! -name 'backup_*' -print0
)

for source_file in VERSION QH_P0_Implementation_Guide.md pairscan_universe.json; do
  if [[ -f "/opt/quanthedge/${source_file}" ]]; then
    cp -a "/opt/quanthedge/${source_file}" "${PUBLIC_TREE}/backend/"
  fi
done

if [[ -d /opt/quanthedge/tests ]]; then
  copy_tree /opt/quanthedge/tests "${PUBLIC_TREE}/backend/tests"
fi
# GeoIP binary datasets are runtime data and may carry redistribution terms;
# record their metadata rather than publishing them in the public repository.
if [[ -d /opt/quanthedge/geoip ]]; then
  find /opt/quanthedge/geoip -maxdepth 2 -type f \
    -printf '%P|%s|%TY-%Tm-%TdT%TH:%TM:%TSZ\n' \
    | LC_ALL=C sort > "${PUBLIC_TREE}/metadata/geoip-files.txt"
fi

cp -a /home/ubuntu/qh_ws_hub/Cargo.toml "${PUBLIC_TREE}/qh_ws_hub/"
cp -a /home/ubuntu/qh_ws_hub/Cargo.lock "${PUBLIC_TREE}/qh_ws_hub/"
mkdir -p "${PUBLIC_TREE}/qh_ws_hub/src"
cp -a /home/ubuntu/qh_ws_hub/src/main.rs "${PUBLIC_TREE}/qh_ws_hub/src/"
cp -a /home/ubuntu/qh_ws_hub/target/release/qh-ws-hub "${PUBLIC_TREE}/qh_ws_hub/bin/"
cp -a /opt/goview/goview-serve "${PUBLIC_TREE}/goview/"

echo "Collecting sanitized runtime configuration and inventories..."
for nginx_site in quanthedge qhadmin qhwww; do
  cp -L "/etc/nginx/sites-enabled/${nginx_site}" \
    "${PUBLIC_TREE}/ops/nginx/${nginx_site}.conf"
done

while IFS= read -r -d '' unit_file; do
  relative="${unit_file#/etc/systemd/system/}"
  destination="${PUBLIC_TREE}/ops/systemd/${relative}"
  mkdir -p "$(dirname "${destination}")"
  sed -E \
    -e 's/^([[:space:]]*Environment=).*/\1<REDACTED>/' \
    -e 's/^([[:space:]]*EnvironmentFile=).*/\1<REDACTED>/' \
    "${unit_file}" > "${destination}"
done < <(
  find /etc/systemd/system -maxdepth 3 -type f \
    \( -path '*quanthedge*' -o -path '*qh-ws-hub*' -o -path '*goview*' \) \
    -print0
)

if [[ -f /opt/goview/config.ini ]]; then
  sed -E 's/^([[:space:]]*[^#;][^=]*=).*/\1<REDACTED>/' \
    /opt/goview/config.ini > "${PUBLIC_TREE}/goview/config.ini.example"
fi

{
  echo "snapshot_date=${SNAPSHOT_DATE}"
  echo "created_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "hostname=$(hostname)"
  echo "kernel=$(uname -srmo)"
  echo "python=$(python3 --version 2>&1)"
  echo "postgres=$(pg_dump --version)"
  echo "redis=$(redis-cli --version)"
  echo "rustc=$(rustc --version 2>/dev/null || echo unavailable)"
  echo "cargo=$(cargo --version 2>/dev/null || echo unavailable)"
  echo "go=$(go version 2>/dev/null || echo unavailable)"
} > "${PUBLIC_TREE}/metadata/runtime-versions.txt"

/opt/quanthedge/venv/bin/pip freeze --all \
  > "${PUBLIC_TREE}/metadata/python-pip-freeze.txt"
systemctl is-enabled quanthedge-api qh-ws-hub goview \
  > "${PUBLIC_TREE}/metadata/services-enabled.txt"
systemctl is-active quanthedge-api qh-ws-hub goview \
  > "${PUBLIC_TREE}/metadata/services-active.txt"

echo "Creating consistent database backups..."
cd /tmp
runuser -u postgres -- pg_dump \
  --format=custom --compress=6 --no-owner --no-acl quanthedge \
  > "${PRIVATE_TREE}/databases/postgresql/quanthedge.dump"
runuser -u postgres -- pg_dump \
  --format=custom --compress=6 --no-owner --no-acl postgres \
  > "${PRIVATE_TREE}/databases/postgresql/postgres.dump"
runuser -u postgres -- pg_dumpall --globals-only \
  > "${PRIVATE_TREE}/databases/postgresql/globals.sql"

redis-cli --rdb "${PRIVATE_TREE}/databases/redis/dump.rdb" > /dev/null
sqlite_backup /opt/goview/goview.db \
  "${PRIVATE_TREE}/databases/sqlite/goview-live.db"
sqlite_backup /opt/goview/src/goview.db \
  "${PRIVATE_TREE}/databases/sqlite/goview-source-copy.db"

echo "Collecting exact private runtime configuration..."
for nginx_site in quanthedge qhadmin qhwww; do
  cp -L "/etc/nginx/sites-enabled/${nginx_site}" \
    "${PRIVATE_TREE}/runtime-config/nginx/${nginx_site}.conf"
done
rsync -a /etc/systemd/system/quanthedge-api.service* \
  "${PRIVATE_TREE}/runtime-config/systemd/" 2>/dev/null || true
rsync -a /etc/systemd/system/qh-ws-hub.service* \
  "${PRIVATE_TREE}/runtime-config/systemd/" 2>/dev/null || true
rsync -a /etc/systemd/system/goview.service* \
  "${PRIVATE_TREE}/runtime-config/systemd/" 2>/dev/null || true
if [[ -d /etc/postgresql/14/main ]]; then
  rsync -a /etc/postgresql/14/main/ \
    "${PRIVATE_TREE}/runtime-config/postgresql/"
fi
if [[ -f /etc/redis/redis.conf ]]; then
  mkdir -p "${PRIVATE_TREE}/runtime-config/redis"
  cp -a /etc/redis/redis.conf \
    "${PRIVATE_TREE}/runtime-config/redis/redis.conf"
fi

for private_file in \
  /opt/quanthedge/channels.json \
  /opt/goview/config.ini \
  /opt/goview/src/config.ini \
  /opt/quanthedge/.env \
  /home/ubuntu/qh_ws_hub/.env; do
  if [[ -f "${private_file}" ]]; then
    safe_name="$(printf '%s' "${private_file#/}" | tr '/' '_')"
    cp -a "${private_file}" \
      "${PRIVATE_TREE}/runtime-config/application/${safe_name}"
  fi
done

write_tree_manifest "${PRIVATE_TREE}" "${STAGE}/private-MANIFEST.sha256"
mv "${STAGE}/private-MANIFEST.sha256" "${PRIVATE_TREE}/MANIFEST.sha256"

echo "Generating dedicated recovery certificate..."
openssl genpkey -quiet -algorithm RSA \
  -pkeyopt rsa_keygen_bits:4096 \
  -out "${STAGE}/qh-backup-recovery-private-${SNAPSHOT_DATE}.pem"
openssl req -new -x509 -sha256 -days 3650 \
  -key "${STAGE}/qh-backup-recovery-private-${SNAPSHOT_DATE}.pem" \
  -out "${ARTIFACTS}/qh-backup-recovery-public-${SNAPSHOT_DATE}.crt" \
  -subj "/CN=QH Production Backup Recovery ${SNAPSHOT_DATE}/"

tar --acls --xattrs --numeric-owner --sort=name -C "${PRIVATE_TREE}" -cf - . \
  | zstd -T0 -10 -q -o "${STAGE}/private-backup.tar.zst"
openssl cms -encrypt -binary -aes-256-cbc -outform DER \
  -in "${STAGE}/private-backup.tar.zst" \
  -out "${ARTIFACTS}/qh-private-databases-and-config-${SNAPSHOT_DATE}.tar.zst.cms" \
  "${ARTIFACTS}/qh-backup-recovery-public-${SNAPSHOT_DATE}.crt"

openssl cms -decrypt -binary -inform DER \
  -in "${ARTIFACTS}/qh-private-databases-and-config-${SNAPSHOT_DATE}.tar.zst.cms" \
  -recip "${ARTIFACTS}/qh-backup-recovery-public-${SNAPSHOT_DATE}.crt" \
  -inkey "${STAGE}/qh-backup-recovery-private-${SNAPSHOT_DATE}.pem" \
  | zstd -q -t -

echo "Writing exact frontend manifests and archives..."
write_tree_manifest "${PUBLIC_TREE}/web" \
  "${ARTIFACTS}/frontend-dist/qh-web-${SNAPSHOT_DATE}.sha256"
write_tree_manifest "${PUBLIC_TREE}/admin" \
  "${ARTIFACTS}/frontend-dist/qhadmin-${SNAPSHOT_DATE}.sha256"
write_tree_manifest "${PUBLIC_TREE}/qhwww" \
  "${ARTIFACTS}/frontend-dist/qhwww-${SNAPSHOT_DATE}.sha256"
write_tree_manifest "${PUBLIC_TREE}/goview/web" \
  "${ARTIFACTS}/frontend-dist/goview-web-${SNAPSHOT_DATE}.sha256"

archive_tree "${PUBLIC_TREE}" web \
  "${ARTIFACTS}/frontend-dist/qh-web-${SNAPSHOT_DATE}.tar.zst"
archive_tree "${PUBLIC_TREE}" admin \
  "${ARTIFACTS}/frontend-dist/qhadmin-${SNAPSHOT_DATE}.tar.zst"
archive_tree "${PUBLIC_TREE}" qhwww \
  "${ARTIFACTS}/frontend-dist/qhwww-${SNAPSHOT_DATE}.tar.zst"
archive_tree "${PUBLIC_TREE}/goview" web \
  "${ARTIFACTS}/frontend-dist/goview-web-${SNAPSHOT_DATE}.tar.zst"

write_tree_manifest "${PUBLIC_TREE}" \
  "${ARTIFACTS}/public-tree-${SNAPSHOT_DATE}.sha256"
tar --acls --xattrs --numeric-owner --sort=name -C "${PUBLIC_TREE}" -cf - . \
  | zstd -T0 -10 -q -o "${STAGE}/public-tree-${SNAPSHOT_DATE}.tar.zst"

(
  cd "${STAGE}"
  find artifacts -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum
  sha256sum "public-tree-${SNAPSHOT_DATE}.tar.zst"
) > "${STAGE}/DOWNLOADS.sha256"

{
  echo "snapshot_date=${SNAPSHOT_DATE}"
  echo "created_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "hostname=$(hostname)"
  echo "source_git_head=$(git -C /opt/quanthedge rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "source_git_branch=$(git -C /opt/quanthedge branch --show-current 2>/dev/null || echo unknown)"
  echo "database_encryption=OpenSSL CMS AES-256-CBC RSA-4096"
  echo "plaintext_database_files_in_export=no"
} > "${STAGE}/SNAPSHOT.txt"

rm -rf -- "${PRIVATE_TREE}"
rm -f -- "${STAGE}/private-backup.tar.zst"

chmod 600 "${STAGE}/qh-backup-recovery-private-${SNAPSHOT_DATE}.pem"
chown -R ubuntu:ubuntu "${STAGE}"
chmod 700 "${STAGE}"

echo "SNAPSHOT_DIR=${STAGE}"
echo "SNAPSHOT_READY=1"
