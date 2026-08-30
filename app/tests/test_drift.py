"""The missing baseline and a retype carried through Studio (#8). The
library's drift detection is not re-tested — only that Studio *carries*
`retype_unchecked` and a `retyped` `DriftedField` so the recovery screen
can name them. Asserted through the HTTP API (#81 "Testing decisions").
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import SigningKeys, bearer_headers
from tests.test_charts import (
    TRANSFORM_FRAME,
    _bind_block,
    _create_spec,
    _preview_bind,
    _upload_source,
)
from tests.test_refresh import _refresh, _refresh_runs, _saved_chart_with_cache

# Transform names `a` and `b`; the baseline records only `a`. A partial
# baseline still checks the columns it has (ADR-0010 D7).
PARTIAL_FRAME: dict[str, Any] = {
    "chart_spec": {
        "chartType": "Bar Chart",
        "encodings": {"x": {"field": "b"}, "y": {"field": "a"}},
    },
    "x_chartagent": {
        "spec_version": "1.1",
        "transform": {
            "filter": {
                "kind": "and",
                "args": [
                    {
                        "kind": "is_not_null",
                        "args": [{"kind": "col", "name": "a"}],
                    },
                    {
                        "kind": "is_not_null",
                        "args": [{"kind": "col", "name": "b"}],
                    },
                ],
            }
        },
        "source_schema": {"a": "number"},
    },
}

# Same column names as the saved transform, but `a` is a string — a retype
# against a `number` baseline. DuckDB reports VARCHAR, bucket `string`.
CSV_RETYPED = b"a,b\nhello,x\nworld,y\n"


def test_frame_with_no_baseline_binds_and_surfaces_retype_unchecked(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    response = _preview_bind(db_client, signing, source_id, content=TRANSFORM_FRAME)
    assert response.status_code == 200
    body = response.json()
    # Rows so the client can draw — absence of a baseline is not a refusal.
    assert body["row_count"] == 2
    codes = [item["code"] for item in body["warnings"]]
    assert "retype_unchecked" in codes
    message = next(
        item["message"]
        for item in body["warnings"]
        if item["code"] == "retype_unchecked"
    )
    assert "a" in message
    assert "absent" in message


def test_partial_baseline_binds_and_names_the_unchecked_columns(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    response = _preview_bind(db_client, signing, source_id, content=PARTIAL_FRAME)
    assert response.status_code == 200
    body = response.json()
    assert body["row_count"] == 3
    message = next(
        item["message"]
        for item in body["warnings"]
        if item["code"] == "retype_unchecked"
    )
    assert "b" in message
    # `a` is in the baseline and is still checked — it is not in the
    # unchecked list (the names after the last colon).
    assert "a" not in message.split(":")[-1]


def test_partial_baseline_still_carries_a_retype_on_a_named_column(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    envelope = _preview_bind(
        db_client, signing, source_id, content=PARTIAL_FRAME
    ).json()
    created = _create_spec(
        db_client,
        signing,
        source_id,
        content=PARTIAL_FRAME,
        bind=_bind_block(envelope, content=PARTIAL_FRAME),
    )
    assert created.status_code == 201
    body = created.json()
    broken_id = _upload_source(db_client, signing, content=CSV_RETYPED)

    response = _refresh(db_client, signing, body["id"], source_id=broken_id)
    assert response.status_code == 409
    payload = response.json()
    assert payload["error"] == "schema_drift"
    assert payload["drifted"] == [
        {"name": "a", "kind": "retyped", "expected": "number", "found": "string"}
    ]
    # The failed refresh is a run with an error code; the cache is not
    # replaced (P0). This ticket does not change that.
    refresh_runs = _refresh_runs(db_client, signing, body["id"])
    assert [(r["status"], r["error_code"]) for r in refresh_runs] == [
        ("error", "SchemaDriftError")
    ]
    fetched = db_client.get(
        f"/api/specs/{body['id']}", headers=bearer_headers(signing)
    ).json()
    assert fetched["cache"] == body["cache"]


def test_cross_owner_chart_is_not_a_recovery_surface(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _saved_chart_with_cache(db_client, signing, source_id)
    headers = bearer_headers(signing, sub="user_other")
    assert (
        db_client.get(f"/api/specs/{created['id']}", headers=headers).status_code
        == 404
    )
    assert (
        db_client.post(
            f"/api/specs/{created['id']}/bind",
            json={"backend": "echarts", "trigger": "refresh"},
            headers=headers,
        ).status_code
        == 404
    )
