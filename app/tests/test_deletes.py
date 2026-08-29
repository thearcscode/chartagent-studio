"""Hard deletes (#77; ADR-0007 D9), asserted through the HTTP API only.

Deleting a chart removes its revisions, runs, cache row and the cached
object. Deleting a source leaves charts alive with a null default source
(*pick a source*), cascades the cache row (a cache whose source is gone is
meaningless), and removes the source's bytes only when the last
`(owner_id, sha256)` row is gone. No tombstones.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tests.conftest import SigningKeys, bearer_headers
from tests.test_charts import _create_spec, _runs, _upload_source
from tests.test_library import _list, _read_cache
from tests.test_refresh import _saved_chart_with_cache
from tests.test_sources import CSV_SHA256


def test_delete_chart_removes_revisions_runs_cache_row_and_object(
    db_client: TestClient, signing: SigningKeys, tmp_path: Path
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _saved_chart_with_cache(db_client, signing, source_id)
    chart_id = created["id"]
    assert _read_cache(db_client, signing, chart_id).status_code == 200
    assert _runs(db_client, signing, chart_id)
    assert list(tmp_path.rglob("last_bind.json"))

    response = db_client.delete(
        f"/api/specs/{chart_id}", headers=bearer_headers(signing)
    )
    assert response.status_code == 204

    headers = bearer_headers(signing)
    assert db_client.get(f"/api/specs/{chart_id}", headers=headers).status_code == 404
    assert _list(db_client, signing) == []
    assert (
        db_client.get(f"/api/specs/{chart_id}/cache", headers=headers).status_code
        == 404
    )
    assert (
        db_client.get(f"/api/specs/{chart_id}/runs", headers=headers).status_code == 404
    )
    # The cached object is gone; the source's bytes stay — deleting a chart
    # does not empty another lifetime.
    assert list(tmp_path.rglob("last_bind.json")) == []
    assert (tmp_path / "objects" / f"user_2abc/{CSV_SHA256}.csv").is_file()
    # The source itself survives.
    assert (
        db_client.get(f"/api/sources/{source_id}", headers=headers).status_code == 200
    )


def test_delete_source_leaves_the_chart_asking_for_a_source(
    db_client: TestClient, signing: SigningKeys, tmp_path: Path
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _saved_chart_with_cache(db_client, signing, source_id)
    chart_id = created["id"]
    assert created["default_source_id"] == source_id
    assert created["cache"] is not None

    response = db_client.delete(
        f"/api/sources/{source_id}", headers=bearer_headers(signing)
    )
    assert response.status_code == 204

    headers = bearer_headers(signing)
    assert (
        db_client.get(f"/api/sources/{source_id}", headers=headers).status_code == 404
    )
    fetched = db_client.get(f"/api/specs/{chart_id}", headers=headers)
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["id"] == chart_id
    assert body["default_source_id"] is None
    assert body["cache"] is None  # CASCADE: a cache whose source is gone
    assert _read_cache(db_client, signing, chart_id).status_code == 404
    # History survives its referent — the run list is still there.
    assert _runs(db_client, signing, chart_id)
    # Last (owner_id, sha256) row is gone → the bytes go with it.
    assert not (tmp_path / "objects" / f"user_2abc/{CSV_SHA256}.csv").exists()
    assert list(tmp_path.rglob("last_bind.json")) == []


def test_delete_source_keeps_another_owners_bytes(
    db_client: TestClient, signing: SigningKeys, tmp_path: Path
) -> None:
    mine = _upload_source(db_client, signing, sub="user_2abc")
    theirs = _upload_source(db_client, signing, sub="user_other")
    assert mine != theirs

    db_client.delete(
        f"/api/sources/{mine}", headers=bearer_headers(signing, sub="user_2abc")
    )
    # Dedup never crosses a tenant boundary: the other owner's copy stays.
    assert (tmp_path / "objects" / f"user_other/{CSV_SHA256}.csv").is_file()
    assert not (tmp_path / "objects" / f"user_2abc/{CSV_SHA256}.csv").exists()


def test_delete_chart_never_crosses_an_owner_boundary(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _create_spec(db_client, signing, source_id).json()
    other = bearer_headers(signing, sub="user_other")
    assert (
        db_client.delete(
            f"/api/specs/{created['id']}", headers=other
        ).status_code
        == 404
    )
    assert (
        db_client.get(
            f"/api/specs/{created['id']}", headers=bearer_headers(signing)
        ).status_code
        == 200
    )


def test_delete_source_never_crosses_an_owner_boundary(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing, sub="user_2abc")
    assert (
        db_client.delete(
            f"/api/sources/{source_id}",
            headers=bearer_headers(signing, sub="user_other"),
        ).status_code
        == 404
    )
    assert (
        db_client.get(
            f"/api/sources/{source_id}", headers=bearer_headers(signing)
        ).status_code
        == 200
    )


def test_deletes_require_auth(db_client: TestClient) -> None:
    some_id = "018f3c3c-0000-7000-8000-000000000000"
    assert db_client.delete(f"/api/specs/{some_id}").status_code == 401
    assert db_client.delete(f"/api/sources/{some_id}").status_code == 401


def test_delete_url_source_leaves_no_bytes_to_remove(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source = db_client.post(
        "/api/sources",
        json={"url": "https://data.example.com/q3.csv"},
        headers=bearer_headers(signing),
    ).json()
    created = _create_spec(db_client, signing, source["id"]).json()

    response = db_client.delete(
        f"/api/sources/{source['id']}", headers=bearer_headers(signing)
    )
    assert response.status_code == 204
    fetched = db_client.get(
        f"/api/specs/{created['id']}", headers=bearer_headers(signing)
    ).json()
    assert fetched["default_source_id"] is None
