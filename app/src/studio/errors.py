"""The one error-mapping table (ADR-0006 D13): each library error class →
status code → user-facing body carrying the error's own typed fields, so the
UI can name an offending key or a drifted field list rather than "something
went wrong". Planner errors join the same table (Studio ADR-0001 D10).
`pydantic.ValidationError` never crosses the library seam, so it never
reaches this table. An unmapped exception is a 500 with a request id and
nothing else.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from chartagent.errors import (
    BackendCapabilityError,
    DataSourceError,
    InexpressibleRequestError,
    ModelClientUnavailableError,
    PlannerFailureError,
    RawSqlRejectedError,
    SchemaDriftError,
    SpecShapeError,
    SpecVocabularyError,
    TransformError,
    UnanswerableInstructionError,
)
from fastapi import Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger("studio")


class RowCapExceededError(Exception):
    """Studio's own refusal: the bind returned more rows than the configured
    cap. Raises, never truncates (ADR-0006 D9)."""

    def __init__(self, *, row_count: int, cap: int) -> None:
        super().__init__(
            f"bind returned {row_count} rows, over the configured cap of {cap}"
        )
        self.row_count = row_count
        self.cap = cap


class ModelVendorError(Exception):
    """A model-vendor transport, auth, or model-string failure, wrapped so a
    rate limit does not read as a Studio bug (Studio ADR-0001 D10)."""

    def __init__(self, *, request_id: str | None) -> None:
        super().__init__("the model vendor is unavailable")
        self.request_id = request_id


class PlanBusyError(Exception):
    """The plan-concurrency semaphore is full (Studio ADR-0001 D8)."""

    def __init__(self) -> None:
        super().__init__("try again shortly")


def _body(message: str, code: str, **fields: Any) -> dict[str, Any]:
    return {"error": code, "message": message, **fields}


def _spec_shape(exc: SpecShapeError) -> tuple[int, dict[str, Any]]:
    return status.HTTP_422_UNPROCESSABLE_CONTENT, _body(str(exc), "spec_shape")


def _spec_vocabulary(exc: SpecVocabularyError) -> tuple[int, dict[str, Any]]:
    return status.HTTP_422_UNPROCESSABLE_CONTENT, _body(
        str(exc),
        "spec_vocabulary",
        kind=exc.kind,
        keys=list(exc.keys),
        chart_type=exc.chart_type,
        backend=exc.backend,
        pin=exc.pin,
    )


def _backend_capability(exc: BackendCapabilityError) -> tuple[int, dict[str, Any]]:
    return status.HTTP_422_UNPROCESSABLE_CONTENT, _body(
        str(exc),
        "backend_capability",
        kind=exc.kind,
        keys=list(exc.keys),
        chart_type=exc.chart_type,
        backend=exc.backend,
        pin=exc.pin,
    )


def _schema_drift(exc: SchemaDriftError) -> tuple[int, dict[str, Any]]:
    return status.HTTP_409_CONFLICT, _body(
        str(exc),
        "schema_drift",
        stage=exc.stage,
        drifted=[
            {
                "name": field.name,
                "kind": field.kind,
                "expected": field.expected,
                "found": field.found,
            }
            for field in exc.drifted
        ],
    )


def _data_source(exc: DataSourceError) -> tuple[int, dict[str, Any]]:
    return status.HTTP_422_UNPROCESSABLE_CONTENT, _body(str(exc), "data_source")


def _raw_sql_rejected(exc: RawSqlRejectedError) -> tuple[int, dict[str, Any]]:
    return status.HTTP_422_UNPROCESSABLE_CONTENT, _body(
        str(exc), "raw_sql_rejected", reason=exc.reason, path=exc.path
    )


def _transform(exc: TransformError) -> tuple[int, dict[str, Any]]:
    return status.HTTP_422_UNPROCESSABLE_CONTENT, _body(
        str(exc), "transform", path=exc.path
    )


def _row_cap(exc: RowCapExceededError) -> tuple[int, dict[str, Any]]:
    return status.HTTP_422_UNPROCESSABLE_CONTENT, _body(
        str(exc), "row_cap_exceeded", row_count=exc.row_count, cap=exc.cap
    )


def _inexpressible(exc: InexpressibleRequestError) -> tuple[int, dict[str, Any]]:
    return status.HTTP_422_UNPROCESSABLE_CONTENT, _body(
        str(exc), "inexpressible_request", bucket=exc.bucket
    )


def _unanswerable(exc: UnanswerableInstructionError) -> tuple[int, dict[str, Any]]:
    return status.HTTP_422_UNPROCESSABLE_CONTENT, _body(
        str(exc),
        "unanswerable_instruction",
        kind=exc.kind,
        keys=list(exc.keys),
    )


def _planner_failure(exc: PlannerFailureError) -> tuple[int, dict[str, Any]]:
    return status.HTTP_502_BAD_GATEWAY, _body(
        str(exc), "planner_failure", reason=exc.reason
    )


def _model_client_unavailable(
    exc: ModelClientUnavailableError,
) -> tuple[int, dict[str, Any]]:
    return status.HTTP_500_INTERNAL_SERVER_ERROR, _body(
        str(exc), "model_client_unavailable", extra=exc.extra
    )


def _model_vendor(exc: ModelVendorError) -> tuple[int, dict[str, Any]]:
    return status.HTTP_502_BAD_GATEWAY, {
        "error": "model_vendor_unavailable",
        "request_id": exc.request_id,
    }


def _plan_busy(exc: PlanBusyError) -> tuple[int, dict[str, Any]]:
    return status.HTTP_503_SERVICE_UNAVAILABLE, _body(str(exc), "plan_busy")


# Subclass-before-base where one exists (RawSqlRejectedError is a
# TransformError); lookup walks the MRO, so order here is documentation.
_MAPPERS: dict[type[Exception], Callable[[Any], tuple[int, dict[str, Any]]]] = {
    SpecShapeError: _spec_shape,
    SpecVocabularyError: _spec_vocabulary,
    BackendCapabilityError: _backend_capability,
    SchemaDriftError: _schema_drift,
    DataSourceError: _data_source,
    RawSqlRejectedError: _raw_sql_rejected,
    TransformError: _transform,
    RowCapExceededError: _row_cap,
    InexpressibleRequestError: _inexpressible,
    UnanswerableInstructionError: _unanswerable,
    PlannerFailureError: _planner_failure,
    ModelClientUnavailableError: _model_client_unavailable,
    ModelVendorError: _model_vendor,
    PlanBusyError: _plan_busy,
}


def map_error(exc: Exception) -> tuple[int, dict[str, Any]] | None:
    """The mapping table lookup. None means unmapped → 500 with a request id."""
    for cls in type(exc).__mro__:
        mapper = _MAPPERS.get(cls)
        if mapper is not None:
            return mapper(exc)
    return None


def error_code_for(exc: Exception) -> str:
    """The stable code written to `runs.error_code` — the typed error's
    class name (the library's public contract), or Studio's own refusal."""
    return type(exc).__name__


async def chartagent_error_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    mapped = map_error(exc)
    if mapped is None:  # a ChartAgentError subclass we have no row for
        return await unmapped_error_handler(request, exc)
    status_code, body = mapped
    return JSONResponse(status_code=status_code, content=body)


async def mapped_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """A Studio or library type that has a row in the table."""
    mapped = map_error(exc)
    assert mapped is not None  # registered for the mapped class only
    status_code, body = mapped
    return JSONResponse(status_code=status_code, content=body)


async def unmapped_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """500 with a request id and nothing else — internals do not leak."""
    request_id = getattr(request.state, "request_id", None)
    logger.error(
        json.dumps(
            {
                "event": "unmapped_exception",
                "request_id": request_id,
                "path": request.url.path,
                "error": f"{type(exc).__name__}: {exc}",
            }
        ),
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    content = {"request_id": request_id} if request_id else {}
    return JSONResponse(status_code=500, content=content)
