from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ASSEMBLER_PATH = REPOSITORY_ROOT / ".github" / "scripts" / "assemble_pages.py"


def _load_assembler():
    spec = importlib.util.spec_from_file_location("assemble_pages", ASSEMBLER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_proof(web_dist: Path, html: str = '<script src="./assets/app.js"></script>') -> None:
    (web_dist / "assets").mkdir(parents=True)
    (web_dist / "index.html").write_text(html, encoding="utf-8")
    (web_dist / "assets" / "app.js").write_text("export {};\n", encoding="utf-8")


def test_assemble_pages_copies_proof_and_preserves_mkdocs_site(tmp_path: Path, monkeypatch) -> None:
    assembler = _load_assembler()
    site = tmp_path / "site"
    web_dist = tmp_path / "web-dist"
    site.mkdir()
    (site / "index.html").write_text("<h1>Modelable docs</h1>", encoding="utf-8")
    _write_proof(web_dist)
    monkeypatch.chdir(tmp_path)

    assembler.assemble_pages(site, web_dist)

    assert (site / "index.html").read_text(encoding="utf-8") == "<h1>Modelable docs</h1>"
    assert (site / "playground" / "index.html").is_file()
    assert (site / "playground" / "assets" / "app.js").is_file()


def test_assemble_pages_refuses_proof_without_index(tmp_path: Path, monkeypatch) -> None:
    assembler = _load_assembler()
    site = tmp_path / "site"
    web_dist = tmp_path / "web-dist"
    site.mkdir()
    web_dist.mkdir()
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match=r"index\.html"):
        assembler.assemble_pages(site, web_dist)


def test_assemble_pages_replaces_existing_playground(tmp_path: Path, monkeypatch) -> None:
    assembler = _load_assembler()
    site = tmp_path / "site"
    web_dist = tmp_path / "web-dist"
    stale = site / "playground" / "stale.txt"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale", encoding="utf-8")
    _write_proof(web_dist)
    monkeypatch.chdir(tmp_path)

    assembler.assemble_pages(site, web_dist)

    assert not stale.exists()
    assert (site / "playground" / "index.html").is_file()


@pytest.mark.parametrize(
    "html",
    [
        '<script src="/assets/app.js"></script>',
        '<link href="/assets/app.css" rel="stylesheet">',
    ],
)
def test_assemble_pages_rejects_origin_root_assets(tmp_path: Path, monkeypatch, html: str) -> None:
    assembler = _load_assembler()
    site = tmp_path / "site"
    web_dist = tmp_path / "web-dist"
    site.mkdir()
    _write_proof(web_dist, html)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="origin-root asset URL"):
        assembler.assemble_pages(site, web_dist)
