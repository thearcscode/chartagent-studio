"""Custom-rail fixtures served as a mountable shell (#32). Asserted through the
HTTP API: the session gate, the sandbox tokens as the library returned them, a
rows-free shell, the wire rows, and the existing 404 shape. The shell's
internals are the library's to test, not ours.
"""

from typing import Any

import pytest
from chartagent import DocumentAssemblyError
from fastapi.testclient import TestClient

from studio.routes import fixtures
from tests.conftest import SigningKeys, bearer_headers

DRAWING_ROWS: list[dict[str, Any]] = [
    {"day": "2026-01-01", "value": 1.5},
    {"day": "2026-01-02", "value": None},
    {"day": "2026-01-03", "value": 4.0},
]


def test_fixture_route_requires_a_session(client: TestClient) -> None:
    assert client.get("/api/fixtures/drawing").status_code == 401


def test_drawing_fixture_returns_shell_and_wire_rows(
    client: TestClient, signing: SigningKeys
) -> None:
    response = client.get("/api/fixtures/drawing", headers=bearer_headers(signing))
    assert response.status_code == 200
    body = response.json()
    assert body["sandbox"] == ["allow-scripts"]
    assert body["html"]
    assert body["rows"] == DRAWING_ROWS


def test_shell_carries_none_of_the_rows(
    client: TestClient, signing: SigningKeys
) -> None:
    body = client.get("/api/fixtures/drawing", headers=bearer_headers(signing)).json()
    for marker in ("2026-01-01", "2026-01-02", "2026-01-03", "1.5"):
        assert marker not in body["html"]


def test_throwing_fixture_is_served_like_any_other(
    client: TestClient, signing: SigningKeys
) -> None:
    response = client.get("/api/fixtures/throwing", headers=bearer_headers(signing))
    assert response.status_code == 200
    assert response.json()["sandbox"] == ["allow-scripts"]


def test_unknown_fixture_is_404_in_the_error_shape(
    client: TestClient, signing: SigningKeys
) -> None:
    response = client.get("/api/fixtures/nope", headers=bearer_headers(signing))
    assert response.status_code == 404
    assert response.json() == {"detail": "Unknown fixture"}


def test_assembly_failure_surfaces_as_the_unmapped_5xx(
    client: TestClient,
    signing: SigningKeys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise DocumentAssemblyError("too big", kind="assembled_too_large")

    monkeypatch.setattr(fixtures, "build_shell", refuse)
    response = client.get("/api/fixtures/drawing", headers=bearer_headers(signing))
    assert response.status_code == 500
    assert "too big" not in response.text
