from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, NamedTuple

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

from studio.config import Settings
from studio.main import create_app

TEST_KID = "studio-test-key"


class SigningKeys(NamedTuple):
    private_key: Any
    jwks: dict[str, Any]


class FakeJwksClient:
    """Stand-in for jwt.PyJWKClient that verifies against a test key set."""

    def __init__(self, jwks: dict[str, Any]) -> None:
        self._key_set = jwt.PyJWKSet.from_dict(jwks)

    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK:
        kid = jwt.get_unverified_header(token).get("kid")
        for key in self._key_set.keys:
            if key.key_id == kid:
                return key
        raise jwt.PyJWTError(f"unknown signing key: {kid!r}")


@pytest.fixture(scope="session")
def signing() -> SigningKeys:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    jwk.update(kid=TEST_KID, alg="RS256", use="sig")
    return SigningKeys(private_key=private_key, jwks={"keys": [jwk]})


def mint_token(
    private_key: Any,
    *,
    sub: str = "user_2abc",
    expires_in: float = 300,
    azp: str | None = None,
    iss: str | None = None,
    kid: str = TEST_KID,
) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {"sub": sub, "iat": now - 1, "exp": now + int(expires_in)}
    if azp is not None:
        claims["azp"] = azp
    if iss is not None:
        claims["iss"] = iss
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})


def make_app(
    jwks: dict[str, Any],
    *,
    authorized_parties: list[str] | None = None,
    issuer: str | None = None,
    web_dist_dir: Path | None = None,
) -> FastAPI:
    settings = Settings(
        clerk_jwks_url="https://clerk.test/.well-known/jwks.json",
        clerk_authorized_parties=authorized_parties or [],
        clerk_issuer=issuer,
        web_dist_dir=web_dist_dir or Path("/definitely/not/a/dist"),
    )
    app = create_app(settings)
    app.state.jwks_client = FakeJwksClient(jwks)
    return app


@pytest.fixture()
def app(signing: SigningKeys) -> FastAPI:
    return make_app(signing.jwks)


@pytest.fixture()
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
