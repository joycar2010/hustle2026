#!/bin/bash
# Database backup script for Hustle XAU Arbitrage System

# Configuration
BACKUP_DIR="/var/backups/hustle_db"
DB_NAME="${DB_NAME:-hustle_db}"
DB_USER="${DB_USER:-hustle_user}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
RETENTION_DAYS=30

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Generate backup filename with timestamp
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="$BACKUP_DIR/hustle_db_$TIMESTAMP.sql.gz"

echo "Starting database backup..."
echo "Database: $DB_NAME"
echo "Backup file: $BACKUP_FILE"

# Perform backup
PGPASSWORD="$DB_PASSWORD" pg_dump \
    -h "$DB_HOST" \
    -p "$DB_PORT" \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    --format=plain \
    --no-owner \
    --no-acl \
    | gzip > "$BACKUP_FILE"

# Check if backup was successful
if [ $? -eq 0 ]; then
    echo "✅ Backup completed successfully"
    echo "Backup size: $(du -h "$BACKUP_FILE" | cut -f1)"

    # Remove old backups
    echo "Cleaning up old backups (older than $RETENTION_DAYS days)..."
    find "$BACKUP_DIR" -name "hustle_db_*.sql.gz" -type f -mtime +$RETENTION_DAYS -delete

    # List recent backups
    echo "Recent backups:"
    ls -lh "$BACKUP_DIR" | tail -5
else
    echo "❌ Backup failed"
    exit 1
fi

# Optional: Upload to cloud storage (uncomment and configure)
# aws s3 cp "$BACKUP_FILE" "s3://your-bucket/backups/"
# rclone copy "$BACKUP_FILE" "remote:backups/"

echo "Backup process completed"
