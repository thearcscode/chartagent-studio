"""Resolving a library pin to bytes at plan time (#67, parent #62).

The agent names a library as ``(name, version)``. Studio resolves it once,
through the one pinned registry, to the version's single browser entry and
keeps those bytes in a globally content-addressed blob store. The pin's
sha256 is the hash of that file, not of the tarball. Nothing else is ever
fetched: a free URL is refused before any network call, and every URL the
resolver follows (including the tarball a manifest names) must be on the
registry host.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import tarfile
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urlsplit

from studio.storage import ObjectStore

REGISTRY_HOST = "registry.npmjs.org"
REGISTRY_URL = f"https://{REGISTRY_HOST}"

# build_shell caps one library at 10 MiB; the tarball may be larger than the
# file inside it, but not unboundedly so.
MAX_ENTRY_BYTES = 10 * 1024 * 1024
MAX_FETCH_BYTES = 64 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 20.0

_NAME = re.compile(r"^(@[a-z0-9][a-z0-9._~-]*/)?[a-z0-9][a-z0-9._~-]*$")
_VERSION = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$")

# The manifest fields that name a file for a browser global, in order.
_BROWSER_FIELDS = ("unpkg", "jsdelivr", "browser")

RegistryFetch = Callable[[str], bytes]
"""``url -> bytes``. The seam a fake registry stands in at."""


class RegistryFetchError(Exception):
    """The registry did not give us the bytes (unknown package, outage)."""


class LibraryResolveError(Exception):
    """A library could not be resolved; the message says why."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def fetch_registry_url(url: str) -> bytes:
    """The real fetcher: HTTPS GET, no redirects, a size cap, a timeout."""
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(url, timeout=FETCH_TIMEOUT_SECONDS) as response:
            data: bytes = response.read(MAX_FETCH_BYTES + 1)
    except (urllib.error.URLError, OSError) as exc:
        raise RegistryFetchError(f"registry request failed: {exc}") from exc
    if len(data) > MAX_FETCH_BYTES:
        raise RegistryFetchError("registry response is too large")
    return data


class LibraryBlobStore:
    """Library bytes by sha256: global, immutable, not owner-scoped.

    Keys are ``libraries/{sha256}.js`` on the object store, which is
    write-once; storing a hash that is already there is a no-op."""

    def __init__(self, store: ObjectStore) -> None:
        self._store = store

    @staticmethod
    def _key(sha256: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise ValueError(f"not a sha256: {sha256!r}")
        return f"libraries/{sha256}.js"

    def put(self, sha256: str, data: bytes) -> None:
        try:
            self._store.put(self._key(sha256), io.BytesIO(data))
        except FileExistsError:
            pass

    def get(self, sha256: str) -> bytes:
        with self._store.open(self._key(sha256)) as handle:
            return handle.read()


def _registry_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != REGISTRY_HOST or parts.port:
        raise LibraryResolveError("only the pinned registry can be contacted")
    return url


def _fetch(fetch: RegistryFetch, url: str) -> bytes:
    try:
        return fetch(_registry_url(url))
    except RegistryFetchError as exc:
        raise LibraryResolveError(str(exc)) from exc


def _browser_entry(manifest: dict[str, Any]) -> str:
    for field in _BROWSER_FIELDS:
        value = manifest.get(field)
        if isinstance(value, str) and value:
            return value.removeprefix("./").lstrip("/")
    raise LibraryResolveError("the package names no browser entry file")


def _extract(tarball: bytes, entry: str) -> bytes:
    wanted = f"package/{entry}"
    try:
        with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as archive:
            for member in archive:
                if member.isfile() and member.name == wanted:
                    if member.size > MAX_ENTRY_BYTES:
                        raise LibraryResolveError("the browser entry is too large")
                    handle = archive.extractfile(member)
                    if handle is not None:
                        return handle.read()
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise LibraryResolveError("the package tarball is unreadable") from exc
    raise LibraryResolveError(f"the package has no file {entry!r}")


def make_resolver(
    fetch: RegistryFetch, blobs: LibraryBlobStore
) -> Callable[[str, str], tuple[str, bytes]]:
    """The callable installed as ``ChartAgent._library_resolver``."""

    def resolve(name: str, version: str) -> tuple[str, bytes]:
        if not _NAME.fullmatch(name) or not _VERSION.fullmatch(version):
            raise LibraryResolveError(
                "a library is a registry package name and an exact version"
            )
        url = f"{REGISTRY_URL}/{quote(name, safe='@')}/{version}"
        try:
            manifest = json.loads(_fetch(fetch, url))
            if not isinstance(manifest, dict):
                raise TypeError("manifest is not an object")
            tarball_url = manifest["dist"]["tarball"]
            entry = _browser_entry(manifest)
        except (ValueError, KeyError, TypeError) as exc:
            raise LibraryResolveError("the registry manifest is unreadable") from exc
        data = _extract(_fetch(fetch, tarball_url), entry)
        sha256 = hashlib.sha256(data).hexdigest()
        blobs.put(sha256, data)
        return sha256, data

    return resolve
