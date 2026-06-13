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
    assert "uv run pytest tests/ -v" in text
    assert "uv run modelable validate ../samples/mvp --strict" in text
    assert "python -m modelable.release" in text
    assert "SHA256SUMS" in text
    assert "release-manifest.json" in text
    assert "softprops/action-gh-release" in text


def test_release_workflow_uses_current_actions() -> None:
    assert _workflow_actions("release.yml") == {
        "actions/checkout@v6.0.3",
        "actions/setup-python@v6.2.0",
        "astral-sh/setup-uv@v8.2.0",
        "softprops/action-gh-release@v3.0.0",
    }


def test_validation_workflow_uses_current_actions() -> None:
    assert _workflow_actions("validate.yml") == {
        "actions/checkout@v6.0.3",
        "actions/setup-node@v6.4.0",
        "astral-sh/setup-uv@v8.2.0",
    }
