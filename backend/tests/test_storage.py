from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.storage import LocalFileStore


def test_save_read_exists_and_overwrite(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path)
    store.save("versions/abc/original", b"one")
    assert store.exists("versions/abc/original")
    assert store.read("versions/abc/original") == b"one"
    store.save("versions/abc/original", b"two")
    assert store.read("versions/abc/original") == b"two"
    assert not list(tmp_path.rglob(".tmp-*"))


def test_delete_prefix_removes_tree(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path)
    store.save("versions/abc/original", b"x")
    store.save("versions/abc/pages/1.png", b"y")
    store.delete_prefix("versions/abc")
    assert not store.exists("versions/abc/original")
    assert not (tmp_path / "versions" / "abc").exists()


@pytest.mark.parametrize("key", ["", "../etc/passwd", "/abs", "a//b", "a/../b", ".hidden", "a\\b"])
def test_invalid_keys_are_rejected(tmp_path: Path, key: str) -> None:
    with pytest.raises(ValueError):
        LocalFileStore(tmp_path).save(key, b"x")


def test_ingestion_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_JWT_SECRET", "s" * 40)
    settings = Settings(_env_file=None)
    assert settings.max_upload_mb == 100
    assert settings.embedding_model == "text-embedding-3-large"
    assert settings.embedding_dimensions == 1024
    assert settings.openai_api_key is None
