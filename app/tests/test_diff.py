"""Structural revision diffs over canonical_json (#10; ADR-0007 D3 erratum).

One HTTP route, hunks as added/removed/changed paths — not a text diff.
Asserted through the HTTP API only (#81 "Testing decisions").
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import SigningKeys, bearer_headers
from tests.test_charts import (
    FRAME,
    TRANSFORM_FRAME,
    _bind_block,
    _create_spec,
    _preview_bind,
    _upload_source,
)
from tests.test_revisions import CHANGED_FRAME, _two_revision_chart


def _diff(
    client: TestClient,
    signing: SigningKeys,
    chart_id: str,
    from_rev: int,
    to_rev: int,
    *,
    sub: str = "user_2abc",
) -> Any:
    return client.get(
        f"/api/specs/{chart_id}/revisions/{from_rev}/diff/{to_rev}",
        headers=bearer_headers(signing, sub=sub),
    )


def test_a_revision_diffed_against_itself_returns_zero_hunks(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _create_spec(db_client, signing, source_id).json()

    response = _diff(db_client, signing, created["id"], 1, 1)
    assert response.status_code == 200
    body = response.json()
    assert body["from_revision"] == 1
    assert body["to_revision"] == 1
    assert body["hunks"] == []
    assert body["source_schema_only"] is False


def test_two_revisions_return_structural_hunks_over_canonical_paths(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _two_revision_chart(db_client, signing, source_id)

    response = _diff(db_client, signing, created["id"], 1, 2)
    assert response.status_code == 200
    body = response.json()
    assert body["from_revision"] == 1
    assert body["to_revision"] == 2
    assert body["source_schema_only"] is False
    # FRAME x.field is "b"; CHANGED_FRAME x.field is "a". One path, not a
    # text diff of the pretty-printed documents.
    assert body["hunks"] == [
        {
            "op": "changed",
            "path": "/chart_spec/encodings/x/field",
            "from_value": "b",
            "to_value": "a",
        }
    ]
    assert FRAME["chart_spec"]["encodings"]["x"]["field"] == "b"
    assert CHANGED_FRAME["chart_spec"]["encodings"]["x"]["field"] == "a"


def test_source_schema_only_change_is_labelled(
    db_client: TestClient, signing: SigningKeys
) -> None:
    """The first honest save copies Envelope.source_schema onto the frame
    (ADR-0007 D8 erratum). That is an edit nobody made; the diff names it
    rather than hiding it."""
    source_id = _upload_source(db_client, signing)
    created = _create_spec(
        db_client, signing, source_id, content=TRANSFORM_FRAME
    ).json()
    envelope = _preview_bind(
        db_client, signing, source_id, content=TRANSFORM_FRAME
    ).json()
    assert envelope["source_schema"] == {"a": "number"}
    resaved = db_client.put(
        f"/api/specs/{created['id']}",
        json={
            "content": TRANSFORM_FRAME,
            "bind": _bind_block(envelope, content=TRANSFORM_FRAME),
        },
        headers=bearer_headers(signing),
    )
    assert resaved.status_code == 200
    assert resaved.json()["revision_number"] == 2

    response = _diff(db_client, signing, created["id"], 1, 2)
    assert response.status_code == 200
    body = response.json()
    assert body["source_schema_only"] is True
    assert body["hunks"] == [
        {
            "op": "added",
            "path": "/x_chartagent/source_schema",
            "from_value": None,
            "to_value": {"a": "number"},
        }
    ]


def test_diff_404s_on_every_id_it_takes(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing, sub="user_2abc")
    created = _create_spec(db_client, signing, source_id, sub="user_2abc").json()

    # Another owner's chart.
    assert (
        _diff(
            db_client, signing, created["id"], 1, 1, sub="user_other"
        ).status_code
        == 404
    )
    # A revision number that is not on this chart.
    assert _diff(db_client, signing, created["id"], 1, 9).status_code == 404
    assert _diff(db_client, signing, created["id"], 9, 1).status_code == 404
    # A chart that does not exist.
    missing = "018f3c3c-0000-7000-8000-000000000000"
    assert _diff(db_client, signing, missing, 1, 1).status_code == 404
