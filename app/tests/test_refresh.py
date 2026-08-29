"""Zero-LLM refresh (#75): one bind against the chart's default source — or
a chosen source that then becomes default — with no model, no planner, no
new revision. Success replaces the cache and moves `bound_at`; failure
writes an error run and leaves the cache (and the picture it backs)
untouched, with drift named field by field. Asserted through the HTTP API
only (#63 "Testing decisions").
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import SigningKeys, bearer_headers
from tests.test_charts import (
    CSV_BYTES_2,
    FRAME,
    TRANSFORM_FRAME,
    _bind_block,
    _create_spec,
    _preview_bind,
    _runs,
    _upload_source,
)

# A CSV whose columns lack the `a` the transform frame references.
CSV_MISSING_COLUMN = b"c,b\n4,p\n5,q\n"


def _refresh(
    client: TestClient,
    signing: SigningKeys,
    chart_id: str,
    *,
    source_id: str | None = None,
    backend: str = "echarts",
    sub: str = "user_2abc",
) -> Any:
    payload: dict[str, Any] = {"backend": backend, "trigger": "refresh"}
    if source_id is not None:
        payload["source_id"] = source_id
    return client.post(
        f"/api/specs/{chart_id}/bind",
        json=payload,
        headers=bearer_headers(signing, sub=sub),
    )


def _saved_chart_with_cache(
    client: TestClient,
    signing: SigningKeys,
    source_id: str,
    *,
    content: dict[str, Any] = FRAME,
) -> dict[str, Any]:
    envelope = _preview_bind(client, signing, source_id, content=content).json()
    created = _create_spec(
        client,
        signing,
        source_id,
        content=content,
        bind=_bind_block(envelope, content=content),
    )
    assert created.status_code == 201
    body: dict[str, Any] = created.json()
    assert body["cache"] is not None  # the honest save wrote the cache
    return body


def _refresh_runs(
    client: TestClient, signing: SigningKeys, chart_id: str
) -> list[dict[str, Any]]:
    return [
        run
        for run in _runs(client, signing, chart_id)
        if run["trigger_kind"] == "refresh"
    ]


def test_refresh_against_the_default_source_moves_the_cache_pointer(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _saved_chart_with_cache(db_client, signing, source_id)

    response = _refresh(db_client, signing, created["id"])
    assert response.status_code == 200
    assert response.json()["row_count"] == 3

    # No new revision: the document is untouched, so the diff stays empty.
    fetched = db_client.get(
        f"/api/specs/{created['id']}", headers=bearer_headers(signing)
    ).json()
    assert fetched["revision_number"] == 1
    assert fetched["revision_id"] == created["revision_id"]
    assert fetched["content_hash"] == created["content_hash"]

    # The cache was replaced: same rows, but bound_at moved.
    assert fetched["cache"]["source_id"] == source_id
    assert fetched["cache"]["row_count"] == 3
    assert fetched["cache"]["bound_at"] > created["cache"]["bound_at"]

    refresh_runs = _refresh_runs(db_client, signing, created["id"])
    assert [(r["status"], r["backend"], r["row_count"]) for r in refresh_runs] == [
        ("ok", "echarts", 3)
    ]


def test_refresh_with_a_chosen_source_replaces_the_cache_and_moves_the_default(
    db_client: TestClient, signing: SigningKeys
) -> None:
    first_id = _upload_source(db_client, signing)
    second_id = _upload_source(db_client, signing, content=CSV_BYTES_2)
    created = _saved_chart_with_cache(db_client, signing, first_id)
    assert created["cache"]["row_count"] == 3

    response = _refresh(db_client, signing, created["id"], source_id=second_id)
    assert response.status_code == 200
    assert response.json()["row_count"] == 2  # the second CSV's rows

    fetched = db_client.get(
        f"/api/specs/{created['id']}", headers=bearer_headers(signing)
    ).json()
    assert fetched["revision_number"] == 1  # still no new revision
    assert fetched["default_source_id"] == second_id  # the chosen source is now default
    assert fetched["cache"]["source_id"] == second_id
    assert fetched["cache"]["row_count"] == 2
    assert fetched["cache"]["bound_at"] > created["cache"]["bound_at"]

    refresh_runs = _refresh_runs(db_client, signing, created["id"])
    assert [(r["status"], r["row_count"]) for r in refresh_runs] == [("ok", 2)]


def test_failed_refresh_keeps_the_previous_cache_and_the_default(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _saved_chart_with_cache(
        db_client, signing, source_id, content=TRANSFORM_FRAME
    )
    assert created["cache"]["row_count"] == 2  # the a > 1 filter keeps two rows
    broken_id = _upload_source(db_client, signing, content=CSV_MISSING_COLUMN)

    response = _refresh(db_client, signing, created["id"], source_id=broken_id)
    assert response.status_code == 409

    refresh_runs = _refresh_runs(db_client, signing, created["id"])
    assert [(r["status"], r["error_code"]) for r in refresh_runs] == [
        ("error", "SchemaDriftError")
    ]

    # The cache pointer still names the old successful bind, exactly — a
    # failed refresh must not blank a card that was showing a chart.
    fetched = db_client.get(
        f"/api/specs/{created['id']}", headers=bearer_headers(signing)
    ).json()
    assert fetched["cache"] == created["cache"]
    assert fetched["default_source_id"] == source_id
    assert fetched["revision_number"] == 1


def test_refresh_drift_error_names_the_drifted_fields(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _saved_chart_with_cache(
        db_client, signing, source_id, content=TRANSFORM_FRAME
    )
    broken_id = _upload_source(db_client, signing, content=CSV_MISSING_COLUMN)

    response = _refresh(db_client, signing, created["id"], source_id=broken_id)
    assert response.status_code == 409
    body = response.json()
    assert body["error"] == "schema_drift"
    assert body["stage"] == "source"
    assert body["drifted"] == [
        {"name": "a", "kind": "dropped", "expected": "a", "found": None}
    ]


def test_cross_owner_refresh_fails(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _saved_chart_with_cache(db_client, signing, source_id)

    response = _refresh(db_client, signing, created["id"], sub="user_other")
    assert response.status_code == 404

    # No run, no cache change on the real owner's side.
    runs = _runs(db_client, signing, created["id"])
    assert [r["trigger_kind"] for r in runs] == ["save"]
    fetched = db_client.get(
        f"/api/specs/{created['id']}", headers=bearer_headers(signing)
    ).json()
    assert fetched["cache"] == created["cache"]
