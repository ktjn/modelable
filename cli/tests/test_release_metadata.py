from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from modelable.release import build_release_manifest, load_package_version


def test_build_release_manifest_writes_checksums_and_manifest(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel = dist / "modelable-0.1.0-py3-none-any.whl"
    sdist = dist / "modelable-0.1.0.tar.gz"
    wheel.write_bytes(b"wheel-bytes")
    sdist.write_bytes(b"sdist-bytes")

    manifest = build_release_manifest(
        dist_dir=dist,
        commit_sha="abc1234",
        git_tag="v0.1.0",
        package_version="0.1.0",
        python_version="3.14.0",
        build_timestamp="2026-05-31T12:00:00Z",
    )

    assert manifest["package_name"] == "modelable"
    assert manifest["package_version"] == "0.1.0"
    assert manifest["git_sha"] == "abc1234"
    assert manifest["git_tag"] == "v0.1.0"
    assert manifest["artifacts"]["wheel"]["filename"] == wheel.name
    assert manifest["artifacts"]["sdist"]["filename"] == sdist.name
    assert (dist / "SHA256SUMS").exists()
    assert (dist / "release-manifest.json").exists()


def test_load_package_version_reads_cli_pyproject() -> None:
    cli_pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    assert load_package_version(cli_pyproject) == "0.2.1"


def test_release_cli_writes_manifest_and_checksums(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "modelable-0.1.0-py3-none-any.whl").write_bytes(b"wheel-bytes")
    (dist / "modelable-0.1.0.tar.gz").write_bytes(b"sdist-bytes")

    subprocess.run(
        [
            sys.executable,
            "-m",
            "modelable.release",
            "--dist",
            str(dist),
            "--commit-sha",
            "abc1234",
            "--git-tag",
            "v0.1.0",
            "--package-version",
            "0.1.0",
            "--python-version",
            "3.14.0",
            "--build-timestamp",
            "2026-05-31T12:00:00Z",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    manifest = json.loads((dist / "release-manifest.json").read_text(encoding="utf-8"))
    assert manifest["git_sha"] == "abc1234"
    assert manifest["artifacts"]["wheel"]["filename"] == "modelable-0.1.0-py3-none-any.whl"


def test_release_version_mismatch_fails() -> None:
    with pytest.raises(ValueError, match="package version .* does not match release tag"):
        build_release_manifest(
            dist_dir=Path("dist"),
            commit_sha="abc1234",
            git_tag="v0.2.0",
            package_version="0.1.0",
            python_version="3.14.0",
            build_timestamp="2026-05-31T12:00:00Z",
        )
