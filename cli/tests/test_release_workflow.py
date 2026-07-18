from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PINNED_ACTION_REF = re.compile(r"^(?:v\d+(?:\.\d+){0,2}|release/v\d+)$")


def _workflow(workflow_name: str) -> dict[str, Any]:
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
        step.get("uses") == "actions/setup-node@v6.4.0" and step.get("with", {}).get("node-version") == 26
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
        assert jobs[surface]["needs"] == "changes"
        assert jobs[surface]["if"] == f"needs.changes.outputs.{surface} == 'true'"


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
        "browser": "browser",
    }

    for job_name, expected_suffix in expected_suffixes.items():
        setup_uv_steps = [
            step for step in jobs[job_name]["steps"] if str(step.get("uses", "")).startswith("astral-sh/setup-uv@")
        ]
        assert len(setup_uv_steps) == 1
        assert setup_uv_steps[0]["with"]["cache-dependency-glob"] == "cli/uv.lock"
        assert setup_uv_steps[0]["with"]["cache-suffix"] == expected_suffix


def test_validation_workflow_runs_complete_browser_spike_gate() -> None:
    workflow = _workflow("validate.yml")
    steps = workflow["jobs"]["browser"]["steps"]
    commands = "\n".join(step["run"] for step in steps if "run" in step)

    assert any(
        step.get("uses") == "actions/setup-node@v6.4.0" and step.get("with", {}).get("node-version") == 26
        for step in steps
    )
    assert "uv python install 3.14" in commands
    assert "uv sync --extra dev --frozen" in commands
    assert "npm ci" in commands
    assert "npx playwright install --with-deps chromium" in commands
    assert "uv run python .github/scripts/run_browser_spike.py --skip-install" in commands
    assert any(
        step.get("uses") == "actions/upload-artifact@v7.0.1"
        and step.get("if") == "${{ failure() }}"
        and step.get("with", {}).get("path") == "web/output/playwright"
        for step in steps
    )
    assert any(
        step.get("uses") == "actions/upload-artifact@v7.0.1"
        and step.get("if") == "${{ failure() }}"
        and step.get("with", {}).get("path") == "web/dist"
        for step in steps
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
