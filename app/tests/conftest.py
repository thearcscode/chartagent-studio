from __future__ import annotations

import os
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
from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url

from studio.config import Settings
from studio.describe import DuckDbDescriber, SchemaSnapshot, SourceUnreadableError
from studio.main import create_app

TEST_KID = "studio-test-key"

_APP_DIR = Path(__file__).resolve().parents[1]


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


class FakeUrlDescriber:
    """URL describes need the network (DuckDB httpfs), which tests never
    touch — the same reason `FakeJwksClient` stands in above. Upload
    describes stay on the real DuckDB path: a local temp file is read
    in-process.
    """

    def __init__(self) -> None:
        self._uploads = DuckDbDescriber()
        self.unreadable_urls: set[str] = set()

    def describe_upload(self, path: Path, *, filename: str) -> SchemaSnapshot:
        return self._uploads.describe_upload(path, filename=filename)

    def describe_url(self, url: str) -> SchemaSnapshot:
        if url in self.unreadable_urls:
            raise SourceUnreadableError("source cannot be read")
        return {
            "columns": [
                {"name": "a", "type": "BIGINT"},
                {"name": "b", "type": "VARCHAR"},
            ]
        }


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


def bearer_headers(signing: SigningKeys, sub: str = "user_2abc") -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_token(signing.private_key, sub=sub)}"}


def make_app(
    jwks: dict[str, Any],
    *,
    authorized_parties: list[str] | None = None,
    issuer: str | None = None,
    web_dist_dir: Path | None = None,
    database_url: str | None = None,
    object_store_dir: Path | None = None,
    upload_max_bytes: int | None = None,
) -> FastAPI:
    overrides: dict[str, Any] = {}
    if database_url is not None:
        overrides["database_url"] = database_url
    if object_store_dir is not None:
        overrides["object_store_dir"] = object_store_dir
    if upload_max_bytes is not None:
        overrides["upload_max_bytes"] = upload_max_bytes
    settings = Settings(
        clerk_jwks_url="https://clerk.test/.well-known/jwks.json",
        clerk_authorized_parties=authorized_parties or [],
        clerk_issuer=issuer,
        web_dist_dir=web_dist_dir or Path("/definitely/not/a/dist"),
        **overrides,
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


# --- Database-backed fixtures ---------------------------------------------
#
# The URL names a *disposable* database: the session fixture creates it if
# missing, resets its public schema, and runs the real Alembic migrations —
# the migration is tested by being the only way the tables ever come into
# being. CI provides Postgres as a service; locally, any server works:
#
#   STUDIO_TEST_DATABASE_URL=postgresql+psycopg://user@localhost:5433/studio_test


@pytest.fixture(scope="session")
def db_url() -> Iterator[str]:
    url = os.environ.get(
        "STUDIO_TEST_DATABASE_URL",
        "postgresql+psycopg://studio:studio@localhost:5432/studio_test",
    )
    _ensure_database(url)
    _reset_schema(url)
    _migrate(url)
    yield url


def _ensure_database(url: str) -> None:
    target = make_url(url)
    maintenance = create_engine(
        target.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    try:
        with maintenance.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": target.database},
            ).first()
            if exists is None:
                connection.execute(text(f'CREATE DATABASE "{target.database}"'))
    finally:
        maintenance.dispose()


def _reset_schema(url: str) -> None:
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    finally:
        engine.dispose()


def _migrate(url: str) -> None:
    from alembic import command
    from alembic.config import Config

    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        config = Config(str(_APP_DIR / "alembic.ini"))
        command.upgrade(config, "head")
    finally:
        if previous is None:
            del os.environ["DATABASE_URL"]
        else:
            os.environ["DATABASE_URL"] = previous


@pytest.fixture()
def clean_db(db_url: str) -> None:
    engine = create_engine(db_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE charts, spec_revisions, data_sources,"
                    " bind_caches, runs CASCADE"
                )
            )
    finally:
        engine.dispose()


@pytest.fixture()
def db_app(
    signing: SigningKeys, db_url: str, clean_db: None, tmp_path: Path
) -> FastAPI:
    app = make_app(
        signing.jwks,
        database_url=db_url,
        object_store_dir=tmp_path / "objects",
    )
    app.state.source_describer = FakeUrlDescriber()
    return app


@pytest.fixture()
def db_client(db_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(db_app) as test_client:
        yield test_client
