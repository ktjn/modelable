from __future__ import annotations

import argparse
import ast
import hashlib
import json
import shutil
import subprocess
import tempfile
import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

CLI_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = CLI_ROOT.parent
SOURCE_ROOT = CLI_ROOT / "src"
BROWSER_ROOT = CLI_ROOT / "browser"
BROWSER_OVERRIDES_ROOT = BROWSER_ROOT / "overrides"

INCLUDE_TREES = (
    "browser",
    "compat",
    "compiler",
    "diagnostics",
    "expressions",
    "governance",
    "grammar",
    "parser",
    "planner",
    "validation",
)
INCLUDE_FILES = (
    "__init__.py",
    "_pydantic_py314_compat.py",
    "emitters/__init__.py",
    "emitters/base.py",
    "emitters/diagnostics.py",
    "emitters/json_schema.py",
    "registry/__init__.py",
    "registry/resolver.py",
    "registry/signature.py",
)
FORBIDDEN_IMPORTS = {
    "click",
    "rich",
    "pygls",
    "lsprotocol",
    "psycopg",
    "psycopg_binary",
    "socket",
    "subprocess",
}


def selected_source_paths() -> tuple[Path, ...]:
    package_root = SOURCE_ROOT / "modelable"
    selected = [
        path.relative_to(SOURCE_ROOT)
        for tree in INCLUDE_TREES
        for path in (package_root / tree).rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}
    ]
    selected.extend(Path("modelable") / relative for relative in INCLUDE_FILES)
    return tuple(sorted(selected, key=lambda path: path.as_posix()))


def scan_forbidden_imports(paths: Iterable[Path]) -> list[tuple[Path, int, str]]:
    findings: list[tuple[Path, int, str]] = []
    for path in paths:
        if path.suffix != ".py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = (alias.name.partition(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots = (node.module.partition(".")[0],)
            else:
                continue
            findings.extend((path, node.lineno, root) for root in roots if root in FORBIDDEN_IMPORTS)
    return sorted(findings, key=lambda finding: (finding[0].as_posix(), finding[1], finding[2]))


def _project_version(pyproject_path: Path) -> str:
    with pyproject_path.open("rb") as pyproject:
        return str(tomllib.load(pyproject)["project"]["version"])


def _load_browser_lock() -> dict[str, Any]:
    return json.loads((BROWSER_ROOT / "browser-lock.json").read_text(encoding="utf-8"))


def build_browser_wheel(output_dir: Path) -> Path:
    browser_version = _project_version(BROWSER_ROOT / "pyproject.toml")
    root_version = _project_version(CLI_ROOT / "pyproject.toml")
    if browser_version != root_version:
        raise ValueError(f"Browser package version {browser_version} does not match Modelable version {root_version}")

    selected = selected_source_paths()
    source_paths = [SOURCE_ROOT / path for path in selected]
    findings = scan_forbidden_imports(source_paths)
    if findings:
        for path, line, module in findings:
            print(f"{path}:{line}: forbidden browser import: {module}")
        raise RuntimeError("Browser source contains forbidden imports")

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary_directory:
        staging_root = Path(temporary_directory)
        shutil.copy2(BROWSER_ROOT / "pyproject.toml", staging_root / "pyproject.toml")
        shutil.copy2(
            BROWSER_ROOT / "build-constraints.txt",
            staging_root / "build-constraints.txt",
        )
        for relative_path, source_path in zip(selected, source_paths, strict=True):
            destination = staging_root / "src" / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)
        shutil.copytree(
            BROWSER_OVERRIDES_ROOT,
            staging_root / "src",
            dirs_exist_ok=True,
        )

        subprocess.run(
            [
                "uv",
                "build",
                "--wheel",
                "--build-constraints",
                str(staging_root / "build-constraints.txt"),
                "--out-dir",
                str(output_dir),
            ],
            cwd=staging_root,
            check=True,
        )

    wheel_path = output_dir / f"modelable_browser-{browser_version}-py3-none-any.whl"
    if not wheel_path.is_file():
        raise FileNotFoundError(f"Expected browser wheel was not built: {wheel_path}")

    browser_lock = _load_browser_lock()
    manifest = {
        "schemaVersion": 1,
        "distribution": "modelable-browser",
        "version": browser_version,
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            text=True,
        ).strip(),
        "wheel": wheel_path.name,
        "sha256": hashlib.sha256(wheel_path.read_bytes()).hexdigest(),
        "pyodide": browser_lock["pyodide"],
        "python": browser_lock["python"],
        "platform": browser_lock["platform"],
    }
    (output_dir / "browser-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return wheel_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the browser-only Modelable wheel")
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    build_browser_wheel(arguments.output)


if __name__ == "__main__":
    main()
