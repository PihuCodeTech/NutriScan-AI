#!/bin/sh
# Restore a database dump made by backup.sh into the LIVE database. Destructive: replaces every table.
#
#   docker compose stop api
#   docker compose run --rm -e CONFIRM=yes backup sh /backup/restore.sh /backups/db-<STAMP>.dump
#   docker compose start api          # runs `alembic upgrade head` first, so an older dump is migrated forward
#
# Runs in a single transaction: if anything fails, the database is left exactly as it was.
set -eu
dump=${1:?usage: restore.sh /backups/db-<STAMP>.dump}
[ -f "$dump" ] || { echo "no such file: $dump" >&2; exit 1; }
if [ "${CONFIRM:-}" != "yes" ]; then
    echo "This REPLACES all data in database '$PGDATABASE' on '$PGHOST' with $dump." >&2
    echo "Stop the api service first, then re-run with -e CONFIRM=yes." >&2
    exit 1
fi
pg_restore --list "$dump" >/dev/null
pg_restore --clean --if-exists --no-owner --no-privileges --exit-on-error --single-transaction \
    --dbname="$PGDATABASE" "$dump"
echo "restored $dump into $PGDATABASE: $(psql -Atc 'select count(*) from users') users"
