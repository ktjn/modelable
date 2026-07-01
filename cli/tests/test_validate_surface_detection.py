from __future__ import annotations

import importlib.util
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DETECTOR_PATH = REPOSITORY_ROOT / ".github" / "scripts" / "detect_validate_surfaces.py"


def _load_detector():
    spec = importlib.util.spec_from_file_location("detect_validate_surfaces", DETECTOR_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    }


def test_manual_dispatch_and_validate_workflow_changes_run_every_job() -> None:
    detector = _load_detector()

    assert all(detector.detect_surfaces([], event_name="workflow_dispatch").values())
    assert all(detector.detect_surfaces([".github/workflows/validate.yml"]).values())
