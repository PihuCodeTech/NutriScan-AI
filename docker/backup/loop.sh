#!/bin/sh
# Entry point of the compose "backup" service: back up now, then every BACKUP_INTERVAL_HOURS (default 24).
# A failed run is reported by backup.sh (webhook + heartbeat /fail) and retried at the next interval.
interval=$(( ${BACKUP_INTERVAL_HOURS:-24} * 3600 ))
while true; do
    sh /backup/backup.sh || true
    sleep "$interval"
done
