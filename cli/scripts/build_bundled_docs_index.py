from __future__ import annotations

import argparse
from pathlib import Path

from modelable.rag.bundled_index_builder import build_bundled_index

CLI_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CLI_ROOT.parent
DOCS_ROOT = REPO_ROOT / "docs"
OUTPUT_DIR = CLI_ROOT / "src" / "modelable" / "data" / "docs-index"


def _docs_root() -> Path:
    return DOCS_ROOT


def _output_dir() -> Path:
    return OUTPUT_DIR


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the bundled documentation index for development")
    parser.add_argument("--docs-root", type=Path, default=_docs_root())
    parser.add_argument("--out", type=Path, default=_output_dir())
    args = parser.parse_args()

    if not args.docs_root.is_dir():
        raise SystemExit(f"Documentation root does not exist: {args.docs_root}")

    build_bundled_index(args.docs_root, args.out)
    print(f"Bundled documentation index written to {args.out / 'manifest.json'}")


if __name__ == "__main__":
    main()
