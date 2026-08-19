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
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from modelable.emitters.targets import list_implemented_codegen_targets

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


def test_golden_targets_cover_every_implemented_codegen_target() -> None:
    """A newly added or newly-implemented codegen target must gain golden coverage.

    Guards against exactly the drift this module exists to prevent: a target
    shipping without the regression coverage the rest of this file provides.
    """
    generator = _load_generator_module()

    assert generator.ALL_GOLDEN_TARGETS == IMPLEMENTED_TARGETS


def test_golden_artifacts_are_up_to_date(tmp_path: Path) -> None:
    regenerated = tmp_path / "artifacts"
    _regenerate(regenerated)

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


def test_golden_artifact_generation_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _regenerate(first)
    _regenerate(second)

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
