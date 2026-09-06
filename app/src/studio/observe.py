"""Structured JSON logs to stdout; no third-party APM (ADR-0006 D13). Every
bind logs backend, row count, elapsed and advisory codes — the audit trail
behind the cost-and-latency line. Logs are not the product trail: a log line
cannot be rendered into a card.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from studio.ids import new_id

logger = logging.getLogger("studio")


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        try:
            payload: dict[str, Any] = json.loads(message)
        except (ValueError, TypeError):
            payload = {"event": "log", "message": message}
        payload.setdefault("level", record.levelname.lower())
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    if any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Stamps every request with an id (the only thing an unmapped 500 may
    carry) and enforces the configured request timeout — the backstop cap;
    the DuckDB statement timeout is the real guard for bind work. A timed-out
    sync route keeps running on its thread; the client gets an honest 504."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.request_id = new_id().hex
        settings = request.app.state.settings
        try:
            response = await asyncio.wait_for(
                call_next(request), timeout=settings.request_timeout_seconds
            )
        except TimeoutError:
            logger.warning(
                json.dumps(
                    {
                        "event": "request_timeout",
                        "request_id": request.state.request_id,
                        "path": request.url.path,
                        "timeout_seconds": settings.request_timeout_seconds,
                    }
                )
            )
            return JSONResponse(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                content={
                    "error": "request_timeout",
                    "request_id": request.state.request_id,
                },
            )
        response.headers["X-Request-Id"] = request.state.request_id
        return response


def log_bind(
    *,
    request_id: str | None,
    chart_id: str | None,
    backend: str,
    trigger: str,
    outcome: str,
    row_count: int | None = None,
    elapsed_ms: int | None = None,
    advisories: tuple[str, ...] = (),
    error_code: str | None = None,
) -> None:
    """One JSON line per bind — success or failure (ADR-0006 D13)."""
    logger.info(
        json.dumps(
            {
                "event": "bind",
                "request_id": request_id,
                "chart_id": chart_id,
                "backend": backend,
                "trigger": trigger,
                "outcome": outcome,
                "row_count": row_count,
                "elapsed_ms": elapsed_ms,
                "advisories": list(advisories),
                "error_code": error_code,
            }
        )
    )


def log_plan(
    *,
    request_id: str | None,
    backend: str | None,
    outcome: str,
    row_count: int | None = None,
    elapsed_ms: int | None = None,
    plan_elapsed_ms: int | None = None,
    error_code: str | None = None,
) -> None:
    """One JSON line per plan — success or failure (Studio ADR-0001 D5)."""
    logger.info(
        json.dumps(
            {
                "event": "plan",
                "request_id": request_id,
                "backend": backend,
                "outcome": outcome,
                "row_count": row_count,
                "elapsed_ms": elapsed_ms,
                "plan_elapsed_ms": plan_elapsed_ms,
                "error_code": error_code,
            }
        )
    )
