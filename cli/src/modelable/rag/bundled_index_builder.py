from __future__ import annotations

from pathlib import Path

from modelable.rag.chunking import load_documentation_chunks
from modelable.rag.index import build_documentation_index


def build_bundled_index(
    docs_root: Path,
    output_dir: Path,
    *,
    base_url: str = "https://ktjn.github.io/modelable/",
) -> Path:
    """Generate a Searchable documentation index from docs_root into output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    chunks = load_documentation_chunks(docs_root, base_url=base_url)
    build_documentation_index(chunks, output_dir)
    return output_dir / "manifest.json"
