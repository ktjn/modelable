from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _workflow_actions(workflow_name: str) -> set[str]:
    workflow = REPOSITORY_ROOT / ".github" / "workflows" / workflow_name
    return {
        line.split("uses:", 1)[1].strip()
        for line in workflow.read_text(encoding="utf-8").splitlines()
        if "uses:" in line
    }


def test_release_workflow_contains_release_gates() -> None:
    workflow = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"
    text = workflow.read_text(encoding="utf-8")
    assert "workflow_dispatch" in text
    assert "push:" in text and "tags:" in text
    assert "uv run pytest tests/ --tb=short" in text
    assert "uv run modelable validate ../samples/mvp --strict" in text
    assert "python -m modelable.release" in text
    assert "SHA256SUMS" in text
    assert "release-manifest.json" in text
    assert "softprops/action-gh-release" in text
    assert "pypa/gh-action-pypi-publish@release/v1" in text
    assert "environment: pypi" in text
    assert "id-token: write" in text
    assert "npm run package" in text


def test_release_workflow_uses_current_actions() -> None:
    assert _workflow_actions("release.yml") == {
        "actions/checkout@v6.0.3",
        "actions/setup-node@v6.4.0",
        "actions/upload-artifact@v7.0.1",
        "actions/download-artifact@v8.0.1",
        "astral-sh/setup-uv@v8.2.0",
        "pypa/gh-action-pypi-publish@release/v1",
        "softprops/action-gh-release@v3.0.0",
    }


def test_validation_workflow_uses_current_actions() -> None:
    assert _workflow_actions("validate.yml") == {
        "actions/checkout@v6.0.3",
        "actions/setup-node@v6.4.0",
        "astral-sh/setup-uv@v8.2.0",
    }


def test_codeql_workflow_has_required_permissions() -> None:
    workflow = REPOSITORY_ROOT / ".github" / "workflows" / "codeql.yml"
    text = workflow.read_text(encoding="utf-8")
    for permission in (
        "actions: read",
        "contents: read",
        "packages: read",
        "security-events: write",
    ):
        assert permission in text

    assert "upload: never" in text
