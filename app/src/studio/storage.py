"""Object storage behind a narrow interface (ADR-0006 D10): the vendor is
deliberately unchosen, the web filesystem is ephemeral and is not a store,
and Postgres `bytea` is rejected. The local-filesystem implementation is the
dev backend; keys are content-addressed, owner-scoped and write-once
(ADR-0007 D5) — `{owner_id}/{sha256}.{ext}`.
"""

import os
import tempfile
import uuid
from pathlib import Path
from typing import BinaryIO, Protocol


class ObjectStore(Protocol):
    def put(self, key: str, source: BinaryIO) -> None:
        """Write `source` at `key`. Write-once: raises FileExistsError if the
        key is already taken. Callers dedup by content address first, so a
        raise means a race between identical bytes."""
        ...

    def open(self, key: str) -> BinaryIO:
        """Read the bytes at `key` back (the bind path's seam)."""
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

    def open(self, key: str) -> BinaryIO:
        return open(self._path_for(key), "rb")
