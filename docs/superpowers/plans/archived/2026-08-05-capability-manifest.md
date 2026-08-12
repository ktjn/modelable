# Capability Manifest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Modelable one compiler-owned "capability manifest" answering what it supports (output targets, SQL dialects, model kinds, annotations, and known deferred features), exposed via `modelable capabilities [--format json]`, and stop the output-target list from being independently hand-maintained in three more places than the existing registry.

**Architecture:** `emitters/targets.py::CODEGEN_TARGETS` is already a real per-target registry (name/description/status), but three other places keep their own independent copies of the same target-name list: `operations/compilation.py::TARGETS` (a bare tuple used only for a membership check), `commands/validate_compat.py`'s hardcoded `click.Choice(["protobuf", "grpc"])`, and README's prose capability list. SQL dialects (`emitters/sql.py::_DIALECTS`) have no registry at all today — just a private, undescribed set. This plan (a) makes `CodegenTarget` carry a `supports_compat_check` flag so `validate_compat.py` derives its choices instead of hardcoding a second list, (b) points `compilation.py`'s validation at the registry instead of its own tuple, (c) promotes SQL dialects to a real `SqlDialect` registry, (d) adds a new `capabilities.py` module that aggregates targets, SQL dialects, model kinds (from `parser.ir.ModelKind`, already a clean enum), annotations (from `parser.ir.Annotation`'s 11-member discriminated union, already a clean source), and a small hand-curated list of verified deferred features, and (e) exposes it through a new `modelable capabilities` command.

**Tech Stack:** Python 3.14, Click, dataclasses/StrEnum, pytest (`uv run pytest`).

## Global Constraints

- This is Slice B1 of `docs/correction-and-capability-plan.md`. Full purpose/scope/acceptance-criteria text lives there under "Slice B1 — add a canonical capability manifest"; this plan implements a deliberately-scoped first pass, not the full nine-area list the slice describes.
- **`CapabilityStatus` uses the plan's already-specified five-value vocabulary** (`implemented, experimental, deferred, candidate, removed` — from Slice B2's acceptance criteria in the same plan document, not invented here) even though this PR's data only ever assigns `implemented` or `deferred`. This avoids Slice B2 needing to widen a public enum later; it does not pull any B2 work into this PR.
- **Explicitly deferred, not in this plan** (document these in the PR description too):
  - **Import formats, integrations (publish/pull/validate/sync verbs), and wire-hint value enums** don't exist as data anywhere in the codebase today (confirmed by research — import formats are an if/elif dispatch chain, integration capability is implicit in which methods each `registry/*.py` module happens to expose, and wire hint `case`/`encoding`/`field_case` values are free-form strings with no enum). Building real registries for these is genuine new design work belonging to a follow-up slice, not a mechanical wiring task like the areas in this plan.
  - **LSP/browser/Playground capability introspection** — LSP capabilities are inline `types.ServerCapabilities(...)` kwargs in `lsp/server.py`, not data. Exposing them through the manifest is a separate, LSP-specific follow-up.
  - **Automated README/`docs/compiler-reference.md` prose-vs-manifest consistency checking** is not attempted — README's capability section is free prose (e.g. "SQL DDL" for both `sql-postgres`/`sql-clickhouse`, "FHIR R4 profile" for `fhir-profile`) with no reliable 1:1 mapping to `CodegenTarget.name` without inventing and maintaining a second translation table, which would undermine the point. Instead: README's capability prose is hand-corrected to current accuracy as part of this plan (Task 6), and the "documentation consistency" acceptance criterion is satisfied with **code-to-code** regression tests (CLI target choices vs. the registry) rather than fragile prose-parsing.
  - `docs/compiler-reference.md` is stale in places (e.g. still describes TypeScript delegating to `json-schema-to-typescript`, which the native TypeScript emitter replaced) — reconciling it is Slice B2's job, not touched here.
  - Fully resolving the composite-keys/model-lifecycle-status documentation contradictions (Slices D5/D6) is not attempted — this plan only **labels** them as deferred in the manifest, using the same verified evidence the correction plan already cites.
- Run `uv run ruff format --check <files>`, `uv run ruff check <files>`, and the mypy baseline ratchet (`uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes`, from `cli/`) before each commit.
- Run `uv run pytest -q` (the full suite) after every task, not just the touched files — recent slices in this series repeatedly caught real cross-cutting regressions (sample scenarios, CI surface-detection duplication, browser conformance snapshots) this way.
- All commands below assume the current working directory is `cli/` inside the repo checkout, unless stated otherwise.

---

### Task 1: Promote SQL dialects to a real registry

**Files:**
- Modify: `cli/src/modelable/emitters/sql.py:1-35`
- Test: `cli/tests/test_emit_sql.py`

**Interfaces:**
- Produces: `SqlDialect` dataclass (`name: str`, `description: str`) and `SQL_DIALECTS: tuple[SqlDialect, ...]` (2 entries: `postgres`, `clickhouse`), plus `list_sql_dialects() -> list[SqlDialect]` — the shape Task 4 will import directly, mirroring `emitters/targets.py`'s existing `CodegenTarget`/`CODEGEN_TARGETS`/`list_codegen_targets` pattern.
- `emit_sql`'s public behavior is unchanged — `_DIALECTS` (the validity check) is replaced by a set derived from `SQL_DIALECTS`, not removed.

Current code (`emitters/sql.py:26,34-35`):
```python
_DIALECTS = {"postgres", "clickhouse"}
...
    if dialect not in _DIALECTS:
        raise ValueError(f"unsupported SQL dialect: {dialect!r}")
```
`_emit_projection_ddl` (confirmed at `sql.py:86,93`) already branches on `if dialect == "postgres": ... _emit_secondary_index_ddl(...) ... else:` — only the ClickHouse branch skips index emission (a bare `MergeTree()` table with a `-- TODO: set ORDER BY for production use` comment, no secondary indexes at all). This is the evidence Task 4's deferred-features entry cites; this task doesn't change that emission behavior, only the dialect registry.

- [ ] **Step 1: Write the failing test**

Add to `cli/tests/test_emit_sql.py` (check the file's existing import style first and match it — other tests in this file likely already import from `modelable.emitters.sql`):

```python
def test_sql_dialect_registry_lists_postgres_and_clickhouse():
    from modelable.emitters.sql import list_sql_dialects

    dialects = {dialect.name: dialect.description for dialect in list_sql_dialects()}

    assert set(dialects) == {"postgres", "clickhouse"}
    assert all(description for description in dialects.values())


def test_emit_sql_still_rejects_unknown_dialect(tmp_path):
    from modelable.compiler.workspace import load_workspace
    from modelable.emitters.sql import emit_sql

    (tmp_path / "model.mdl").write_text(
        """
domain billing {
  owner: "test-team"
  entity Invoice @ 1 (additive) {
    @key invoiceId: uuid
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    import pytest

    with pytest.raises(ValueError, match="unsupported SQL dialect: 'mysql'"):
        emit_sql(workspace, tmp_path / "dist", "mysql")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_emit_sql.py -k "dialect_registry or still_rejects_unknown" -v`
Expected: `test_sql_dialect_registry_lists_postgres_and_clickhouse` FAILS with `ImportError: cannot import name 'list_sql_dialects'`. `test_emit_sql_still_rejects_unknown_dialect` PASSES already (it's a regression guard for existing behavior you're about to refactor, not new behavior — confirm it passes on the *current* code before touching `sql.py`, so you know your refactor didn't silently change the error path).

- [ ] **Step 3: Write the minimal implementation**

In `cli/src/modelable/emitters/sql.py`, replace lines 26 and the check at lines 34-35:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class SqlDialect:
    name: str
    description: str


SQL_DIALECTS: tuple[SqlDialect, ...] = (
    SqlDialect(
        name="postgres",
        description="PostgreSQL CREATE TABLE DDL, including primary and secondary index declarations",
    ),
    SqlDialect(
        name="clickhouse",
        description="ClickHouse CREATE TABLE DDL (MergeTree engine); secondary index declarations are not yet emitted",
    ),
)


def list_sql_dialects() -> list[SqlDialect]:
    return list(SQL_DIALECTS)


_DIALECT_NAMES = {dialect.name for dialect in SQL_DIALECTS}
```

(Add the `from dataclasses import dataclass` import near the top of the file, alongside the existing imports — check it isn't already imported before adding a duplicate.) Then change the check at the former lines 34-35 to:
```python
    if dialect not in _DIALECT_NAMES:
        raise ValueError(f"unsupported SQL dialect: {dialect!r}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_emit_sql.py -v`
Expected: all tests in the file PASS, including both new ones and every pre-existing test.

- [ ] **Step 5: Lint and type-check**

```bash
uv run ruff format --check src/modelable/emitters/sql.py tests/test_emit_sql.py
uv run ruff check src/modelable/emitters/sql.py tests/test_emit_sql.py
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
```

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add src/modelable/emitters/sql.py tests/test_emit_sql.py
git commit -m "feat(sql): promote SQL dialects to a real registry (Slice B1)"
```

---

### Task 2: Give targets a `supports_compat_check` flag; derive `validate-compat`'s choices from it

**Files:**
- Modify: `cli/src/modelable/emitters/targets.py`
- Modify: `cli/src/modelable/commands/validate_compat.py:25`
- Test: `cli/tests/test_targets.py` (new file — no existing test file for `emitters/targets.py` was found; check for one before creating to avoid a duplicate)

**Interfaces:**
- `CodegenTarget` gains a new field `supports_compat_check: bool = False`.
- Produces: `list_compat_checkable_targets() -> list[CodegenTarget]` (targets where `supports_compat_check` is `True`) — used by Task 4 for the manifest and by `validate_compat.py`.

Background: `commands/validate_compat.py:25` hardcodes `click.Choice(["protobuf", "grpc"])` — a second, independent copy of "which targets support target-compatibility checking," unrelated to the *codegen* target list duplication Task 3 fixes (this is a genuinely different capability dimension: not every codegen target has a compat-checker, only protobuf and grpc do today, confirmed via `compat/targets.py`'s `compare_protobuf_manifests`/`compare_grpc_artifacts`).

- [ ] **Step 1: Write the failing tests**

Create `cli/tests/test_targets.py`:

```python
from modelable.emitters.targets import CODEGEN_TARGETS, get_codegen_target, list_compat_checkable_targets


def test_protobuf_and_grpc_support_compat_check():
    assert get_codegen_target("protobuf").supports_compat_check is True
    assert get_codegen_target("grpc").supports_compat_check is True


def test_other_targets_do_not_support_compat_check():
    non_compat_targets = [target for target in CODEGEN_TARGETS if target.name not in ("protobuf", "grpc")]
    assert non_compat_targets
    assert all(target.supports_compat_check is False for target in non_compat_targets)


def test_list_compat_checkable_targets_returns_exactly_protobuf_and_grpc():
    names = {target.name for target in list_compat_checkable_targets()}
    assert names == {"protobuf", "grpc"}
```

And add to `cli/tests/test_validate_compat.py` (check the file's existing import/invocation style first and match it):

```python
def test_validate_compat_target_choices_match_the_registry():
    from click.testing import CliRunner

    from modelable.cli import cli

    result = CliRunner().invoke(cli, ["validate-compat", "--help"])

    assert "protobuf|grpc" in result.output or ("protobuf" in result.output and "grpc" in result.output)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_targets.py -v`
Expected: all 3 fail with `ImportError` (`supports_compat_check` doesn't exist on `CodegenTarget`; `list_compat_checkable_targets` doesn't exist).

Run: `uv run pytest tests/test_validate_compat.py -k target_choices_match -v`
Expected: this one already PASSES (it's a guard confirming today's hardcoded choice list still renders `protobuf`/`grpc` in `--help`, which will remain true after the refactor — run it now to prove it isn't a new-behavior test).

- [ ] **Step 3: Write the minimal implementation**

In `cli/src/modelable/emitters/targets.py`, add the field to `CodegenTarget` (after `default_out_dir`):
```python
@dataclass(frozen=True)
class CodegenTarget:
    name: str
    description: str
    status: TargetStatus
    kind: TargetKind
    default_out_dir: Path | None = None
    supports_compat_check: bool = False
```
Set `supports_compat_check=True` on exactly the `protobuf` and `grpc` entries in `CODEGEN_TARGETS` (leave every other entry's constructor call unchanged — the new field defaults to `False`). Add after `get_codegen_target`:
```python
def list_compat_checkable_targets() -> list[CodegenTarget]:
    return [target for target in CODEGEN_TARGETS if target.supports_compat_check]
```

In `cli/src/modelable/commands/validate_compat.py`, replace:
```python
@click.option("--target", type=click.Choice(["protobuf", "grpc"]), required=True)
```
with:
```python
@click.option(
    "--target",
    type=click.Choice([target.name for target in list_compat_checkable_targets()]),
    required=True,
)
```
and add the import: `from modelable.emitters.targets import list_compat_checkable_targets`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_targets.py tests/test_validate_compat.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint and type-check**

```bash
uv run ruff format --check src/modelable/emitters/targets.py src/modelable/commands/validate_compat.py tests/test_targets.py tests/test_validate_compat.py
uv run ruff check src/modelable/emitters/targets.py src/modelable/commands/validate_compat.py tests/test_targets.py tests/test_validate_compat.py
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
```

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add src/modelable/emitters/targets.py src/modelable/commands/validate_compat.py tests/test_targets.py tests/test_validate_compat.py
git commit -m "fix(cli): derive validate-compat's --target choices from the codegen target registry"
```

---

### Task 3: Fix `compilation.py`'s duplicate `TARGETS` tuple

**Files:**
- Modify: `cli/src/modelable/operations/compilation.py:57-75,584,1211`
- Test: `cli/tests/test_compilation_service.py`

**Interfaces:** None new — `TARGETS` (module-level tuple) is replaced by a set derived from the registry; both call sites (`_validate_preview_request` at line 584, and the equivalent check at line 1211) keep their exact same `if request.target not in ...:` shape.

Background: `TARGETS` (`compilation.py:57-75`) is a bare 17-string tuple, independently listing the same names `emitters/targets.py::CODEGEN_TARGETS` already has — confirmed as the only real duplicate of the *codegen* target list (as opposed to Task 2's *compat-checkable* target list, a different concept). `_DEFAULT_OUT_DIRS` two lines below it (line 77-81) already correctly derives from `list_implemented_codegen_targets()` — this task makes `TARGETS`'s replacement follow the same existing pattern in the same file, not a new one.

- [ ] **Step 1: Write the failing test**

Add to `cli/tests/test_compilation_service.py` (find the existing `preview_for`/`write_workspace` test helpers already used elsewhere in this file and reuse them — do not redefine):

```python
def test_preview_rejects_a_target_not_in_the_codegen_registry(tmp_path: Path) -> None:
    source = write_workspace(
        tmp_path,
        """
domain billing {
  owner: "test-team"
  entity Invoice @ 1 (additive) {
    @key invoiceId: uuid
  }
}
""",
    )

    from modelable.operations.compilation import CompilationError

    try:
        preview_for(tmp_path, source, target="cobol")
    except CompilationError as exc:
        assert "cobol" in str(exc)
    else:
        raise AssertionError("expected CompilationError for an unknown target")
```

- [ ] **Step 2: Run the test to verify it currently passes (it's a regression guard, not new behavior)**

Run: `uv run pytest tests/test_compilation_service.py -k rejects_a_target_not_in -v`
Expected: PASSES already — `"cobol"` isn't in the current hand-written `TARGETS` tuple either, so this proves today's behavior before you touch anything. (This task doesn't change *which* targets are rejected — `TARGETS` and `list_implemented_codegen_targets()` currently name the exact same 17 targets, confirmed by direct comparison — it only changes *where* that list comes from, so there is no genuine RED step here. Treat this test as characterization coverage for the refactor, matching the same "already passes" pattern used for `validate_compat` in Task 2 and for the join/computed-field alias checks in Slice A3.)

- [ ] **Step 3: Write the implementation**

In `cli/src/modelable/operations/compilation.py`, replace the `TARGETS` tuple (lines 57-75):
```python
TARGETS = (
    "json-schema",
    "markdown",
    ...
    "sql-clickhouse",
)
```
with:
```python
TARGETS = frozenset(target.name for target in list_implemented_codegen_targets())
```
`list_implemented_codegen_targets` is already imported in this file (line 36: `from modelable.emitters.targets import list_implemented_codegen_targets`) — no new import needed. Both existing call sites (`if request.target not in TARGETS:` at lines 584 and 1211) work unchanged against a `frozenset` the same way they did against a `tuple`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_compilation_service.py -v`
Expected: all PASS, including the new regression-guard test.

- [ ] **Step 5: Lint and type-check**

```bash
uv run ruff format --check src/modelable/operations/compilation.py tests/test_compilation_service.py
uv run ruff check src/modelable/operations/compilation.py tests/test_compilation_service.py
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
```

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add src/modelable/operations/compilation.py tests/test_compilation_service.py
git commit -m "fix(compilation): derive the target validation set from the codegen registry"
```

---

### Task 4: Build the capability manifest module

**Files:**
- Create: `cli/src/modelable/capabilities.py`
- Test: `cli/tests/test_capabilities.py`

**Interfaces:**
- Consumes: `modelable.emitters.targets.CODEGEN_TARGETS`, `modelable.emitters.sql.SQL_DIALECTS` (Task 1), `modelable.parser.ir.ModelKind`, `modelable.parser.ir.Annotation` (the `Annotated[Union[...], Field(discriminator="kind")]` at `ir.py:136-149` — iterate its member types directly, listed below).
- Produces (used by Task 5): `CapabilityStatus` (StrEnum), `Capability` (frozen dataclass), `CapabilityManifest` (frozen dataclass with a `.all()` method), `build_capability_manifest() -> CapabilityManifest`.

The 11 concrete annotation classes and their exact `kind` literal (from `parser/ir.py`, confirmed): `AnnKey` (`"key"`), `AnnPii` (`"pii"`), `AnnClassification` (`"classification"`), `AnnDeprecated` (`"deprecated"`), `AnnOwner` (`"owner"`), `AnnServer` (`"server"`), `AnnWire` (`"wire"`), `AnnPitCutoff` (`"pit_cutoff"`), `AnnLatestBefore` (`"latest_before"`), `AnnLatestOnly` (`"latest_only"`), `AnnCustom` (`"custom"`). `ModelKind` (`parser/ir.py:258-262`) has exactly 4 members: `entity`, `aggregate`, `event`, `value`.

- [ ] **Step 1: Write the failing tests**

Create `cli/tests/test_capabilities.py`:

```python
from modelable.capabilities import Capability, CapabilityStatus, build_capability_manifest


def test_manifest_targets_match_the_codegen_registry():
    from modelable.emitters.targets import CODEGEN_TARGETS

    manifest = build_capability_manifest()

    manifest_names = {capability.name for capability in manifest.targets}
    registry_names = {target.name for target in CODEGEN_TARGETS}
    assert manifest_names == registry_names


def test_manifest_sql_dialects_match_the_sql_registry():
    from modelable.emitters.sql import SQL_DIALECTS

    manifest = build_capability_manifest()

    manifest_names = {capability.name for capability in manifest.sql_dialects}
    registry_names = {dialect.name for dialect in SQL_DIALECTS}
    assert manifest_names == registry_names


def test_manifest_model_kinds_match_model_kind_enum():
    from modelable.parser.ir import ModelKind

    manifest = build_capability_manifest()

    manifest_names = {capability.name for capability in manifest.model_kinds}
    enum_names = {kind.value for kind in ModelKind}
    assert manifest_names == enum_names


def test_manifest_annotations_include_all_eleven_kinds():
    manifest = build_capability_manifest()

    manifest_names = {capability.name for capability in manifest.annotations}
    assert manifest_names == {
        "key",
        "pii",
        "classification",
        "deprecated",
        "owner",
        "server",
        "wire",
        "pit_cutoff",
        "latest_before",
        "latest_only",
        "custom",
    }


def test_manifest_deferred_features_are_all_status_deferred():
    manifest = build_capability_manifest()

    assert manifest.deferred_features
    assert all(capability.status is CapabilityStatus.deferred for capability in manifest.deferred_features)
    assert all(capability.notes for capability in manifest.deferred_features)


def test_manifest_all_returns_every_capability_across_categories():
    manifest = build_capability_manifest()

    total = len(manifest.all())
    expected = (
        len(manifest.targets)
        + len(manifest.sql_dialects)
        + len(manifest.model_kinds)
        + len(manifest.annotations)
        + len(manifest.deferred_features)
    )
    assert total == expected
    assert total > 0


def test_capability_status_has_the_plans_five_values():
    assert {status.value for status in CapabilityStatus} == {
        "implemented",
        "experimental",
        "deferred",
        "candidate",
        "removed",
    }


def test_capability_is_a_plain_frozen_record():
    capability = Capability(name="x", category="target", status=CapabilityStatus.implemented, description="d")
    assert capability.notes is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_capabilities.py -v`
Expected: all fail with `ModuleNotFoundError: No module named 'modelable.capabilities'`.

- [ ] **Step 3: Write the implementation**

Create `cli/src/modelable/capabilities.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from modelable.emitters.sql import SQL_DIALECTS
from modelable.emitters.targets import CODEGEN_TARGETS
from modelable.parser.ir import ModelKind


class CapabilityStatus(StrEnum):
    """One of the five statuses docs/correction-and-capability-plan.md Slice B2 standardizes on."""

    implemented = "implemented"
    experimental = "experimental"
    deferred = "deferred"
    candidate = "candidate"
    removed = "removed"


@dataclass(frozen=True)
class Capability:
    name: str
    category: str
    status: CapabilityStatus
    description: str
    notes: str | None = None


@dataclass(frozen=True)
class CapabilityManifest:
    targets: tuple[Capability, ...]
    sql_dialects: tuple[Capability, ...]
    model_kinds: tuple[Capability, ...]
    annotations: tuple[Capability, ...]
    deferred_features: tuple[Capability, ...]

    def all(self) -> tuple[Capability, ...]:
        return self.targets + self.sql_dialects + self.model_kinds + self.annotations + self.deferred_features


_MODEL_KIND_DESCRIPTIONS: dict[str, str] = {
    "entity": "A model with a single stable identity, mutable over time",
    "aggregate": "A model composed of related entities under one consistency boundary",
    "event": "An immutable fact emitted at a point in time",
    "value": "A model with no independent identity, embedded within another model",
}

_ANNOTATION_DESCRIPTIONS: dict[str, str] = {
    "key": "Marks a field as the model's identity field",
    "pii": "Marks a field as personally identifiable information",
    "classification": "Sets a field's data-classification level",
    "deprecated": "Marks a field as deprecated in favor of a named replacement",
    "owner": "Attaches an owning team to a declaration",
    "server": "Marks a field as server-assigned, excluded from write models",
    "wire": "Attaches target-specific wire representation hints to a field",
    "pit_cutoff": "Attaches a point-in-time cutoff expression to a join",
    "latest_before": "Attaches a latest-before expression to a join",
    "latest_only": "Restricts a join to only the latest matching row",
    "custom": "Attaches an opaque, target-defined annotation",
}

_DEFERRED_FEATURES: tuple[Capability, ...] = (
    Capability(
        name="composite-keys",
        category="deferred_feature",
        status=CapabilityStatus.deferred,
        description="Multiple @key fields on a single entity or aggregate",
        notes=(
            "docs/architecture.md describes this as supported; "
            "cli/src/modelable/validation/semantic.py requires exactly one @key field "
            "per entity/aggregate today. See Slice D5 in docs/correction-and-capability-plan.md."
        ),
    ),
    Capability(
        name="clickhouse-secondary-indexes",
        category="deferred_feature",
        status=CapabilityStatus.deferred,
        description="Secondary index declarations emitted as ClickHouse DDL",
        notes=(
            "Only the sql-postgres target emits index declarations today; "
            "sql-clickhouse emits a bare MergeTree table with no secondary indexes."
        ),
    ),
    Capability(
        name="model-lifecycle-status",
        category="deferred_feature",
        status=CapabilityStatus.deferred,
        description="Draft, published, deprecated, and retired version status",
        notes=(
            "docs/architecture.md describes this lifecycle; it is not represented in the "
            "current stable grammar or IR. See Slice D6 in docs/correction-and-capability-plan.md."
        ),
    ),
    Capability(
        name="nominal-semantic-types-beyond-rust",
        category="deferred_feature",
        status=CapabilityStatus.deferred,
        description="Preserving semantic-type nominal identity in targets other than Rust, Protobuf, and gRPC",
        notes=(
            "Other targets resolve a semantic type reference structurally today. "
            "See Slice F1 in docs/correction-and-capability-plan.md and ROADMAP.md Priority 4 item 4."
        ),
    ),
)


def build_capability_manifest() -> CapabilityManifest:
    targets = tuple(
        Capability(
            name=target.name,
            category="target",
            status=CapabilityStatus.implemented if target.status == "implemented" else CapabilityStatus.deferred,
            description=target.description,
        )
        for target in CODEGEN_TARGETS
    )
    sql_dialects = tuple(
        Capability(
            name=dialect.name,
            category="sql_dialect",
            status=CapabilityStatus.implemented,
            description=dialect.description,
        )
        for dialect in SQL_DIALECTS
    )
    model_kinds = tuple(
        Capability(
            name=kind.value,
            category="model_kind",
            status=CapabilityStatus.implemented,
            description=_MODEL_KIND_DESCRIPTIONS[kind.value],
        )
        for kind in ModelKind
    )
    annotations = tuple(
        Capability(
            name=name,
            category="annotation",
            status=CapabilityStatus.implemented,
            description=description,
        )
        for name, description in _ANNOTATION_DESCRIPTIONS.items()
    )
    return CapabilityManifest(
        targets=targets,
        sql_dialects=sql_dialects,
        model_kinds=model_kinds,
        annotations=annotations,
        deferred_features=_DEFERRED_FEATURES,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_capabilities.py -v`
Expected: all 8 PASS.

- [ ] **Step 5: Lint and type-check**

```bash
uv run ruff format --check src/modelable/capabilities.py tests/test_capabilities.py
uv run ruff check src/modelable/capabilities.py tests/test_capabilities.py
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
```

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add src/modelable/capabilities.py tests/test_capabilities.py
git commit -m "feat: add compiler-owned capability manifest (Slice B1)"
```

---

### Task 5: Add the `modelable capabilities` command

**Files:**
- Create: `cli/src/modelable/commands/capabilities.py`
- Modify: `cli/src/modelable/cli.py`
- Test: `cli/tests/test_cli_capabilities.py`

**Interfaces:**
- Consumes: `modelable.capabilities.build_capability_manifest` (Task 4).
- Produces: a `capabilities` Click command registered via `register_capabilities_commands(cli_group)`, matching every other command module's registration pattern (`cli.py:5-21,35-47`).

No workspace/`.mdl` file is needed — this command only reads compiler-owned static data, unlike every other example command in this codebase (`graph`, `compile`, etc., which all call `load_workspace_or_exit`).

- [ ] **Step 1: Write the failing tests**

Create `cli/tests/test_cli_capabilities.py`:

```python
import json

from click.testing import CliRunner

from modelable.cli import cli


def test_capabilities_text_output_lists_every_category():
    result = CliRunner().invoke(cli, ["capabilities"])

    assert result.exit_code == 0
    assert "target" in result.output
    assert "sql_dialect" in result.output
    assert "model_kind" in result.output
    assert "annotation" in result.output
    assert "deferred_feature" in result.output
    assert "typescript" in result.output
    assert "composite-keys" in result.output


def test_capabilities_json_output_is_valid_and_complete():
    result = CliRunner().invoke(cli, ["capabilities", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert isinstance(payload, list)
    names = {entry["name"] for entry in payload}
    assert "typescript" in names
    assert "postgres" in names
    assert "entity" in names
    assert "key" in names
    assert "composite-keys" in names
    for entry in payload:
        assert set(entry) == {"name", "category", "status", "description", "notes"}


def test_capabilities_json_output_marks_deferred_features():
    result = CliRunner().invoke(cli, ["capabilities", "--format", "json"])

    payload = json.loads(result.output)
    composite_keys = next(entry for entry in payload if entry["name"] == "composite-keys")
    assert composite_keys["status"] == "deferred"
    assert composite_keys["notes"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli_capabilities.py -v`
Expected: all fail — `capabilities` isn't a registered CLI command yet, so Click reports "No such command".

- [ ] **Step 3: Write the implementation**

Create `cli/src/modelable/commands/capabilities.py`:

```python
from __future__ import annotations

import json
from dataclasses import asdict

import click

from modelable.capabilities import build_capability_manifest
from modelable.commands.common import console


def register_capabilities_commands(cli_group: click.Group) -> None:
    cli_group.add_command(capabilities)


@click.command("capabilities")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format.",
)
def capabilities(output_format: str) -> None:
    """List Modelable's compiler-owned capabilities: targets, SQL dialects, model kinds, annotations, and known deferred features."""
    manifest = build_capability_manifest()
    entries = manifest.all()

    if output_format == "json":
        payload = [{**asdict(entry), "status": entry.status.value} for entry in entries]
        click.echo(json.dumps(payload, indent=2))
        return

    for entry in entries:
        console.print(f"[bold]{entry.category}[/bold] {entry.name} ({entry.status.value}): {entry.description}")
        if entry.notes:
            console.print(f"  {entry.notes}")
```

Add to `cli/src/modelable/cli.py`: import `from modelable.commands.capabilities import register_capabilities_commands` alongside the other command imports (line 5-21), and call `register_capabilities_commands(cli)` alongside the other registration calls (line 35-47).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cli_capabilities.py -v`
Expected: all 3 PASS.

- [ ] **Step 5: Lint and type-check**

```bash
uv run ruff format --check src/modelable/commands/capabilities.py src/modelable/cli.py tests/test_cli_capabilities.py
uv run ruff check src/modelable/commands/capabilities.py src/modelable/cli.py tests/test_cli_capabilities.py
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
```

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add src/modelable/commands/capabilities.py src/modelable/cli.py tests/test_cli_capabilities.py
git commit -m "feat(cli): add modelable capabilities command (Slice B1)"
```

---

### Task 6: Documentation-consistency regression tests and README accuracy

**Files:**
- Modify: `README.md:56-74,100-113`
- Test: `cli/tests/test_capabilities.py` (extend)

**Interfaces:** None new — this task adds regression tests proving the CLI's actual target list (via `compile --help`) matches the registry, and brings README's hand-written capability prose back in sync with `CODEGEN_TARGETS` as a one-time correction (see Global Constraints for why this stays manual rather than automated).

- [ ] **Step 1: Write the failing test**

Add to `cli/tests/test_capabilities.py`:

```python
def test_compile_command_target_choices_match_the_manifest():
    from click.testing import CliRunner

    from modelable.capabilities import build_capability_manifest
    from modelable.cli import cli

    result = CliRunner().invoke(cli, ["compile", "--help"])
    manifest = build_capability_manifest()
    implemented_target_names = {
        capability.name for capability in manifest.targets if capability.status.value == "implemented"
    }

    for name in implemented_target_names:
        assert name in result.output, f"{name} is implemented but missing from `compile --help`"
```

- [ ] **Step 2: Run the test to verify it currently passes**

Run: `uv run pytest tests/test_capabilities.py -k target_choices_match_the_manifest -v`
Expected: PASSES already — `commands/compile.py` already derives its `--target` choices from `list_implemented_codegen_targets()` (confirmed in research; this predates this plan). This is intentional characterization coverage locking in behavior that already exists, the same pattern used in Tasks 2 and 3 — it protects against a future regression (someone hardcoding a new target list in `compile.py` instead of extending the registry), not new behavior.

- [ ] **Step 3: Update README's capability prose**

In `README.md`, read the current "## Capabilities" section (lines 56-74) and "## 1.0 stable surface" → "In scope for 1.0" list (lines 100-113) and cross-check every target name mentioned against `CODEGEN_TARGETS`' current 17 entries plus `SQL_DIALECTS`' 2 entries. As of this plan, both lists are already accurate against the registry (verified during planning) — this step is a checkpoint to catch drift if the registry changed between planning and implementation, not a known fix. If a discrepancy is found, correct the prose to match the registry; do not change the registry to match stale prose.

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 5: Lint and type-check**

```bash
uv run ruff format --check tests/test_capabilities.py
uv run ruff check tests/test_capabilities.py
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
```

- [ ] **Step 6: Verify the docs site still builds clean**

Run (from the repo root): `uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict`
Expected: exit 0, no warnings.

- [ ] **Step 7: Commit**

```bash
git add README.md tests/test_capabilities.py
git commit -m "test: lock in CLI/registry target consistency; verify README capability prose"
```

(If Step 3 found and fixed a real discrepancy, mention it explicitly in the commit message and the PR description instead of the generic message above.)

---

## Explicitly deferred (not in this plan)

See "Explicitly deferred" under Global Constraints above for the full list: import-format and integration-verb registries, wire-hint value enums, LSP/browser/Playground capability introspection, automated prose-consistency checking, and `docs/compiler-reference.md` staleness (Slice B2 territory).
