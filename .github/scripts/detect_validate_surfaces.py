from __future__ import annotations

import argparse
import os
from collections.abc import Iterable
from pathlib import Path

SURFACE_NAMES = ("cli", "vscode", "odcs", "openmetadata", "openlineage", "fhir", "browser")
_BROWSER_PACKAGE_TREES = (
    "browser",
    "compat",
    "compiler",
    "diagnostics",
    "expressions",
    "governance",
    "grammar",
    "parser",
    "planner",
    "validation",
)
_BROWSER_PACKAGE_FILES = {
    "__init__.py",
    "_pydantic_py314_compat.py",
    "emitters/__init__.py",
    "emitters/base.py",
    "emitters/diagnostics.py",
    "emitters/json_schema.py",
    "registry/__init__.py",
    "registry/resolver.py",
    "registry/signature.py",
}
WORKFLOW_POLICY_FILES = {
    ".github/scripts/detect_validate_surfaces.py",
    ".github/workflows/validate.yml",
    "cli/tests/test_release_workflow.py",
    "cli/tests/test_validate_surface_detection.py",
}


def _normalize(path: str) -> str:
    return path.replace("\\", "/").strip()


def _has_prefix(path: str, prefixes: Iterable[str]) -> bool:
    return any(path.startswith(prefix) for prefix in prefixes)


def _has_exact(path: str, names: Iterable[str]) -> bool:
    return path in set(names)


def detect_surfaces(changed_files: Iterable[str], *, event_name: str = "pull_request") -> dict[str, bool]:
    paths = [_normalize(path) for path in changed_files if path.strip()]
    if event_name == "workflow_dispatch" or any(_has_exact(path, WORKFLOW_POLICY_FILES) for path in paths):
        return dict.fromkeys(SURFACE_NAMES, True)

    outputs = dict.fromkeys(SURFACE_NAMES, False)
    if any(_has_prefix(path, ("cli/", "samples/")) for path in paths):
        outputs["cli"] = True

    if any(
        _has_prefix(path, ("vscode/", "cli/src/modelable/lsp/")) or path.startswith("cli/tests/test_lsp_")
        for path in paths
    ):
        outputs["cli"] = True
        outputs["vscode"] = True

    if any(_has_external_export_risk(path) for path in paths):
        outputs["odcs"] = True
        outputs["openmetadata"] = True
        outputs["openlineage"] = True
        outputs["fhir"] = True

    if any(_has_browser_risk(path) for path in paths):
        outputs["browser"] = True

    if any(path == "cli/src/modelable/emitters/odcs.py" or path == "cli/tests/test_emit_odcs.py" for path in paths):
        outputs["odcs"] = True

    if any(
        path in {"cli/src/modelable/emitters/openmetadata.py", "cli/tests/test_emit_openmetadata.py"}
        or path == "cli/tests/test_openmetadata_testcontainers.py"
        for path in paths
    ):
        outputs["openmetadata"] = True

    if any(
        path
        in {
            "cli/src/modelable/emitters/openlineage.py",
            "cli/src/modelable/registry/openlineage.py",
            "cli/src/modelable/commands/sync.py",
            "cli/tests/test_emit_openlineage.py",
            "cli/tests/test_openlineage_sync.py",
            "cli/tests/test_openlineage_testcontainers.py",
        }
        for path in paths
    ):
        outputs["openlineage"] = True

    if any(
        path in {"cli/src/modelable/emitters/fhir.py", "cli/src/modelable/emitters/fhir_validator.py"}
        or path in {"cli/tests/test_emit_fhir.py", "cli/tests/test_fhir_validator.py"}
        for path in paths
    ):
        outputs["fhir"] = True

    if any(path in {"cli/src/modelable/emitters/base.py", "cli/src/modelable/emitters/shapes.py"} for path in paths):
        outputs["odcs"] = True
        outputs["openmetadata"] = True
        outputs["openlineage"] = True
        outputs["fhir"] = True

    if any(path == "cli/src/modelable/emitters/targets.py" for path in paths):
        outputs["cli"] = True
        outputs["odcs"] = True
        outputs["openmetadata"] = True
        outputs["openlineage"] = True
        outputs["fhir"] = True

    if any(path in _export_contract_docs() for path in paths):
        outputs["odcs"] = True
        outputs["openmetadata"] = True
        outputs["openlineage"] = True
        outputs["fhir"] = True

    return outputs


def _has_external_export_risk(path: str) -> bool:
    return _has_prefix(
        path,
        (
            "cli/src/modelable/parser/",
            "cli/src/modelable/compiler/",
            "cli/src/modelable/planner/",
            "cli/src/modelable/governance/",
            "cli/src/modelable/validation/",
        ),
    )


def _has_browser_risk(path: str) -> bool:
    package_path = "cli/src/modelable/"
    return (
        _has_prefix(
            path,
            (
                "web/",
                "cli/browser/",
                "cli/tests/conformance/browser/",
                "cli/tests/test_browser_",
                *(f"{package_path}{tree}/" for tree in _BROWSER_PACKAGE_TREES),
            ),
        )
        or path
        in {
            ".github/scripts/assemble_pages.py",
            ".github/scripts/run_browser_playground.py",
            ".github/workflows/docs.yml",
            "cli/pyproject.toml",
            "cli/uv.lock",
            "cli/scripts/build_browser_wheel.py",
            "cli/scripts/write_browser_conformance.py",
            "cli/tests/test_pages_assembly.py",
            "docs/playground-design.md",
            "docs/maintainers.md",
            *(f"{package_path}{relative}" for relative in _BROWSER_PACKAGE_FILES),
        }
        or (
            _has_prefix(
                path,
                (
                    "docs/superpowers/specs/",
                    "docs/superpowers/plans/",
                ),
            )
            and "browser-compiler-wasm" in path
        )
    )


def _export_contract_docs() -> set[str]:
    return {
        "docs/cli-reference.md",
        "docs/compiler-reference.md",
        "docs/integrations.md",
        "docs/maintainers.md",
    }


def _write_outputs(outputs: dict[str, bool]) -> None:
    lines = [f"{name}={str(value).lower()}" for name, value in outputs.items()]
    output_path = os.getenv("GITHUB_OUTPUT")
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
            handle.write("\n")
        return
    print("\n".join(lines))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect Modelable Validate workflow surfaces from a changed-file list."
    )
    parser.add_argument("--event-name", default="pull_request")
    parser.add_argument("--changed-files", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    changed_files = args.changed_files.read_text(encoding="utf-8").splitlines()
    _write_outputs(detect_surfaces(changed_files, event_name=args.event_name))


if __name__ == "__main__":
    main()
