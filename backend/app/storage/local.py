"""Opaque relative keys; original clinical filenames never become disk paths."""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import uuid4


@dataclass(frozen=True)
class StoredFile:
    path: str
    sha256: str


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()

    def _resolve(self, key: str) -> Path:
        if not re.fullmatch(r"(?:images|masks)/[0-9a-f]{32}\.(?:png|jpg|jpeg)", key):
            raise ValueError("Invalid storage key.")
        path = self.root.joinpath(*PurePosixPath(key).parts).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Storage path escapes root.")
        return path

    def save(self, content: bytes, *, category: str, suffix: str) -> StoredFile:
        """Caller validates image/mask bytes before saving; no overwrite."""
        key = f"{category}/{uuid4().hex}{suffix}"
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb") as stream:
                stream.write(content)
        except FileExistsError:
            raise
        except OSError:
            path.unlink(missing_ok=True)
            raise
        return StoredFile(key, hashlib.sha256(content).hexdigest())

    def read(self, key: str) -> bytes:
        return self._resolve(key).read_bytes()

    def delete(self, key: str) -> None:
        """Explicit cleanup for files whose database transaction failed."""
        self._resolve(key).unlink(missing_ok=True)
