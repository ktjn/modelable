from pathlib import Path

import pytest

from modelable.rag.bundled_index import bundled_documentation_index_path


def test_bundled_documentation_index_path_returns_manifest(monkeypatch, tmp_path: Path) -> None:
    fake_data = tmp_path / "modelable" / "data"
    fake_docs_index = fake_data / "docs-index"
    fake_docs_index.mkdir(parents=True)
    manifest = fake_docs_index / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        "modelable.rag.bundled_index.importlib.resources.files",
        lambda package: fake_data if package == "modelable.data" else tmp_path,
    )

    assert bundled_documentation_index_path() == manifest


def test_bundled_documentation_index_path_raises_when_missing(monkeypatch, tmp_path: Path) -> None:
    fake_data = tmp_path / "modelable" / "data"
    fake_data.mkdir(parents=True)

    monkeypatch.setattr(
        "modelable.rag.bundled_index.importlib.resources.files",
        lambda package: fake_data if package == "modelable.data" else tmp_path,
    )

    with pytest.raises(RuntimeError, match="Bundled documentation index"):
        bundled_documentation_index_path()
