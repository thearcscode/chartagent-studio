"""Save, bind and the cache rules, asserted through the HTTP API only (#63
"Testing decisions"; the behaviours are #74's acceptance criteria). What the
library returns — rows, diagnostics, typed errors — is carried, not
re-tested.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
from chartagent import canonical_json
from fastapi.testclient import TestClient

from tests.conftest import DelegatingStore, SigningKeys, bearer_headers, make_app

CSV_BYTES = b"a,b\n1,x\n2,y\n3,z\n"
CSV_BYTES_2 = b"a,b\n4,p\n5,q\n"

# The CSV's columns: a BIGINT, b VARCHAR.
FRAME: dict[str, Any] = {
    "chart_spec": {
        "chartType": "Bar Chart",
        "encodings": {"x": {"field": "b"}, "y": {"field": "a"}},
    }
}

# Passes save-time validation (backend-free); fails at bind on vegalite —
# innerRadius is not in that backend's property set.
BIND_FAILING_FRAME: dict[str, Any] = {
    "chart_spec": {
        "chartType": "Rose Chart",
        "encodings": {"x": {"field": "b"}, "y": {"field": "a"}},
        "chartProperties": {"innerRadius": 40},
    }
}

# A transform referencing column `a`, so the envelope's source_schema names
# the columns the transform touched (an absent transform binds with an empty
# seen-schema).
TRANSFORM_FRAME: dict[str, Any] = {
    "chart_spec": {
        "chartType": "Bar Chart",
        "encodings": {"x": {"field": "b"}, "y": {"field": "a"}},
    },
    "x_chartagent": {
        "transform": {
            "filter": {
                "kind": "gt",
                "args": [
                    {"kind": "col", "name": "a"},
                    {"kind": "lit", "value": 1},
                ],
            }
        }
    },
}


def _upload_source(
    client: TestClient,
    signing: SigningKeys,
    *,
    sub: str = "user_2abc",
    content: bytes = CSV_BYTES,
) -> str:
    response = client.post(
        "/api/sources/upload",
        files={"file": ("q3.csv", content, "text/csv")},
        headers=bearer_headers(signing, sub=sub),
    )
    assert response.status_code == 201
    return response.json()["id"]  # type: ignore[no-any-return]


def _create_spec(
    client: TestClient,
    signing: SigningKeys,
    source_id: str,
    *,
    content: dict[str, Any] = FRAME,
    sub: str = "user_2abc",
    **extra: Any,
) -> httpx.Response:
    response: httpx.Response = client.post(
        "/api/specs",
        json={"content": content, "source_id": source_id, **extra},
        headers=bearer_headers(signing, sub=sub),
    )
    return response


def _preview_bind(
    client: TestClient,
    signing: SigningKeys,
    source_id: str,
    *,
    content: dict[str, Any] = FRAME,
    backend: str = "echarts",
    sub: str = "user_2abc",
) -> httpx.Response:
    response: httpx.Response = client.post(
        "/api/specs/bind",
        json={"content": content, "source_id": source_id, "backend": backend},
        headers=bearer_headers(signing, sub=sub),
    )
    return response


def _bind_block(
    envelope: dict[str, Any], *, content: dict[str, Any] = FRAME
) -> dict[str, Any]:
    return {
        "backend": envelope["backend"],
        "content": content,
        "rows": envelope["input"]["data"]["values"],
        "elapsed_ms": int(envelope["elapsed"] * 1000),
        "source_schema": envelope["source_schema"],
    }


def _runs(
    client: TestClient, signing: SigningKeys, chart_id: str
) -> list[dict[str, Any]]:
    response = client.get(
        f"/api/specs/{chart_id}/runs", headers=bearer_headers(signing)
    )
    assert response.status_code == 200
    return response.json()  # type: ignore[no-any-return]


# --- Save -------------------------------------------------------------------


def test_create_spec_stores_canonical_content_and_defaults_title(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    response = _create_spec(db_client, signing, source_id)
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Bar chart · q3.csv"
    assert body["revision_number"] == 1
    assert body["kind"] == "frame"
    assert body["default_source_id"] == source_id
    assert body["authored_flint_version"]  # the pin, recorded at save time
    assert body["cache"] is None
    # canonical_json() verbatim: the stored doc is the canonical form (empty
    # collections materialised), and sha256 of the canonical string is the
    # content hash.
    canonical = canonical_json(FRAME)
    assert body["content"] == json.loads(canonical)
    assert body["content_hash"] == hashlib.sha256(canonical.encode()).hexdigest()


def test_identical_resave_is_a_no_op(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _create_spec(db_client, signing, source_id).json()

    resaved = db_client.put(
        f"/api/specs/{created['id']}",
        json={"content": created["content"]},
        headers=bearer_headers(signing),
    )
    assert resaved.status_code == 200
    body = resaved.json()
    assert body["revision_number"] == 1
    assert body["revision_id"] == created["revision_id"]


def test_no_op_resave_still_applies_metadata(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _create_spec(db_client, signing, source_id).json()

    resaved = db_client.put(
        f"/api/specs/{created['id']}",
        json={"content": created["content"], "title": "Q3 by letter"},
        headers=bearer_headers(signing),
    )
    assert resaved.status_code == 200
    assert resaved.json()["title"] == "Q3 by letter"
    assert resaved.json()["revision_number"] == 1


def test_changed_content_appends_a_numbered_revision(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _create_spec(db_client, signing, source_id).json()

    changed = {
        "chart_spec": {
            "chartType": "Bar Chart",
            "encodings": {"x": {"field": "a"}, "y": {"field": "a"}},
        }
    }
    resaved = db_client.put(
        f"/api/specs/{created['id']}",
        json={"content": changed},
        headers=bearer_headers(signing),
    )
    assert resaved.status_code == 200
    body = resaved.json()
    assert body["revision_number"] == 2
    assert body["revision_id"] != created["revision_id"]
    assert body["content"]["chart_spec"]["encodings"]["x"] == {"field": "a"}


def test_save_copies_source_schema_from_the_bind_block(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    envelope = _preview_bind(
        db_client, signing, source_id, content=TRANSFORM_FRAME
    ).json()
    # The bind saw the bucket of every column the transform referenced.
    assert envelope["source_schema"] == {"a": "number"}
    assert envelope["row_count"] == 2  # a > 1 keeps two rows

    created = _create_spec(
        db_client,
        signing,
        source_id,
        content=TRANSFORM_FRAME,
        bind=_bind_block(envelope, content=TRANSFORM_FRAME),
    )
    assert created.status_code == 201
    body = created.json()
    xc = body["content"]["x_chartagent"]
    assert xc["source_schema"] == {"a": "number"}
    assert xc["transform"] == TRANSFORM_FRAME["x_chartagent"]["transform"]
    # The copy takes spec_version to 1.1 or later (ADR-0007 §4).
    major, minor = (int(p) for p in xc["spec_version"].split("."))
    assert (major, minor) >= (1, 1)


def test_honest_save_writes_cache_and_a_save_run(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    envelope = _preview_bind(db_client, signing, source_id).json()

    created = _create_spec(
        db_client, signing, source_id, bind=_bind_block(envelope)
    ).json()
    cache = created["cache"]
    assert cache is not None
    assert cache["revision_id"] == created["revision_id"]
    assert cache["source_id"] == source_id
    assert cache["row_count"] == 3

    runs = _runs(db_client, signing, created["id"])
    assert len(runs) == 1
    assert runs[0]["trigger_kind"] == "save"
    assert runs[0]["status"] == "ok"
    assert runs[0]["backend"] == "echarts"
    assert runs[0]["row_count"] == 3


def test_dishonest_save_writes_no_cache(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    envelope = _preview_bind(db_client, signing, source_id).json()
    # The bind block describes a frame other than the one being saved:
    # edited after the bind, so the cached rows are not honest for it.
    edited = {
        "chart_spec": {
            "chartType": "Bar Chart",
            "encodings": {"x": {"field": "a"}, "y": {"field": "a"}},
        }
    }
    created = _create_spec(
        db_client,
        signing,
        source_id,
        content=edited,
        bind=_bind_block(envelope),
    )
    assert created.status_code == 201
    assert created.json()["cache"] is None
    assert _runs(db_client, signing, created.json()["id"]) == []


class _UnwritableCacheStore(DelegatingStore):
    """Reads and upload writes work; the cache slot write fails."""

    def replace(self, key: str, source: Any) -> None:
        raise OSError("disk full")


def test_save_succeeds_even_if_the_cache_object_write_fails(
    signing: SigningKeys, tmp_path: Path, db_url: str, clean_db: None
) -> None:
    app = make_app(
        signing.jwks,
        database_url=db_url,
        object_store_dir=tmp_path / "objects",
    )
    app.state.object_store = _UnwritableCacheStore(app.state.object_store)
    with TestClient(app) as client:
        source_id = _upload_source(client, signing)
        envelope = _preview_bind(client, signing, source_id).json()
        created = _create_spec(
            client, signing, source_id, bind=_bind_block(envelope)
        )
        assert created.status_code == 201
        assert created.json()["cache"] is None  # no cache row without its object
        assert _runs(client, signing, created.json()["id"]) == []


def test_save_with_a_malformed_frame_maps_the_library_error(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    response = _create_spec(
        db_client,
        signing,
        source_id,
        content={
            "chart_spec": {
                "chartType": "Bogus Chart",
                "encodings": {"x": {"field": "b"}, "y": {"field": "a"}},
            }
        },
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "spec_vocabulary"
    assert body["kind"] == "chart_type"
    assert "Bogus Chart" in body["keys"]
    assert body["pin"]


# --- Bind -------------------------------------------------------------------


def test_preview_bind_returns_envelope_plus_diagnostics(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    response = _preview_bind(db_client, signing, source_id)
    assert response.status_code == 200
    body = response.json()
    # Envelope JSON plus diagnostics — and never a compiled option.
    assert set(body) == {
        "flint_version",
        "backend",
        "input",
        "row_count",
        "elapsed",
        "warnings",
        "source_schema",
    }
    assert body["flint_version"]
    assert body["backend"] == "echarts"
    assert body["input"]["data"]["values"] == [
        {"a": 1, "b": "x"},
        {"a": 2, "b": "y"},
        {"a": 3, "b": "z"},
    ]
    # Diagnostics.
    assert body["row_count"] == 3
    assert body["elapsed"] >= 0.0
    assert body["warnings"] == []
    # No transform → no referenced columns → the seen-schema is empty.
    assert body["source_schema"] == {}


def test_saved_bind_writes_a_run_and_replaces_the_cache(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _create_spec(db_client, signing, source_id).json()
    assert created["cache"] is None

    response = db_client.post(
        f"/api/specs/{created['id']}/bind",
        json={"backend": "plotly", "trigger": "open"},
        headers=bearer_headers(signing),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["backend"] == "plotly"
    assert body["row_count"] == 3

    fetched = db_client.get(
        f"/api/specs/{created['id']}", headers=bearer_headers(signing)
    ).json()
    assert fetched["cache"]["row_count"] == 3
    assert fetched["cache"]["revision_id"] == created["revision_id"]

    runs = _runs(db_client, signing, created["id"])
    assert [(r["trigger_kind"], r["status"], r["backend"]) for r in runs] == [
        ("open", "ok", "plotly")
    ]


def test_failed_saved_bind_writes_an_error_run_and_keeps_the_cache(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    envelope = _preview_bind(db_client, signing, source_id).json()
    created = _create_spec(
        db_client, signing, source_id, bind=_bind_block(envelope)
    ).json()
    assert created["cache"] is not None

    # Point the chart at a frame that fails at bind time, then bind it.
    db_client.put(
        f"/api/specs/{created['id']}",
        json={"content": BIND_FAILING_FRAME},
        headers=bearer_headers(signing),
    )
    response = db_client.post(
        f"/api/specs/{created['id']}/bind",
        json={"backend": "vegalite", "trigger": "backend_switch"},
        headers=bearer_headers(signing),
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "spec_vocabulary"
    assert body["kind"] == "property"
    assert "innerRadius" in body["keys"]
    assert body["chart_type"] == "Rose Chart"
    assert body["backend"] == "vegalite"

    runs = _runs(db_client, signing, created["id"])
    error_run = next(r for r in runs if r["status"] == "error")
    assert error_run["trigger_kind"] == "backend_switch"
    assert error_run["error_code"] == "SpecVocabularyError"

    # The stale cache stays exactly as it was — staleness is never silent,
    # and a failed bind must not clobber the last good rows.
    fetched = db_client.get(
        f"/api/specs/{created['id']}", headers=bearer_headers(signing)
    ).json()
    assert fetched["cache"]["revision_id"] == created["revision_id"]


def test_bind_row_cap_raises_rather_than_truncates(
    signing: SigningKeys, tmp_path: Path, db_url: str, clean_db: None
) -> None:
    app = make_app(
        signing.jwks,
        database_url=db_url,
        object_store_dir=tmp_path / "objects",
        bind_row_cap=2,
    )
    with TestClient(app) as client:
        source_id = _upload_source(client, signing)
        response = _preview_bind(client, signing, source_id)
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "row_cap_exceeded"
    assert body["row_count"] == 3
    assert body["cap"] == 2


def test_bind_with_another_source_moves_the_default(
    db_client: TestClient, signing: SigningKeys
) -> None:
    first_id = _upload_source(db_client, signing)
    second_id = _upload_source(db_client, signing, content=CSV_BYTES_2)
    created = _create_spec(db_client, signing, first_id).json()
    assert created["default_source_id"] == first_id

    moved = db_client.post(
        f"/api/specs/{created['id']}/bind",
        json={"backend": "echarts", "source_id": second_id},
        headers=bearer_headers(signing),
    )
    assert moved.status_code == 200
    assert moved.json()["row_count"] == 2  # the second CSV's rows

    fetched = db_client.get(
        f"/api/specs/{created['id']}", headers=bearer_headers(signing)
    ).json()
    assert fetched["default_source_id"] == second_id  # ADR-0007 D5
    assert fetched["cache"]["source_id"] == second_id


# --- Ownership --------------------------------------------------------------


def test_chart_routes_never_cross_an_owner_boundary(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing, sub="user_2abc")
    created = _create_spec(db_client, signing, source_id, sub="user_2abc").json()
    other = bearer_headers(signing, sub="user_other")

    assert (
        db_client.get(f"/api/specs/{created['id']}", headers=other).status_code == 404
    )
    assert (
        db_client.put(
            f"/api/specs/{created['id']}", json={"content": FRAME}, headers=other
        ).status_code
        == 404
    )
    assert (
        db_client.post(
            f"/api/specs/{created['id']}/bind",
            json={"backend": "echarts"},
            headers=other,
        ).status_code
        == 404
    )
    assert (
        db_client.get(f"/api/specs/{created['id']}/runs", headers=other).status_code
        == 404
    )
    # Another owner's source cannot be named in a save or a bind either.
    assert (
        _create_spec(db_client, signing, source_id, sub="user_other").status_code
        == 404
    )
    assert (
        _preview_bind(db_client, signing, source_id, sub="user_other").status_code
        == 404
    )


def test_chart_routes_require_auth(db_client: TestClient) -> None:
    some_id = "018f3c3c-0000-7000-8000-000000000000"
    valid_create = {"content": FRAME, "source_id": some_id}
    valid_preview = {"content": FRAME, "source_id": some_id, "backend": "echarts"}
    assert db_client.post("/api/specs", json=valid_create).status_code == 401
    assert db_client.get(f"/api/specs/{some_id}").status_code == 401
    assert db_client.post("/api/specs/bind", json=valid_preview).status_code == 401
    assert (
        db_client.post(f"/api/specs/{some_id}/bind", json={"backend": "echarts"})
        .status_code
        == 401
    )
