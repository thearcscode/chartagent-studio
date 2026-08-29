from fastapi.testclient import TestClient

from tests.conftest import SigningKeys, make_app, mint_token


def test_health_is_public_and_reports_the_library_pin(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["chartagent"]  # the resolved chartagent distribution's version


def test_private_route_requires_auth(client: TestClient) -> None:
    response = client.get("/api/me")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_garbage_token_is_rejected(client: TestClient) -> None:
    response = client.get("/api/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


def test_expired_token_is_rejected(client: TestClient, signing: SigningKeys) -> None:
    token = mint_token(signing.private_key, expires_in=-120)
    response = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_unknown_signing_key_is_rejected(
    client: TestClient, signing: SigningKeys
) -> None:
    token = mint_token(signing.private_key, kid="some-other-key")
    response = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_valid_token_returns_the_clerk_user_id(
    client: TestClient, signing: SigningKeys
) -> None:
    token = mint_token(signing.private_key, sub="user_2f8k1")
    response = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == {"owner_id": "user_2f8k1"}


def test_azp_is_checked_when_authorized_parties_are_configured(
    signing: SigningKeys,
) -> None:
    app = make_app(signing.jwks, authorized_parties=["https://studio.example.com"])
    with TestClient(app) as client:
        bad = mint_token(signing.private_key, azp="https://evil.example.com")
        bad_response = client.get("/api/me", headers={"Authorization": f"Bearer {bad}"})
        assert bad_response.status_code == 401
        good = mint_token(signing.private_key, azp="https://studio.example.com")
        good_response = client.get(
            "/api/me", headers={"Authorization": f"Bearer {good}"}
        )
        assert good_response.status_code == 200


def test_issuer_is_checked_when_configured(signing: SigningKeys) -> None:
    app = make_app(signing.jwks, issuer="https://clerk.studio.example.com")
    with TestClient(app) as client:
        bad = mint_token(signing.private_key, iss="https://clerk.elsewhere.example.com")
        bad_response = client.get("/api/me", headers={"Authorization": f"Bearer {bad}"})
        assert bad_response.status_code == 401
        good = mint_token(
            signing.private_key, iss="https://clerk.studio.example.com"
        )
        good_response = client.get(
            "/api/me", headers={"Authorization": f"Bearer {good}"}
        )
        assert good_response.status_code == 200
