"""Object storage behind a narrow interface (ADR-0006 D10): the vendor is
deliberately unchosen, the web filesystem is ephemeral and is not a store,
and Postgres `bytea` is rejected. The local-filesystem implementation is the
dev backend; keys are content-addressed, owner-scoped and write-once
(ADR-0007 D5) — `{owner_id}/{sha256}.{ext}`.
"""

import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import BinaryIO, Protocol

logger = logging.getLogger("studio")


class ObjectStore(Protocol):
    def put(self, key: str, source: BinaryIO) -> None:
        """Write `source` at `key`. Write-once: raises FileExistsError if the
        key is already taken. Callers dedup by content address first, so a
        raise means a race between identical bytes."""
        ...

    def replace(self, key: str, source: BinaryIO) -> None:
        """Write `source` at `key`, overwriting in place. The bind cache is a
        stable per-chart slot replaced on every successful user-initiated
        bind (ADR-0007 D6) — unlike content-addressed upload keys."""
        ...

    def open(self, key: str) -> BinaryIO:
        """Read the bytes at `key` back (the bind path's seam)."""
        ...

    def delete(self, key: str) -> None:
        """Remove the bytes at `key`. Missing keys are a no-op — deletes
        are hard and must not fail because the bucket was already empty."""
        ...


class LocalObjectStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def _path_for(self, key: str) -> Path:
        path = (self._root / key).resolve()
        if not path.is_relative_to(self._root.resolve()):
            raise ValueError(f"object key escapes the store root: {key!r}")
        return path

    def put(self, key: str, source: BinaryIO) -> None:
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-temp-then-link: a key only ever appears holding complete
        # bytes, and the link is the atomic no-clobber create. A partial
        # write stays at the temp name and is never served.
        fd, tmp_name = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=f".{uuid.uuid4().hex}.tmp"
        )
        try:
            with os.fdopen(fd, "wb") as target:
                while chunk := source.read(1024 * 1024):
                    target.write(chunk)
            os.link(tmp_name, path)  # raises FileExistsError if the key is taken
        finally:
            Path(tmp_name).unlink(missing_ok=True)

    def replace(self, key: str, source: BinaryIO) -> None:
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Same write-temp-then-move discipline as put, but the rename
        # atomically overwrites the slot.
        fd, tmp_name = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=f".{uuid.uuid4().hex}.tmp"
        )
        try:
            with os.fdopen(fd, "wb") as target:
                while chunk := source.read(1024 * 1024):
                    target.write(chunk)
            os.replace(tmp_name, path)
        finally:
            Path(tmp_name).unlink(missing_ok=True)

    def open(self, key: str) -> BinaryIO:
        return open(self._path_for(key), "rb")

    def delete(self, key: str) -> None:
        self._path_for(key).unlink(missing_ok=True)


def drop(store: ObjectStore, key: str | None) -> None:
    """Postgres does not empty the bucket (ADR-0007 D9). Missing keys
    are a no-op; a store failure is logged and does not resurrect the row."""
    if key is None:
        return
    try:
        store.delete(key)
    except Exception:
        logger.warning("object delete failed", extra={"object_key": key})
