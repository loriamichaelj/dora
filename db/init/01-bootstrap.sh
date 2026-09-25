#!/usr/bin/env bash
# Local wrapper for db/bootstrap.sql (§6.4). The postgres image runs this from
# /docker-entrypoint-initdb.d only when the data volume is empty.
set -euo pipefail

: "${DORA_OWNER_PASSWORD:?DORA_OWNER_PASSWORD must be set}"
: "${DORA_APP_PASSWORD:?DORA_APP_PASSWORD must be set}"

psql --no-psqlrc --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v ON_ERROR_STOP=1 \
    -v owner_password="$DORA_OWNER_PASSWORD" \
    -v app_password="$DORA_APP_PASSWORD" \
    -f /bootstrap.sql
