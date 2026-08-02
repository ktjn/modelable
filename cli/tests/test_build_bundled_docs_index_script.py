import subprocess
import sys
from pathlib import Path


def test_dev_script_generates_manifest(tmp_path: Path) -> None:
    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    (docs_root / "guide.md").write_text("# Guide\n\nInstall with uv.\n", encoding="utf-8")
    output_dir = tmp_path / "data" / "docs-index"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_bundled_docs_index.py",
            "--docs-root",
            str(docs_root),
            "--out",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert (output_dir / "manifest.json").is_file()
