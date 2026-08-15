from __future__ import annotations

import re
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
    assert "python -m modelable.release" in text
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
        step.get("uses") == "actions/setup-node@v7.0.0" and step.get("with", {}).get("node-version") == 26
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
        "actions/cache",
        "actions/checkout",
        "actions/download-artifact",
        "actions/setup-java",
        "actions/setup-node",
        "actions/upload-artifact",
        "astral-sh/setup-uv",
    }
    _assert_workflow_actions_are_pinned("validate.yml")


def test_validation_workflow_is_split_and_path_gated() -> None:
    workflow = _workflow("validate.yml")
    jobs = workflow["jobs"]
    expected_surfaces = {"cli", "vscode", "odcs", "openmetadata", "openlineage", "fhir", "browser"}

    assert set(jobs["changes"]["outputs"]) == expected_surfaces
    detection_steps = [
        step
        for step in jobs["changes"]["steps"]
        if "run" in step and ".github/scripts/detect_validate_surfaces.py" in step["run"]
    ]
    assert len(detection_steps) == 1

    for surface in expected_surfaces:
        if surface == "browser":
            assert jobs["browser-build"]["needs"] == "changes"
            assert jobs["browser-build"]["if"] == "needs.changes.outputs.browser == 'true'"
            assert jobs["browser-e2e"]["needs"] == "browser-build"
        else:
            assert jobs[surface]["needs"] == "changes"
            assert jobs[surface]["if"] == f"needs.changes.outputs.{surface} == 'true'"


def test_validation_workflow_handles_history_without_a_merge_base() -> None:
    workflow = _workflow("validate.yml")
    detection_step = next(
        step
        for step in workflow["jobs"]["changes"]["steps"]
        if "run" in step and ".github/scripts/detect_validate_surfaces.py" in step["run"]
    )
    script = detection_step["run"]

    assert "git merge-base FETCH_HEAD HEAD" in script
    assert 'git merge-base "${{ github.event.before }}" HEAD' in script
    assert "git ls-tree -r --name-only HEAD > changed-files.txt" in script


def test_validation_workflow_uses_distinct_uv_cache_suffixes() -> None:
    workflow = _workflow("validate.yml")
    jobs = workflow["jobs"]
    expected_suffixes = {
        "cli": "cli",
        "odcs": "odcs",
        "openmetadata": "openmetadata",
        "openlineage": "openlineage",
        "fhir": "fhir",
        "vscode": "vscode",
        "browser-build": "browser",
    }

    for job_name, expected_suffix in expected_suffixes.items():
        setup_uv_steps = [
            step for step in jobs[job_name]["steps"] if str(step.get("uses", "")).startswith("astral-sh/setup-uv@")
        ]
        assert len(setup_uv_steps) == 1
        assert setup_uv_steps[0]["with"]["cache-dependency-glob"] == "cli/uv.lock"
        assert setup_uv_steps[0]["with"]["cache-suffix"] == expected_suffix


def test_validation_workflow_runs_complete_browser_playground_gate() -> None:
    workflow = _workflow("validate.yml")

    build_steps = workflow["jobs"]["browser-build"]["steps"]
    build_commands = "\n".join(step["run"] for step in build_steps if "run" in step)
    assert any(
        step.get("uses") == "actions/setup-node@v7.0.0" and step.get("with", {}).get("node-version") == 26
        for step in build_steps
    )
    assert "uv python install 3.14" in build_commands
    assert "uv sync --extra dev --frozen" in build_commands
    assert "npm ci" in build_commands
    assert "npm run build" in build_commands
    assert any(
        step.get("uses") == "actions/upload-artifact@v7.0.1" and step.get("with", {}).get("name") == "browser-dist"
        for step in build_steps
    )

    e2e_steps = workflow["jobs"]["browser-e2e"]["steps"]
    e2e_commands = "\n".join(step["run"] for step in e2e_steps if "run" in step)
    assert "npx playwright install --with-deps" in e2e_commands
    assert "npx playwright test --project" in e2e_commands
    # Firefox is temporarily out of the matrix (see the comment in validate.yml);
    # restore ["chromium", "firefox"] here when it is re-enabled.
    assert workflow["jobs"]["browser-e2e"]["strategy"]["matrix"]["browser"] == ["chromium"]
    assert any(
        step.get("uses") == "actions/download-artifact@v8.0.1" and step.get("with", {}).get("name") == "browser-dist"
        for step in e2e_steps
    )
    assert any(
        step.get("uses") == "actions/upload-artifact@v7.0.1"
        and step.get("if") == "${{ failure() }}"
        and step.get("with", {}).get("path") == "web/output/playwright"
        for step in e2e_steps
    )


def test_validation_workflow_runs_dependency_audits() -> None:
    workflow = _workflow("validate.yml")
    cli_commands = "\n".join(step["run"] for step in workflow["jobs"]["cli"]["steps"] if "run" in step)
    vscode_commands = "\n".join(step["run"] for step in workflow["jobs"]["vscode"]["steps"] if "run" in step)

    assert "uv export --no-emit-project --format requirements-txt -o audit-requirements.txt" in cli_commands
    assert "uv run --with pip-audit pip-audit --strict --progress-spinner off -r audit-requirements.txt" in cli_commands
    assert "npm audit --omit=dev" in vscode_commands


def test_validation_workflow_runs_mypy_baseline_ratchet() -> None:
    workflow = _workflow("validate.yml")
    cli_commands = "\n".join(step["run"] for step in workflow["jobs"]["cli"]["steps"] if "run" in step)

    assert "check_mypy_baseline.py --baseline mypy-baseline.txt" in cli_commands
    assert "uv run mypy src/modelable --no-error-summary --show-error-codes" in cli_commands


def test_validation_workflow_runs_coverage_ratchet() -> None:
    workflow = _workflow("validate.yml")
    cli_steps = workflow["jobs"]["cli"]["steps"]
    cli_commands = "\n".join(step["run"] for step in cli_steps if "run" in step)

    assert "check_coverage_ratchet.py" in cli_commands
    assert "--coverage-xml coverage.xml" in cli_commands
    assert "--baseline coverage-baseline.txt" in cli_commands

    test_step_index = next(
        index
        for index, step in enumerate(cli_steps)
        if "run" in step and "pytest --tb=short --cov=modelable" in step["run"]
    )
    ratchet_step_index = next(
        index for index, step in enumerate(cli_steps) if "run" in step and "check_coverage_ratchet.py" in step["run"]
    )
    assert ratchet_step_index > test_step_index


def test_validation_workflow_publishes_cli_coverage_report() -> None:
    workflow = _workflow("validate.yml")
    cli_steps = workflow["jobs"]["cli"]["steps"]
    cli_commands = "\n".join(step["run"] for step in cli_steps if "run" in step)

    assert "uv run pytest --tb=short --cov=modelable --cov-report=term-missing --cov-report=xml" in cli_commands
    assert any(
        step.get("uses") == "actions/upload-artifact@v7.0.1"
        and step.get("with", {}).get("name") == "cli-coverage-xml"
        and step.get("with", {}).get("path") == "cli/coverage.xml"
        for step in cli_steps
    )


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
        step.get("uses") == "astral-sh/setup-uv@v9.0.0"
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
