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
import threading
import urllib.error
import urllib.request
import zlib
from collections import OrderedDict
from collections.abc import Callable, Iterable
from typing import Any
from urllib.parse import quote, urlsplit

from chartagent import LibraryPin

from studio.storage import ObjectStore

REGISTRY_HOST = "registry.npmjs.org"
REGISTRY_URL = f"https://{REGISTRY_HOST}"

# build_shell caps one library at 10 MiB; the tarball may be larger than the
# file inside it, but not unboundedly so.
MAX_ENTRY_BYTES = 10 * 1024 * 1024
MAX_FETCH_BYTES = 64 * 1024 * 1024
# Decompressed bytes a tarball may expand to while we look for the entry.
MAX_SCAN_BYTES = 4 * MAX_ENTRY_BYTES
FETCH_TIMEOUT_SECONDS = 20.0
# The in-process blob cache (ADR-0007): a Library page of cards sharing a
# pin reads it once. Plotly is ~5 MB, so this holds a handful.
CACHE_MAX_BYTES = 64 * 1024 * 1024

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


class LibraryShellError(Exception):
    """One card's shell could not be assembled from its pinned bytes (#64).
    Raised by Studio so the fixtures route's unmapped-5xx contract for a
    bare `DocumentAssemblyError` stays as it was."""

    def __init__(self, message: str, *, kind: str) -> None:
        super().__init__(message)
        self.kind = kind


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
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        self._cache_bytes = 0
        self._lock = threading.Lock()

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
        """The bytes for `sha256`, read from the store once per process.

        Only bytes that hash to `sha256` are cached, so a corrupt object is
        re-read (and re-reported) rather than remembered; a missing one
        raises ``FileNotFoundError`` and caches nothing."""
        with self._lock:
            cached = self._cache.get(sha256)
            if cached is not None:
                self._cache.move_to_end(sha256)
                return cached
        with self._store.open(self._key(sha256)) as handle:
            data = handle.read()
        if hashlib.sha256(data).hexdigest() == sha256:
            self._remember(sha256, data)
        return data

    def _remember(self, sha256: str, data: bytes) -> None:
        if len(data) > CACHE_MAX_BYTES:
            return
        with self._lock:
            if sha256 in self._cache:
                self._cache.move_to_end(sha256)
                return
            self._cache[sha256] = data
            self._cache_bytes += len(data)
            while self._cache_bytes > CACHE_MAX_BYTES:
                _, evicted = self._cache.popitem(last=False)
                self._cache_bytes -= len(evicted)


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
    found: bytes | None = None
    try:
        # Decompress at most MAX_SCAN_BYTES: a gzip bomb stops here.
        inflater = zlib.decompressobj(wbits=31)
        raw = inflater.decompress(tarball, MAX_SCAN_BYTES + 1)
        if len(raw) > MAX_SCAN_BYTES:
            raise LibraryResolveError("the package tarball is too large")
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
            for member in archive:
                if member.isfile() and member.name == wanted:
                    if found is not None:
                        raise LibraryResolveError(
                            f"the package lists {entry!r} more than once"
                        )
                    if member.size > MAX_ENTRY_BYTES:
                        raise LibraryResolveError("the browser entry is too large")
                    handle = archive.extractfile(member)
                    if handle is not None:
                        found = handle.read()
    except (tarfile.TarError, OSError, EOFError, zlib.error) as exc:
        raise LibraryResolveError("the package tarball is unreadable") from exc
    if found is None:
        raise LibraryResolveError(f"the package has no file {entry!r}")
    return found


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
            tarball = _fetch(fetch, tarball_url)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise LibraryResolveError("the registry manifest is unreadable") from exc
        data = _extract(tarball, entry)
        sha256 = hashlib.sha256(data).hexdigest()
        blobs.put(sha256, data)
        return sha256, data

    return resolve


def load_library_bytes(
    blobs: LibraryBlobStore, pins: Iterable[LibraryPin]
) -> dict[str, bytes]:
    """The `libraries` mapping `build_shell` takes: each pin's bytes by
    sha256, read from the blob store. A pin whose blob is gone is left out,
    so `build_shell` reports it as ``pin_missing`` — one verifier, the
    library's."""
    found: dict[str, bytes] = {}
    for pin in pins:
        try:
            found[pin.sha256] = blobs.get(pin.sha256)
        except (FileNotFoundError, ValueError):
            continue
    return found
