"""Refreshing a saved custom-rail chart (#40): `bind_recipe` against the
chosen or default source, no model call, a run with a null backend. Asserted
through the HTTP API only; the library's transform, drift check and
serialisation are not re-tested here."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import update

from studio.models import BindCache, SpecRevision
from tests.conftest import SigningKeys, bearer_headers, make_app
from tests.test_charts import CSV_BYTES_2, FRAME, _runs, _upload_source
from tests.test_recipe_save import RECIPE, _create, _pinned, _put

# Lacks the `a` column the recipe's baseline and transform name.
CSV_MISSING_COLUMN = b"c,b\n4,p\n5,q\n"
CSV_DATES = b"a,d,x\n2,2024-01-02 03:04:05+00,1.5\n3,2024-01-03 00:00:00+00,nan\n"

NO_MODEL = "refresh must not call the model"


class _RaisingAgent:
    def create_chart(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError(NO_MODEL)


def _refresh(
    client: TestClient,
    signing: SigningKeys,
    chart_id: str,
    *,
    source_id: str | None = None,
    trigger: str = "refresh",
    body: dict[str, Any] | None = None,
    sub: str = "user_2abc",
) -> Any:
    payload: dict[str, Any] = body if body is not None else {"trigger": trigger}
    if source_id is not None:
        payload["source_id"] = source_id
    return client.post(
        f"/api/specs/{chart_id}/bind",
        json=payload,
        headers=bearer_headers(signing, sub=sub),
    )


def _get(client: TestClient, signing: SigningKeys, chart_id: str) -> Any:
    return client.get(f"/api/specs/{chart_id}", headers=bearer_headers(signing))


def _cache_object(client: TestClient, signing: SigningKeys, chart_id: str) -> Any:
    response = client.get(
        f"/api/specs/{chart_id}/cache", headers=bearer_headers(signing)
    )
    return response


def _recipe_chart(
    client: TestClient,
    signing: SigningKeys,
    recipe: dict[str, Any] = RECIPE,
    *,
    content: bytes | None = None,
) -> tuple[str, str]:
    source_id = (
        _upload_source(client, signing)
        if content is None
        else _upload_source(client, signing, content=content)
    )
    chart_id = _create(client, signing, source_id, recipe).json()["id"]
    return chart_id, source_id


def test_refresh_against_the_default_source_writes_cache_and_a_null_backend_run(
    db_client: TestClient, signing: SigningKeys
) -> None:
    db_client.app.state.chart_agent = _RaisingAgent()  # type: ignore[attr-defined]
    chart_id, source_id = _recipe_chart(db_client, signing)

    response = _refresh(db_client, signing, chart_id)
    assert response.status_code == 200
    body = response.json()
    assert body["row_count"] == 2  # a > 1 over 1, 2, 3
    assert body["elapsed"] >= 0
    assert body["warnings"] == []
    assert body["source_schema"]["a"]
    assert body["theme_spec"] is None
    assert body["rows"] == [{"a": 2, "b": "y"}, {"a": 3, "b": "z"}]

    fetched = _get(db_client, signing, chart_id).json()
    assert fetched["cache"]["source_id"] == source_id
    assert fetched["cache"]["row_count"] == 2
    assert fetched["cache"]["revision_id"] == fetched["revision_id"]

    cached = _cache_object(db_client, signing, chart_id)
    assert cached.status_code == 200
    assert json.loads(cached.content) == {
        "revision_id": fetched["revision_id"],
        "rows": body["rows"],
    }

    runs = _runs(db_client, signing, chart_id)
    assert [
        (r["trigger_kind"], r["backend"], r["status"], r["row_count"]) for r in runs
    ] == [("refresh", None, "ok", 2)]


def test_open_trigger_binds_a_recipe_too_and_a_client_backend_is_not_needed(
    db_client: TestClient, signing: SigningKeys
) -> None:
    db_client.app.state.chart_agent = _RaisingAgent()  # type: ignore[attr-defined]
    chart_id, _ = _recipe_chart(db_client, signing)

    assert _refresh(db_client, signing, chart_id, body={}).status_code == 200
    runs = _runs(db_client, signing, chart_id)
    assert [(r["trigger_kind"], r["backend"]) for r in runs] == [("open", None)]


def test_refresh_against_a_chosen_source_replaces_cache_and_moves_the_default(
    db_client: TestClient, signing: SigningKeys
) -> None:
    chart_id, first_id = _recipe_chart(db_client, signing)
    second_id = _upload_source(db_client, signing, content=CSV_BYTES_2)
    assert _refresh(db_client, signing, chart_id).status_code == 200

    response = _refresh(db_client, signing, chart_id, source_id=second_id)
    assert response.status_code == 200
    assert response.json()["row_count"] == 2  # 4, 5 both > 1

    fetched = _get(db_client, signing, chart_id).json()
    assert fetched["default_source_id"] == second_id
    assert fetched["cache"]["source_id"] == second_id
    assert first_id != second_id


def test_cached_rows_are_the_librarys_wire_rows(
    db_client: TestClient, signing: SigningKeys
) -> None:
    recipe = deepcopy(RECIPE)
    recipe["source_schema"] = {"a": "number", "d": "timestamptz", "x": "number"}
    chart_id, _ = _recipe_chart(db_client, signing, recipe, content=CSV_DATES)
    response = _refresh(db_client, signing, chart_id)
    assert response.status_code == 200
    rows = json.loads(_cache_object(db_client, signing, chart_id).content)["rows"]
    assert [r["d"] for r in rows] == ["2024-01-02T03:04:05Z", "2024-01-03T00:00:00Z"]
    assert [r["x"] for r in rows] == [1.5, None]
    assert rows == response.json()["rows"]


def test_a_retired_theme_preset_is_carried_not_validated_or_applied(
    db_client: TestClient, signing: SigningKeys
) -> None:
    recipe = deepcopy(RECIPE)
    recipe["theme_spec"] = "retired-preset"
    chart_id, _ = _recipe_chart(db_client, signing, recipe)

    response = _refresh(db_client, signing, chart_id)
    assert response.status_code == 200
    assert response.json()["theme_spec"] == "retired-preset"
    stored = _get(db_client, signing, chart_id).json()["content"]
    assert stored["theme_spec"] == "retired-preset"


def _assert_failed_refresh_changes_nothing(
    client: TestClient,
    signing: SigningKeys,
    chart_id: str,
    good_source_id: str,
    response: Any,
    *,
    status: int,
    error: str,
    error_code: str,
) -> dict[str, Any]:
    assert response.status_code == status
    body: dict[str, Any] = response.json()
    assert body["error"] == error
    before = _get(client, signing, chart_id).json()
    assert before["default_source_id"] == good_source_id
    assert before["cache"]["row_count"] == 2
    runs = _runs(client, signing, chart_id)
    failed = [r for r in runs if r["status"] == "error"]
    assert [(r["backend"], r["error_code"], r["row_count"]) for r in failed] == [
        (None, error_code, None)
    ]
    return body


def test_drift_leaves_cache_and_default_and_names_the_fields(
    db_client: TestClient, signing: SigningKeys
) -> None:
    chart_id, source_id = _recipe_chart(db_client, signing)
    assert _refresh(db_client, signing, chart_id).status_code == 200
    cached_before = _cache_object(db_client, signing, chart_id).content
    bad_id = _upload_source(db_client, signing, content=CSV_MISSING_COLUMN)

    body = _assert_failed_refresh_changes_nothing(
        db_client,
        signing,
        chart_id,
        source_id,
        _refresh(db_client, signing, chart_id, source_id=bad_id),
        status=409,
        error="schema_drift",
        error_code="SchemaDriftError",
    )
    assert [d["name"] for d in body["drifted"]] == ["a"]
    assert _cache_object(db_client, signing, chart_id).content == cached_before


def test_transform_error_leaves_cache_and_default_untouched(
    db_client: TestClient, signing: SigningKeys
) -> None:
    broken = deepcopy(RECIPE)
    broken["transform"] = {"raw_sql": "SELECT nonsense FROM"}
    broken["escape_reason"] = {"bucket": 1}
    chart_id, source_id = _recipe_chart(db_client, signing)
    assert _refresh(db_client, signing, chart_id).status_code == 200
    assert _put(db_client, signing, chart_id, broken).status_code == 200
    cache_before = _get(db_client, signing, chart_id).json()["cache"]

    response = _refresh(db_client, signing, chart_id)
    assert response.status_code == 422
    assert response.json()["error"] in {"transform", "raw_sql_rejected"}
    after = _get(db_client, signing, chart_id).json()
    assert after["cache"] == cache_before
    assert after["default_source_id"] == source_id
    errors = [r for r in _runs(db_client, signing, chart_id) if r["status"] == "error"]
    assert [(r["backend"], r["trigger_kind"]) for r in errors] == [(None, "refresh")]


def test_row_cap_leaves_cache_and_default_untouched(
    signing: SigningKeys, tmp_path: Path, db_url: str, clean_db: None
) -> None:
    app = make_app(
        signing.jwks,
        database_url=db_url,
        object_store_dir=tmp_path / "objects",
        bind_row_cap=1,
    )
    with TestClient(app) as client:
        chart_id, _ = _recipe_chart(client, signing)
        response = _refresh(client, signing, chart_id)
        assert response.status_code == 422
        body = response.json()
        assert (body["error"], body["row_count"], body["cap"]) == (
            "row_cap_exceeded",
            2,
            1,
        )
        assert _get(client, signing, chart_id).json()["cache"] is None
        assert _cache_object(client, signing, chart_id).status_code == 404
        runs = _runs(client, signing, chart_id)
        assert [(r["backend"], r["status"], r["error_code"]) for r in runs] == [
            (None, "error", "RowCapExceededError")
        ]


def test_a_rail_change_leaves_the_cache_pointer_stale(
    db_client: TestClient, signing: SigningKeys
) -> None:
    chart_id, _ = _recipe_chart(db_client, signing)
    assert _refresh(db_client, signing, chart_id).status_code == 200
    cached_revision = _get(db_client, signing, chart_id).json()["cache"]["revision_id"]

    saved = _put(db_client, signing, chart_id, FRAME).json()
    assert saved["kind"] == "frame"
    assert saved["cache"]["revision_id"] == cached_revision != saved["revision_id"]

    # The cache route still serves the old revision's object; the id mismatch
    # is what the client reads as *Refresh to bind*.
    cached = json.loads(_cache_object(db_client, signing, chart_id).content)
    assert cached["revision_id"] == cached_revision != saved["revision_id"]

    # Refresh on the frame rail re-points the cache at the frame revision.
    frame_refresh = _refresh(
        db_client, signing, chart_id, body={"backend": "echarts", "trigger": "refresh"}
    )
    assert frame_refresh.status_code == 200
    assert (
        _get(db_client, signing, chart_id).json()["cache"]["revision_id"]
        == saved["revision_id"]
    )


def test_a_frame_bind_still_requires_a_backend(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    chart_id = _create(db_client, signing, source_id, FRAME).json()["id"]
    response = _refresh(db_client, signing, chart_id, body={"trigger": "refresh"})
    assert response.status_code == 422


def test_a_pinned_recipe_cannot_be_bound(
    db_client: TestClient, signing: SigningKeys
) -> None:
    chart_id, _ = _recipe_chart(db_client, signing)
    with db_client.app.state.session_factory() as session:  # type: ignore[attr-defined]
        session.execute(update(SpecRevision).values(content=_pinned()))
        session.commit()
    response = _refresh(db_client, signing, chart_id)
    assert response.status_code == 422
    assert response.json()["error"] == "pinned_libraries_unsupported"
    with db_client.app.state.session_factory() as session:  # type: ignore[attr-defined]
        assert session.query(BindCache).count() == 0


def test_cross_owner_and_signed_out_are_refused(
    db_client: TestClient, signing: SigningKeys
) -> None:
    chart_id, source_id = _recipe_chart(db_client, signing)
    other = _refresh(db_client, signing, chart_id, sub="user_other")
    assert other.status_code == 404
    other_source = _upload_source(db_client, signing, sub="user_other")
    assert (
        _refresh(db_client, signing, chart_id, source_id=other_source).status_code
        == 404
    )
    signed_out = db_client.post(f"/api/specs/{chart_id}/bind", json={})
    assert signed_out.status_code == 401
