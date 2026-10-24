from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PINNED_ACTION_REF = re.compile(r"^(?:v\d+(?:\.\d+){0,2}|release/v\d+)$")


def _workflow(workflow_name: str) -> Any:
    workflow = REPOSITORY_ROOT / ".github" / "workflows" / workflow_name
    return yaml.safe_load(workflow.read_text(encoding="utf-8"))


def _workflow_actions(workflow_name: str) -> set[str]:
    workflow = REPOSITORY_ROOT / ".github" / "workflows" / workflow_name
    return {
        line.split("uses:", 1)[1].strip()
        for line in workflow.read_text(encoding="utf-8").splitlines()
        if "uses:" in line
    }


def _workflow_action_names(workflow_name: str) -> set[str]:
    return {action.rsplit("@", 1)[0] for action in _workflow_actions(workflow_name)}


def test_conversational_compilation_documentation_and_roadmap_contract() -> None:
    cli_reference = (REPOSITORY_ROOT / "docs" / "cli-reference.md").read_text(encoding="utf-8")
    roadmap = (REPOSITORY_ROOT / "ROADMAP.md").read_text(encoding="utf-8")

    assert "literal /apply" in cli_reference
    assert ".modelable/audit/compilations/" in cli_reference
    assert "Conversational Compilation Management" in roadmap
    assert "specs/archived/2026-07-19-conversational-compilation-management-design.md" in roadmap


def _assert_workflow_actions_are_pinned(workflow_name: str) -> None:
    for action in _workflow_actions(workflow_name):
        action_name, separator, ref = action.rpartition("@")
        assert separator == "@", f"{workflow_name} action is not pinned: {action}"
        assert action_name, f"{workflow_name} action is missing an action name: {action}"
        assert PINNED_ACTION_REF.fullmatch(ref), f"{workflow_name} action is not pinned to a version tag: {action}"


def test_release_workflow_contains_release_gates() -> None:
    workflow = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"
    text = workflow.read_text(encoding="utf-8")
    assert "workflow_dispatch" in text
    assert "push:" in text and "tags:" in text
    assert "uv run pytest tests/ --tb=short" in text
    assert "uv run modelable validate ../samples/mvp --strict" in text
    assert "python .github/scripts/run_release_preflight.py" in text
    assert "SHA256SUMS" in text
    assert "release-manifest.json" in text
    assert "softprops/action-gh-release" in text
    assert "pypa/gh-action-pypi-publish@release/v1" in text
    assert "environment: pypi" in text
    assert "id-token: write" in text
    assert "npm run package" in text
    assert "https://ktjn.github.io/modelable/" in text


def test_release_workflow_uses_current_actions() -> None:
    assert _workflow_action_names("release.yml") == {
        "actions/checkout",
        "actions/setup-node",
        "actions/upload-artifact",
        "actions/download-artifact",
        "astral-sh/setup-uv",
        "pypa/gh-action-pypi-publish",
        "softprops/action-gh-release",
    }
    _assert_workflow_actions_are_pinned("release.yml")


def test_docs_workflow_uses_current_actions() -> None:
    assert _workflow_action_names("docs.yml") == {
        "actions/checkout",
        "actions/deploy-pages",
        "actions/setup-node",
        "actions/upload-pages-artifact",
        "astral-sh/setup-uv",
    }
    _assert_workflow_actions_are_pinned("docs.yml")


def test_docs_workflow_builds_strict_mkdocs_site() -> None:
    workflow = _workflow("docs.yml")
    steps = workflow["jobs"]["build"]["steps"]
    commands = "\n".join(step["run"] for step in steps if "run" in step)

    assert any(
        step.get("uses") == "actions/setup-node@v7.1.0" and step.get("with", {}).get("node-version") == 26
        for step in steps
    )
    assert "uv python install 3.14" in commands
    assert "npm ci" in commands
    assert "npm run build" in commands
    assert "mkdocs==1.6.1" in commands
    assert "mkdocs-material==9.7.6" in commands
    assert "mkdocs build --strict" in commands
    assert "uv run --project cli python .github/scripts/assemble_pages.py --site site --web-dist web/dist" in commands
    assert (
        sum(
            str(step.get("uses", "")).startswith("actions/upload-pages-artifact@")
            for job in workflow["jobs"].values()
            for step in job["steps"]
        )
        == 1
    )
    assert (
        sum(
            str(step.get("uses", "")).startswith("actions/deploy-pages@")
            for job in workflow["jobs"].values()
            for step in job["steps"]
        )
        == 1
    )
    assert workflow["jobs"]["deploy"]["environment"]["url"] == "${{ steps.deployment.outputs.page_url }}"


def test_docs_workflow_manual_dispatch_builds_without_deploying() -> None:
    workflow = _workflow("docs.yml")

    assert "workflow_dispatch" in workflow[True]
    assert workflow["jobs"]["deploy"]["if"] == ("github.event_name == 'push' && github.ref == 'refs/heads/main'")


def test_docs_workflow_main_push_can_deploy() -> None:
    workflow = _workflow("docs.yml")

    assert workflow[True]["push"]["branches"] == ["main"]
    assert workflow["jobs"]["deploy"]["if"] == ("github.event_name == 'push' && github.ref == 'refs/heads/main'")


def test_validation_workflow_uses_current_actions() -> None:
    assert _workflow_action_names("validate.yml") == {
        "actions/checkout",
        "actions/setup-node",
        "actions/upload-artifact",
        "astral-sh/setup-uv",
    }
    _assert_workflow_actions_are_pinned("validate.yml")


def test_validation_workflow_is_build_only() -> None:
    workflow = _workflow("validate.yml")
    assert set(workflow["jobs"]) == {"build"}

    build_script = "\n".join(str(step.get("run", "")) for step in workflow["jobs"]["build"]["steps"])
    assert "npm run build" in build_script
    assert "npm run check:budgets" in build_script
    for forbidden in ("ruff", "mypy", "pytest", "npm test", "test:e2e", "docker pull"):
        assert forbidden not in build_script


def test_build_pins_selectolax_before_deprecated_parser_backend() -> None:
    pyproject = tomllib.loads((REPOSITORY_ROOT / "cli" / "pyproject.toml").read_text(encoding="utf-8"))
    expected = "selectolax>=0.3.21,<0.4"

    assert expected in pyproject["build-system"]["requires"]
    assert expected in pyproject["project"]["dependencies"]


def test_versioned_pre_push_hook_runs_local_gate() -> None:
    hook = REPOSITORY_ROOT / ".githooks" / "pre-push"
    assert hook.exists()
    content = hook.read_text(encoding="utf-8")
    assert "git diff --quiet" in content
    assert "git diff --cached --quiet" in content
    assert "git status --porcelain --untracked-files=all" in content
    assert "refs/heads/" in content
    assert "git rev-parse HEAD" in content
    assert "run_browser_playground.py" in content


def test_release_prep_workflow_uses_current_actions() -> None:
    assert _workflow_action_names("release-prep.yml") == {
        "actions/checkout",
        "astral-sh/setup-uv",
    }
    _assert_workflow_actions_are_pinned("release-prep.yml")


def test_release_prep_is_manual_dispatch_with_version_input() -> None:
    workflow = _workflow("release-prep.yml")
    assert workflow[True]["workflow_dispatch"]["inputs"]["version"]["required"] is True
    assert workflow["permissions"]["contents"] == "write"
    assert workflow["permissions"]["pull-requests"] == "write"

    steps = workflow["jobs"]["prepare"]["steps"]
    assert any(
        step.get("uses") == "astral-sh/setup-uv@v10.3.0"
        and step.get("with", {}).get("cache-dependency-glob") == "cli/uv.lock"
        for step in steps
    )
    assert any(
        step.get("uses") == "actions/checkout@v7.0.1" and step.get("with", {}).get("ref") == "main" for step in steps
    )


def test_release_prep_drives_scripts_and_release_notes() -> None:
    workflow = _workflow("release-prep.yml")
    steps = workflow["jobs"]["prepare"]["steps"]
    commands = "\n".join(step["run"] for step in steps if "run" in step)

    assert ".github/scripts/prepare_release.py" in commands
    assert "--pyproject cli/pyproject.toml" in commands
    assert "--browser-pyproject cli/browser/pyproject.toml" in commands
    assert "--package-json vscode/package.json" in commands
    assert "--package-lock vscode/package-lock.json" in commands
    assert "--changelog CHANGELOG.md" in commands
    assert "uv lock" in commands
    assert "git add CHANGELOG.md cli/pyproject.toml cli/browser/pyproject.toml cli/uv.lock" in commands
    assert "gh pr create" in commands
    assert '--title "Release' in commands
    assert "git push -u origin" in commands

    assert any(
        step.get("if") == "github.event.inputs.auto_merge == 'true'" and "gh pr merge --auto" in (step.get("run") or "")
        for step in steps
    )


def test_release_tag_workflow_tags_merged_release_prs() -> None:
    workflow = _workflow("release-tag.yml")
    assert workflow[True]["pull_request"]["types"] == ["closed"]
    assert workflow["jobs"]["tag"]["if"] == "${{ github.event.pull_request.merged == true }}"
    assert workflow["permissions"]["contents"] == "write"

    steps = workflow["jobs"]["tag"]["steps"]
    commands = "\n".join(step["run"] for step in steps if "run" in step)
    assert "s/^Release " in commands
    assert 'git config user.name "github-actions[bot]"' in commands
    assert "git config user.email" in commands
    assert "git tag -a" in commands
    assert "RELEASE_TAG_TOKEN" in commands
    tag_step_index = next(index for index, step in enumerate(steps) if "run" in step and "git tag -a" in step["run"])
    assert 'git config user.name "github-actions[bot]"' in steps[tag_step_index]["run"]
    # The tag push must use a PAT, not the default GITHUB_TOKEN: pushes made
    # with the default token don't trigger other workflows (release.yml's
    # `push: tags: v*`), so a tag pushed with it would never get published.
    assert "git push origin" not in steps[tag_step_index]["run"]
    assert "x-access-token:${RELEASE_TAG_TOKEN}@github.com" in steps[tag_step_index]["run"]
    guard_step_index = next(
        index
        for index, step in enumerate(steps)
        if "run" in step and "RELEASE_TAG_TOKEN repository secret" in step["run"]
    )
    assert guard_step_index < tag_step_index
    _assert_workflow_actions_are_pinned("release-tag.yml")


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


def test_codeql_workflow_runs_on_schedule() -> None:
    workflow = _workflow("codeql.yml")

    assert "workflow_dispatch" in workflow[True]
    assert workflow[True]["schedule"] == [{"cron": "27 3 * * 1"}]
