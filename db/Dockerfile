# syntax=docker/dockerfile:1

# The dbinit image (docs/CLOUD-DEVOPS-DESIGN.md §6.5, §7.3, C8): runs
# bootstrap.sql against RDS as the master user, as a one-off ECS task on every
# deploy. The script is idempotent, so reruns change nothing.
FROM postgres:18.6

ARG APP_VERSION=unknown
ARG GIT_SHA=unknown
ARG BUILD_TIME=unknown
ARG SOURCE_URL=https://github.com/loriamichaelj/dora

LABEL org.opencontainers.image.title="dora-dbinit" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.created="${BUILD_TIME}" \
      org.opencontainers.image.source="${SOURCE_URL}"

# The same pinned RDS CA bundle as api/Dockerfile: psql verifies the
# database's certificate (PGSSLMODE=verify-full). Create the directory first,
# as there: ADD --chmod would make a directory it creates untraversable.
RUN install -d -m 0755 /etc/ssl/rds
ADD --checksum=sha256:e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3 --chmod=644 \
    https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem /etc/ssl/rds/global-bundle.pem

COPY --chmod=644 bootstrap.sql /bootstrap.sql
COPY --chmod=755 run-bootstrap.sh /usr/local/bin/run-bootstrap

# Only the client is used; never start a server here.
USER postgres
ENTRYPOINT ["run-bootstrap"]
