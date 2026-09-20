import hashlib
from pathlib import Path

import pytest

from backend.app.storage.local import LocalStorage


def test_round_trip_hash_and_unique_keys(tmp_path):
    storage = LocalStorage(tmp_path / "files")
    content = b"synthetic test bytes"
    first = storage.save(content, category="images", suffix=".png")
    second = storage.save(content, category="images", suffix=".png")
    assert first.path != second.path
    assert first.sha256 == hashlib.sha256(content).hexdigest()
    assert storage.read(first.path) == content
    assert not Path(first.path).is_absolute()
    storage.delete(first.path)
    storage.delete(first.path)
    assert storage.read(second.path) == content
    with pytest.raises(FileNotFoundError):
        storage.read(first.path)


@pytest.mark.parametrize("key", ["../secret", "/tmp/secret", "C:/secret", "images/../secret", "images\\secret", "images/a.png:secret"])
def test_rejects_unsafe_keys(tmp_path, key):
    storage = LocalStorage(tmp_path)
    for operation in (storage.read, storage.delete):
        with pytest.raises(ValueError):
            operation(key)


@pytest.mark.parametrize("category,suffix", [("../outside", ".png"), ("images", ".exe"), ("masks", ".png/../x")])
def test_rejects_unsafe_save(tmp_path, category, suffix):
    with pytest.raises(ValueError):
        LocalStorage(tmp_path).save(b"data", category=category, suffix=suffix)
    assert list(tmp_path.iterdir()) == []


def test_rejects_resolved_path_outside_root(tmp_path, monkeypatch):
    storage = LocalStorage(tmp_path / "root")
    monkeypatch.setattr(Path, "resolve", lambda self: tmp_path / "outside")
    with pytest.raises(ValueError, match="escapes"):
        storage.read("images/" + "a" * 32 + ".png")
