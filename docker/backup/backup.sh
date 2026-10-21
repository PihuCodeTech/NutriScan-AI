#!/bin/sh
# One backup run (docker compose "backup" service): dump PostgreSQL, PROVE the dump restores by loading it into a
# scratch database, archive the uploaded photos, prune old backups, then report success or failure.
#
# Connection: the standard libpq variables PGHOST, PGUSER, PGPASSWORD, PGDATABASE.
# Optional:   BACKUP_RETENTION_DAYS (14), BACKUP_DIR (/backups), UPLOADS_DIR (/data/uploads),
#             BACKUP_HEARTBEAT_URL  dead-man's switch (e.g. healthchecks.io): pinged on success, <url>/fail on
#                                   failure, so a backup that silently stops running also raises an alert,
#             ALERT_WEBHOOK_URL     Slack/Discord webhook told about failures.
# Never prints PGPASSWORD or the URLs above: they are secrets.
set -eu
umask 077  # dumps hold every user's data (emails, password hashes, meals): owner-only

BACKUP_DIR=${BACKUP_DIR:-/backups}
UPLOADS_DIR=${UPLOADS_DIR:-/data/uploads}
RETENTION_DAYS=${BACKUP_RETENTION_DAYS:-14}
VERIFY_DB="${PGDATABASE}_restore_check"
# Tables a usable restore must contain (alembic_version proves the schema version came along).
REQUIRED_TABLES="alembic_version users profiles scans scan_items intake_entries chat_sessions chat_messages foods"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DUMP="$BACKUP_DIR/db-$STAMP.dump"
UPLOADS="$BACKUP_DIR/uploads-$STAMP.tar.gz"
STARTED=$(date +%s)

log() { printf '{"ts":"%s","level":"%s","logger":"backup","msg":"%s"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2"; }

ping_url() {  # ping_url <url> [json-body]; best effort, never fails the run
    [ -n "$1" ] || return 0
    if [ -n "${2:-}" ]; then
        wget -q -T 10 -O /dev/null --header 'Content-Type: application/json' --post-data "$2" "$1" 2>/dev/null \
            || log WARNING "notification failed"
    else
        wget -q -T 10 -O /dev/null "$1" 2>/dev/null || log WARNING "heartbeat ping failed"
    fi
}

fail() {
    log ERROR "backup failed: $1"
    rm -f "$DUMP.partial" "$UPLOADS.partial"
    dropdb --if-exists "$VERIFY_DB" >/dev/null 2>&1 || true
    msg="🔴 [backup] NutriScan database backup FAILED at step: $1. Check: docker compose logs backup"
    ping_url "${ALERT_WEBHOOK_URL:-}" "{\"text\":\"$msg\",\"content\":\"$msg\"}"
    [ -n "${BACKUP_HEARTBEAT_URL:-}" ] && ping_url "${BACKUP_HEARTBEAT_URL%/}/fail"
    exit 1
}

mkdir -p "$BACKUP_DIR"

# 1. Dump (custom format: compressed, restorable table by table). Written to .partial, renamed when complete.
log INFO "dumping database"
pg_dump --format=custom --no-owner --no-privileges --file="$DUMP.partial" || fail "pg_dump"
mv "$DUMP.partial" "$DUMP"

# 2. Verify: restore into a scratch database and check the schema and data are there.
log INFO "verifying dump by restoring it into $VERIFY_DB"
dropdb --if-exists "$VERIFY_DB" || fail "drop old scratch database"
createdb "$VERIFY_DB" || fail "create scratch database"
pg_restore --no-owner --no-privileges --exit-on-error --dbname="$VERIFY_DB" "$DUMP" || fail "test restore"
for table in $REQUIRED_TABLES; do
    found=$(psql -d "$VERIFY_DB" -Atc "select to_regclass('public.$table') is not null") || fail "verify query"
    [ "$found" = "t" ] || fail "restored copy is missing table $table"
done
[ "$(psql -d "$VERIFY_DB" -Atc 'select count(*) from alembic_version')" = "1" ] || fail "restored copy has no schema version"
# Row counts (no row contents) so the log shows the restored copy is not empty.
counts=$(psql -d "$VERIFY_DB" -Atc "select 'users=' || (select count(*) from users) || ' scans=' || (select count(*) from scans) || ' intake=' || (select count(*) from intake_entries) || ' chat_messages=' || (select count(*) from chat_messages)") \
    || fail "verify query"
dropdb "$VERIFY_DB" || log WARNING "could not drop $VERIFY_DB"
log INFO "restore check passed: $counts"

# 3. Uploaded photos (signed-URL media). Skipped if the volume isn't mounted.
if [ -d "$UPLOADS_DIR" ]; then
    tar -czf "$UPLOADS.partial" -C "$(dirname "$UPLOADS_DIR")" "$(basename "$UPLOADS_DIR")" || fail "archive uploads"
    tar -tzf "$UPLOADS.partial" >/dev/null || fail "verify uploads archive"
    mv "$UPLOADS.partial" "$UPLOADS"
else
    log WARNING "uploads directory $UPLOADS_DIR not mounted; photos not backed up"
fi

# 4. Retention. Only files older than RETENTION_DAYS go; the backup just written is never among them.
find "$BACKUP_DIR" -maxdepth 1 \( -name 'db-*.dump' -o -name 'uploads-*.tar.gz' \) -mtime +"$RETENTION_DAYS" \
    -exec rm -f {} + || log WARNING "pruning old backups failed"

date -u +%Y-%m-%dT%H:%M:%SZ > "$BACKUP_DIR/last_success"
size=$(du -h "$DUMP" | cut -f1)
log INFO "backup ok: $(basename "$DUMP") ($size) in $(( $(date +%s) - STARTED ))s, keeping ${RETENTION_DAYS} days"
ping_url "${BACKUP_HEARTBEAT_URL:-}"
