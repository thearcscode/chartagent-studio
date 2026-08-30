"""Revision history and revert-by-pointer (#9; ADR-0007 D3 erratum).

List is newest-first and marks current from the pointer, never from
`max(revision_number)`. Revert repoints, writes no revision row and no run,
leaves every revision in place (so it is itself revertible), and makes the
bind cache pointer stale — a load is *Refresh to bind*, still writing no
run. Asserted through the HTTP API only (#81 "Testing decisions").
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import SigningKeys, bearer_headers
from tests.test_charts import (
    _bind_block,
    _create_spec,
    _preview_bind,
    _runs,
    _upload_source,
)
from tests.test_refresh import _saved_chart_with_cache

CHANGED_FRAME: dict[str, Any] = {
    "chart_spec": {
        "chartType": "Bar Chart",
        "encodings": {"x": {"field": "a"}, "y": {"field": "a"}},
    }
}


def _revisions(
    client: TestClient, signing: SigningKeys, chart_id: str, *, sub: str = "user_2abc"
) -> Any:
    return client.get(
        f"/api/specs/{chart_id}/revisions", headers=bearer_headers(signing, sub=sub)
    )


def _revert(
    client: TestClient,
    signing: SigningKeys,
    chart_id: str,
    revision_number: int,
    *,
    sub: str = "user_2abc",
) -> Any:
    return client.post(
        f"/api/specs/{chart_id}/revert",
        json={"revision_number": revision_number},
        headers=bearer_headers(signing, sub=sub),
    )


def _two_revision_chart(
    client: TestClient, signing: SigningKeys, source_id: str
) -> dict[str, Any]:
    """Rev 1 cached, then an honest save of a different frame as rev 2 —
    so the cache names rev 2. Reverting to 1 is the stale-pointer case."""
    created = _saved_chart_with_cache(client, signing, source_id)
    envelope = _preview_bind(
        client, signing, source_id, content=CHANGED_FRAME
    ).json()
    resaved = client.put(
        f"/api/specs/{created['id']}",
        json={
            "content": CHANGED_FRAME,
            "bind": _bind_block(envelope, content=CHANGED_FRAME),
        },
        headers=bearer_headers(signing),
    )
    assert resaved.status_code == 200
    body = resaved.json()
    assert body["revision_number"] == 2
    assert body["cache"] is not None
    assert body["cache"]["revision_id"] == body["revision_id"]
    return created


def test_revisions_list_is_newest_first_and_marks_current_from_the_pointer(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _two_revision_chart(db_client, signing, source_id)

    response = _revisions(db_client, signing, created["id"])
    assert response.status_code == 200
    rows = response.json()
    assert [row["revision_number"] for row in rows] == [2, 1]
    assert set(rows[0]) == {
        "revision_number",
        "created_at",
        "content_hash",
        "authored_flint_version",
        "current",
    }
    assert rows[0]["current"] is True
    assert rows[1]["current"] is False
    assert rows[0]["authored_flint_version"]
    assert rows[0]["content_hash"] != rows[1]["content_hash"]
    assert rows[1]["content_hash"] == created["content_hash"]


def test_revert_repoints_without_writing_a_row_and_the_list_says_so(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _two_revision_chart(db_client, signing, source_id)

    reverted = _revert(db_client, signing, created["id"], 1)
    assert reverted.status_code == 200
    body = reverted.json()
    assert body["revision_number"] == 1
    assert body["revision_id"] == created["revision_id"]
    assert body["content_hash"] == created["content_hash"]

    rows = _revisions(db_client, signing, created["id"]).json()
    assert [row["revision_number"] for row in rows] == [2, 1]
    # Current is the pointer, not the highest number — after a revert the
    # highest is not current, and a UI that computed it would be wrong.
    assert rows[0]["current"] is False
    assert rows[1]["current"] is True


def test_revert_leaves_every_revision_in_place_and_is_itself_revertible(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _two_revision_chart(db_client, signing, source_id)

    _revert(db_client, signing, created["id"], 1)
    back = _revert(db_client, signing, created["id"], 2)
    assert back.status_code == 200
    assert back.json()["revision_number"] == 2

    rows = _revisions(db_client, signing, created["id"]).json()
    assert [row["revision_number"] for row in rows] == [2, 1]
    assert rows[0]["current"] is True
    assert rows[1]["current"] is False


def test_revert_writes_no_run_and_a_load_is_refresh_to_bind(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _two_revision_chart(db_client, signing, source_id)
    runs_before = _runs(db_client, signing, created["id"])
    assert {run["trigger_kind"] for run in runs_before} == {"save"}

    reverted = _revert(db_client, signing, created["id"], 1).json()
    # The pointer moved; the cache still names the revision it was bound
    # against. That disagreement is *Refresh to bind* — pairing those rows
    # with this frame is a wrong chart, not a display that is merely early.
    assert reverted["cache"] is not None
    assert reverted["cache"]["revision_id"] != reverted["revision_id"]
    assert reverted["revision_id"] == created["revision_id"]

    assert _runs(db_client, signing, created["id"]) == runs_before

    loaded = db_client.get(
        f"/api/specs/{created['id']}", headers=bearer_headers(signing)
    ).json()
    assert loaded["revision_id"] == created["revision_id"]
    assert loaded["cache"]["revision_id"] != loaded["revision_id"]
    assert _runs(db_client, signing, created["id"]) == runs_before


def test_unknown_revision_number_is_404(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _create_spec(db_client, signing, source_id).json()
    response = _revert(db_client, signing, created["id"], 9)
    assert response.status_code == 404


def test_list_and_revert_404_on_another_owners_chart(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing, sub="user_2abc")
    created = _create_spec(db_client, signing, source_id, sub="user_2abc").json()

    assert (
        _revisions(db_client, signing, created["id"], sub="user_other").status_code
        == 404
    )
    assert (
        _revert(db_client, signing, created["id"], 1, sub="user_other").status_code
        == 404
    )
