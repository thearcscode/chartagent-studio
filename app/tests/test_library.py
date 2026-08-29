"""The Library reads the bind cache; it does not bind (#76; ADR-0007 D6,
#63 §9). A matching pointer reads the cache object — `{revision_id, rows}`
and nothing else — with zero new runs; a stale pointer or a missing object
is the *Refresh to bind* state, still with zero runs. A failed bind leaves
the Library reading the old picture. Asserted through the HTTP API only
(#63 "Testing decisions").
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import DelegatingStore, SigningKeys, bearer_headers, make_app
from tests.test_charts import (
    TRANSFORM_FRAME,
    _create_spec,
    _runs,
    _upload_source,
)
from tests.test_refresh import CSV_MISSING_COLUMN, _refresh, _saved_chart_with_cache

# Same columns as the saved frame, different fields referenced — a real
# edit, so the save appends a revision and the pointer goes stale.
CHANGED_FRAME: dict[str, Any] = {
    "chart_spec": {
        "chartType": "Bar Chart",
        "encodings": {"x": {"field": "a"}, "y": {"field": "a"}},
    }
}


def _list(
    client: TestClient, signing: SigningKeys, *, sub: str = "user_2abc"
) -> list[dict[str, Any]]:
    response = client.get("/api/specs", headers=bearer_headers(signing, sub=sub))
    assert response.status_code == 200
    return response.json()  # type: ignore[no-any-return]


def _read_cache(
    client: TestClient, signing: SigningKeys, chart_id: str, *, sub: str = "user_2abc"
) -> Any:
    return client.get(
        f"/api/specs/{chart_id}/cache", headers=bearer_headers(signing, sub=sub)
    )


def test_library_lists_the_signed_in_users_cards_newest_first(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    first = _create_spec(db_client, signing, source_id).json()
    second = _create_spec(db_client, signing, source_id).json()

    cards = _list(db_client, signing)
    assert [card["id"] for card in cards] == [second["id"], first["id"]]
    # The card carries what the client compiles from: the current frame and
    # the cache pointer.
    assert cards[0]["content"] == second["content"]
    assert cards[0]["cache"] is None  # never bound — honestly


def test_matching_pointer_reads_the_cache_with_no_new_runs(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    # The save-writes-cache rule (#74), end to end into the Library read.
    created = _saved_chart_with_cache(db_client, signing, source_id)

    cards = _list(db_client, signing)
    assert [card["id"] for card in cards] == [created["id"]]
    card = cards[0]
    # The pointer agrees with the chart's current values — the card compiles
    # from the cache; no bind, no DuckDB, no run row.
    assert card["revision_id"] == created["revision_id"]
    assert card["cache"]["revision_id"] == created["revision_id"]
    assert card["cache"]["source_id"] == source_id
    assert card["cache"]["source_kind"] == "upload"

    cache_read = _read_cache(db_client, signing, created["id"])
    assert cache_read.status_code == 200
    # The slot is overwritten in place at a stable URL — nothing may serve
    # last bind's bytes as this bind's.
    assert cache_read.headers["cache-control"] == "no-store"
    body = cache_read.json()
    # The cache object is {revision_id, rows} and nothing else — no
    # envelope, no flint_version, no backend, no theme_spec, no advisories.
    assert set(body) == {"revision_id", "rows"}
    assert body["revision_id"] == created["revision_id"]
    assert body["rows"] == [
        {"a": 1, "b": "x"},
        {"a": 2, "b": "y"},
        {"a": 3, "b": "z"},
    ]

    # The whole page cost zero runs: the save's run is still the only one.
    runs = _runs(db_client, signing, created["id"])
    assert [run["trigger_kind"] for run in runs] == ["save"]


def test_stale_pointer_is_the_refresh_to_bind_state_with_no_new_runs(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _saved_chart_with_cache(db_client, signing, source_id)

    # An edited save with no bind block appends a revision; the pointer
    # still names the old one.
    resaved = db_client.put(
        f"/api/specs/{created['id']}",
        json={"content": CHANGED_FRAME},
        headers=bearer_headers(signing),
    )
    assert resaved.status_code == 200
    assert resaved.json()["revision_number"] == 2

    card = _list(db_client, signing)[0]
    assert card["revision_id"] == resaved.json()["revision_id"]
    # The disagreement is the *Refresh to bind* state — the client compares
    # and never binds behind a page load.
    assert card["cache"]["revision_id"] == created["revision_id"]
    assert card["cache"]["revision_id"] != card["revision_id"]

    # The old object is still served; the client discards it against the
    # pointer rather than pairing old rows with the new frame.
    cache_read = _read_cache(db_client, signing, created["id"])
    assert cache_read.status_code == 200
    assert cache_read.json()["revision_id"] == created["revision_id"]

    runs = _runs(db_client, signing, created["id"])
    assert [run["trigger_kind"] for run in runs] == ["save"]


class _MissingCacheObjectStore(DelegatingStore):
    """Writes behave; the cache object's read reports it gone — a pointer
    whose object was lost underneath it."""

    def open(self, key: str) -> Any:
        if key.endswith("last_bind.json"):
            raise FileNotFoundError(key)
        return super().open(key)


def test_missing_cache_object_is_the_refresh_to_bind_state_with_no_new_runs(
    signing: SigningKeys, tmp_path: Path, db_url: str, clean_db: None
) -> None:
    app = make_app(
        signing.jwks,
        database_url=db_url,
        object_store_dir=tmp_path / "objects",
    )
    app.state.object_store = _MissingCacheObjectStore(app.state.object_store)
    with TestClient(app) as client:
        source_id = _upload_source(client, signing)
        created = _saved_chart_with_cache(client, signing, source_id)

        # The pointer row is there and fresh; the object is gone.
        card = _list(client, signing)[0]
        assert card["cache"]["revision_id"] == created["revision_id"]
        assert _read_cache(client, signing, created["id"]).status_code == 404

        runs = _runs(client, signing, created["id"])
        assert [run["trigger_kind"] for run in runs] == ["save"]


def test_failed_bind_leaves_the_library_reading_the_old_picture(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _saved_chart_with_cache(
        db_client, signing, source_id, content=TRANSFORM_FRAME
    )
    broken_id = _upload_source(db_client, signing, content=CSV_MISSING_COLUMN)

    response = _refresh(db_client, signing, created["id"], source_id=broken_id)
    assert response.status_code == 409

    # The pointer is unmoved — a failed bind never blanks a card that was
    # rendering a moment ago (#75's rule, asserted from the Library read).
    card = _list(db_client, signing)[0]
    assert card["cache"] == created["cache"]
    # …and the object still serves the old rows.
    body = _read_cache(db_client, signing, created["id"]).json()
    assert body["revision_id"] == created["revision_id"]
    assert body["rows"] == [{"a": 2, "b": "y"}, {"a": 3, "b": "z"}]

    # The failed refresh wrote its error run; the Library reads wrote none.
    runs = _runs(db_client, signing, created["id"])
    assert [(run["trigger_kind"], run["status"]) for run in runs] == [
        ("refresh", "error"),
        ("save", "ok"),
    ]


def test_library_reads_never_cross_an_owner_boundary(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _saved_chart_with_cache(db_client, signing, source_id)

    assert _list(db_client, signing, sub="user_other") == []
    assert (
        _read_cache(db_client, signing, created["id"], sub="user_other").status_code
        == 404
    )


def test_library_routes_require_auth(db_client: TestClient) -> None:
    some_id = "018f3c3c-0000-7000-8000-000000000000"
    assert db_client.get("/api/specs").status_code == 401
    assert db_client.get(f"/api/specs/{some_id}/cache").status_code == 401
