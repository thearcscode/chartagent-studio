"""Opening a saved custom-rail chart (#41): the owner-scoped shell route,
asserted through the HTTP API only. The library assembles the shell; these
tests check Studio carries it, refuses what it must, and writes nothing."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import update

from studio.models import SpecRevision
from tests.conftest import SigningKeys, bearer_headers
from tests.test_charts import FRAME, _runs, _upload_source
from tests.test_recipe_refresh import _recipe_chart, _refresh
from tests.test_recipe_save import RECIPE, _create, _pinned, _put


def _shell(
    client: TestClient, signing: SigningKeys, chart_id: str, *, sub: str = "user_2abc"
) -> Any:
    return client.get(
        f"/api/specs/{chart_id}/shell", headers=bearer_headers(signing, sub=sub)
    )


def test_shell_is_the_library_shell_with_exact_sandbox_and_no_rows(
    db_client: TestClient, signing: SigningKeys
) -> None:
    chart_id, _ = _recipe_chart(db_client, signing)
    rows = _refresh(db_client, signing, chart_id).json()["rows"]
    assert rows  # there are cached rows to leak

    response = _shell(db_client, signing, chart_id)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"html", "sandbox"}
    assert body["sandbox"] == ["allow-scripts"]
    assert body["html"]
    assert "window.render" in body["html"]  # the stored module, assembled
    for row in rows:
        for value in row.values():
            assert f'"{value}"' not in body["html"]
    # Pure read: the refresh above is the only run.
    assert len(_runs(db_client, signing, chart_id)) == 1
    _shell(db_client, signing, chart_id)
    assert len(_runs(db_client, signing, chart_id)) == 1


def test_shell_for_unknown_cross_owner_and_signed_out(
    db_client: TestClient, signing: SigningKeys
) -> None:
    chart_id, _ = _recipe_chart(db_client, signing)
    assert _shell(db_client, signing, chart_id, sub="user_other").status_code == 404
    unknown = "00000000-0000-0000-0000-000000000000"
    assert _shell(db_client, signing, unknown).status_code == 404
    assert db_client.get(f"/api/specs/{chart_id}/shell").status_code == 401


def test_shell_on_a_pinned_recipe_is_the_typed_refusal_not_a_fault(
    db_client: TestClient, signing: SigningKeys
) -> None:
    chart_id, _ = _recipe_chart(db_client, signing)
    with db_client.app.state.session_factory() as session:  # type: ignore[attr-defined]
        session.execute(update(SpecRevision).values(content=_pinned()))
        session.commit()
    response = _shell(db_client, signing, chart_id)
    assert response.status_code == 422
    assert response.json()["error"] == "pinned_libraries_unsupported"


def test_shell_on_a_frame_chart_is_refused_and_the_frame_chart_is_unaffected(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    created = _create(db_client, signing, source_id, FRAME).json()
    assert created["kind"] == "frame"
    assert _shell(db_client, signing, created["id"]).status_code == 422
    opened = db_client.get(
        f"/api/specs/{created['id']}", headers=bearer_headers(signing)
    )
    assert opened.status_code == 200
    assert opened.json()["kind"] == "frame"


def test_shell_follows_the_current_revision_across_a_rail_change(
    db_client: TestClient, signing: SigningKeys
) -> None:
    source_id = _upload_source(db_client, signing)
    chart_id = _create(db_client, signing, source_id, FRAME).json()["id"]
    assert _shell(db_client, signing, chart_id).status_code == 422
    assert _put(db_client, signing, chart_id, RECIPE).status_code == 200
    assert _shell(db_client, signing, chart_id).status_code == 200
    other_frame = deepcopy(FRAME)
    other_frame["chart_spec"]["encodings"]["x"] = {"field": "a"}
    assert _put(db_client, signing, chart_id, other_frame).status_code == 200
    assert _shell(db_client, signing, chart_id).status_code == 422
