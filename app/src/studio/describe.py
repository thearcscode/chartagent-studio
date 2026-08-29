"""The schema snapshot recorded on `data_sources` at registration time
(ADR-0007 D5): the *source's* schema as DuckDB reports it, names and reported
types verbatim. This is deliberately not the library's coarse bucket map —
that baseline is the library's to compute at bind time (CONTEXT.md, "Source
schema baseline"), and two bucketings of one source would drift silently.

The library exposes no describe verb on its public surface, so Studio reads
the source itself, mirroring the library's conventions — Parquet suffixes,
httpfs for HTTPS — so the snapshot describes what a later bind will read.
"""

from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

import duckdb

SchemaSnapshot = dict[str, Any]

# The suffix dispatch the library's source registration uses; the upload
# accept-list in routes/sources.py is built from this, so the two never drift.
PARQUET_SUFFIXES = (".parquet", ".pq")


class SourceUnreadableError(Exception):
    """The bytes or URL could not be read as CSV/Parquet by DuckDB."""


class SourceDescriber(Protocol):
    def describe_upload(self, path: Path, *, filename: str) -> SchemaSnapshot: ...
    def describe_url(self, url: str) -> SchemaSnapshot: ...


def read_kind(name: str) -> str:
    """The reader a source gets, from its name: Parquet suffixes, else CSV —
    the same dispatch the library's source registration uses."""
    return "parquet" if name.lower().endswith(PARQUET_SUFFIXES) else "csv"


class DuckDbDescriber:
    def describe_upload(self, path: Path, *, filename: str) -> SchemaSnapshot:
        return _describe(str(path), read_kind(filename), remote=False)

    def describe_url(self, url: str) -> SchemaSnapshot:
        return _describe(url, read_kind(urlparse(url).path), remote=True)


def _describe(source: str, kind: str, *, remote: bool) -> SchemaSnapshot:
    connection = duckdb.connect(":memory:")
    try:
        if remote:
            _load_httpfs(connection)
        try:
            if kind == "parquet":
                relation = connection.read_parquet(source)
            else:
                relation = connection.read_csv(source)
            relation.create_view("source")
            rows = connection.execute("DESCRIBE source").fetchall()
        except duckdb.Error as exc:
            raise SourceUnreadableError("source cannot be read") from exc
    finally:
        connection.close()
    # A list, not a map: jsonb does not preserve key order, and column order
    # is part of what a CSV's schema means.
    return {
        "columns": [{"name": str(row[0]), "type": str(row[1])} for row in rows]
    }


def _load_httpfs(connection: duckdb.DuckDBPyConnection) -> None:
    try:
        connection.execute("LOAD httpfs")
    except duckdb.Error:
        try:
            connection.execute("INSTALL httpfs")
            connection.execute("LOAD httpfs")
        except duckdb.Error as exc:
            raise SourceUnreadableError("source cannot be read") from exc
