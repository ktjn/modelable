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
            # When building from an sdist where docs were not included,
            # we may need to skip or use the already-bundled index if it exists.
            print(f"Warning: Documentation root not found at {docs_root}, checking for bundled index...")
            bundled_index = CLI_ROOT / "src" / "modelable" / "data" / "docs-index"
            if (bundled_index / "manifest.json").exists():
                print("Using existing bundled index.")
                return
            raise RuntimeError(f"Documentation root not found and no bundled index exists at {bundled_index}")

        output_dir = CLI_ROOT / "src" / "modelable" / "data" / "docs-index"
        build_bundled_index(docs_root, output_dir)
