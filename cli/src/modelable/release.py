from __future__ import annotations

import argparse
import hashlib
import json
import tomllib
from pathlib import Path
from typing import Any, cast


def load_package_version(pyproject_path: Path) -> str:
    with pyproject_path.open("rb") as fh:
        data = tomllib.load(fh)
    return cast(str, data["project"]["version"])


def _artifact_kind(path: Path) -> str | None:
    if path.name.endswith(".whl"):
        return "wheel"
    if path.name.endswith(".tar.gz"):
        return "sdist"
    if path.name.endswith(".vsix"):
        return "vsix"
    return None


def build_release_manifest(
    *,
    dist_dir: Path,
    commit_sha: str,
    git_tag: str | None,
    package_version: str,
    python_version: str,
    build_timestamp: str,
    repository_url: str = "https://github.com/ktjn/modelable",
    license_expression: str = "Apache-2.0",
    workflow_run_url: str | None = None,
    extension_version: str | None = None,
) -> dict[str, Any]:
    tag_version = git_tag.removeprefix("v") if git_tag else None
    if tag_version is not None and tag_version != package_version:
        raise ValueError(f"package version {package_version} does not match release tag {git_tag}")

    wheel: dict[str, str] | None = None
    sdist: dict[str, str] | None = None
    vsix: dict[str, str] | None = None
    checksum_lines: list[str] = []

    for artifact in sorted(dist_dir.iterdir()):
        if not artifact.is_file() or artifact.name in {"SHA256SUMS", "release-manifest.json"}:
            continue
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        checksum_lines.append(f"{digest}  {artifact.name}")
        kind = _artifact_kind(artifact)
        if kind == "wheel":
            wheel = {"filename": artifact.name, "sha256": digest}
        elif kind == "sdist":
            sdist = {"filename": artifact.name, "sha256": digest}
        elif kind == "vsix":
            vsix = {"filename": artifact.name, "sha256": digest}

    if wheel is None:
        raise ValueError(f"no wheel artifact found in {dist_dir}")
    if sdist is None:
        raise ValueError(f"no sdist artifact found in {dist_dir}")
    if extension_version is not None and vsix is None:
        raise ValueError(f"no VS Code extension artifact found in {dist_dir}")

    manifest = {
        "package_name": "modelable",
        "package_version": package_version,
        "git_sha": commit_sha,
        "git_tag": git_tag,
        "python_version": python_version,
        "build_timestamp": build_timestamp,
        "repository_url": repository_url,
        "license": license_expression,
        "workflow_run_url": workflow_run_url,
        "extension_version": extension_version,
        "artifacts": {
            "wheel": wheel,
            "sdist": sdist,
            **({"vsix": vsix} if vsix is not None else {}),
        },
    }

    (dist_dir / "SHA256SUMS").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    (dist_dir / "release-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", required=True, type=Path)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--git-tag")
    parser.add_argument("--package-version", required=True)
    parser.add_argument("--python-version", required=True)
    parser.add_argument("--build-timestamp", required=True)
    parser.add_argument("--repository-url", default="https://github.com/ktjn/modelable")
    parser.add_argument("--license-expression", default="Apache-2.0")
    parser.add_argument("--workflow-run-url")
    parser.add_argument("--extension-version")
    args = parser.parse_args(argv)

    build_release_manifest(
        dist_dir=args.dist,
        commit_sha=args.commit_sha,
        git_tag=args.git_tag,
        package_version=args.package_version,
        python_version=args.python_version,
        build_timestamp=args.build_timestamp,
        repository_url=args.repository_url,
        license_expression=args.license_expression,
        workflow_run_url=args.workflow_run_url,
        extension_version=args.extension_version,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
