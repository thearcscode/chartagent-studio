"""Save after revert numbers past the highest revision, not past current
(#16; hole left by #9). `current.revision_number + 1` collides with a row a
revert stepped back from — the fix is `max(revision_number) + 1`. Revert
itself, the revisions list, and library behaviour are #9's tests, not
this file's.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import SigningKeys, bearer_headers
from tests.test_charts import (
    FRAME,
    _bind_block,
    _preview_bind,
    _upload_source,
)
from tests.test_refresh import _saved_chart_with_cache
from tests.test_revisions import CHANGED_FRAME, _revert

# A third, distinct frame — different from both FRAME (rev 1) and
# CHANGED_FRAME (rev 2) — for the honest save after reverting to rev 1.
THIRD_FRAME: dict[str, Any] = {
    "chart_spec": {
        "chartType": "Bar Chart",
        "encodings": {"x": {"field": "b"}, "y": {"field": "b"}},
    }
}


def _save(
    client: TestClient,
    signing: SigningKeys,
    chart_id: str,
    source_id: str,
    *,
    content: dict[str, Any],
) -> Any:
    envelope = _preview_bind(client, signing, source_id, content=content).json()
    return client.put(
        f"/api/specs/{chart_id}",
        json={"content": content, "bind": _bind_block(envelope, content=content)},
        headers=bearer_headers(signing),
    )


def test_save_after_revert_numbers_past_the_highest_revision(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _saved_chart_with_cache(db_client, signing, source_id, content=FRAME)

    resaved = _save(db_client, signing, created["id"], source_id, content=CHANGED_FRAME)
    assert resaved.status_code == 200
    assert resaved.json()["revision_number"] == 2

    reverted = _revert(db_client, signing, created["id"], 1)
    assert reverted.status_code == 200
    assert reverted.json()["revision_number"] == 1

    third_save = _save(
        db_client, signing, created["id"], source_id, content=THIRD_FRAME
    )
    assert third_save.status_code == 200
    body = third_save.json()
    assert body["revision_number"] == 3

    revisions = db_client.get(
        f"/api/specs/{created['id']}/revisions", headers=bearer_headers(signing)
    ).json()
    assert [row["revision_number"] for row in revisions] == [3, 2, 1]
    assert revisions[0]["current"] is True


def test_save_after_revert_with_unchanged_content_is_still_a_no_op(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _saved_chart_with_cache(db_client, signing, source_id, content=FRAME)

    _save(db_client, signing, created["id"], source_id, content=CHANGED_FRAME)
    _revert(db_client, signing, created["id"], 1)

    # Reverted to 1, and 1's content is exactly what a save of `FRAME`
    # would produce — the no-op rule (ADR-0007 §4) still applies even
    # though a higher-numbered row (2) exists.
    noop_save = _save(db_client, signing, created["id"], source_id, content=FRAME)
    assert noop_save.status_code == 200
    body = noop_save.json()
    assert body["revision_number"] == 1
    assert body["revision_id"] == created["revision_id"]

    revisions = db_client.get(
        f"/api/specs/{created['id']}/revisions", headers=bearer_headers(signing)
    ).json()
    assert [row["revision_number"] for row in revisions] == [2, 1]


def test_remap_preview_to_revision_agrees_with_the_next_honest_save(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _saved_chart_with_cache(db_client, signing, source_id, content=FRAME)

    _save(db_client, signing, created["id"], source_id, content=CHANGED_FRAME)
    _revert(db_client, signing, created["id"], 1)

    response = db_client.post(
        f"/api/specs/{created['id']}/remap-preview",
        json={
            "mapping": {},
            "drifted": [],
        },
        headers=bearer_headers(signing),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["from_revision"] == 1
    # The honest save above would land on 3 (max is 2, not current's 1) —
    # remap-preview's header has to say the same thing.
    assert body["to_revision"] == 3

    # Pure preview: no row written, current still the pointer at 1.
    fetched = db_client.get(
        f"/api/specs/{created['id']}", headers=bearer_headers(signing)
    ).json()
    assert fetched["revision_number"] == 1
