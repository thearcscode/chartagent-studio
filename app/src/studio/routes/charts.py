"""The ticket #74 seam: save a frame, bind it, and carry what the library
returns.

Save (ADR-0007 §4): explicit user action, numbered immutable revisions,
no-op on byte-identical content, `canonical_json()` stored verbatim, the
`source_schema` copy is the one place Studio touches `x_chartagent`.

Bind (ADR-0006 D4/D5): the server binds; preview binds write nothing,
user-initiated binds on saved charts write a `runs` row and replace the
cache — only when the cache is honest (ADR-0007 D8 erratum).
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import shutil
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from chartagent import Backend, InputFrame, bind, canonical_json, flint_bundle
from chartagent.errors import ChartAgentError
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from studio.auth import Session as AuthSession
from studio.auth import get_session
from studio.config import Settings
from studio.db import get_db
from studio.errors import RowCapExceededError, error_code_for
from studio.ids import new_id
from studio.models import BindCache, Chart, DataSource, Run, SpecRevision
from studio.observe import log_bind
from studio.storage import ObjectStore

router = APIRouter()

logger = logging.getLogger("studio")


# --------------------------------------------------------------------------
# Wire shapes
# --------------------------------------------------------------------------


class BindBlock(BaseModel):
    """The bound result the editor is looking at when the user hits Save —
    the save-writes-cache handoff. The server re-checks honesty against the
    posted frame before writing any cache (ADR-0007 D8 erratum)."""

    model_config = ConfigDict(extra="forbid")

    backend: Backend
    content: dict[str, Any]
    rows: list[dict[str, Any]]
    elapsed_ms: int
    source_schema: dict[str, str] | None = None


class SpecCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: dict[str, Any]
    source_id: uuid.UUID
    title: str | None = None
    bind: BindBlock | None = None


class SpecUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: dict[str, Any]
    title: str | None = None
    source_id: uuid.UUID | None = None
    bind: BindBlock | None = None


class PreviewBindIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: dict[str, Any]
    source_id: uuid.UUID
    backend: Backend


class SavedBindIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: Backend
    source_id: uuid.UUID | None = None
    trigger: Literal["open", "backend_switch"] = "open"


class AdvisoryOut(BaseModel):
    code: str
    message: str


class BindOut(BaseModel):
    """Envelope JSON (the three keys) plus diagnostics — the wire shape the
    browser compiles against (ADR-0006 D4)."""

    flint_version: str
    backend: str
    input: dict[str, Any]
    row_count: int
    elapsed: float
    warnings: list[AdvisoryOut]
    source_schema: dict[str, str] | None


class CacheOut(BaseModel):
    revision_id: uuid.UUID
    source_id: uuid.UUID
    row_count: int
    elapsed_ms: int
    bound_at: datetime


class SpecOut(BaseModel):
    id: uuid.UUID
    title: str
    kind: str
    revision_id: uuid.UUID
    revision_number: int
    content: dict[str, Any]
    content_hash: str
    authored_flint_version: str | None
    default_source_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    cache: CacheOut | None


class RunOut(BaseModel):
    id: uuid.UUID
    trigger_kind: str
    backend: str | None
    status: str
    error_code: str | None
    row_count: int | None
    elapsed_ms: int | None
    created_at: datetime


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def _store(request: Request) -> ObjectStore:
    return request.app.state.object_store  # type: ignore[no-any-return]


def _owned_chart(db: OrmSession, chart_id: uuid.UUID, owner_id: str) -> Chart:
    chart = db.get(Chart, chart_id)
    if chart is None or chart.owner_id != owner_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chart not found"
        )
    return chart


def _owned_source(db: OrmSession, source_id: uuid.UUID, owner_id: str) -> DataSource:
    source = db.get(DataSource, source_id)
    if source is None or source.owner_id != owner_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Source not found"
        )
    return source


def _current_revision(db: OrmSession, chart: Chart) -> SpecRevision:
    revision = db.get(SpecRevision, chart.current_revision_id)
    assert revision is not None  # the pointer is never null once set
    return revision


def _source_name(source: DataSource) -> str:
    if source.kind == "upload":
        return source.original_filename or "upload"
    parsed = urlparse(source.url or "")
    segment = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    return segment or parsed.netloc or "source"


def _default_title(content: dict[str, Any], source: DataSource) -> str:
    chart_type = InputFrame.model_validate(content).chart_spec.chart_type
    sentence = chart_type[:1] + chart_type[1:].lower()
    return f"{sentence} · {_source_name(source)}"


def _copy_source_schema(
    content: dict[str, Any], source_schema: dict[str, str] | None
) -> dict[str, Any]:
    """The one place Studio touches `x_chartagent` (ADR-0007 §4): copy
    `Envelope.source_schema` in verbatim, bumping `spec_version` to at least
    1.1 (the key exists from 1.1 on)."""
    doc: dict[str, Any] = json.loads(canonical_json(content))
    if source_schema is None:
        return doc
    xc = doc.setdefault("x_chartagent", {})
    xc["source_schema"] = source_schema
    version = xc.get("spec_version", "1.2")
    if tuple(int(p) for p in str(version).split(".")) < (1, 1):
        xc["spec_version"] = "1.1"
    result: dict[str, Any] = json.loads(canonical_json(doc))
    return result


def _strip_source_schema(doc: dict[str, Any]) -> dict[str, Any]:
    """Remove `x_chartagent.source_schema` for the cache-honesty comparison.
    A lone `spec_version` goes with it: it is a validation floor the
    canonical form materialises, with no effect on the rows a bind produces
    — and row-identity is what the comparison is about."""
    stripped = {k: v for k, v in doc.items() if k != "x_chartagent"}
    xc = doc.get("x_chartagent")
    if isinstance(xc, dict):
        rest = {k: v for k, v in xc.items() if k != "source_schema"}
        if rest and set(rest) != {"spec_version"}:
            stripped["x_chartagent"] = rest
    return stripped


def _cache_honest(
    stored: dict[str, Any], block: BindBlock
) -> bool:
    """ADR-0007 D8 erratum: the cache is written only if the saved frame is
    byte-identical to the frame the bound result came from, or differs only
    by the `source_schema` copied from that same bind's envelope. Otherwise
    the cache stays stale and the next open re-binds — staleness is never
    silent."""
    bound = json.loads(canonical_json(block.content))
    if canonical_json(stored) == canonical_json(bound):
        return True
    if block.source_schema is None:
        return False
    if stored.get("x_chartagent", {}).get("source_schema") != block.source_schema:
        return False
    return canonical_json(_strip_source_schema(stored)) == canonical_json(
        _strip_source_schema(bound)
    )


def _write_cache(
    db: OrmSession,
    store: ObjectStore,
    *,
    chart: Chart,
    revision: SpecRevision,
    source: DataSource,
    block: BindBlock,
) -> bool:
    """Cache row plus the sibling object `{revision_id, rows}` — written in
    the same request as the save or bind (ADR-0007 D6). The object goes down
    first; a store failure is logged and skips the cache (and its `save`
    run), never fails the save or bind itself (ADR-0007 §4)."""
    payload = json.dumps(
        {"revision_id": str(revision.id), "rows": block.rows}
    ).encode()
    cache_key = f"{chart.owner_id}/charts/{chart.id}/last_bind.json"
    try:
        store.replace(cache_key, io.BytesIO(payload))
    except Exception:
        # "Save succeeds even if cache object write fails" (#74) — whatever
        # the store raises (filesystem, S3, …), the cache is best-effort.
        logger.warning(
            "cache object write failed; skipping cache",
            extra={"chart_id": str(chart.id), "cache_key": cache_key},
        )
        return False
    cache = db.get(BindCache, chart.id)
    if cache is None:
        cache = BindCache(
            chart_id=chart.id, owner_id=chart.owner_id, cache_key=cache_key
        )
        db.add(cache)
    cache.revision_id = revision.id
    cache.source_id = source.id
    cache.row_count = len(block.rows)
    cache.elapsed_ms = block.elapsed_ms
    cache.bound_at = datetime.now(UTC)
    return True


def _record_run(
    db: OrmSession,
    *,
    owner_id: str,
    chart: Chart,
    revision: SpecRevision | None,
    source: DataSource | None,
    backend: str,
    trigger: str,
    outcome: Literal["ok", "error"],
    row_count: int | None = None,
    elapsed_ms: int | None = None,
    error: Exception | None = None,
) -> None:
    db.add(
        Run(
            id=new_id(),
            owner_id=owner_id,
            chart_id=chart.id,
            revision_id=revision.id if revision else None,
            source_id=source.id if source else None,
            backend=backend,
            trigger_kind=trigger,
            row_count=row_count,
            elapsed_ms=elapsed_ms,
            status=outcome,
            error_code=error_code_for(error) if error else None,
        )
    )


def _save_with_cache(
    db: OrmSession,
    store: ObjectStore,
    *,
    owner_id: str,
    chart: Chart,
    revision: SpecRevision,
    source: DataSource,
    doc: dict[str, Any],
    block: BindBlock | None,
) -> None:
    """Save-writes-cache (#74): when the saved frame is the bound frame
    (modulo the `source_schema` copy), write the cache and its `save` run in
    the same request. Otherwise the cache stays stale and the next open
    re-binds."""
    if block is None or not _cache_honest(doc, block):
        return
    if _write_cache(
        db, store, chart=chart, revision=revision, source=source, block=block
    ):
        _record_run(
            db,
            owner_id=owner_id,
            chart=chart,
            revision=revision,
            source=source,
            backend=block.backend,
            trigger="save",
            outcome="ok",
            row_count=len(block.rows),
            elapsed_ms=block.elapsed_ms,
        )


@contextmanager
def _bind_data(store: ObjectStore, source: DataSource) -> Iterator[str | Path]:
    """Resolve a registered source to what the library binds against: the
    URL itself, or a spooled temp file for an upload (the library reads
    paths/URLs; the object store is Studio's seam)."""
    if source.kind == "url":
        assert source.url is not None
        yield source.url
        return
    assert source.object_key is not None  # upload shape (DB CHECK)
    suffix = Path(source.object_key).suffix
    with store.open(source.object_key) as stream:
        fd, tmp_name = tempfile.mkstemp(suffix=suffix)
        try:
            with os.fdopen(fd, "wb") as tmp:
                shutil.copyfileobj(stream, tmp)
            yield Path(tmp_name)
        finally:
            Path(tmp_name).unlink(missing_ok=True)


def _do_bind(
    *,
    content: dict[str, Any],
    source: DataSource,
    backend: Backend,
    settings: Settings,
    store: ObjectStore,
) -> Any:
    """One library call behind the four caps (ADR-0006 D9). The row cap
    raises rather than truncates."""
    with _bind_data(store, source) as data:
        envelope = bind(
            content,
            data,
            backend=backend,
            timeout=settings.bind_timeout_seconds,
        )
    if envelope.row_count > settings.bind_row_cap:
        raise RowCapExceededError(
            row_count=envelope.row_count, cap=settings.bind_row_cap
        )
    return envelope


def _bind_out(envelope: Any) -> BindOut:
    return BindOut(
        flint_version=envelope.flint_version,
        backend=envelope.backend,
        input=envelope.input,
        row_count=envelope.row_count,
        elapsed=envelope.elapsed,
        warnings=[
            AdvisoryOut(code=w.code, message=w.message) for w in envelope.warnings
        ],
        source_schema=(
            dict(envelope.source_schema) if envelope.source_schema is not None else None
        ),
    )


def _spec_out(db: OrmSession, chart: Chart) -> SpecOut:
    revision = _current_revision(db, chart)
    cache = db.get(BindCache, chart.id)
    return SpecOut(
        id=chart.id,
        title=chart.title,
        kind=revision.kind,
        revision_id=revision.id,
        revision_number=revision.revision_number,
        content=revision.content,
        content_hash=revision.content_hash,
        authored_flint_version=revision.authored_flint_version,
        default_source_id=chart.default_source_id,
        created_at=chart.created_at,
        updated_at=chart.updated_at,
        cache=(
            CacheOut(
                revision_id=cache.revision_id,
                source_id=cache.source_id,
                row_count=cache.row_count,
                elapsed_ms=cache.elapsed_ms,
                bound_at=cache.bound_at,
            )
            if cache
            else None
        ),
    )


def _save_common(
    content: dict[str, Any], block: BindBlock | None
) -> tuple[dict[str, Any], str]:
    """Validate, copy `source_schema`, canonicalize. Returns (doc, hash)."""
    doc = _copy_source_schema(
        content, block.source_schema if block is not None else None
    )
    return doc, hashlib.sha256(canonical_json(doc).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


@router.post("/specs", status_code=status.HTTP_201_CREATED)
def create_spec(
    payload: SpecCreate,
    request: Request,
    session: Annotated[AuthSession, Depends(get_session)],
    db: Annotated[OrmSession, Depends(get_db)],
) -> SpecOut:
    source = _owned_source(db, payload.source_id, session.owner_id)
    doc, content_hash = _save_common(payload.content, payload.bind)
    title = (payload.title or "").strip() or _default_title(doc, source)

    chart_id = new_id()
    revision_id = new_id()
    chart = Chart(
        id=chart_id,
        owner_id=session.owner_id,
        title=title,
        current_revision_id=revision_id,
        default_source_id=source.id,
    )
    revision = SpecRevision(
        id=revision_id,
        chart_id=chart_id,
        owner_id=session.owner_id,
        revision_number=1,
        content_hash=content_hash,
        content=doc,
        kind="frame",
        authored_flint_version=flint_bundle().version,
    )
    db.add(chart)
    db.add(revision)

    _save_with_cache(
        db,
        _store(request),
        owner_id=session.owner_id,
        chart=chart,
        revision=revision,
        source=source,
        doc=doc,
        block=payload.bind,
    )

    db.commit()
    return _spec_out(db, chart)


@router.put("/specs/{chart_id}")
def update_spec(
    chart_id: uuid.UUID,
    payload: SpecUpdate,
    request: Request,
    session: Annotated[AuthSession, Depends(get_session)],
    db: Annotated[OrmSession, Depends(get_db)],
) -> SpecOut:
    chart = _owned_chart(db, chart_id, session.owner_id)
    source_id = payload.source_id or chart.default_source_id
    if source_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Chart has no source; pass source_id",
        )
    source = _owned_source(db, source_id, session.owner_id)
    current = _current_revision(db, chart)
    doc, content_hash = _save_common(payload.content, payload.bind)

    if payload.title is not None:
        stripped = payload.title.strip()
        if not stripped:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Title must not be blank",
            )
        chart.title = stripped
    if payload.source_id is not None:
        chart.default_source_id = source.id
    chart.updated_at = datetime.now(UTC)

    if content_hash == current.content_hash:
        # The no-op rule (ADR-0007 §4): same content, same revision — no new
        # row, no cache write. Metadata edits above still apply.
        db.commit()
        return _spec_out(db, chart)

    revision = SpecRevision(
        id=new_id(),
        chart_id=chart.id,
        owner_id=session.owner_id,
        revision_number=current.revision_number + 1,
        content_hash=content_hash,
        content=doc,
        kind="frame",
        authored_flint_version=flint_bundle().version,
    )
    db.add(revision)
    db.flush()
    chart.current_revision_id = revision.id

    _save_with_cache(
        db,
        _store(request),
        owner_id=session.owner_id,
        chart=chart,
        revision=revision,
        source=source,
        doc=doc,
        block=payload.bind,
    )

    db.commit()
    return _spec_out(db, chart)


@router.get("/specs/{chart_id}")
def get_spec(
    chart_id: uuid.UUID,
    session: Annotated[AuthSession, Depends(get_session)],
    db: Annotated[OrmSession, Depends(get_db)],
) -> SpecOut:
    chart = _owned_chart(db, chart_id, session.owner_id)
    return _spec_out(db, chart)


@router.get("/specs/{chart_id}/runs")
def list_runs(
    chart_id: uuid.UUID,
    session: Annotated[AuthSession, Depends(get_session)],
    db: Annotated[OrmSession, Depends(get_db)],
) -> list[RunOut]:
    chart = _owned_chart(db, chart_id, session.owner_id)
    runs = db.scalars(
        select(Run)
        .where(Run.chart_id == chart.id)
        .order_by(Run.created_at.desc())
        .limit(50)
    ).all()
    return [
        RunOut(
            id=run.id,
            trigger_kind=run.trigger_kind,
            backend=run.backend,
            status=run.status,
            error_code=run.error_code,
            row_count=run.row_count,
            elapsed_ms=run.elapsed_ms,
            created_at=run.created_at,
        )
        for run in runs
    ]


@router.post("/specs/bind")
def preview_bind(
    payload: PreviewBindIn,
    request: Request,
    session: Annotated[AuthSession, Depends(get_session)],
    db: Annotated[OrmSession, Depends(get_db)],
) -> BindOut:
    """The unsaved-frame bind: no chart, no cache, no run (ADR-0007 D6)."""
    source = _owned_source(db, payload.source_id, session.owner_id)
    envelope = _do_bind(
        content=payload.content,
        source=source,
        backend=payload.backend,
        settings=_settings(request),
        store=_store(request),
    )
    return _bind_out(envelope)


@router.post("/specs/{chart_id}/bind")
def saved_bind(
    chart_id: uuid.UUID,
    payload: SavedBindIn,
    request: Request,
    session: Annotated[AuthSession, Depends(get_session)],
    db: Annotated[OrmSession, Depends(get_db)],
) -> BindOut:
    """The user-initiated bind on a saved chart: writes a `runs` row either
    way, and replaces the cache on success (ADR-0007 D6/D8)."""
    chart = _owned_chart(db, chart_id, session.owner_id)
    revision = _current_revision(db, chart)
    source_id = payload.source_id or chart.default_source_id
    if source_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Chart has no source; pass source_id",
        )
    source = _owned_source(db, source_id, session.owner_id)
    if source.id != chart.default_source_id:
        chart.default_source_id = source.id  # ADR-0007 D5

    request_id: str | None = getattr(request.state, "request_id", None)
    try:
        envelope = _do_bind(
            content=revision.content,
            source=source,
            backend=payload.backend,
            settings=_settings(request),
            store=_store(request),
        )
    except (ChartAgentError, RowCapExceededError) as exc:
        _record_run(
            db,
            owner_id=session.owner_id,
            chart=chart,
            revision=revision,
            source=source,
            backend=payload.backend,
            trigger=payload.trigger,
            outcome="error",
            error=exc,
        )
        db.commit()
        log_bind(
            request_id=request_id,
            chart_id=str(chart.id),
            backend=payload.backend,
            trigger=payload.trigger,
            outcome="error",
            error_code=error_code_for(exc),
        )
        raise

    elapsed_ms = int(round(envelope.elapsed * 1000))
    rows: list[dict[str, Any]] = envelope.input["data"]["values"]
    block = BindBlock(
        backend=payload.backend,
        content=revision.content,
        rows=rows,
        elapsed_ms=elapsed_ms,
        source_schema=(
            dict(envelope.source_schema) if envelope.source_schema is not None else None
        ),
    )
    # A failed cache object write skips the cache row but not the run — the
    # bind happened and the run is its audit (ADR-0007 §4, D6).
    _write_cache(
        db, _store(request), chart=chart, revision=revision, source=source, block=block
    )
    _record_run(
        db,
        owner_id=session.owner_id,
        chart=chart,
        revision=revision,
        source=source,
        backend=payload.backend,
        trigger=payload.trigger,
        outcome="ok",
        row_count=envelope.row_count,
        elapsed_ms=elapsed_ms,
    )
    db.commit()
    log_bind(
        request_id=request_id,
        chart_id=str(chart.id),
        backend=payload.backend,
        trigger=payload.trigger,
        outcome="ok",
        row_count=envelope.row_count,
        elapsed_ms=elapsed_ms,
        advisories=tuple(w.code for w in envelope.warnings),
    )
    return _bind_out(envelope)
