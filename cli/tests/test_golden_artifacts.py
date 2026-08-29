"""Golden-file regression coverage for every implemented codegen target.

Per-emitter unit tests (test_emit_*.py) assert specific behaviors -- a field
maps to the right type, a constraint renders correctly -- but none of them
pin a target's *complete* generated output. A change to shared rendering code
(naming, ordering, an unrelated field) can drift output in ways no existing
assertion happens to catch. This module closes that gap: it compiles one
shared, representative fixture (tests/golden/model.mdl, covering keys,
annotations, enums, arrays, maps, optional fields, a cross-domain ref, a
secondary index with a unique constraint, an auto-projection event, and an
api operation) to every `status="implemented"` codegen target and
byte-compares the result against the checked-in copies in
tests/golden/artifacts/, including each artifact's emitter warnings.

A deliberate change to generated output must regenerate the golden files and
include the diff in the same PR, exactly like reviewing any other generated
artifact:

    uv run python scripts/write_golden_artifacts.py --output tests/golden/artifacts

fhir-profile uses tests/fixtures/fhir_patient_profile.mdl instead of the
shared fixture, since FHIR mapping needs its own @fhir-annotated shape.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml
from jsonschema import Draft202012Validator

from modelable.compat.checker import check_model_version_compatibility
from modelable.compiler.workspace import load_workspace
from modelable.emitters.base import compute_content_hash, render_artifact_text
from modelable.emitters.targets import list_implemented_codegen_targets
from modelable.registry.snapshot import (
    load_snapshot_workspace,
    load_workspace_with_snapshot,
    resolve_workspace_snapshot,
)

GOLDEN_ROOT = Path(__file__).parent / "golden"
GOLDEN_ARTIFACTS = GOLDEN_ROOT / "artifacts"
GENERATOR = Path(__file__).parents[1] / "scripts" / "write_golden_artifacts.py"

IMPLEMENTED_TARGETS = {target.name for target in list_implemented_codegen_targets()}


def _load_generator_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("write_golden_artifacts", GENERATOR)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _regenerate(output: Path) -> None:
    subprocess.run(
        [sys.executable, str(GENERATOR), "--output", str(output)],
        check=True,
        cwd=Path(__file__).parents[1],
    )


@pytest.fixture(scope="module")
def regenerated_artifacts(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Generate two trees once for freshness and determinism assertions."""
    root = tmp_path_factory.mktemp("golden-artifacts")
    first = root / "first"
    second = root / "second"
    _regenerate(first)
    _regenerate(second)
    return first, second


def test_golden_targets_cover_every_implemented_codegen_target() -> None:
    """A newly added or newly-implemented codegen target must gain golden coverage.

    Guards against exactly the drift this module exists to prevent: a target
    shipping without the regression coverage the rest of this file provides.
    """
    generator = _load_generator_module()

    assert generator.ALL_GOLDEN_TARGETS == IMPLEMENTED_TARGETS


def test_snapshot_round_trip_preserves_every_codegen_target_output(tmp_path: Path) -> None:
    """The offline snapshot must be a lossless compiler input for every target."""
    generator = _load_generator_module()
    source_root = tmp_path / "source"
    source_root.mkdir()
    shutil.copyfile(GOLDEN_ROOT / "model.mdl", source_root / "model.mdl")
    fhir_source = (Path(__file__).parent / "fixtures" / "fhir_patient_profile.mdl").read_text(encoding="utf-8")
    fhir_source = fhir_source.replace(
        "  entity Patient @ 1 (additive) {",
        "  entity Organization @ 1 (additive) {\n    @key\n    organizationId: uuid\n  }\n\n"
        "  entity Patient @ 1 (additive) {",
        1,
    )
    (source_root / "fhir_patient_profile.mdl").write_text(fhir_source, encoding="utf-8")

    source_workspace = load_workspace(source_root)
    resolve_workspace_snapshot(source_workspace, tmp_path / ".modelable")
    snapshot_workspace = load_snapshot_workspace(tmp_path / ".modelable")

    emitters = dict(generator.TARGET_EMITTERS)
    emitters["fhir-profile"] = generator.FHIR_TARGET_EMITTER
    for target, emitter in emitters.items():
        source_artifacts = {
            artifact.ref: (render_artifact_text(artifact), artifact.warnings)
            for artifact in emitter(source_workspace, Path("source-artifacts") / target)
        }
        snapshot_artifacts = {
            artifact.ref: (render_artifact_text(artifact), artifact.warnings)
            for artifact in emitter(snapshot_workspace, Path("snapshot-artifacts") / target)
        }
        assert snapshot_artifacts == source_artifacts, target


def test_composed_snapshot_generates_every_codegen_target(tmp_path: Path) -> None:
    """A consumer workspace can generate every target from an offline provider snapshot."""
    generator = _load_generator_module()
    provider_root = tmp_path / "provider"
    provider_root.mkdir()
    shutil.copyfile(GOLDEN_ROOT / "model.mdl", provider_root / "model.mdl")
    consumer_path = tmp_path / "consumer.mdl"
    consumer_path.write_text(
        """
domain analytics {
  owner: "analytics-team"
  projection CustomerSummary @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    name <- c.displayName
  }
}
""",
        encoding="utf-8",
    )

    snapshot_dir = tmp_path / ".modelable"
    resolve_workspace_snapshot(load_workspace(provider_root), snapshot_dir)
    composed = load_workspace_with_snapshot(load_workspace(consumer_path), snapshot_dir)
    assert composed.errors == []

    for target, emitter in generator.TARGET_EMITTERS.items():
        artifacts = emitter(composed, tmp_path / "artifacts" / target)
        assert artifacts, target
        for artifact in artifacts:
            rendered = render_artifact_text(artifact)
            assert rendered
            assert artifact.content_hash == compute_content_hash(artifact.content)
            suffix = Path(artifact.path).suffix.lower()
            if suffix == ".json":
                document = json.loads(rendered)
                assert document is not None
                if target == "json-schema":
                    Draft202012Validator.check_schema(document)
                    assert document["x-modelable"]["version"] == int(artifact.ref.rsplit("@", 1)[1])
                elif target == "registry":
                    assert all(contract["ref"] and contract["signature"] for contract in document["contracts"])
            elif suffix in {".yaml", ".yml"}:
                assert yaml.safe_load(rendered.replace("# @generated by Modelable\n", "")) is not None


def test_compatible_v2_snapshot_generates_every_codegen_target(tmp_path: Path) -> None:
    """A compatible provider candidate remains generatable across every target."""
    generator = _load_generator_module()
    provider_path = tmp_path / "provider.mdl"
    provider_path.write_text(
        """
domain customer {
  owner: "customer-platform"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName: string
  }
  entity Customer @ 2 (additive) {
    @key customerId: uuid
    displayName: string
    segment?: string
  }
}
""",
        encoding="utf-8",
    )
    consumer_path = tmp_path / "consumer.mdl"
    consumer_path.write_text(
        """
domain analytics {
  owner: "analytics-team"
  projection CustomerSummary @ 1
    from customer.Customer @ 2 as c
  {
    customerId <- c.customerId
    name <- c.displayName
  }
}
""",
        encoding="utf-8",
    )

    provider = load_workspace(provider_path)
    report = check_model_version_compatibility(provider.mdl, "customer", "Customer", 1, 2)
    assert report.status == "compatible"
    snapshot_dir = tmp_path / ".modelable"
    resolve_workspace_snapshot(provider, snapshot_dir)
    composed = load_workspace_with_snapshot(load_workspace(consumer_path), snapshot_dir)
    assert composed.errors == []

    generated_refs: set[str] = set()
    for target, emitter in generator.TARGET_EMITTERS.items():
        artifacts = emitter(composed, tmp_path / "candidate-artifacts" / target)
        assert artifacts, target
        refs = {artifact.ref for artifact in artifacts}
        generated_refs.update(refs)
        for artifact in artifacts:
            assert artifact.content_hash == compute_content_hash(artifact.content)
    assert "analytics.CustomerSummary@1" in generated_refs
    assert "customer.Customer@2" in generated_refs


def test_golden_artifacts_are_up_to_date(regenerated_artifacts: tuple[Path, Path]) -> None:
    regenerated, _ = regenerated_artifacts

    checked_in_targets = {path.name for path in GOLDEN_ARTIFACTS.iterdir() if path.is_dir()}
    regenerated_targets = {path.name for path in regenerated.iterdir() if path.is_dir()}
    assert regenerated_targets == checked_in_targets == IMPLEMENTED_TARGETS

    mismatches: list[str] = []
    for target in sorted(IMPLEMENTED_TARGETS):
        checked_in_files = {
            path.relative_to(GOLDEN_ARTIFACTS / target).as_posix()
            for path in (GOLDEN_ARTIFACTS / target).rglob("*")
            if path.is_file()
        }
        regenerated_files = {
            path.relative_to(regenerated / target).as_posix()
            for path in (regenerated / target).rglob("*")
            if path.is_file()
        }
        if checked_in_files != regenerated_files:
            mismatches.append(
                f"{target}: file set differs -- "
                f"missing from checked-in: {sorted(regenerated_files - checked_in_files)}, "
                f"stale in checked-in: {sorted(checked_in_files - regenerated_files)}"
            )
            continue
        for relative in sorted(checked_in_files):
            checked_in_text = (GOLDEN_ARTIFACTS / target / relative).read_text(encoding="utf-8")
            regenerated_text = (regenerated / target / relative).read_text(encoding="utf-8")
            if checked_in_text != regenerated_text:
                mismatches.append(f"{target}/{relative}: content differs from checked-in golden file")

    assert not mismatches, (
        "Golden artifacts are out of date. If this change is intentional, regenerate with:\n"
        "    uv run python scripts/write_golden_artifacts.py --output tests/golden/artifacts\n"
        "and review the diff before committing.\n\nMismatches:\n" + "\n".join(mismatches)
    )


def test_golden_artifact_generation_is_deterministic(regenerated_artifacts: tuple[Path, Path]) -> None:
    first, second = regenerated_artifacts

    first_files = sorted(path.relative_to(first) for path in first.rglob("*") if path.is_file())
    second_files = sorted(path.relative_to(second) for path in second.rglob("*") if path.is_file())
    assert first_files == second_files
    for relative in first_files:
        assert (first / relative).read_bytes() == (second / relative).read_bytes()


_SQL_DIALECT_TARGETS = {"sql-postgres", "sql-clickhouse"}


@pytest.mark.parametrize("target", sorted(IMPLEMENTED_TARGETS))
def test_golden_target_has_no_unexpected_warnings(target: str) -> None:
    """Every warning in a golden fixture's output must be one we intentionally pinned.

    The fixture's `byEmail` secondary index references the @pii `email`
    field, which the `reply` auto-projection excludes -- so every SQL
    dialect warns that the index can't resolve a column on
    CustomerReply. ClickHouse additionally can't enforce the index's
    `unique: true` on the other three projections, per its MergeTree
    limitation (see the sql-clickhouse emitter). Any other warning means
    something in the fixture or an emitter started silently degrading.
    """
    warnings_path = GOLDEN_ARTIFACTS / target / "_warnings.json"
    warnings_by_ref = json.loads(warnings_path.read_text(encoding="utf-8"))

    if target not in _SQL_DIALECT_TARGETS:
        assert warnings_by_ref == {}, f"{target}: unexpected warnings {warnings_by_ref}"
        return

    not_projected_refs = {"customer.CustomerReply@1"}
    uniqueness_refs = (
        {"customer.CustomerDb@1", "customer.CustomerRequest@1", "customer.CustomerEvent@1"}
        if target == "sql-clickhouse"
        else set()
    )
    assert set(warnings_by_ref) == not_projected_refs | uniqueness_refs

    for ref, warnings in warnings_by_ref.items():
        assert len(warnings) == 1
        if ref in not_projected_refs:
            assert "field 'email' is not projected" in warnings[0]
        else:
            assert "cannot enforce uniqueness" in warnings[0]
