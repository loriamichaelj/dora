"""Initial schema: default privileges for dora_app, then the §6.2 tables.

Revision ID: 0001
Revises:
Create Date: 2026-09-25

Runs as dora_owner. Default privileges are granted *before* any table exists,
so dora_app gets DML on every table without the migration needing role
membership the RDS master user may not have (§6.4).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "dora"


def _uuid_pk() -> sa.Column[object]:
    return sa.Column(
        "id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuidv7()"), nullable=False
    )


def _timestamp(name: str) -> sa.Column[object]:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _version() -> sa.Column[object]:
    return sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False)


def upgrade() -> None:
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA dora "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO dora_app"
    )

    op.create_table(
        "services",
        _uuid_pk(),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("owner_team", sa.Text(), nullable=False),
        sa.Column("repo_url", sa.Text(), nullable=True),
        _version(),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.CheckConstraint("slug ~ '^[a-z0-9][a-z0-9-]{1,62}$'", name="ck_services_slug"),
        sa.CheckConstraint("length(name) BETWEEN 1 AND 200", name="ck_services_name"),
        sa.CheckConstraint(
            "length(owner_team) BETWEEN 1 AND 100", name="ck_services_owner_team"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_services"),
        sa.UniqueConstraint("slug", name="uq_services_slug"),
        schema=SCHEMA,
    )

    op.create_table(
        "deployments",
        _uuid_pk(),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("environment", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), server_default=sa.text("'planned'"), nullable=False),
        sa.Column("release", sa.Text(), nullable=False),
        sa.Column("head_sha", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deployed_by", sa.Text(), nullable=True),
        sa.Column("pipeline_url", sa.Text(), nullable=True),
        sa.Column("external_id", sa.Text(), nullable=True),
        _version(),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.CheckConstraint(
            "environment IN ('development', 'staging', 'production')",
            name="ck_deployments_environment",
        ),
        sa.CheckConstraint("kind IN ('planned', 'remediation')", name="ck_deployments_kind"),
        sa.CheckConstraint("length(release) BETWEEN 1 AND 100", name="ck_deployments_release"),
        sa.CheckConstraint("head_sha ~ '^[0-9a-f]{7,40}$'", name="ck_deployments_head_sha"),
        sa.CheckConstraint(
            "status IN ('in_progress', 'succeeded', 'failed', 'rolled_back')",
            name="ck_deployments_status",
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at", name="finished_after_started"
        ),
        sa.CheckConstraint(
            "status = 'in_progress' OR finished_at IS NOT NULL", name="terminal_has_finish"
        ),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["dora.services.id"],
            name="fk_deployments_service_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_deployments"),
        sa.UniqueConstraint("service_id", "external_id", name="uq_service_external"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_deployments_live",
        "deployments",
        ["environment", "finished_at", "service_id"],
        schema=SCHEMA,
        postgresql_where=sa.text("status IN ('succeeded', 'rolled_back')"),
    )
    op.create_index(
        "ix_deployments_service_started",
        "deployments",
        ["service_id", sa.text("started_at DESC")],
        schema=SCHEMA,
    )

    op.create_table(
        "commits",
        _uuid_pk(),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sha", sa.Text(), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("author", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        _timestamp("created_at"),
        sa.CheckConstraint("sha ~ '^[0-9a-f]{7,40}$'", name="ck_commits_sha"),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["dora.services.id"],
            name="fk_commits_service_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_commits"),
        sa.UniqueConstraint("service_id", "sha", name="uq_service_sha"),
        schema=SCHEMA,
    )

    op.create_table(
        "deployment_commits",
        sa.Column("deployment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("commit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["deployment_id"],
            ["dora.deployments.id"],
            name="fk_deployment_commits_deployment_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["commit_id"],
            ["dora.commits.id"],
            name="fk_deployment_commits_commit_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("deployment_id", "commit_id", name="pk_deployment_commits"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_deployment_commits_commit", "deployment_commits", ["commit_id"], schema=SCHEMA
    )

    op.create_table(
        "failures",
        _uuid_pk(),
        sa.Column("deployment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_ref", sa.Text(), nullable=True),
        _version(),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.CheckConstraint(
            "severity IN ('sev1', 'sev2', 'sev3', 'sev4')", name="ck_failures_severity"
        ),
        sa.CheckConstraint("length(summary) BETWEEN 1 AND 500", name="ck_failures_summary"),
        sa.CheckConstraint(
            "resolved_at IS NULL OR resolved_at >= detected_at", name="resolved_after_detected"
        ),
        sa.ForeignKeyConstraint(
            ["deployment_id"],
            ["dora.deployments.id"],
            name="fk_failures_deployment_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_failures"),
        schema=SCHEMA,
    )
    op.create_index("ix_failures_deployment", "failures", ["deployment_id"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_table("failures", schema=SCHEMA)
    op.drop_table("deployment_commits", schema=SCHEMA)
    op.drop_table("commits", schema=SCHEMA)
    op.drop_table("deployments", schema=SCHEMA)
    op.drop_table("services", schema=SCHEMA)
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA dora "
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM dora_app"
    )
