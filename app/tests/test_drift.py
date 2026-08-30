"""The missing baseline and a retyped field, carried through Studio (#8).
The library's drift detection is not re-tested — only that the bind
response carries `retype_unchecked` and that a `retyped` kind reaches
the 409 body the recovery table renders. Asserted through the HTTP API
(#81 "Testing decisions").
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import SigningKeys
from tests.test_charts import (
    TRANSFORM_FRAME,
    _bind_block,
    _create_spec,
    _preview_bind,
    _upload_source,
)
from tests.test_refresh import _refresh

# Transform names `a` and `b`; the baseline records only `a`.
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
    assert any(item["code"] == "retype_unchecked" for item in body["warnings"])


def test_partial_baseline_binds_and_surfaces_retype_unchecked(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    response = _preview_bind(db_client, signing, source_id, content=PARTIAL_FRAME)
    assert response.status_code == 200
    body = response.json()
    assert body["row_count"] == 3
    assert any(item["code"] == "retype_unchecked" for item in body["warnings"])


def test_refresh_carries_a_retyped_kind_in_the_drifted_body(
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
    broken_id = _upload_source(db_client, signing, content=CSV_RETYPED)

    response = _refresh(db_client, signing, created.json()["id"], source_id=broken_id)
    assert response.status_code == 409
    payload = response.json()
    assert payload["error"] == "schema_drift"
    assert any(field["kind"] == "retyped" for field in payload["drifted"])
