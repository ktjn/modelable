"""Local release-packaging preflight.

Runs the same packaging steps that ``release.yml`` uses to create release
artifacts, without publishing, tagging, or touching a registry. ``release.yml``
invokes this script so the local gate and release CI cannot drift apart.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PREFLIGHT_SCRIPT_PATH = ".github/scripts/run_release_preflight.py"
COMMAND_TIMEOUT_SECONDS = 20 * 60
DIST_METADATA_FILES = ("SHA256SUMS", "release-manifest.json")

CommandRunner = Callable[..., object]


class PreflightError(RuntimeError):
    """Raised when release packaging diverges from what release CI produces."""


def read_package_version(pyproject_path: Path) -> str:
    with pyproject_path.open("rb") as pyproject_file:
        data = tomllib.load(pyproject_file)
    return str(data["project"]["version"])


def read_extension_version(package_json_path: Path) -> str:
    data = json.loads(package_json_path.read_text(encoding="utf-8"))
    return str(data["version"])


def verify_version_parity(*, package_version: str, extension_version: str) -> None:
    if package_version != extension_version:
        raise PreflightError(
            f"CLI package version {package_version} does not match extension version {extension_version}"
        )


def prepare_dist_directory(dist_dir: Path) -> None:
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    dist_dir.mkdir(parents=True)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_checksums(checksums_path: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line in checksums_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, filename = line.partition("  ")
        checksums[filename] = digest
    return checksums


def _artifact_entries(manifest: dict[str, Any]) -> dict[str, dict[str, str]]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise PreflightError("release manifest has no artifact inventory")
    return {key: value for key, value in artifacts.items() if isinstance(value, dict)}


def verify_release_inventory(*, dist_dir: Path, package_version: str, extension_version: str) -> None:
    manifest_path = dist_dir / "release-manifest.json"
    checksums_path = dist_dir / "SHA256SUMS"
    if not manifest_path.is_file():
        raise PreflightError(f"release manifest is missing from {dist_dir}")
    if not checksums_path.is_file():
        raise PreflightError(f"release checksum file is missing from {dist_dir}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("package_version") != package_version:
        raise PreflightError(
            f"manifest package version {manifest.get('package_version')!r} "
            f"does not match pyproject package version {package_version!r}"
        )
    if manifest.get("extension_version") != extension_version:
        raise PreflightError(
            f"manifest extension version {manifest.get('extension_version')!r} "
            f"does not match vscode extension version {extension_version!r}"
        )

    artifacts = _artifact_entries(manifest)
    expected_names = set()
    for kind, label in (("wheel", "wheel"), ("sdist", "sdist"), ("vsix", "VS Code extension")):
        entry = artifacts.get(kind)
        if entry is None or "filename" not in entry:
            raise PreflightError(f"release manifest has no {label} artifact")
        filename = str(entry["filename"])
        expected_names.add(filename)
        if not (dist_dir / filename).is_file():
            raise PreflightError(f"release inventory is missing the {label} artifact {filename}")

    expected_names.update(DIST_METADATA_FILES)
    actual_names = {path.name for path in dist_dir.iterdir() if path.is_file()}
    unexpected = sorted(actual_names - expected_names)
    if unexpected:
        raise PreflightError(f"release inventory contains unexpected artifacts: {unexpected}")
    missing = sorted(expected_names - actual_names)
    if missing:
        raise PreflightError(f"release inventory is missing artifacts: {missing}")

    checksums = _parse_checksums(checksums_path)
    for filename in sorted(expected_names - set(DIST_METADATA_FILES)):
        if filename not in checksums:
            raise PreflightError(f"release checksum file has no entry for {filename}")
        if checksums[filename] != _sha256(dist_dir / filename):
            raise PreflightError(f"release checksum mismatch for {filename}")


def _run(runner: CommandRunner, argv: Sequence[str], *, cwd: Path) -> None:
    runner(list(argv), cwd=cwd, check=True, timeout=COMMAND_TIMEOUT_SECONDS)


def _single_artifact(dist_dir: Path, pattern: str) -> Path:
    matches = sorted(dist_dir.glob(pattern))
    if len(matches) != 1:
        raise PreflightError(f"expected exactly one {pattern} artifact in {dist_dir}, found {len(matches)}")
    return matches[0]


def venv_bin(venv_dir: Path, executable: str) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / f"{executable}.exe"
    return venv_dir / "bin" / executable


def run_preflight(
    *,
    repo_root: Path,
    commit_sha: str,
    git_tag: str | None,
    package_version: str | None,
    extension_version: str | None,
    python_version: str,
    build_timestamp: str,
    repository_url: str,
    license_expression: str,
    workflow_run_url: str | None,
    runner: CommandRunner = subprocess.run,
) -> None:
    cli_root = repo_root / "cli"
    dist_dir = cli_root / "dist"
    resolved_package_version = package_version or read_package_version(cli_root / "pyproject.toml")
    resolved_extension_version = extension_version or read_extension_version(repo_root / "vscode" / "package.json")
    verify_version_parity(
        package_version=resolved_package_version,
        extension_version=resolved_extension_version,
    )

    source_vsix = repo_root / "vscode" / f"modelable-vscode-{resolved_extension_version}.vsix"
    if not source_vsix.is_file():
        raise PreflightError(f"VS Code extension artifact {source_vsix} is missing; run `npm run package` first")

    prepare_dist_directory(dist_dir)
    _run(runner, ("uv", "run", "python", "-m", "build"), cwd=cli_root)
    wheel = _single_artifact(dist_dir, "*.whl")
    sdist = _single_artifact(dist_dir, "*.tar.gz")
    _run(runner, ("uv", "run", "--with", "twine", "twine", "check", str(wheel), str(sdist)), cwd=cli_root)

    staged_vsix = dist_dir / source_vsix.name
    shutil.copy2(source_vsix, staged_vsix)

    with tempfile.TemporaryDirectory(prefix="modelable-release-preflight-") as temporary_root:
        venv_dir = Path(temporary_root) / "venv"
        _run(runner, ("uv", "venv", str(venv_dir), "--python", python_version), cwd=cli_root)
        venv_python = venv_bin(venv_dir, "python")
        modelable = venv_bin(venv_dir, "modelable")
        _run(runner, ("uv", "pip", "install", "--python", str(venv_python), str(wheel)), cwd=cli_root)
        _run(runner, (str(modelable), "--version"), cwd=cli_root)
        _run(runner, (str(modelable), "validate", "samples/mvp", "--strict"), cwd=repo_root)

    manifest_argv = [
        "uv",
        "run",
        "python",
        "-m",
        "modelable.release",
        "--dist",
        str(dist_dir),
        "--commit-sha",
        commit_sha,
        "--package-version",
        resolved_package_version,
        "--python-version",
        python_version,
        "--build-timestamp",
        build_timestamp,
        "--repository-url",
        repository_url,
        "--license-expression",
        license_expression,
        "--extension-version",
        resolved_extension_version,
    ]
    if git_tag is not None:
        manifest_argv.extend(["--git-tag", git_tag])
    if workflow_run_url is not None:
        manifest_argv.extend(["--workflow-run-url", workflow_run_url])
    _run(runner, manifest_argv, cwd=cli_root)

    verify_release_inventory(
        dist_dir=dist_dir,
        package_version=resolved_package_version,
        extension_version=resolved_extension_version,
    )


def resolve_commit_sha(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _default_build_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Package and verify release artifacts without publishing.")
    parser.add_argument("--commit-sha", help="commit recorded in the release manifest (default: HEAD)")
    parser.add_argument("--git-tag", help="release tag; only set when producing a tagged release")
    parser.add_argument("--package-version", help="CLI package version (default: cli/pyproject.toml)")
    parser.add_argument("--extension-version", help="VS Code extension version (default: vscode/package.json)")
    parser.add_argument("--python-version", default="3.14")
    parser.add_argument("--build-timestamp", default=_default_build_timestamp())
    parser.add_argument("--repository-url", default="https://github.com/ktjn/modelable")
    parser.add_argument("--license-expression", default="Apache-2.0")
    parser.add_argument("--workflow-run-url")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    repo_root = Path(__file__).resolve().parents[2]
    assert repo_root.is_dir(), f"repository root {repo_root} is missing"
    run_preflight(
        repo_root=repo_root,
        commit_sha=args.commit_sha or resolve_commit_sha(repo_root),
        git_tag=args.git_tag,
        package_version=args.package_version,
        extension_version=args.extension_version,
        python_version=args.python_version,
        build_timestamp=args.build_timestamp,
        repository_url=args.repository_url,
        license_expression=args.license_expression,
        workflow_run_url=args.workflow_run_url,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
