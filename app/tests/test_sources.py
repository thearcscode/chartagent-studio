"""Source registration, asserted through the HTTP API only (the one
server-side seam, #63 "Testing decisions"). The library's own reading and
type inference are not re-tested here; what is asserted is that Studio
carries what the read returns.
"""

import hashlib
from pathlib import Path

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.conftest import FakeUrlDescriber, SigningKeys, bearer_headers, make_app

CSV_BYTES = b"a,b\n1,x\n2,y\n3,z\n"
CSV_SHA256 = hashlib.sha256(CSV_BYTES).hexdigest()

URL = "https://data.example.com/q3.csv"


def _parquet_bytes() -> bytes:
    table = pa.table({"x": [1, 2], "name": ["p", "q"]})
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink)
    return bytes(sink.getvalue().to_pybytes())


def _upload(
    client: TestClient,
    signing: SigningKeys,
    *,
    sub: str = "user_2abc",
    filename: str = "q3.csv",
    content: bytes = CSV_BYTES,
    content_type: str = "text/csv",
) -> httpx.Response:
    response: httpx.Response = client.post(
        "/api/sources/upload",
        files={"file": (filename, content, content_type)},
        headers=bearer_headers(signing, sub=sub),
    )
    return response


def test_upload_csv_registers_source(
    db_client: TestClient, signing: SigningKeys
) -> None:
    response = _upload(db_client, signing)
    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "upload"
    assert body["sha256"] == CSV_SHA256
    assert body["object_key"] == f"user_2abc/{CSV_SHA256}.csv"
    assert body["original_filename"] == "q3.csv"
    assert body["content_type"] == "text/csv"
    assert body["byte_size"] == len(CSV_BYTES)
    assert body["url"] is None
    # The source's schema at registration, as DuckDB reported it.
    assert body["schema_snapshot"] == {
        "columns": [
            {"name": "a", "type": "BIGINT", "bucket": "number"},
            {"name": "b", "type": "VARCHAR", "bucket": "string"},
        ]
    }

    fetched = db_client.get(
        f"/api/sources/{body['id']}", headers=bearer_headers(signing)
    )
    assert fetched.status_code == 200
    assert fetched.json() == body


def test_upload_parquet_registers_source(
    db_client: TestClient, signing: SigningKeys
) -> None:
    response = _upload(
        db_client,
        signing,
        filename="q3.parquet",
        content=_parquet_bytes(),
        content_type="application/octet-stream",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["object_key"].endswith(".parquet")
    assert body["schema_snapshot"] == {
        "columns": [
            {"name": "x", "type": "BIGINT", "bucket": "number"},
            {"name": "name", "type": "VARCHAR", "bucket": "string"},
        ]
    }


def test_same_upload_twice_reuses_bytes_and_writes_one_row(
    db_client: TestClient, signing: SigningKeys
) -> None:
    first = _upload(db_client, signing)
    assert first.status_code == 201
    second = _upload(db_client, signing)
    assert second.status_code == 200
    # One blob: the content-addressed key is identical.
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["object_key"] == first.json()["object_key"]
    # One source row.
    listing = db_client.get("/api/sources", headers=bearer_headers(signing))
    assert [row["id"] for row in listing.json()] == [first.json()["id"]]


def test_dedup_never_crosses_an_owner_boundary(
    db_client: TestClient, signing: SigningKeys
) -> None:
    first = _upload(db_client, signing, sub="user_2abc")
    second = _upload(db_client, signing, sub="user_other")
    assert second.status_code == 201
    assert second.json()["id"] != first.json()["id"]
    assert second.json()["object_key"] == f"user_other/{CSV_SHA256}.csv"


def test_upload_over_the_configured_limit_is_refused_before_consume(
    db_client: TestClient, signing: SigningKeys
) -> None:
    # A body that is not multipart at all: a 413 (not a 422 from the form
    # parser) proves the refusal happened before the body was consumed.
    response = db_client.post(
        "/api/sources/upload",
        content=b"this is never parsed as multipart",
        headers={
            **bearer_headers(signing),
            "content-type": "multipart/form-data; boundary=unused",
            "content-length": str(51 * 1024 * 1024),
        },
    )
    assert response.status_code == 413
    assert "52428800" in response.json()["detail"]


def test_upload_limit_is_configuration(
    signing: SigningKeys, tmp_path: Path, db_url: str
) -> None:
    app = make_app(
        signing.jwks,
        database_url=db_url,
        object_store_dir=tmp_path / "objects",
        upload_max_bytes=64,
    )
    with TestClient(app) as client:
        response = _upload(client, signing)
    assert response.status_code == 413


def test_chunked_upload_over_the_limit_is_refused_while_streaming(
    signing: SigningKeys, tmp_path: Path, db_url: str
) -> None:
    # No Content-Length (a streamed, chunked body): the header gate cannot
    # fire, so the spool-side check refuses as the bytes arrive.
    app = make_app(
        signing.jwks,
        database_url=db_url,
        object_store_dir=tmp_path / "objects",
        upload_max_bytes=64,
    )
    boundary = "testboundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="q3.csv"\r\n'
        "Content-Type: text/csv\r\n\r\n"
        f"a,b\n{'x' * 100}\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    # An iterator body goes out chunked: httpx sends no Content-Length.
    with TestClient(app) as client:
        response = client.post(
            "/api/sources/upload",
            content=iter([body]),
            headers={
                **bearer_headers(signing),
                "content-type": f"multipart/form-data; boundary={boundary}",
            },
        )
    assert response.status_code == 413


def test_cross_owner_fetch_fails(db_client: TestClient, signing: SigningKeys) -> None:
    created = _upload(db_client, signing, sub="user_2abc")
    source_id = created.json()["id"]

    fetched = db_client.get(
        f"/api/sources/{source_id}", headers=bearer_headers(signing, sub="user_other")
    )
    assert fetched.status_code == 404

    listing = db_client.get(
        "/api/sources", headers=bearer_headers(signing, sub="user_other")
    )
    assert listing.json() == []


def test_register_url_source(db_client: TestClient, signing: SigningKeys) -> None:
    response = db_client.post(
        "/api/sources", json={"url": URL}, headers=bearer_headers(signing)
    )
    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "url"
    assert body["url"] == URL
    assert body["object_key"] is None
    assert body["original_filename"] is None
    assert body["content_type"] is None
    assert body["byte_size"] is None
    assert body["sha256"] is None
    assert body["schema_snapshot"]["columns"]


def test_url_source_must_be_https(db_client: TestClient, signing: SigningKeys) -> None:
    for url in ("http://example.com/x.csv", "s3://bucket/x.parquet", "/tmp/x.csv"):
        response = db_client.post(
            "/api/sources", json={"url": url}, headers=bearer_headers(signing)
        )
        assert response.status_code == 422, url


def test_unreadable_url_is_refused(
    db_client: TestClient, db_app: FastAPI, signing: SigningKeys
) -> None:
    describer = db_app.state.source_describer
    assert isinstance(describer, FakeUrlDescriber)
    describer.unreadable_urls.add(URL)
    response = db_client.post(
        "/api/sources", json={"url": URL}, headers=bearer_headers(signing)
    )
    assert response.status_code == 422


def test_unreadable_upload_is_refused_and_writes_nothing(
    db_client: TestClient, signing: SigningKeys
) -> None:
    response = _upload(
        db_client,
        signing,
        filename="junk.parquet",
        content=b"definitely not parquet bytes",
        content_type="application/octet-stream",
    )
    assert response.status_code == 422
    listing = db_client.get("/api/sources", headers=bearer_headers(signing))
    assert listing.json() == []


def test_upload_must_be_csv_or_parquet(
    db_client: TestClient, signing: SigningKeys
) -> None:
    response = _upload(db_client, signing, filename="notes.txt", content=b"hello")
    assert response.status_code == 422


def test_cannot_set_both_shapes(db_client: TestClient, signing: SigningKeys) -> None:
    # A multipart request carrying a file and a url field.
    response = db_client.post(
        "/api/sources/upload",
        files={"file": ("q3.csv", CSV_BYTES, "text/csv")},
        data={"url": URL},
        headers=bearer_headers(signing),
    )
    assert response.status_code == 400
    # A JSON body carrying url plus upload-shape fields.
    response = db_client.post(
        "/api/sources",
        json={"url": URL, "object_key": "user_2abc/abc.csv"},
        headers=bearer_headers(signing),
    )
    assert response.status_code == 422


def test_sources_require_auth(db_client: TestClient) -> None:
    assert db_client.get("/api/sources").status_code == 401
    assert db_client.post("/api/sources", json={"url": URL}).status_code == 401
