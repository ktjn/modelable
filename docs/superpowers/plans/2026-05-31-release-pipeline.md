# Release Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible release pipeline that produces `cli/` wheel and sdist artifacts, checksums, and a machine-readable manifest, then uploads them as GitHub release assets with optional package-index publication.

**Architecture:** Keep the release logic in one small Python helper under `cli/src/modelable/` so both the GitHub Actions workflow and local verification call the same code. Use a single release workflow for build, test, package, and upload; keep publish-to-index optional and configuration-driven so the first slice does not hardcode a package registry decision.

**Tech Stack:** Python 3.14, `uv`, Hatchling, `pytest`, GitHub Actions, `hashlib`, `json`, `pathlib`, `tomllib`

---

### Task 1: Add release metadata helper and package build support

**Files:**
- Modify: `cli/pyproject.toml`
- Modify: `cli/uv.lock`
- Create: `cli/src/modelable/release.py`
- Create: `cli/tests/test_release_metadata.py`

- [ ] **Step 1: Write the failing tests**

```python
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


def test_load_package_version_reads_pyproject() -> None:
    assert load_package_version(Path("pyproject.toml")) == "0.1.0"


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
```

- [ ] **Step 2: Run the new tests and confirm they fail for the right reason**

Run:

```bash
cd cli
uv sync --extra dev
uv run pytest tests/test_release_metadata.py -v
```

Expected:

- Fails because `modelable.release` does not exist yet and the manifest/checksum helpers are missing.

- [ ] **Step 3: Implement the helper and build dependency**

Create `cli/src/modelable/release.py` with:

```python
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import tomllib


def load_package_version(pyproject_path: Path) -> str:
    with pyproject_path.open("rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def build_release_manifest(
    *,
    dist_dir: Path,
    commit_sha: str,
    git_tag: str | None,
    package_version: str,
    python_version: str,
    build_timestamp: str,
) -> dict[str, Any]:
    if git_tag is not None and git_tag.lstrip("v") != package_version:
        raise ValueError(f"package version {package_version} does not match release tag {git_tag}")

    artifacts = {}
    checksums_lines: list[str] = []
    for artifact in sorted(dist_dir.glob("*")):
        if not artifact.is_file() or artifact.name in {"SHA256SUMS", "release-manifest.json"}:
            continue
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        artifacts[artifact.suffix] = {"filename": artifact.name, "sha256": digest}
        checksums_lines.append(f"{digest}  {artifact.name}")

    manifest = {
        "package_name": "modelable",
        "package_version": package_version,
        "git_sha": commit_sha,
        "git_tag": git_tag,
        "python_version": python_version,
        "build_timestamp": build_timestamp,
        "artifacts": {
            "wheel": artifacts[".whl"],
            "sdist": artifacts[".gz"],
        },
    }

    (dist_dir / "SHA256SUMS").write_text("\n".join(checksums_lines) + "\n", encoding="utf-8")
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
    args = parser.parse_args(argv)

    build_release_manifest(
        dist_dir=args.dist,
        commit_sha=args.commit_sha,
        git_tag=args.git_tag,
        package_version=args.package_version,
        python_version=args.python_version,
        build_timestamp=args.build_timestamp,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Update `cli/pyproject.toml` so the release helper can run the package build command locally and in CI:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-cov>=4.0",
    "build>=1.2",
]
```

- [ ] **Step 4: Re-run the focused tests**

Run:

```bash
cd cli
uv sync --extra dev
uv run pytest tests/test_release_metadata.py -v
```

Expected:

- `test_release_metadata.py` passes.
- `cli/uv.lock` updates to include the new build dependency.

- [ ] **Step 5: Verify the release slice against the full CLI gate**

Run:

```bash
cd cli
uv run pytest tests/ -v
uv run modelable validate ../samples/mvp --strict
git diff --check
```

Expected:

- CLI suite passes.
- MVP validation passes.
- No diff hygiene issues remain.

- [ ] **Step 6: Commit the helper slice**

```bash
git add cli/pyproject.toml cli/uv.lock cli/src/modelable/release.py cli/tests/test_release_metadata.py
git commit -m "feat: add release metadata helper"
```

### Task 2: Add the GitHub release workflow and workflow smoke test

**Files:**
- Create: `.github/workflows/release.yml`
- Create: `cli/tests/test_release_workflow.py`

- [ ] **Step 1: Write the failing workflow text test**

```python
from pathlib import Path


def test_release_workflow_contains_release_gates() -> None:
    text = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch" in text
    assert "push:" in text and "tags:" in text
    assert "uv run pytest tests/ -v" in text
    assert "uv run modelable validate ../samples/mvp --strict" in text
    assert "python -m modelable.release" in text
    assert "SHA256SUMS" in text
    assert "release-manifest.json" in text
    assert "softprops/action-gh-release" in text
```

- [ ] **Step 2: Run the new test and confirm it fails for the right reason**

Run:

```bash
cd cli
uv run pytest tests/test_release_workflow.py -v
```

Expected:

- Fails because `.github/workflows/release.yml` does not exist yet.

- [ ] **Step 3: Implement the workflow**

Create `.github/workflows/release.yml` with:

```yaml
name: release

on:
  workflow_dispatch:
    inputs:
      publish:
        description: Publish to the configured package index
        required: false
        type: boolean
        default: false
  push:
    tags:
      - "v*"

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.14"
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --extra dev --frozen
        working-directory: cli
      - run: uv run pytest tests/ -v
        working-directory: cli
      - run: uv run modelable validate ../samples/mvp --strict
        working-directory: cli
      - run: uv run python -m build
        working-directory: cli
      - run: uv run python -m modelable.release --dist dist --commit-sha "${GITHUB_SHA}" --git-tag "${GITHUB_REF_NAME}" --package-version "0.1.0" --python-version "3.14" --build-timestamp "${BUILD_TIMESTAMP}"
        working-directory: cli
      - uses: softprops/action-gh-release@v2
        with:
          files: |
            cli/dist/*.whl
            cli/dist/*.tar.gz
            cli/dist/SHA256SUMS
            cli/dist/release-manifest.json
      - if: inputs.publish == true
        run: echo "publish step enabled by workflow input and configured secrets"
```

Keep the publish step optional and guarded so the workflow does not hardcode a package-index decision in this first slice.

- [ ] **Step 4: Re-run the workflow smoke test and confirm the workflow text is coherent**

Run:

```bash
cd cli
uv run pytest tests/test_release_workflow.py -v
git diff --check
```

Expected:

- Workflow text test passes.
- No whitespace or line-ending issues are introduced.

- [ ] **Step 5: Commit the workflow slice**

```bash
git add .github/workflows/release.yml cli/tests/test_release_workflow.py
git commit -m "ci: add release workflow"
```

### Task 3: Update the release-facing docs and governance text

**Files:**
- Modify: `README.md`
- Modify: `docs/README.md`
- Modify: `docs/agent-governance.md`

- [ ] **Step 1: Update the docs with the release path**

Make the docs say, in plain language:

- the release pipeline builds the `cli/` wheel and sdist,
- the workflow attaches `SHA256SUMS` and `release-manifest.json`,
- the release build is driven from clean repository state,
- local verification for release changes still uses the CLI gate plus the release metadata tests,
- package publication remains optional and configured in the workflow, not hardcoded in docs.

Suggested Markdown content to add:

```md
### Release pipeline

Modelable's release workflow builds the `cli/` wheel and sdist from a clean checkout, verifies the local CLI gates, and uploads release artifacts with checksums and a machine-readable manifest. The workflow keeps package-index publication optional and configuration-driven so GitHub release assets remain the default distribution artifact.
```

- [ ] **Step 2: Review the Markdown diff for coherence**

Run:

```bash
git diff -- README.md docs/README.md docs/agent-governance.md
```

Check:

- no stale references to the old release model,
- terminology matches the existing CLI and governance language,
- the release workflow is described as a repo artifact, not as a runtime feature.

- [ ] **Step 3: Commit the docs slice**

```bash
git add README.md docs/README.md docs/agent-governance.md
git commit -m "docs: describe release pipeline"
```

### Task 4: Run an end-to-end release dry run

**Files:**
- No new files expected; this is the integration checkpoint after the helper, workflow, and docs slices.

- [ ] **Step 1: Produce local release artifacts from a temp directory**

Run:

```bash
cd cli
uv run python -m modelable.release --dist ../tmp-release-dist --commit-sha abc1234 --git-tag v0.1.0 --package-version 0.1.0 --python-version 3.14.0 --build-timestamp 2026-05-31T12:00:00Z
```

Expected:

- `tmp-release-dist/SHA256SUMS` exists.
- `tmp-release-dist/release-manifest.json` exists.
- the manifest points at the exact wheel and sdist filenames in the directory.

- [ ] **Step 2: Run the release-specific tests together**

Run:

```bash
cd cli
uv run pytest tests/test_release_metadata.py tests/test_release_workflow.py -v
uv run pytest tests/ -v
uv run modelable validate ../samples/mvp --strict
```

Expected:

- Release helper tests pass.
- Workflow smoke test passes.
- Full CLI suite passes.
- MVP validation passes.

- [ ] **Step 3: Final hygiene check and push**

Run:

```bash
git status --short
git diff --check
```

Expected:

- only the intended release files are modified,
- no transient release artifacts are left behind.

Then commit and push the release slice set.
