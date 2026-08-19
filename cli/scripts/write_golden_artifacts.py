"""Regenerate the checked-in golden codegen artifacts under tests/golden/artifacts/.

Compiles the shared tests/golden/model.mdl fixture (and, for fhir-profile,
the existing tests/fixtures/fhir_patient_profile.mdl fixture) to every
`status="implemented"` codegen target and writes each emitted artifact's
content plus its warnings to disk. tests/test_golden_artifacts.py regenerates
into a temp directory with this same script and byte-compares against the
checked-in copy, so any unintended change to any target's generated output --
not just the specific cases existing per-emitter unit tests happen to assert
-- fails a test.

Run after a deliberate emitter change:
    uv run python scripts/write_golden_artifacts.py --output tests/golden/artifacts

Review the resulting diff like any other generated-output change before
committing it.
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections.abc import Callable
from pathlib import Path

from modelable.compiler.workspace import Workspace, load_workspace
from modelable.emitters.avro import emit_avro
from modelable.emitters.base import EmittedArtifact, render_artifact_text
from modelable.emitters.csharp import emit_csharp
from modelable.emitters.dbt_yaml import emit_dbt_yaml
from modelable.emitters.event_sink import emit_event_sink
from modelable.emitters.fhir import emit_fhir_profile
from modelable.emitters.go import emit_go
from modelable.emitters.grpc import emit_grpc
from modelable.emitters.java import emit_java
from modelable.emitters.json_schema import emit_json_schema
from modelable.emitters.markdown import emit_markdown
from modelable.emitters.odcs import emit_odcs
from modelable.emitters.openapi import emit_openapi
from modelable.emitters.openlineage import emit_openlineage
from modelable.emitters.openmetadata import emit_openmetadata
from modelable.emitters.protobuf import emit_protobuf
from modelable.emitters.python import emit_python
from modelable.emitters.registry_manifest import emit_registry_manifest
from modelable.emitters.rust import emit_rust
from modelable.emitters.sql import emit_sql
from modelable.emitters.typescript import emit_typescript

FIXTURE_ROOT = Path(__file__).parents[1] / "tests" / "golden"
FIXTURE_PATH = FIXTURE_ROOT / "model.mdl"
FHIR_FIXTURE_PATH = Path(__file__).parents[1] / "tests" / "fixtures" / "fhir_patient_profile.mdl"

# One entry per `status="implemented"` codegen target in
# modelable.emitters.targets.CODEGEN_TARGETS. test_golden_artifacts.py
# asserts this set matches that list exactly, so a newly added target
# without golden coverage fails loudly instead of silently shipping untested.
Emitter = Callable[[Workspace, Path], list[EmittedArtifact]]
TARGET_EMITTERS: dict[str, Emitter] = {
    "json-schema": emit_json_schema,
    "markdown": emit_markdown,
    "typescript": emit_typescript,
    "csharp": emit_csharp,
    "java": emit_java,
    "python": emit_python,
    "rust": lambda workspace, out_dir: emit_rust(workspace, out_dir),
    "go": emit_go,
    "sql-postgres": lambda workspace, out_dir: emit_sql(workspace, out_dir, "postgres"),
    "sql-clickhouse": lambda workspace, out_dir: emit_sql(workspace, out_dir, "clickhouse"),
    "dbt-yaml": emit_dbt_yaml,
    "openmetadata": emit_openmetadata,
    "openlineage": emit_openlineage,
    "odcs": emit_odcs,
    "protobuf": lambda workspace, out_dir: emit_protobuf(workspace, out_dir),
    "grpc": lambda workspace, out_dir: emit_grpc(workspace, out_dir),
    "openapi": emit_openapi,
    "avro": emit_avro,
    "registry": lambda workspace, out_dir: emit_registry_manifest(workspace, out_dir),
    "event-sink": emit_event_sink,
}

# fhir-profile uses a dedicated fixture (FHIR mapping needs its own
# @fhir-annotated shape) instead of the shared model.mdl.
FHIR_TARGET_EMITTER: Emitter = emit_fhir_profile

ALL_GOLDEN_TARGETS = frozenset({*TARGET_EMITTERS, "fhir-profile"})

# Purely symbolic: none of the emit_* functions perform disk I/O themselves,
# they only compute EmittedArtifact.path relative to whatever out_dir they're
# given, so any fixed path works here.
_SYMBOLIC_OUT_DIR = Path("artifact-root")


def _write_target(workspace: Workspace, target: str, emitter: Emitter, output_root: Path) -> None:
    target_dir = output_root / target
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True)

    artifacts = sorted(
        emitter(workspace, _SYMBOLIC_OUT_DIR),
        key=lambda artifact: artifact.path.relative_to(_SYMBOLIC_OUT_DIR).as_posix(),
    )

    warnings_by_ref: dict[str, list[str]] = {}
    for artifact in artifacts:
        relative = artifact.path.relative_to(_SYMBOLIC_OUT_DIR)
        destination = target_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(render_artifact_text(artifact), encoding="utf-8")
        if artifact.warnings:
            warnings_by_ref[artifact.ref] = list(artifact.warnings)

    (target_dir / "_warnings.json").write_text(
        json.dumps(warnings_by_ref, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_golden_artifacts(output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    workspace = load_workspace(FIXTURE_PATH)
    for target, emitter in TARGET_EMITTERS.items():
        _write_target(workspace, target, emitter, output_root)

    fhir_workspace = load_workspace(FHIR_FIXTURE_PATH)
    _write_target(fhir_workspace, "fhir-profile", FHIR_TARGET_EMITTER, output_root)


def main() -> None:
    parser = argparse.ArgumentParser(description="Write checked-in golden codegen artifacts.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    write_golden_artifacts(args.output)


if __name__ == "__main__":
    main()
