"""Remap dropped columns, preview the patch, approve via ordinary save (#11).

Asserted through the HTTP API (#81 "Testing decisions"). The library's
drift detection is not re-tested — Studio repairs what the bind reported.
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
    _runs,
    _upload_source,
)
from tests.test_drift import CSV_RETYPED, PARTIAL_FRAME
from tests.test_refresh import CSV_MISSING_COLUMN, _refresh, _saved_chart_with_cache


def _preview_remap(
    client: TestClient,
    signing: SigningKeys,
    chart_id: str,
    *,
    mapping: dict[str, str],
    drifted: list[dict[str, Any]],
    sub: str = "user_2abc",
) -> Any:
    return client.post(
        f"/api/specs/{chart_id}/remap-preview",
        json={"mapping": mapping, "drifted": drifted},
        headers=bearer_headers(signing, sub=sub),
    )


def _dropped_a() -> list[dict[str, Any]]:
    return [{"name": "a", "kind": "dropped", "expected": "a", "found": None}]


def test_remap_preview_returns_the_diff_and_writes_nothing(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _saved_chart_with_cache(
        db_client, signing, source_id, content=TRANSFORM_FRAME
    )
    runs_before = _runs(db_client, signing, created["id"])
    cache_before = created["cache"]

    response = _preview_remap(
        db_client,
        signing,
        created["id"],
        mapping={"a": "c"},
        drifted=_dropped_a(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["from_revision"] == 1
    assert body["to_revision"] == 2
    hunks = {hunk["path"]: hunk for hunk in body["hunks"]}
    assert hunks["/chart_spec/encodings/y/field"] == {
        "op": "changed",
        "path": "/chart_spec/encodings/y/field",
        "from_value": "a",
        "to_value": "c",
    }
    assert hunks["/x_chartagent/transform/filter/args/0/name"]["to_value"] == "c"
    assert body["content"]["chart_spec"]["encodings"]["y"]["field"] == "c"
    assert (
        body["content"]["x_chartagent"]["transform"]["filter"]["args"][0]["name"]
        == "c"
    )
    # The baseline is not rewritten here — save copies it from the bind.
    assert body["content"]["x_chartagent"]["source_schema"] == {"a": "number"}

    fetched = db_client.get(
        f"/api/specs/{created['id']}", headers=bearer_headers(signing)
    ).json()
    assert fetched["revision_number"] == 1
    assert fetched["cache"] == cache_before
    assert _runs(db_client, signing, created["id"]) == runs_before


def test_partial_remap_is_refused(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _saved_chart_with_cache(
        db_client, signing, source_id, content=TRANSFORM_FRAME
    )
    runs_before = _runs(db_client, signing, created["id"])

    response = _preview_remap(
        db_client,
        signing,
        created["id"],
        mapping={},
        drifted=_dropped_a(),
    )
    assert response.status_code == 422
    assert "every dropped field must be mapped" in response.json()["detail"]

    fetched = db_client.get(
        f"/api/specs/{created['id']}", headers=bearer_headers(signing)
    ).json()
    assert fetched["revision_number"] == 1
    assert _runs(db_client, signing, created["id"]) == runs_before


def test_retyped_field_preview_is_refused(
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
    ).json()

    response = _preview_remap(
        db_client,
        signing,
        created["id"],
        mapping={"a": "a"},
        drifted=[
            {
                "name": "a",
                "kind": "retyped",
                "expected": "number",
                "found": "string",
            }
        ],
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "retype cannot be remapped" in detail
    assert "raw_sql" in detail


def test_cross_owner_remap_preview_fails(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _saved_chart_with_cache(
        db_client, signing, source_id, content=TRANSFORM_FRAME
    )
    response = _preview_remap(
        db_client,
        signing,
        created["id"],
        mapping={"a": "c"},
        drifted=_dropped_a(),
        sub="user_other",
    )
    assert response.status_code == 404
    fetched = db_client.get(
        f"/api/specs/{created['id']}", headers=bearer_headers(signing)
    ).json()
    assert fetched["revision_number"] == 1
    runs = _runs(db_client, signing, created["id"])
    assert [run["trigger_kind"] for run in runs] == ["save"]


def test_full_recovery_path_against_a_renamed_column(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _saved_chart_with_cache(
        db_client, signing, source_id, content=TRANSFORM_FRAME
    )
    spec_version = created["content"]["x_chartagent"]["spec_version"]
    cache_before = created["cache"]
    renamed_id = _upload_source(db_client, signing, content=CSV_MISSING_COLUMN)

    refresh = _refresh(db_client, signing, created["id"], source_id=renamed_id)
    assert refresh.status_code == 409
    drifted = refresh.json()["drifted"]
    after_refresh = db_client.get(
        f"/api/specs/{created['id']}", headers=bearer_headers(signing)
    ).json()
    assert after_refresh["cache"] == cache_before
    assert after_refresh["revision_number"] == 1
    assert after_refresh["default_source_id"] == source_id
    error_runs = [
        run
        for run in _runs(db_client, signing, created["id"])
        if run["status"] == "error"
    ]
    assert [(run["trigger_kind"], run["error_code"]) for run in error_runs] == [
        ("refresh", "SchemaDriftError")
    ]

    preview = _preview_remap(
        db_client,
        signing,
        created["id"],
        mapping={"a": "c"},
        drifted=drifted,
    )
    assert preview.status_code == 200
    after_preview = db_client.get(
        f"/api/specs/{created['id']}", headers=bearer_headers(signing)
    ).json()
    assert after_preview["revision_number"] == 1
    assert after_preview["cache"] == cache_before
    assert len(_runs(db_client, signing, created["id"])) == len(error_runs) + 1

    candidate = preview.json()["content"]
    bound = _preview_bind(
        db_client, signing, renamed_id, content=candidate
    )
    assert bound.status_code == 200
    envelope = bound.json()
    approved = db_client.put(
        f"/api/specs/{created['id']}",
        json={
            "content": candidate,
            "source_id": renamed_id,
            "bind": _bind_block(envelope, content=candidate),
        },
        headers=bearer_headers(signing),
    )
    assert approved.status_code == 200
    body = approved.json()
    assert body["revision_number"] == 2
    assert body["content"]["x_chartagent"]["spec_version"] == spec_version
    assert body["content"]["x_chartagent"]["source_schema"] == envelope["source_schema"]
    assert envelope["source_schema"] == {"c": "number"}
    assert body["cache"] is not None
    assert body["cache"]["revision_id"] == body["revision_id"]
    assert body["cache"]["source_id"] == renamed_id
    assert body["default_source_id"] == renamed_id

    cache_object = db_client.get(
        f"/api/specs/{created['id']}/cache", headers=bearer_headers(signing)
    )
    assert cache_object.status_code == 200
    assert cache_object.json()["revision_id"] == body["revision_id"]

    save_runs = [
        run
        for run in _runs(db_client, signing, created["id"])
        if run["trigger_kind"] == "save"
    ]
    assert save_runs[0]["status"] == "ok"
    assert save_runs[0]["row_count"] == envelope["row_count"]


def test_repair_whose_rebind_fails_writes_nothing(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _saved_chart_with_cache(
        db_client, signing, source_id, content=TRANSFORM_FRAME
    )
    cache_before = created["cache"]
    renamed_id = _upload_source(db_client, signing, content=CSV_MISSING_COLUMN)

    refresh = _refresh(db_client, signing, created["id"], source_id=renamed_id)
    assert refresh.status_code == 409

    preview = _preview_remap(
        db_client,
        signing,
        created["id"],
        mapping={"a": "zzz"},
        drifted=refresh.json()["drifted"],
    )
    assert preview.status_code == 200
    candidate = preview.json()["content"]
    bound = _preview_bind(db_client, signing, renamed_id, content=candidate)
    assert bound.status_code != 200

    fetched = db_client.get(
        f"/api/specs/{created['id']}", headers=bearer_headers(signing)
    ).json()
    assert fetched["revision_number"] == 1
    assert fetched["cache"] == cache_before
    error_runs = [
        run
        for run in _runs(db_client, signing, created["id"])
        if run["status"] == "error"
    ]
    assert len(error_runs) == 1
    assert error_runs[0]["trigger_kind"] == "refresh"


def test_remap_rewrites_sort_keys_and_semantic_types(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _saved_chart_with_cache(
        db_client, signing, source_id, content=TRANSFORM_FRAME
    )
    frame: dict[str, Any] = {
        "chart_spec": TRANSFORM_FRAME["chart_spec"],
        "semantic_types": {"a": "Amount"},
        "x_chartagent": {
            **created["content"]["x_chartagent"],
            "transform": {
                **TRANSFORM_FRAME["x_chartagent"]["transform"],
                "sort": [{"field": "a", "dir": "asc", "nulls": "last"}],
            },
        },
    }
    updated = db_client.put(
        f"/api/specs/{created['id']}",
        json={"content": frame},
        headers=bearer_headers(signing),
    )
    assert updated.status_code == 200

    response = _preview_remap(
        db_client,
        signing,
        created["id"],
        mapping={"a": "c"},
        drifted=_dropped_a(),
    )
    assert response.status_code == 200
    content = response.json()["content"]
    assert content["semantic_types"] == {"c": "Amount"}
    assert content["x_chartagent"]["transform"]["sort"][0]["field"] == "c"


def test_retyped_refresh_fixture_still_has_no_remap(
    db_client: TestClient, signing: SigningKeys
) -> None:
    """The retyped CSV from #8 still reaches the body; preview refuses it."""
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
    ).json()
    broken_id = _upload_source(db_client, signing, content=CSV_RETYPED)
    refresh = _refresh(db_client, signing, created["id"], source_id=broken_id)
    assert refresh.status_code == 409
    drifted = refresh.json()["drifted"]
    assert any(field["kind"] == "retyped" for field in drifted)

    response = _preview_remap(
        db_client,
        signing,
        created["id"],
        mapping={},
        drifted=drifted,
    )
    assert response.status_code == 422
