from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

CLI_ROOT = Path(__file__).resolve().parent
REPO_ROOT = CLI_ROOT.parent


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        sys.path.insert(0, str(CLI_ROOT / "src"))
        from modelable.rag.bundled_index_builder import build_bundled_index

        docs_root = REPO_ROOT / "docs"
        if not docs_root.is_dir():
            # When building from an sdist, docs are included at the repository root.
            docs_root = Path("docs").resolve()
        if not docs_root.is_dir():
            raise RuntimeError(f"Documentation root not found: {docs_root}")

        output_dir = CLI_ROOT / "src" / "modelable" / "data" / "docs-index"
        build_bundled_index(docs_root, output_dir)
