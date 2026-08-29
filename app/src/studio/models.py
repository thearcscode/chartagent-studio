"""The five tables (ADR-0007 D14), created in their final, post-ADR-0018
shape: `content` (not `frame`), `kind` present, `authored_flint_version` and
`runs.backend` nullable. Enumerated columns are text + CHECK, never Postgres
ENUM (ADR-0007 D13). `owner_id` is denormalised onto all five tables on
purpose (ADR-0007 D10) — do not "normalise" it away.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CHAR, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Chart(Base):
    __tablename__ = "charts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    # The two tables reference each other, so the constraint is DEFERRABLE
    # INITIALLY DEFERRED and created via ALTER TABLE (ADR-0007 D3); use_alter
    # keeps the metadata cycle-free for autogenerate and create_all.
    current_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "spec_revisions.id",
            name="charts_current_revision_fk",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        )
    )
    default_source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "data_sources.id", name="charts_default_source_fk", ondelete="SET NULL"
        )
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("length(btrim(title)) > 0", name="charts_title_not_blank"),
        Index("charts_owner_updated_idx", "owner_id", text("updated_at DESC")),
    )


class SpecRevision(Base):
    __tablename__ = "spec_revisions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    chart_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("charts.id", ondelete="CASCADE")
    )
    owner_id: Mapped[str] = mapped_column(Text)
    revision_number: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(CHAR(64))
    # canonical_json() output verbatim — a frame or a ChartRecipe, never
    # shredded into queryable columns (ADR-0007 D2, ADR-0018 D7).
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # The DEFAULT exists for the migration; every insert writes the value.
    kind: Mapped[str] = mapped_column(Text, server_default="frame")
    # Recorded fact about which pin authored a frame, never a gate
    # (ADR-0007 D11); meaningless for a recipe, hence nullable (ADR-0018 D8).
    authored_flint_version: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "revision_number > 0", name="spec_revisions_revision_number_positive"
        ),
        CheckConstraint("kind IN ('frame','recipe')", name="spec_revisions_kind_check"),
        UniqueConstraint("chart_id", "revision_number"),
        UniqueConstraint("chart_id", "content_hash"),
        Index(
            "revisions_chart_rev_idx", "chart_id", text("revision_number DESC")
        ),
    )


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    # Upload shape: object_key is {owner_id}/{sha256}.{ext}, write-once.
    object_key: Mapped[str | None] = mapped_column(Text)
    original_filename: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(Text)
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(CHAR(64))
    # URL shape.
    url: Mapped[str | None] = mapped_column(Text)
    # The SOURCE's schema at registration — not the spec's planning baseline
    # (ADR-0007 D15; CONTEXT.md "Source schema baseline").
    schema_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("kind IN ('upload','url')", name="data_sources_kind_check"),
        CheckConstraint(
            "(kind = 'upload' AND url IS NULL"
            " AND object_key IS NOT NULL AND original_filename IS NOT NULL"
            " AND content_type IS NOT NULL AND byte_size IS NOT NULL"
            " AND sha256 IS NOT NULL)"
            " OR (kind = 'url' AND url IS NOT NULL"
            " AND object_key IS NULL AND original_filename IS NULL"
            " AND content_type IS NULL AND byte_size IS NULL AND sha256 IS NULL)",
            name="data_sources_shape",
        ),
        Index("sources_owner_created_idx", "owner_id", text("created_at DESC")),
        # Partial unique: dedup is enforced, not hoped for (ADR-0007 D5).
        Index(
            "sources_owner_sha_idx",
            "owner_id",
            "sha256",
            unique=True,
            postgresql_where=text("kind = 'upload'"),
        ),
    )


class BindCache(Base):
    __tablename__ = "bind_caches"

    chart_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("charts.id", ondelete="CASCADE"), primary_key=True
    )
    owner_id: Mapped[str] = mapped_column(Text)
    cache_key: Mapped[str] = mapped_column(Text)
    revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("spec_revisions.id", ondelete="CASCADE")
    )
    # CASCADE, deliberately unlike charts.default_source_id: a cache whose
    # source is gone is not stale, it is meaningless (ADR-0007 D9).
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_sources.id", ondelete="CASCADE")
    )
    row_count: Mapped[int] = mapped_column(Integer)
    elapsed_ms: Mapped[int] = mapped_column(Integer)
    bound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("caches_source_idx", "source_id"),)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(Text)
    chart_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("charts.id", ondelete="CASCADE")
    )
    # SET NULL so history survives its referents (ADR-0007 D9).
    revision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("spec_revisions.id", ondelete="SET NULL")
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("data_sources.id", ondelete="SET NULL")
    )
    # Nullable: a custom-rail bind has no backend (ADR-0018 D8). Nothing in P0
    # writes a null backend.
    backend: Mapped[str | None] = mapped_column(Text)
    # trigger_kind, not trigger: TRIGGER is reserved in SQL (ADR-0007 D7).
    trigger_kind: Mapped[str] = mapped_column(Text)
    row_count: Mapped[int | None] = mapped_column(Integer)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "backend IN ('echarts','vegalite','chartjs','plotly','excel')",
            name="runs_backend_check",
        ),
        CheckConstraint(
            "trigger_kind IN ('refresh','open','backend_switch','save')",
            name="runs_trigger_kind_check",
        ),
        CheckConstraint("status IN ('ok','error')", name="runs_status_check"),
        CheckConstraint(
            "(status = 'ok' AND error_code IS NULL)"
            " OR (status = 'error' AND error_code IS NOT NULL)",
            name="runs_error_shape",
        ),
        Index("runs_chart_created_idx", "chart_id", text("created_at DESC")),
    )
