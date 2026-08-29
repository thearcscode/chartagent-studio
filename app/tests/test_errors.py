"""The one error-mapping table (#77; ADR-0006 D13; #63 testing seam 1).

Each library error class maps to a status and a body that carries the
error's own typed fields. Studio does not re-test the library's validation,
transform or drift behaviour — only that it *carries* what the library
returns. An unmapped exception is a 500 with a request id and nothing else.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import SigningKeys, bearer_headers
from tests.test_charts import FRAME, TRANSFORM_FRAME, _preview_bind, _upload_source
from tests.test_refresh import CSV_MISSING_COLUMN, _saved_chart_with_cache


def _bind(
    client: TestClient,
    signing: SigningKeys,
    source_id: str,
    *,
    content: dict[str, Any] = FRAME,
    backend: str = "echarts",
) -> Any:
    return _preview_bind(
        client, signing, source_id, content=content, backend=backend
    )


def test_spec_shape_error_carries_its_code(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    response = db_client.post(
        "/api/specs",
        json={
            "content": {**FRAME, "data": {"values": [{"a": 1, "b": "x"}]}},
            "source_id": source_id,
        },
        headers=bearer_headers(signing),
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "spec_shape"
    assert "inline data" in body["message"]
    assert "request_id" not in body


def test_spec_vocabulary_error_carries_kind_keys_chart_type_backend_pin(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    response = _bind(
        db_client,
        signing,
        source_id,
        content={
            "chart_spec": {
                "chartType": "Rose Chart",
                "encodings": {"x": {"field": "b"}, "y": {"field": "a"}},
                "chartProperties": {"innerRadius": 40},
            }
        },
        backend="vegalite",
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "spec_vocabulary"
    assert body["kind"] == "property"
    assert "innerRadius" in body["keys"]
    assert body["chart_type"] == "Rose Chart"
    assert body["backend"] == "vegalite"
    assert body["pin"]


def test_backend_capability_error_carries_kind_keys_chart_type_backend_pin(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    response = _bind(
        db_client,
        signing,
        source_id,
        content={
            "chart_spec": {
                "chartType": "Bar Chart",
                "encodings": {
                    "x": {"field": "b"},
                    "y": {"field": "a"},
                    "column": {"field": "b"},
                },
            }
        },
        backend="excel",
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "backend_capability"
    assert body["kind"] == "facet"
    assert body["keys"] == ["column"]
    assert body["chart_type"] == "Bar Chart"
    assert body["backend"] == "excel"
    assert body["pin"]


def test_schema_drift_error_carries_stage_and_drifted_fields(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _saved_chart_with_cache(
        db_client, signing, source_id, content=TRANSFORM_FRAME
    )
    broken_id = _upload_source(db_client, signing, content=CSV_MISSING_COLUMN)
    response = db_client.post(
        f"/api/specs/{created['id']}/bind",
        json={"backend": "echarts", "source_id": broken_id, "trigger": "refresh"},
        headers=bearer_headers(signing),
    )
    assert response.status_code == 409
    body = response.json()
    assert body["error"] == "schema_drift"
    assert body["stage"] == "source"
    assert body["drifted"] == [
        {"name": "a", "kind": "dropped", "expected": "a", "found": None}
    ]


def test_data_source_error_carries_its_code(
    db_client: TestClient, signing: SigningKeys, monkeypatch: Any
) -> None:
    from chartagent.errors import DataSourceError

    source_id = _upload_source(db_client, signing)

    def explode(*args: object, **kwargs: object) -> object:
        raise DataSourceError("source cannot be read")

    monkeypatch.setattr("studio.routes.charts.bind", explode)
    response = _bind(db_client, signing, source_id)
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "data_source"
    assert "cannot be read" in body["message"]


def test_transform_error_carries_path(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    response = _bind(
        db_client,
        signing,
        source_id,
        content={
            "chart_spec": {
                "chartType": "Bar Chart",
                "encodings": {"x": {"field": "b"}, "y": {"field": "a"}},
            },
            "x_chartagent": {
                "transform": {
                    "raw_sql": "SELECT CAST('x' AS INTEGER) AS a, b FROM source"
                }
            },
        },
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "transform"
    # The library names the node that failed; Studio carries it.
    assert body["path"]


def test_raw_sql_rejected_error_carries_reason_and_path(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    response = _bind(
        db_client,
        signing,
        source_id,
        content={
            "chart_spec": {
                "chartType": "Bar Chart",
                "encodings": {"x": {"field": "b"}, "y": {"field": "a"}},
            },
            "x_chartagent": {"transform": {"raw_sql": "SELECT 1; SELECT 2"}},
        },
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "raw_sql_rejected"
    assert body["reason"] == "multi_statement"
    assert "path" in body


def test_unmapped_exception_is_500_with_request_id_only(
    signing: SigningKeys,
    tmp_path: Path,
    db_url: str,
    clean_db: None,
    monkeypatch: Any,
) -> None:
    from tests.conftest import make_app

    def explode(*args: object, **kwargs: object) -> object:
        raise RuntimeError("internal boom; must not leak")

    monkeypatch.setattr("studio.routes.charts.bind", explode)
    app = make_app(
        signing.jwks,
        database_url=db_url,
        object_store_dir=tmp_path / "objects",
    )
    # The handler turns the exception into a 500; the test client must not
    # re-raise it or we never see the body the UI gets.
    with TestClient(app, raise_server_exceptions=False) as client:
        source_id = _upload_source(client, signing)
        response = _bind(client, signing, source_id)
    assert response.status_code == 500
    body = response.json()
    assert set(body) == {"request_id"}
    assert body["request_id"]
    assert "boom" not in str(body)
    assert "RuntimeError" not in str(body)
