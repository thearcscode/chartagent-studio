"""POST /api/specs/plan — a draft from an instruction, store nothing (#19).

Seams (parent #17): the HTTP API through the test client, and the chart
agent on app state replaced by a stub. The stub returns a canned envelope
or raises a chosen error. Nothing here re-tests the library planner.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from chartagent import ChartResult
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from studio.models import BindCache, Chart, Run, SpecRevision
from studio.routes.charts import BindOut
from tests.conftest import SigningKeys, bearer_headers
from tests.test_charts import FRAME, _upload_source

BIND_KEYS = {
    "flint_version",
    "backend",
    "input",
    "row_count",
    "elapsed",
    "warnings",
    "source_schema",
}


def _envelope(
    *,
    row_count: int = 3,
    elapsed: float = 0.01,
    backend: str = "vegalite",
    warnings: tuple[Any, ...] = (),
    source_schema: dict[str, str] | None = None,
) -> SimpleNamespace:
    rows = [{"a": i, "b": letter} for i, letter in enumerate("xyz", start=1)][
        :row_count
    ]
    return SimpleNamespace(
        flint_version="0.1.0",
        backend=backend,
        input={**FRAME, "data": {"values": rows}},
        row_count=row_count,
        elapsed=elapsed,
        warnings=warnings,
        source_schema=source_schema if source_schema is not None else {"a": "number"},
    )


class _StubAgent:
    """Stand-in for ChartAgent: one create_chart, no backend kwarg."""

    def __init__(self, result: ChartResult | BaseException) -> None:
        self._result = result
        self.data: object | None = None
        self.instruction: str | None = None

    def create_chart(self, data: object, instruction: str) -> ChartResult:
        self.data = data
        self.instruction = instruction
        if isinstance(self._result, BaseException):
            raise self._result
        return self._result


def _plan(
    client: TestClient,
    signing: SigningKeys,
    source_id: str,
    *,
    instruction: str = "revenue by region",
    sub: str = "user_2abc",
) -> Any:
    return client.post(
        "/api/specs/plan",
        json={"instruction": instruction, "source_id": source_id},
        headers=bearer_headers(signing, sub=sub),
    )


def test_bind_out_has_no_plan_elapsed_ms() -> None:
    assert "plan_elapsed_ms" not in BindOut.model_fields


def test_plan_returns_bind_keys_plus_plan_elapsed_ms(
    db_app: FastAPI, db_client: TestClient, signing: SigningKeys
) -> None:
    canned = _envelope(
        warnings=(SimpleNamespace(code="theme_spec_ignored", message="ignored"),)
    )
    db_app.state.chart_agent = _StubAgent(ChartResult(envelope=canned))  # type: ignore[arg-type]
    source_id = _upload_source(db_client, signing)

    response = _plan(db_client, signing, source_id)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == BIND_KEYS | {"plan_elapsed_ms"}
    assert body["flint_version"] == "0.1.0"
    assert body["backend"] == "vegalite"
    assert body["input"]["data"]["values"] == [
        {"a": 1, "b": "x"},
        {"a": 2, "b": "y"},
        {"a": 3, "b": "z"},
    ]
    assert body["row_count"] == 3
    assert body["elapsed"] == 0.01
    assert body["warnings"] == [{"code": "theme_spec_ignored", "message": "ignored"}]
    assert body["source_schema"] == {"a": "number"}
    assert isinstance(body["plan_elapsed_ms"], int)
    assert body["plan_elapsed_ms"] >= 0


def test_plan_elapsed_ms_is_clamped_at_zero(
    db_app: FastAPI, db_client: TestClient, signing: SigningKeys
) -> None:
    # Envelope bind time dwarfs an instant stub call — the clamp, not a
    # negative, is what the cost line must be able to print.
    db_app.state.chart_agent = _StubAgent(
        ChartResult(envelope=_envelope(elapsed=100.0))  # type: ignore[arg-type]
    )
    source_id = _upload_source(db_client, signing)

    body = _plan(db_client, signing, source_id).json()

    assert body["plan_elapsed_ms"] == 0


def test_plan_writes_nothing(
    db_app: FastAPI, db_client: TestClient, signing: SigningKeys
) -> None:
    db_app.state.chart_agent = _StubAgent(
        ChartResult(envelope=_envelope())  # type: ignore[arg-type]
    )
    source_id = _upload_source(db_client, signing)
    assert _plan(db_client, signing, source_id).status_code == 200

    listing = db_client.get("/api/specs", headers=bearer_headers(signing))
    assert listing.status_code == 200
    assert listing.json() == []

    with db_app.state.session_factory() as session:
        for model in (Chart, SpecRevision, BindCache, Run):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_plan_passes_a_url_source_as_the_url(
    db_app: FastAPI, db_client: TestClient, signing: SigningKeys
) -> None:
    stub = _StubAgent(ChartResult(envelope=_envelope()))  # type: ignore[arg-type]
    db_app.state.chart_agent = stub
    url = "https://example.com/sales.csv"
    registered = db_client.post(
        "/api/sources",
        json={"url": url},
        headers=bearer_headers(signing),
    )
    assert registered.status_code == 201
    assert _plan(db_client, signing, registered.json()["id"]).status_code == 200
    assert stub.data == url
    assert stub.instruction == "revenue by region"


def test_plan_row_cap_raises_rather_than_truncates(
    signing: SigningKeys, tmp_path: Path, db_url: str, clean_db: None
) -> None:
    from tests.conftest import make_app

    app = make_app(
        signing.jwks,
        database_url=db_url,
        object_store_dir=tmp_path / "objects",
        bind_row_cap=2,
    )
    app.state.chart_agent = _StubAgent(
        ChartResult(envelope=_envelope(row_count=3))  # type: ignore[arg-type]
    )
    with TestClient(app) as client:
        source_id = _upload_source(client, signing)
        response = _plan(client, signing, source_id)
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "row_cap_exceeded"
    assert body["row_count"] == 3
    assert body["cap"] == 2


# --- Error mappings (Studio ADR-0001 D10) -----------------------------------


def test_inexpressible_request_is_422_with_bucket(
    db_app: FastAPI, db_client: TestClient, signing: SigningKeys
) -> None:
    from chartagent.errors import InexpressibleRequestError

    db_app.state.chart_agent = _StubAgent(
        InexpressibleRequestError("cannot express this", bucket=2)
    )
    source_id = _upload_source(db_client, signing)
    response = _plan(db_client, signing, source_id)
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "inexpressible_request"
    assert body["bucket"] == 2


def test_unanswerable_instruction_is_422_with_kind_and_keys(
    db_app: FastAPI, db_client: TestClient, signing: SigningKeys
) -> None:
    from chartagent.errors import UnanswerableInstructionError

    db_app.state.chart_agent = _StubAgent(
        UnanswerableInstructionError(
            "column is missing", kind="missing_column", keys=("revenue",)
        )
    )
    source_id = _upload_source(db_client, signing)
    response = _plan(db_client, signing, source_id)
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "unanswerable_instruction"
    assert body["kind"] == "missing_column"
    assert body["keys"] == ["revenue"]


def test_planner_failure_is_502_with_reason(
    db_app: FastAPI, db_client: TestClient, signing: SigningKeys
) -> None:
    from chartagent.errors import PlannerFailureError

    db_app.state.chart_agent = _StubAgent(
        PlannerFailureError("step 1 failed", reason="retries_exhausted")
    )
    source_id = _upload_source(db_client, signing)
    response = _plan(db_client, signing, source_id)
    assert response.status_code == 502
    body = response.json()
    assert body["error"] == "planner_failure"
    assert body["reason"] == "retries_exhausted"


def test_model_client_unavailable_is_500_with_extra(
    db_app: FastAPI, db_client: TestClient, signing: SigningKeys
) -> None:
    from chartagent.errors import ModelClientUnavailableError

    db_app.state.chart_agent = _StubAgent(
        ModelClientUnavailableError(
            "extra is not installed", extra="chartagent[anthropic]"
        )
    )
    source_id = _upload_source(db_client, signing)
    response = _plan(db_client, signing, source_id)
    assert response.status_code == 500
    body = response.json()
    assert body["error"] == "model_client_unavailable"
    assert body["extra"] == "chartagent[anthropic]"


def test_backend_capability_from_plan_uses_the_existing_422(
    db_app: FastAPI, db_client: TestClient, signing: SigningKeys
) -> None:
    from chartagent.errors import BackendCapabilityError

    db_app.state.chart_agent = _StubAgent(
        BackendCapabilityError(
            "excel cannot facet",
            kind="facet",
            keys=("column",),
            chart_type="Bar Chart",
            backend="excel",
            pin="0.1.0",
        )
    )
    source_id = _upload_source(db_client, signing)
    response = _plan(db_client, signing, source_id)
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "backend_capability"
    assert body["kind"] == "facet"
    assert body["keys"] == ["column"]
    assert body["chart_type"] == "Bar Chart"
    assert body["backend"] == "excel"
    assert body["pin"] == "0.1.0"


class _VendorRateLimit(Exception):
    """Not a ChartAgentError — the shape a vendor client raises."""


def test_vendor_exception_is_502_not_500(
    signing: SigningKeys, tmp_path: Path, db_url: str, clean_db: None
) -> None:
    from tests.conftest import make_app

    app = make_app(
        signing.jwks,
        database_url=db_url,
        object_store_dir=tmp_path / "objects",
    )
    app.state.chart_agent = _StubAgent(_VendorRateLimit("429 too many requests"))
    with TestClient(app, raise_server_exceptions=False) as client:
        source_id = _upload_source(client, signing)
        response = _plan(client, signing, source_id)
    assert response.status_code == 502
    body = response.json()
    assert body["error"] == "model_vendor_unavailable"
    assert "request_id" in body
    assert body["request_id"]
    assert "429" not in str(body)
    assert "too many" not in str(body)


def test_plan_is_503_when_the_semaphore_is_full(
    signing: SigningKeys, tmp_path: Path, db_url: str, clean_db: None
) -> None:
    from tests.conftest import make_app

    app = make_app(
        signing.jwks,
        database_url=db_url,
        object_store_dir=tmp_path / "objects",
        plan_concurrency=1,
    )
    app.state.chart_agent = _StubAgent(
        ChartResult(envelope=_envelope())  # type: ignore[arg-type]
    )
    with TestClient(app) as client:
        source_id = _upload_source(client, signing)
        assert app.state.plan_semaphore.acquire(blocking=False)
        try:
            response = _plan(client, signing, source_id)
            assert response.status_code == 503
            assert response.json()["error"] == "plan_busy"
        finally:
            app.state.plan_semaphore.release()
        later = _plan(client, signing, source_id)
    assert later.status_code == 200


def test_plan_releases_the_semaphore_after_a_failure(
    signing: SigningKeys, tmp_path: Path, db_url: str, clean_db: None
) -> None:
    from chartagent.errors import PlannerFailureError

    from tests.conftest import make_app

    app = make_app(
        signing.jwks,
        database_url=db_url,
        object_store_dir=tmp_path / "objects",
        plan_concurrency=1,
    )
    app.state.chart_agent = _StubAgent(
        PlannerFailureError("broke", reason="empty_response")
    )
    with TestClient(app) as client:
        source_id = _upload_source(client, signing)
        failed = _plan(client, signing, source_id)
        assert failed.status_code == 502
        app.state.chart_agent = _StubAgent(
            ChartResult(envelope=_envelope())  # type: ignore[arg-type]
        )
        retry = _plan(client, signing, source_id)
    assert retry.status_code == 200


def test_plan_requires_a_session(db_client: TestClient, signing: SigningKeys) -> None:
    source_id = _upload_source(db_client, signing)
    response = db_client.post(
        "/api/specs/plan",
        json={"instruction": "revenue by region", "source_id": source_id},
    )
    assert response.status_code == 401
