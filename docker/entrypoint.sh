#!/bin/sh
# Apply database migrations, then start the API.
set -e
alembic upgrade head
exec "$@"
