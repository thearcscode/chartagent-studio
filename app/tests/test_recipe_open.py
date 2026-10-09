"""Opening a saved custom-rail chart (#41): the owner-scoped shell route,
asserted through the HTTP API only. The library assembles the shell; these
tests check Studio carries it, refuses what it must, and writes nothing."""

from __future__ import annotations

import base64
import hashlib
import io
import uuid
from copy import deepcopy
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import update

from studio.models import SpecRevision
from tests.conftest import FakeRegistry, SigningKeys, bearer_headers
from tests.test_charts import FRAME, _runs, _upload_source
from tests.test_recipe_refresh import _recipe_chart, _refresh
from tests.test_recipe_save import RECIPE, _create, _put


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


def _library_bytes(text: str) -> tuple[str, bytes]:
    data = text.encode()
    return hashlib.sha256(data).hexdigest(), data


def _pinned_chart(
    client: TestClient,
    signing: SigningKeys,
    *libraries: tuple[str, str, str],
    seed: bool = True,
) -> str:
    """A saved chart whose stored recipe pins `(name, version, text)`
    libraries; `seed` puts each one's bytes in the blob store."""
    chart_id, _ = _recipe_chart(
        client, signing, content=f"a,b\n{uuid.uuid4().int},1\n".encode()
    )
    recipe = deepcopy(RECIPE)
    pins = []
    for name, version, text in libraries:
        sha256, data = _library_bytes(text)
        pins.append({"name": name, "version": version, "sha256": sha256})
        if seed:
            client.app.state.library_blobs.put(sha256, data)  # type: ignore[attr-defined]
    recipe["document"]["libraries"] = pins
    with client.app.state.session_factory() as session:  # type: ignore[attr-defined]
        session.execute(
            update(SpecRevision)
            .where(SpecRevision.chart_id == uuid.UUID(chart_id))
            .values(content=recipe)
        )
        session.commit()
    return chart_id


def _count_library_reads(client: TestClient) -> list[str]:
    """Patch the object store to record every library key it opens."""
    store = client.app.state.object_store  # type: ignore[attr-defined]
    opened: list[str] = []
    real_open = store.open

    def spy(key: str) -> Any:
        if key.startswith("libraries/"):
            opened.append(key)
        return real_open(key)

    store.open = spy
    return opened


def test_a_pinned_recipe_opens_with_the_library_before_the_module_and_a_csp(
    db_client: TestClient, signing: SigningKeys
) -> None:
    lib = "window.D3 = {tag: 'LIBRARY-ONE'};"
    chart_id = _pinned_chart(db_client, signing, ("d3", "7.9.0", lib))
    response = _shell(db_client, signing, chart_id)
    assert response.status_code == 200
    body = response.json()
    assert body["sandbox"] == ["allow-scripts"]
    html = body["html"]
    assert lib in html
    assert html.index(lib) < html.index("window.render")
    digest = base64.b64encode(hashlib.sha256(lib.encode()).digest()).decode()
    assert f"'sha256-{digest}'" in html


def test_a_recipe_with_two_pins_loads_both_in_pin_order(
    db_client: TestClient, signing: SigningKeys
) -> None:
    first, second = "window.A = 'FIRST-LIB';", "window.B = 'SECOND-LIB';"
    chart_id = _pinned_chart(
        db_client, signing, ("a", "1.0.0", first), ("b", "1.0.0", second)
    )
    html = _shell(db_client, signing, chart_id).json()["html"]
    assert html.index(first) < html.index(second) < html.index("window.render")


def test_open_and_the_library_list_do_not_refuse_a_pinned_recipe(
    db_client: TestClient, signing: SigningKeys
) -> None:
    chart_id = _pinned_chart(db_client, signing, ("d3", "1.0.0", "window.X = 1;"))
    headers = bearer_headers(signing)
    assert db_client.get(f"/api/specs/{chart_id}", headers=headers).status_code == 200
    listed = db_client.get("/api/specs", headers=headers)
    assert [c["id"] for c in listed.json()] == [chart_id]


def test_repeat_loads_of_a_pin_read_the_store_once(
    db_client: TestClient, signing: SigningKeys
) -> None:
    lib = "window.CACHED = 1;"
    first = _pinned_chart(db_client, signing, ("d3", "1.0.0", lib))
    second = _pinned_chart(db_client, signing, ("d3", "1.0.0", lib))
    opened = _count_library_reads(db_client)
    for chart_id in (first, second, first):
        assert _shell(db_client, signing, chart_id).status_code == 200
    assert opened == [f"libraries/{_library_bytes(lib)[0]}.js"]


def test_a_missing_and_a_corrupt_blob_fail_only_their_own_card(
    db_client: TestClient, signing: SigningKeys
) -> None:
    good = _pinned_chart(db_client, signing, ("ok", "1.0.0", "window.OK = 1;"))
    missing = _pinned_chart(
        db_client, signing, ("gone", "1.0.0", "window.GONE = 1;"), seed=False
    )
    corrupt = _pinned_chart(db_client, signing, ("bad", "1.0.0", "window.BAD = 1;"))
    # The store is write-once; swap the object underneath to corrupt it.
    sha256, _ = _library_bytes("window.BAD = 1;")
    db_client.app.state.object_store.replace(  # type: ignore[attr-defined]
        f"libraries/{sha256}.js", io.BytesIO(b"tampered")
    )

    assert _shell(db_client, signing, good).status_code == 200
    gone = _shell(db_client, signing, missing)
    bad = _shell(db_client, signing, corrupt)
    assert gone.status_code == bad.status_code == 422
    assert gone.json()["error"] == "library_missing"
    assert bad.json()["error"] == "library_corrupt"
    assert "gone@1.0.0" in gone.json()["message"]
    assert "bad@1.0.0" in bad.json()["message"]
    # Neither failure took the others down.
    assert _shell(db_client, signing, good).status_code == 200
    listed = db_client.get("/api/specs", headers=bearer_headers(signing))
    assert listed.status_code == 200
    assert len(listed.json()) == 3


def test_open_and_paint_do_not_touch_the_registry(
    db_client: TestClient, signing: SigningKeys, registry: FakeRegistry
) -> None:
    registry.down = True
    chart_id = _pinned_chart(db_client, signing, ("d3", "1.0.0", "window.Z = 1;"))
    assert _shell(db_client, signing, chart_id).status_code == 200
    opened = db_client.get(f"/api/specs/{chart_id}", headers=bearer_headers(signing))
    assert opened.status_code == 200
    assert registry.requests == []


def test_a_from_scratch_chart_reads_no_blobs(
    db_client: TestClient, signing: SigningKeys
) -> None:
    chart_id, _ = _recipe_chart(db_client, signing)
    opened = _count_library_reads(db_client)
    assert _shell(db_client, signing, chart_id).status_code == 200
    assert opened == []


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
