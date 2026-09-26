#!/usr/bin/env bash
# Entrypoint of the dbinit image: run bootstrap.sql (roles, schema, grants).
#
# Connection settings are libpq's own environment variables. On ECS the task
# definition (deploy/ecs/db-bootstrap.json.tmpl) sets PGHOST, PGPORT, and
# PGDATABASE, and injects PGUSER and PGPASSWORD from the RDS-managed master
# secret. TLS defaults to verify-full against the RDS CA bundle in the image;
# the local E2E stack overrides PGSSLMODE because its database has no TLS.
set -euo pipefail

: "${PGHOST:?PGHOST must be set}"
: "${PGUSER:?PGUSER must be set}"
: "${PGPASSWORD:?PGPASSWORD must be set}"
: "${DORA_OWNER_PASSWORD:?DORA_OWNER_PASSWORD must be set}"
: "${DORA_APP_PASSWORD:?DORA_APP_PASSWORD must be set}"

export PGDATABASE="${PGDATABASE:-dora}"
export PGSSLMODE="${PGSSLMODE:-verify-full}"
export PGSSLROOTCERT="${PGSSLROOTCERT:-/etc/ssl/rds/global-bundle.pem}"
export PGCONNECT_TIMEOUT="${PGCONNECT_TIMEOUT:-10}"

echo "run-bootstrap: ${PGUSER}@${PGHOST}/${PGDATABASE} (sslmode=${PGSSLMODE})" >&2
psql --no-psqlrc -v ON_ERROR_STOP=1 \
    -v owner_password="${DORA_OWNER_PASSWORD}" \
    -v app_password="${DORA_APP_PASSWORD}" \
    -f /bootstrap.sql
echo "run-bootstrap: done" >&2
