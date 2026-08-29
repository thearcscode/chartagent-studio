"""The five tables in their final, post-ADR-0018 shape (ADR-0007 D14 as
amended): `content` rather than `frame`, `kind` present with its default,
`authored_flint_version` and `runs.backend` nullable. This repo was empty, so
there is nothing to migrate — writing the ADR-0018 ALTERs first would be
theatre (#63, Further notes).

Revision ID: 0001
Revises:
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Ids are app-generated UUIDv7: no database default, because the object
    # key needs the id before the row exists.
    op.create_table(
        "charts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("current_revision_id", sa.Uuid(), nullable=False),
        sa.Column("default_source_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(btrim(title)) > 0", name="charts_title_not_blank"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "spec_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chart_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Text(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.CHAR(64), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("kind", sa.Text(), server_default="frame", nullable=False),
        sa.Column("authored_flint_version", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "revision_number > 0", name="spec_revisions_revision_number_positive"
        ),
        sa.CheckConstraint(
            "kind IN ('frame','recipe')", name="spec_revisions_kind_check"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chart_id", "revision_number"),
        sa.UniqueConstraint("chart_id", "content_hash"),
        sa.ForeignKeyConstraint(["chart_id"], ["charts.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "data_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=True),
        sa.Column("original_filename", sa.Text(), nullable=True),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.CHAR(64), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("schema_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('upload','url')", name="data_sources_kind_check"
        ),
        sa.CheckConstraint(
            "(kind = 'upload' AND url IS NULL"
            " AND object_key IS NOT NULL AND original_filename IS NOT NULL"
            " AND content_type IS NOT NULL AND byte_size IS NOT NULL"
            " AND sha256 IS NOT NULL)"
            " OR (kind = 'url' AND url IS NOT NULL"
            " AND object_key IS NULL AND original_filename IS NULL"
            " AND content_type IS NULL AND byte_size IS NULL AND sha256 IS NULL)",
            name="data_sources_shape",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "bind_caches",
        sa.Column("chart_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Text(), nullable=False),
        sa.Column("cache_key", sa.Text(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("elapsed_ms", sa.Integer(), nullable=False),
        sa.Column("bound_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("chart_id"),
        sa.ForeignKeyConstraint(["chart_id"], ["charts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["revision_id"], ["spec_revisions.id"], ondelete="CASCADE"
        ),
        # CASCADE, deliberately unlike charts.default_source_id: a cache
        # whose source is gone is not stale, it is meaningless (D9).
        sa.ForeignKeyConstraint(
            ["source_id"], ["data_sources.id"], ondelete="CASCADE"
        ),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Text(), nullable=False),
        sa.Column("chart_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=True),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("backend", sa.Text(), nullable=True),
        sa.Column("trigger_kind", sa.Text(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "backend IN ('echarts','vegalite','chartjs','plotly','excel')",
            name="runs_backend_check",
        ),
        sa.CheckConstraint(
            "trigger_kind IN ('refresh','open','backend_switch','save')",
            name="runs_trigger_kind_check",
        ),
        sa.CheckConstraint("status IN ('ok','error')", name="runs_status_check"),
        sa.CheckConstraint(
            "(status = 'ok' AND error_code IS NULL)"
            " OR (status = 'error' AND error_code IS NOT NULL)",
            name="runs_error_shape",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["chart_id"], ["charts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["revision_id"], ["spec_revisions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["data_sources.id"], ondelete="SET NULL"
        ),
    )

    # The cross-references on charts land last (D14: presentation order is
    # not creation order).
    op.create_foreign_key(
        "charts_current_revision_fk",
        "charts",
        "spec_revisions",
        ["current_revision_id"],
        ["id"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "charts_default_source_fk",
        "charts",
        "data_sources",
        ["default_source_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index(
        "charts_owner_updated_idx", "charts", ["owner_id", sa.text("updated_at DESC")]
    )
    op.create_index(
        "revisions_chart_rev_idx",
        "spec_revisions",
        ["chart_id", sa.text("revision_number DESC")],
    )
    op.create_index(
        "sources_owner_created_idx",
        "data_sources",
        ["owner_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "sources_owner_sha_idx",
        "data_sources",
        ["owner_id", "sha256"],
        unique=True,
        postgresql_where=sa.text("kind = 'upload'"),
    )
    op.create_index("caches_source_idx", "bind_caches", ["source_id"])
    op.create_index(
        "runs_chart_created_idx", "runs", ["chart_id", sa.text("created_at DESC")]
    )


def downgrade() -> None:
    op.drop_index("runs_chart_created_idx", table_name="runs")
    op.drop_index("caches_source_idx", table_name="bind_caches")
    op.drop_index(
        "sources_owner_sha_idx",
        table_name="data_sources",
        postgresql_where=sa.text("kind = 'upload'"),
    )
    op.drop_index("sources_owner_created_idx", table_name="data_sources")
    op.drop_index("revisions_chart_rev_idx", table_name="spec_revisions")
    op.drop_index("charts_owner_updated_idx", table_name="charts")
    op.drop_constraint("charts_default_source_fk", "charts", type_="foreignkey")
    op.drop_constraint("charts_current_revision_fk", "charts", type_="foreignkey")
    op.drop_table("runs")
    op.drop_table("bind_caches")
    op.drop_table("data_sources")
    op.drop_table("spec_revisions")
    op.drop_table("charts")
