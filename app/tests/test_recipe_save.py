"""Saving a custom-rail chart (#39), asserted through the HTTP API only. The
library validates and hashes the recipe; these tests check Studio carries
what it returns and refuses what it must."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

import pytest
from chartagent import ChartRecipe
from fastapi.testclient import TestClient
from sqlalchemy import update

from studio.models import SpecRevision
from tests.conftest import SigningKeys, bearer_headers
from tests.test_charts import FRAME, _upload_source

RECIPE: dict[str, Any] = {
    "spec_version": "1.2",
    "transform": {
        "filter": {
            "kind": "gt",
            "args": [{"kind": "col", "name": "a"}, {"kind": "lit", "value": 1}],
        }
    },
    "source_schema": {"a": "number"},
    "escape_reason": {"bucket": 1},
    "theme_spec": None,
    "document": {
        "module": "window.render = function (d, el) {};",
        "styles": None,
        "libraries": [],
        "contract_version": 1,
    },
}


def _pinned() -> dict[str, Any]:
    recipe = deepcopy(RECIPE)
    recipe["document"]["libraries"] = [
        {"name": "d3", "version": "7.9.0", "sha256": "0" * 64}
    ]
    return recipe


def _create(
    client: TestClient, signing: SigningKeys, source_id: str, content: Any, **extra: Any
) -> Any:
    return client.post(
        "/api/specs",
        json={"content": content, "source_id": source_id, **extra},
        headers=bearer_headers(signing),
    )


def _put(
    client: TestClient, signing: SigningKeys, chart_id: str, content: Any, **extra: Any
) -> Any:
    return client.put(
        f"/api/specs/{chart_id}",
        json={"content": content, **extra},
        headers=bearer_headers(signing),
    )


def _get(client: TestClient, signing: SigningKeys, chart_id: str) -> Any:
    return client.get(f"/api/specs/{chart_id}", headers=bearer_headers(signing))


def test_saving_a_recipe_stores_a_recipe_revision_with_the_library_hash(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    response = _create(db_client, signing, source_id, RECIPE)
    assert response.status_code == 201
    body = response.json()
    canonical = ChartRecipe.from_dict(RECIPE).canonical_json()
    assert body["kind"] == "recipe"
    assert body["authored_flint_version"] is None
    assert body["content"] == json.loads(canonical)
    assert body["content_hash"] == hashlib.sha256(canonical.encode()).hexdigest()
    assert body["revision_number"] == 1
    assert body["cache"] is None


def test_default_title_names_the_source_and_a_supplied_title_wins(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    assert (
        _create(db_client, signing, source_id, RECIPE).json()["title"]
        == "Custom · q3.csv"
    )
    named = _create(db_client, signing, source_id, RECIPE, title="Mine")
    assert named.json()["title"] == "Mine"


def test_identical_recipe_resave_is_a_no_op(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _create(db_client, signing, source_id, RECIPE).json()
    resaved = _put(db_client, signing, created["id"], RECIPE)
    assert resaved.status_code == 200
    assert resaved.json()["revision_number"] == 1
    assert resaved.json()["revision_id"] == created["revision_id"]


def test_invalid_recipe_is_422_and_stores_nothing(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    broken = deepcopy(RECIPE)
    broken["escape_reason"] = {"bucket": 9}
    response = _create(db_client, signing, source_id, broken)
    assert response.status_code == 422
    assert response.json()["error"] == "spec_shape"
    listing = db_client.get("/api/specs", headers=bearer_headers(signing))
    assert listing.json() == []


def test_a_pinned_recipe_saves_as_a_revision_holding_the_pin_only(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    response = _create(db_client, signing, source_id, _pinned())
    assert response.status_code == 201
    body = response.json()
    canonical = ChartRecipe.from_dict(_pinned()).canonical_json()
    assert body["kind"] == "recipe"
    assert body["revision_number"] == 1
    assert body["content_hash"] == hashlib.sha256(canonical.encode()).hexdigest()
    assert body["content"] == json.loads(canonical)
    assert body["content"]["document"]["libraries"] == [
        {"name": "d3", "version": "7.9.0", "sha256": "0" * 64}
    ]
    listed = db_client.get("/api/specs", headers=bearer_headers(signing)).json()
    assert [c["id"] for c in listed] == [body["id"]]


def test_saving_the_same_pinned_recipe_twice_is_an_unchanged_save(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _create(db_client, signing, source_id, _pinned()).json()
    resaved = _put(db_client, signing, created["id"], _pinned())
    assert resaved.status_code == 200
    assert resaved.json()["revision_number"] == 1
    assert resaved.json()["revision_id"] == created["revision_id"]


def test_a_chart_updates_from_scratch_to_pinned_as_a_new_revision(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _create(db_client, signing, source_id, RECIPE).json()
    updated = _put(db_client, signing, created["id"], _pinned())
    assert updated.status_code == 200
    assert updated.json()["revision_number"] == 2


def test_open_returns_a_stored_pinned_recipe_with_theme_spec_unchanged(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    chart_id = _create(db_client, signing, source_id, RECIPE).json()["id"]
    stored = _pinned()
    stored["theme_spec"] = "midnight"
    with db_client.app.state.session_factory() as session:  # type: ignore[attr-defined]
        session.execute(update(SpecRevision).values(content=stored))
        session.commit()
    response = _get(db_client, signing, chart_id)
    assert response.status_code == 200
    assert response.json()["content"]["theme_spec"] == "midnight"
    assert (
        response.json()["content"]["document"]["libraries"]
        == (stored["document"]["libraries"])
    )


def test_a_chart_moves_frame_to_recipe_and_back_with_monotonic_numbers(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _create(db_client, signing, source_id, FRAME).json()
    chart_id = created["id"]

    as_recipe = _put(db_client, signing, chart_id, RECIPE).json()
    assert (as_recipe["kind"], as_recipe["revision_number"]) == ("recipe", 2)
    assert as_recipe["authored_flint_version"] is None

    other_frame = deepcopy(FRAME)
    other_frame["chart_spec"]["encodings"]["x"] = {"field": "a"}
    back = _put(db_client, signing, chart_id, other_frame).json()
    assert (back["kind"], back["revision_number"]) == ("frame", 3)
    assert back["authored_flint_version"]

    revisions = db_client.get(
        f"/api/specs/{chart_id}/revisions", headers=bearer_headers(signing)
    ).json()
    assert [r["revision_number"] for r in revisions] == [3, 2, 1]


def test_get_list_revert_and_delete_work_on_a_recipe(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    chart_id = _create(db_client, signing, source_id, FRAME).json()["id"]
    _put(db_client, signing, chart_id, RECIPE)

    assert _get(db_client, signing, chart_id).json()["kind"] == "recipe"
    listed = db_client.get("/api/specs", headers=bearer_headers(signing)).json()
    assert [c["kind"] for c in listed] == ["recipe"]

    reverted = db_client.post(
        f"/api/specs/{chart_id}/revert",
        json={"revision_number": 1},
        headers=bearer_headers(signing),
    ).json()
    assert reverted["kind"] == "frame"
    db_client.post(
        f"/api/specs/{chart_id}/revert",
        json={"revision_number": 2},
        headers=bearer_headers(signing),
    )
    assert _get(db_client, signing, chart_id).json()["kind"] == "recipe"

    deleted = db_client.delete(
        f"/api/specs/{chart_id}", headers=bearer_headers(signing)
    )
    assert deleted.status_code == 204
    assert _get(db_client, signing, chart_id).status_code == 404


@pytest.mark.parametrize("recipe_side", ["from", "to"])
def test_diff_refuses_when_either_side_is_a_recipe(
    db_client: TestClient, signing: SigningKeys, recipe_side: str
) -> None:
    source_id = _upload_source(db_client, signing)
    chart_id = _create(db_client, signing, source_id, FRAME).json()["id"]
    _put(db_client, signing, chart_id, RECIPE)
    pair = (2, 1) if recipe_side == "from" else (1, 2)
    response = db_client.get(
        f"/api/specs/{chart_id}/revisions/{pair[0]}/diff/{pair[1]}",
        headers=bearer_headers(signing),
    )
    assert response.status_code == 422
    assert response.json()["error"] == "recipe_operation_unsupported"


def test_remap_preview_refuses_a_recipe_current_revision(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    chart_id = _create(db_client, signing, source_id, RECIPE).json()["id"]
    response = db_client.post(
        f"/api/specs/{chart_id}/remap-preview",
        json={"mapping": {}, "drifted": []},
        headers=bearer_headers(signing),
    )
    assert response.status_code == 422
    assert response.json()["error"] == "recipe_operation_unsupported"


def test_a_bind_block_cannot_ride_on_a_recipe(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    block = {"backend": "echarts", "content": FRAME, "rows": [], "elapsed_ms": 1}
    response = _create(db_client, signing, source_id, RECIPE, bind=block)
    assert response.status_code == 422


def test_cross_owner_and_signed_out_are_refused(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    chart_id = _create(db_client, signing, source_id, RECIPE).json()["id"]

    other = bearer_headers(signing, sub="user_other")
    assert (
        db_client.put(
            f"/api/specs/{chart_id}", json={"content": RECIPE}, headers=other
        ).status_code
        == 404
    )
    assert (
        db_client.post(
            "/api/specs",
            json={"content": RECIPE, "source_id": source_id},
            headers=other,
        ).status_code
        == 404
    )
    assert (
        db_client.post(
            "/api/specs", json={"content": RECIPE, "source_id": source_id}
        ).status_code
        == 401
    )
