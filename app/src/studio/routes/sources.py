"""Registering data (Studio P0): upload CSV/Parquet or paste an HTTPS URL.
Bytes live in object storage behind the narrow `ObjectStore` seam; the row
carries the source's schema snapshot taken at registration (ADR-0007 D5).
No warehouse connectors — customer database credentials never enter the app
(ADR-0006 D10).
"""

import hashlib
import tempfile
import uuid
from collections.abc import Callable, Coroutine
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlparse

from chartagent.transform.schema import bucket_for
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from studio.auth import Session as AuthSession
from studio.auth import get_session
from studio.config import Settings
from studio.db import get_db
from studio.describe import (
    PARQUET_SUFFIXES,
    SchemaSnapshot,
    SourceDescriber,
    SourceUnreadableError,
)
from studio.ids import new_id
from studio.models import BindCache, DataSource
from studio.storage import ObjectStore, drop

_UPLOAD_SUFFIXES = (".csv", *PARQUET_SUFFIXES)


class _UploadSizeGuardRoute(APIRoute):
    """Refuse an over-limit upload from the Content-Length header, before the
    body is consumed. FastAPI parses form bodies before dependencies run, so
    the gate has to sit in front of the route handler itself."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            content_type = request.headers.get("content-type", "")
            if content_type.startswith("multipart/form-data"):
                _refuse_oversized(request)
            return await original(request)

        return handler


def _refuse_oversized(request: Request) -> None:
    settings: Settings = request.app.state.settings
    raw = request.headers.get("content-length")
    if raw is None:
        return
    try:
        declared = int(raw)
    except ValueError:
        return
    if declared > settings.upload_max_bytes:
        raise _oversized(settings)


def _oversized(settings: Settings) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        detail=(
            "Upload exceeds the configured limit of"
            f" {settings.upload_max_bytes} bytes"
        ),
    )


def _describe_or_422(
    describe: Callable[[], SchemaSnapshot], detail: str
) -> SchemaSnapshot:
    try:
        return describe()
    except SourceUnreadableError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail
        ) from None


class UrlSourceIn(BaseModel):
    # extra="forbid": a registration request cannot carry both shapes — the
    # API-level face of the data_sources_shape CHECK.
    model_config = ConfigDict(extra="forbid")

    url: str


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    object_key: str | None
    original_filename: str | None
    content_type: str | None
    byte_size: int | None
    sha256: str | None
    url: str | None
    schema_snapshot: dict[str, Any]
    created_at: datetime

    @field_validator("schema_snapshot")
    @classmethod
    def _annotate_buckets(cls, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Carry the library's buckets on the wire. Stored snapshot stays
        DuckDB reported types; Studio does not persist a second table or
        invent heads (ADR-0010 D5). `bucket_for` is the library's mapper —
        the public seam has no equivalent verb."""
        columns = snapshot.get("columns")
        if not isinstance(columns, list):
            return snapshot
        annotated: list[Any] = []
        for column in columns:
            if not isinstance(column, dict) or "type" not in column:
                annotated.append(column)
                continue
            annotated.append({**column, "bucket": bucket_for(str(column["type"]))})
        return {**snapshot, "columns": annotated}


router = APIRouter(route_class=_UploadSizeGuardRoute)


@router.post("/sources/upload", status_code=status.HTTP_201_CREATED)
def register_upload(
    request: Request,
    response: Response,
    session: Annotated[AuthSession, Depends(get_session)],
    db: Annotated[OrmSession, Depends(get_db)],
    file: Annotated[UploadFile, File()],
    url: Annotated[str | None, Form()] = None,
) -> SourceOut:
    if url is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="file and url are mutually exclusive",
        )
    settings: Settings = request.app.state.settings
    filename = Path(file.filename or "").name
    suffix = Path(filename).suffix.lower()
    if suffix not in _UPLOAD_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Uploads must be CSV or Parquet (.csv, .parquet, .pq)",
        )
    filename = filename or f"upload{suffix}"

    tmp_path, sha256_hex, byte_size = _spool_and_hash(file, settings, suffix)
    try:
        owner = session.owner_id
        existing = _find_upload(db, owner=owner, sha256=sha256_hex)
        if existing is not None:
            # Dedup: one blob, one source row (ADR-0007 D5). The partial
            # UNIQUE index enforces this; the SELECT makes reuse clean.
            response.status_code = status.HTTP_200_OK
            return SourceOut.model_validate(existing)

        describer: SourceDescriber = request.app.state.source_describer
        snapshot = _describe_or_422(
            lambda: describer.describe_upload(tmp_path, filename=filename),
            "The upload could not be read as CSV or Parquet",
        )

        object_key = f"{owner}/{sha256_hex}.{suffix.lstrip('.')}"
        store: ObjectStore = request.app.state.object_store
        try:
            with open(tmp_path, "rb") as source_bytes:
                store.put(object_key, source_bytes)
        except FileExistsError:
            # A concurrent identical upload won the write; the key is
            # content-addressed, so the bytes already stored are these bytes.
            pass

        row = DataSource(
            id=new_id(),
            owner_id=owner,
            kind="upload",
            object_key=object_key,
            original_filename=filename,
            content_type=file.content_type or "application/octet-stream",
            byte_size=byte_size,
            sha256=sha256_hex,
            url=None,
            schema_snapshot=snapshot,
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            # Lost the (owner_id, sha256) race; the winner's row is the answer.
            db.rollback()
            winner = _find_upload(db, owner=owner, sha256=sha256_hex)
            if winner is None:  # pragma: no cover — the index guarantees it
                raise
            response.status_code = status.HTTP_200_OK
            return SourceOut.model_validate(winner)
        db.refresh(row)
        return SourceOut.model_validate(row)
    finally:
        tmp_path.unlink(missing_ok=True)


@router.post("/sources", status_code=status.HTTP_201_CREATED)
def register_url_source(
    payload: UrlSourceIn,
    request: Request,
    session: Annotated[AuthSession, Depends(get_session)],
    db: Annotated[OrmSession, Depends(get_db)],
) -> SourceOut:
    parsed = urlparse(payload.url)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Only HTTPS URLs are accepted",
        )
    describer: SourceDescriber = request.app.state.source_describer
    snapshot = _describe_or_422(
        lambda: describer.describe_url(payload.url),
        "The URL could not be read as CSV or Parquet",
    )

    row = DataSource(
        id=new_id(),
        owner_id=session.owner_id,
        kind="url",
        object_key=None,
        original_filename=None,
        content_type=None,
        byte_size=None,
        sha256=None,
        url=payload.url,
        schema_snapshot=snapshot,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return SourceOut.model_validate(row)


@router.get("/sources")
def list_sources(
    session: Annotated[AuthSession, Depends(get_session)],
    db: Annotated[OrmSession, Depends(get_db)],
) -> list[SourceOut]:
    rows = db.scalars(
        select(DataSource)
        .where(DataSource.owner_id == session.owner_id)
        .order_by(DataSource.created_at.desc(), DataSource.id.desc())
    ).all()
    return [SourceOut.model_validate(row) for row in rows]


@router.get("/sources/{source_id}")
def get_source(
    source_id: uuid.UUID,
    session: Annotated[AuthSession, Depends(get_session)],
    db: Annotated[OrmSession, Depends(get_db)],
) -> SourceOut:
    # owner_id is a predicate, not a filter applied after the fact: another
    # owner's source is indistinguishable from a missing one.
    row = db.scalars(
        select(DataSource).where(
            DataSource.id == source_id,
            DataSource.owner_id == session.owner_id,
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Source not found"
        )
    return SourceOut.model_validate(row)


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(
    source_id: uuid.UUID,
    request: Request,
    session: Annotated[AuthSession, Depends(get_session)],
    db: Annotated[OrmSession, Depends(get_db)],
) -> Response:
    """Hard delete (ADR-0007 D9): charts become *pick a source*, the cache
    row cascades, and upload bytes leave only when this was the last
    `(owner_id, sha256)` row. Postgres does not empty the bucket."""
    row = db.scalars(
        select(DataSource).where(
            DataSource.id == source_id,
            DataSource.owner_id == session.owner_id,
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Source not found"
        )

    store: ObjectStore = request.app.state.object_store
    cache_keys = list(
        db.scalars(select(BindCache.cache_key).where(BindCache.source_id == row.id))
    )
    object_key = row.object_key
    # Unique index means at most one upload row per (owner, sha256); the
    # last-row check is the rule, not an accident of that index.
    drop_bytes = False
    if row.kind == "upload" and object_key is not None and row.sha256 is not None:
        other = db.scalars(
            select(DataSource.id).where(
                DataSource.owner_id == row.owner_id,
                DataSource.kind == "upload",
                DataSource.sha256 == row.sha256,
                DataSource.id != row.id,
            )
        ).first()
        drop_bytes = other is None

    db.delete(row)
    db.commit()
    for key in cache_keys:
        drop(store, key)
    if drop_bytes and object_key is not None:
        drop(store, object_key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _spool_and_hash(
    file: UploadFile, settings: Settings, suffix: str
) -> tuple[Path, str, int]:
    """Spool the upload to a temp file while hashing; refuse past the limit.

    Runs on the threadpool (sync route), so the file I/O never touches the
    event loop. The temp file is what DuckDB describes — it needs a path.
    """
    digest = hashlib.sha256()
    total = 0
    tmp = tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=suffix)
    try:
        while chunk := file.file.read(1024 * 1024):
            total += len(chunk)
            if total > settings.upload_max_bytes:
                raise _oversized(settings)
            digest.update(chunk)
            tmp.write(chunk)
    except BaseException:
        tmp.close()
        Path(tmp.name).unlink(missing_ok=True)
        raise
    tmp.close()
    return Path(tmp.name), digest.hexdigest(), total


def _find_upload(
    db: OrmSession, *, owner: str, sha256: str
) -> DataSource | None:
    return db.scalars(
        select(DataSource).where(
            DataSource.owner_id == owner,
            DataSource.kind == "upload",
            DataSource.sha256 == sha256,
        )
    ).first()
