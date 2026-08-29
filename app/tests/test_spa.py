from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import SigningKeys, make_app


@pytest.fixture()
def spa_client(tmp_path: Path, signing: SigningKeys) -> Iterator[TestClient]:
    (tmp_path / "index.html").write_text('<div id="root"></div>')
    app = make_app(signing.jwks, web_dist_dir=tmp_path)
    with TestClient(app) as client:
        yield client


def test_client_side_route_serves_index(spa_client: TestClient) -> None:
    response = spa_client.get("/sign-in")
    assert response.status_code == 200
    assert 'id="root"' in response.text


def test_missing_file_404s_honestly(spa_client: TestClient) -> None:
    response = spa_client.get("/fonts/missing.woff2")
    assert response.status_code == 404


def test_no_openapi_promise(spa_client: TestClient) -> None:
    assert spa_client.get("/openapi.json").status_code == 404
    # /docs is just an unknown client route: the SPA shell, not Swagger UI.
    response = spa_client.get("/docs")
    assert response.status_code == 200
    assert "swagger" not in response.text.lower()
