"""The Flint pin, served by this server at a SHA-256-stamped, immutably
cached URL (ADR-0006 D6). Asserted through the HTTP API: the pin document,
the exact bytes, the cache header, and the refusal of any other hash.
"""

from chartagent import flint_bundle
from fastapi.testclient import TestClient

from tests.conftest import SigningKeys, bearer_headers


def test_flint_pin_names_the_bundle_and_its_url(
    client: TestClient, signing: SigningKeys
) -> None:
    bundle = flint_bundle()
    response = client.get("/api/flint", headers=bearer_headers(signing))
    assert response.status_code == 200
    body = response.json()
    assert body["flint_version"] == bundle.version
    assert body["bundle_sha256"] == bundle.sha256
    assert body["url"] == f"/api/flint/{bundle.sha256}/flint.iife.js"


def test_flint_bundle_serves_exact_bytes_immutably(
    client: TestClient, signing: SigningKeys
) -> None:
    bundle = flint_bundle()
    response = client.get(
        f"/api/flint/{bundle.sha256}/flint.iife.js",
        headers=bearer_headers(signing),
    )
    assert response.status_code == 200
    assert response.content == bundle.read_bytes()
    assert response.headers["cache-control"] == "max-age=31536000, immutable"
    assert response.headers["content-type"].startswith("text/javascript")


def test_flint_bundle_refuses_any_other_hash(
    client: TestClient, signing: SigningKeys
) -> None:
    other = "0" * 64
    response = client.get(
        f"/api/flint/{other}/flint.iife.js", headers=bearer_headers(signing)
    )
    assert response.status_code == 404


def test_flint_routes_require_auth(client: TestClient) -> None:
    bundle = flint_bundle()
    assert client.get("/api/flint").status_code == 401
    assert (
        client.get(f"/api/flint/{bundle.sha256}/flint.iife.js").status_code == 401
    )
