from __future__ import annotations

import importlib.resources
from pathlib import Path


def bundled_documentation_index_path() -> Path:
    """Return the path to the documentation index shipped with the package."""
    manifest = importlib.resources.files("modelable.data") / "docs-index" / "manifest.json"
    if not manifest.is_file():
        raise RuntimeError(
            "Bundled documentation index is missing. "
            "Install a Modelable wheel or run scripts/build_bundled_docs_index.py."
        )
    return Path(str(manifest))
