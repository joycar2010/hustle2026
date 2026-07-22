#!/bin/bash
set -o pipefail
TS=$(date +%Y%m%d_%H%M)
DIR=/data/mix/backups
for db in dcm_main mix_main coin_legacy; do
  if sudo -u postgres pg_dump $db | gzip > $DIR/${db}_${TS}.sql.gz; then
    SZ=$(stat -c%s $DIR/${db}_${TS}.sql.gz)
    if [ "$SZ" -lt 1000 ]; then echo "BACKUP_SUSPECT $db size=$SZ"; fi
  else
    rm -f $DIR/${db}_${TS}.sql.gz; echo "BACKUP_FAILED $db"
  fi
done
find $DIR -name "*.sql.gz" -mtime +14 -delete
