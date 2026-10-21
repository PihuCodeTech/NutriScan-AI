#!/bin/sh
# Healthy while the last successful backup is younger than BACKUP_INTERVAL_HOURS + 2 h (shown by `docker ps`).
max_age_min=$(( (${BACKUP_INTERVAL_HOURS:-24} + 2) * 60 ))
[ -n "$(find /backups/last_success -mmin -"$max_age_min" 2>/dev/null)" ]
