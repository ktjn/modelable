import json
from pathlib import Path

from modelable.rag.bundled_index_builder import build_bundled_index


def test_build_bundled_index_creates_manifest_and_docs(tmp_path: Path) -> None:
    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    (docs_root / "guide.md").write_text("# Guide\n\nInstall with uv.\n", encoding="utf-8")
    output_dir = tmp_path / "out"

    manifest_path = build_bundled_index(docs_root, output_dir)

    assert manifest_path == output_dir / "manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    doc_file = output_dir / manifest["shards"]["docs"][0]["file"]
    docs = json.loads(doc_file.read_text(encoding="utf-8"))
    assert "1" in docs
