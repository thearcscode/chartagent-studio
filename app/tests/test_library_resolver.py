"""The library resolver at plan time (#67, parent #62).

Seam: the plan route through the HTTP API, a fake registry standing in for
registry.npmjs.org, the real blob store. The model is scripted on the app's
chart agent; nothing here re-tests the library planner."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from tests.conftest import FakeRegistry, SigningKeys, bearer_headers
from tests.test_charts import CSV_BYTES, _upload_source

ENTRY = b"/* d3 */ window.d3 = { version: '7.9.0' };"
ENTRY_SHA = hashlib.sha256(ENTRY).hexdigest()
REGISTRY = "https://registry.npmjs.org"

TRANSFORM = {
    "group_by": ["b"],
    "aggregate": [{"name": "total", "op": "sum", "field": "a"}],
}

INEXPRESSIBLE = ("Inexpressible", {"outcome": "inexpressible", "bucket": 1})
D3 = [{"name": "d3", "version": "7.9.0"}]


def _draft(libraries: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "transform": TRANSFORM,
        "semantic_types": {"total": "Quantity"},
        "document": {
            "module": "window.render = function (d, el) {};",
            "styles": None,
            "libraries": libraries,
        },
    }


def _script_model(app: FastAPI, *replies: tuple[str, dict[str, Any]]) -> list[int]:
    """Script the planner's model: each reply is (kind, args). Returns a
    one-item model-call counter."""
    queue = list(replies)
    calls = [0]

    def fn(_messages: object, info: AgentInfo) -> ModelResponse:
        calls[0] += 1
        kind, args = queue.pop(0)
        if kind == "step2":
            name = info.output_tools[0].name
        else:
            name = next(t.name for t in info.output_tools if kind in t.name)
        return ModelResponse(parts=[ToolCallPart(tool_name=name, args=args)])

    app.state.chart_agent._client._model = FunctionModel(fn)
    return calls


def _plan(client: TestClient, signing: SigningKeys, source_id: str) -> Any:
    return client.post(
        "/api/specs/plan",
        json={"instruction": "a force-directed graph", "source_id": source_id},
        headers=bearer_headers(signing),
    )


def _plan_with_libraries(
    app: FastAPI,
    client: TestClient,
    signing: SigningKeys,
    libraries: list[dict[str, str]],
    *extra: tuple[str, dict[str, Any]],
) -> Any:
    _script_model(app, INEXPRESSIBLE, ("step2", _draft(libraries)), *extra)
    # A repeat upload of the same bytes answers 200 with the existing source.
    upload = client.post(
        "/api/sources/upload",
        files={"file": ("q3.csv", CSV_BYTES, "text/csv")},
        headers=bearer_headers(signing),
    )
    return _plan(client, signing, upload.json()["id"])


def test_plan_pins_the_browser_entry_hash_and_stores_the_blob(
    db_app: FastAPI,
    db_client: TestClient,
    signing: SigningKeys,
    registry: FakeRegistry,
) -> None:
    tarball = registry.publish("d3", "7.9.0", "dist/d3.min.js", ENTRY)

    response = _plan_with_libraries(db_app, db_client, signing, D3)

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "recipe"
    assert body["recipe"]["document"]["libraries"] == [
        {"name": "d3", "version": "7.9.0", "sha256": ENTRY_SHA}
    ]
    assert ENTRY_SHA != hashlib.sha256(tarball).hexdigest()
    assert db_app.state.library_blobs.get(ENTRY_SHA) == ENTRY


def test_plan_response_never_carries_the_bytes(
    db_app: FastAPI,
    db_client: TestClient,
    signing: SigningKeys,
    registry: FakeRegistry,
) -> None:
    registry.publish("d3", "7.9.0", "dist/d3.min.js", ENTRY)

    response = _plan_with_libraries(db_app, db_client, signing, D3)

    assert response.status_code == 200
    assert "window.d3" not in response.text
    assert set(response.json()) == {"kind", "recipe", "plan_elapsed_ms"}


def test_storing_the_same_hash_twice_is_a_no_op(
    db_app: FastAPI,
    db_client: TestClient,
    signing: SigningKeys,
    registry: FakeRegistry,
) -> None:
    registry.publish("d3", "7.9.0", "dist/d3.min.js", ENTRY)
    first = _plan_with_libraries(db_app, db_client, signing, D3)
    second = _plan_with_libraries(db_app, db_client, signing, D3)

    assert first.status_code == second.status_code == 200
    db_app.state.library_blobs.put(ENTRY_SHA, ENTRY)
    assert db_app.state.library_blobs.get(ENTRY_SHA) == ENTRY


def test_a_free_url_is_refused_and_nothing_is_contacted(
    db_app: FastAPI,
    db_client: TestClient,
    signing: SigningKeys,
    registry: FakeRegistry,
) -> None:
    evil = [{"name": "https://evil.example/lib.js", "version": "1.0.0"}]
    response = _plan_with_libraries(db_app, db_client, signing, evil, ("step2", {}))

    assert response.status_code == 422
    assert response.json()["error"] == "inexpressible_request"
    assert registry.requests == []


def test_only_the_registry_host_is_contacted_even_if_the_manifest_points_away(
    db_app: FastAPI,
    db_client: TestClient,
    signing: SigningKeys,
    registry: FakeRegistry,
) -> None:
    away = "https://evil.example/d3.tgz"
    registry.publish("d3", "7.9.0", "dist/d3.min.js", ENTRY, tarball_url=away)

    response = _plan_with_libraries(db_app, db_client, signing, D3)

    assert response.status_code == 422
    assert registry.requests == [f"{REGISTRY}/d3/7.9.0"]


def test_an_unknown_version_ends_the_plan_with_a_clear_failure(
    db_app: FastAPI,
    db_client: TestClient,
    signing: SigningKeys,
) -> None:
    calls = _script_model(db_app, INEXPRESSIBLE, ("step2", _draft(D3)))

    response = _plan(db_client, signing, _upload_source(db_client, signing))

    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "inexpressible_request"
    assert "d3@7.9.0" in body["message"]
    assert calls[0] == 2  # no second model ask (ADR-0030 Decision 8)


def test_a_registry_outage_ends_the_plan_with_a_clear_failure(
    db_app: FastAPI,
    db_client: TestClient,
    signing: SigningKeys,
    registry: FakeRegistry,
) -> None:
    registry.publish("d3", "7.9.0", "dist/d3.min.js", ENTRY)
    registry.down = True

    response = _plan_with_libraries(db_app, db_client, signing, D3)

    assert response.status_code == 422
    assert "d3@7.9.0" in response.json()["message"]


def test_a_package_with_no_browser_entry_is_refused(
    db_app: FastAPI,
    db_client: TestClient,
    signing: SigningKeys,
    registry: FakeRegistry,
) -> None:
    registry.publish(
        "d3", "7.9.0", "dist/d3.min.js", ENTRY, manifest={"name": "d3", "main": "x.js"}
    )

    response = _plan_with_libraries(db_app, db_client, signing, D3)

    assert response.status_code == 422
    assert "d3@7.9.0" in response.json()["message"]


def test_with_the_resolver_unset_a_plan_cannot_pin_a_library(
    db_app: FastAPI,
    db_client: TestClient,
    signing: SigningKeys,
    registry: FakeRegistry,
) -> None:
    registry.publish("d3", "7.9.0", "dist/d3.min.js", ENTRY)
    db_app.state.chart_agent._library_resolver = None

    response = _plan_with_libraries(
        db_app, db_client, signing, D3, ("step2", _draft(D3))
    )

    assert response.status_code == 422
    assert registry.requests == []


def test_a_from_scratch_plan_makes_no_registry_or_store_calls(
    db_app: FastAPI,
    db_client: TestClient,
    signing: SigningKeys,
    registry: FakeRegistry,
    tmp_path: Path,
) -> None:
    response = _plan_with_libraries(db_app, db_client, signing, [])

    assert response.status_code == 200
    assert response.json()["recipe"]["document"]["libraries"] == []
    assert registry.requests == []
    assert not (tmp_path / "objects" / "libraries").exists()
