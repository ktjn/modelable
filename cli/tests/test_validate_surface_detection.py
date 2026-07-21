from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DETECTOR_PATH = REPOSITORY_ROOT / ".github" / "scripts" / "detect_validate_surfaces.py"
BROWSER_BUILDER_PATH = REPOSITORY_ROOT / "cli" / "scripts" / "build_browser_wheel.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_detector():
    return _load_module("detect_validate_surfaces", DETECTOR_PATH)


def test_docs_only_change_skips_code_and_external_smoke_jobs() -> None:
    detector = _load_detector()

    outputs = detector.detect_surfaces(["docs/getting-started.md"])

    assert outputs == {
        "cli": False,
        "vscode": False,
        "odcs": False,
        "openmetadata": False,
        "openlineage": False,
        "fhir": False,
        "browser": False,
    }


def test_cli_change_runs_core_cli_job_without_unrelated_external_smokes() -> None:
    detector = _load_detector()

    outputs = detector.detect_surfaces(["cli/src/modelable/cli.py"])

    assert outputs == {
        "cli": True,
        "vscode": False,
        "odcs": False,
        "openmetadata": False,
        "openlineage": False,
        "fhir": False,
        "browser": False,
    }


def test_lsp_change_runs_cli_and_vscode_jobs() -> None:
    detector = _load_detector()

    outputs = detector.detect_surfaces(["cli/src/modelable/lsp/server.py"])

    assert outputs["cli"] is True
    assert outputs["vscode"] is True
    assert outputs["odcs"] is False
    assert outputs["openmetadata"] is False
    assert outputs["openlineage"] is False
    assert outputs["fhir"] is False
    assert outputs["browser"] is False


def test_export_format_surfaces_run_only_relevant_external_smokes() -> None:
    detector = _load_detector()

    assert detector.detect_surfaces(["cli/src/modelable/emitters/odcs.py"])["odcs"] is True
    assert detector.detect_surfaces(["cli/src/modelable/emitters/openmetadata.py"])["openmetadata"] is True
    assert detector.detect_surfaces(["cli/src/modelable/emitters/openlineage.py"])["openlineage"] is True
    assert detector.detect_surfaces(["cli/src/modelable/emitters/fhir.py"])["fhir"] is True


def test_shared_model_graph_change_runs_all_export_smokes() -> None:
    detector = _load_detector()

    outputs = detector.detect_surfaces(["cli/src/modelable/parser/ir.py"])

    assert outputs == {
        "cli": True,
        "vscode": False,
        "odcs": True,
        "openmetadata": True,
        "openlineage": True,
        "fhir": True,
        "browser": True,
    }


@pytest.mark.parametrize(
    "path",
    [
        "web/src/main.ts",
        "cli/browser/browser-lock.json",
        "cli/src/modelable/browser/api.py",
        "cli/scripts/build_browser_wheel.py",
        "cli/scripts/write_browser_conformance.py",
        "cli/tests/conformance/browser/cases.json",
        "cli/src/modelable/compat/checker.py",
        "cli/src/modelable/compiler/render.py",
        "cli/src/modelable/diagnostics/model.py",
        "cli/src/modelable/expressions/cel.py",
        "cli/src/modelable/governance/checker.py",
        "cli/src/modelable/grammar/modelable.lark",
        "cli/src/modelable/graph/export.py",
        "cli/src/modelable/language/completion.py",
        "cli/src/modelable/llm/context.py",
        "cli/src/modelable/parser/ir.py",
        "cli/src/modelable/planner/planner.py",
        "cli/src/modelable/validation/semantic.py",
        "cli/src/modelable/__init__.py",
        "cli/src/modelable/_pydantic_py314_compat.py",
        "cli/src/modelable/emitters/__init__.py",
        "cli/src/modelable/emitters/base.py",
        "cli/src/modelable/emitters/diagnostics.py",
        "cli/src/modelable/emitters/json_schema.py",
        "cli/src/modelable/registry/__init__.py",
        "cli/src/modelable/registry/resolver.py",
        "cli/src/modelable/registry/signature.py",
        "cli/pyproject.toml",
        "cli/uv.lock",
        ".github/scripts/run_browser_playground.py",
        ".github/scripts/assemble_pages.py",
        ".github/workflows/docs.yml",
        "docs/playground-design.md",
        "docs/maintainers.md",
    ],
)
def test_browser_surface_routes_every_browser_dependency(path: str) -> None:
    detector = _load_detector()

    assert detector.detect_surfaces([path])["browser"] is True


def test_unrelated_files_do_not_route_browser_surface() -> None:
    detector = _load_detector()

    assert detector.detect_surfaces(["README.md"])["browser"] is False
    assert detector.detect_surfaces(["docs/getting-started.md"])["browser"] is False
    assert detector.detect_surfaces(["cli/src/modelable/commands/format.py"])["browser"] is False


def test_every_source_staged_in_browser_wheel_routes_browser_surface() -> None:
    detector = _load_detector()
    builder = _load_module("build_browser_wheel", BROWSER_BUILDER_PATH)
    staged_paths = [f"cli/src/{path.as_posix()}" for path in builder.selected_source_paths()]

    missing = [path for path in staged_paths if not detector.detect_surfaces([path])["browser"]]

    assert missing == []


def test_manual_dispatch_and_validate_workflow_changes_run_every_job() -> None:
    detector = _load_detector()

    assert all(detector.detect_surfaces([], event_name="workflow_dispatch").values())
    assert all(detector.detect_surfaces([".github/workflows/validate.yml"]).values())
