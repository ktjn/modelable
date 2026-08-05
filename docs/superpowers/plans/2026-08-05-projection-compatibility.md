# Projection-to-Projection Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `modelable diff <ref> <ref> --path` work for two versions of the same projection (today it raises `LookupError: unknown model version`), classifying changes across shape, lineage, governance, wire, storage, and source-version dimensions.

**Architecture:** New parallel types (`ProjectionChange`, `ProjectionCompatibilityReport`) alongside the existing model-compat types in `compat/diff.py`/`compat/checker.py` — not a modification of the model types, since projections have enough extra shape (joins, `where`, `group_by`) that force-fitting them in would be more confusing than a parallel type. One new shared field-resolution utility (`compat/projection_fields.py`) replaces what would otherwise be a 6th duplicate of an already-5x-duplicated resolver. `commands/diff.py::run_diff` branches on whether the resolved ref is a `ModelVersion` or `ProjectionVersion`.

**Tech Stack:** Python 3.14, Pydantic v2 IR models, pytest + pytest-xdist.

**Spec:** [docs/superpowers/specs/2026-08-05-projection-compatibility-design.md](../specs/2026-08-05-projection-compatibility-design.md)

## Global Constraints

- Do not modify `FieldChange`/`CompatibilityReport` (model-compat types) — projections get parallel types, not a shared/modified one.
- Do not touch the 5 existing duplicate `_resolve_projection_field_type` implementations in the emitters/`validation/semantic.py` — the new `compat/projection_fields.py` utility is additive, not a consolidation of those.
- `compat/diff.py` must not import from `compat/checker.py` (checker.py already imports from diff.py; the reverse would be circular) — this is why source-version comparison (which needs `check_model_version_compatibility`) lives in `checker.py`, not alongside the other `_compare_*` helpers in `diff.py`.
- `materialisation` and `event operation coverage` are not populated by this plan — both are genuine IR gaps (see spec). Do not add IR plumbing for either; the capability-manifest entry (Task 10) is the documented outcome for the second one.
- Every new/changed file must pass `uv run ruff format --check .`, `uv run ruff check .`, and the mypy baseline ratchet (`.github/scripts/check_mypy_baseline.py`) before its task's commit — reconcile `cli/mypy-baseline.txt` line numbers in Task 11 if any pre-existing baseline entries shift.
- Branch: work happens on `c1-projection-compatibility` (already created and checked out from `main` at commit `8c3b80c`/`165fb96`, the C1 design-doc commits). Do not create a new branch — this plan continues on it.

---

### Task 1: Shared projection-field resolver

**Files:**
- Create: `cli/src/modelable/compat/projection_fields.py`
- Test: `cli/tests/test_projection_fields.py`

**Interfaces:**
- Produces: `resolve_projection_field_type_and_optionality(field: ProjectionField, projection: ProjectionVersion, mdl: MdlFile) -> tuple[FieldType | None, bool | None]` — used by Task 2 (`_compare_shape`).

- [ ] **Step 1: Write the failing tests**

Create `cli/tests/test_projection_fields.py`:

```python
from modelable.compat.projection_fields import resolve_projection_field_type_and_optionality
from modelable.parser.parse import parse_text_to_ir

DIRECT_MAPPING_MODEL = """
domain orders {
  owner: "test-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    status?: string
  }
  projection OrderView @ 1 from orders.Order @ 1 as o {
    orderId <- o.orderId
    status <- o.status
  }
}
"""


def test_resolves_type_and_optionality_for_direct_mapping():
    mdl = parse_text_to_ir(DIRECT_MAPPING_MODEL)
    domain = mdl.domains[0]
    projection = domain.projections["OrderView"][0]
    status_field = next(f for f in projection.fields if f.name == "status")

    field_type, optional = resolve_projection_field_type_and_optionality(status_field, projection, mdl)

    assert field_type is not None
    assert field_type.kind == "string"
    assert optional is True


def test_resolves_through_a_join_alias():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
        customerId: uuid
      }
      entity Customer @ 1 (additive) {
        @key customerId: uuid
        name: string
      }
      projection OrderWithCustomer @ 1 from orders.Order @ 1 as o
        join orders.Customer @ 1 as c on o.customerId == c.customerId {
        orderId <- o.orderId
        customerName <- c.name
      }
    }
    """)
    domain = mdl.domains[0]
    projection = domain.projections["OrderWithCustomer"][0]
    name_field = next(f for f in projection.fields if f.name == "customerName")

    field_type, optional = resolve_projection_field_type_and_optionality(name_field, projection, mdl)

    assert field_type is not None
    assert field_type.kind == "string"
    assert optional is False


def test_computed_mapping_returns_none_none():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
        status: string
      }
      projection OrderView @ 1 from orders.Order @ 1 as o {
        orderId <- o.orderId
        isShipped = o.status == "shipped"
      }
    }
    """)
    domain = mdl.domains[0]
    projection = domain.projections["OrderView"][0]
    computed_field = next(f for f in projection.fields if f.name == "isShipped")

    field_type, optional = resolve_projection_field_type_and_optionality(computed_field, projection, mdl)

    assert field_type is None
    assert optional is None


def test_resolves_recursively_through_a_projection_of_a_projection():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
        status?: string
      }
      projection OrderBase @ 1 from orders.Order @ 1 as o {
        orderId <- o.orderId
        status <- o.status
      }
      projection OrderDerived @ 1 from orders.OrderBase @ 1 as b {
        orderId <- b.orderId
        status <- b.status
      }
    }
    """)
    domain = mdl.domains[0]
    derived = domain.projections["OrderDerived"][0]
    status_field = next(f for f in derived.fields if f.name == "status")

    field_type, optional = resolve_projection_field_type_and_optionality(status_field, derived, mdl)

    assert field_type is not None
    assert field_type.kind == "string"
    assert optional is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cli && uv run pytest tests/test_projection_fields.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'modelable.compat.projection_fields'`

- [ ] **Step 3: Write the implementation**

Create `cli/src/modelable/compat/projection_fields.py`:

```python
from __future__ import annotations

from modelable.dependency_graph import resolve_projection_aliases
from modelable.parser.ir import ComputedMapping, FieldType, MdlFile, ModelVersion, ProjectionField, ProjectionVersion


def resolve_projection_field_type_and_optionality(
    field: ProjectionField,
    projection: ProjectionVersion,
    mdl: MdlFile,
) -> tuple[FieldType | None, bool | None]:
    """Resolve a projection field's effective type and optionality from its source.

    Computed-mapping fields have no traceable source field, so both values
    are None for them. Direct-mapping fields resolve through the same
    canonical alias walk `dependency_graph.resolve_projection_aliases` uses,
    so this always agrees with how the rest of the compiler resolves "what
    does alias X refer to" for a projection. Handles projections sourced
    from other projections by recursing through the nested projection's own
    mapping.
    """
    if isinstance(field.mapping, ComputedMapping):
        return None, None

    aliases = resolve_projection_aliases(projection, mdl)
    resolved = aliases.get(field.mapping.source_alias)
    if resolved is None:
        return None, None

    return _resolve_field_from_version(resolved.version, field.mapping.source_field, mdl)


def _resolve_field_from_version(
    version: ModelVersion | ProjectionVersion,
    field_name: str,
    mdl: MdlFile,
) -> tuple[FieldType | None, bool | None]:
    if isinstance(version, ModelVersion):
        for source_field in version.fields:
            if source_field.name == field_name:
                return source_field.type, source_field.optional
        return None, None

    nested_field = next((f for f in version.fields if f.name == field_name), None)
    if nested_field is None:
        return None, None
    return resolve_projection_field_type_and_optionality(nested_field, version, mdl)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cli && uv run pytest tests/test_projection_fields.py -v`
Expected: PASS (all 4 tests)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd cli && uv run pytest -q`
Expected: all previously-passing tests still pass; test count increased by 4

- [ ] **Step 6: Commit**

```bash
git add cli/src/modelable/compat/projection_fields.py cli/tests/test_projection_fields.py
git commit -m "feat: add shared projection-field type/optionality resolver

Needed by the upcoming projection-compatibility shape comparison, which
needs optionality — none of the 5 existing per-emitter
_resolve_projection_field_type duplicates resolve that. Reuses the
canonical dependency_graph.resolve_projection_aliases alias walk instead
of re-deriving source resolution."
```

---

### Task 2: `ProjectionChange` + shape-dimension comparison

**Files:**
- Modify: `cli/src/modelable/compat/diff.py`
- Test: `cli/tests/test_projection_compatibility.py` (new)

**Interfaces:**
- Consumes: `resolve_projection_field_type_and_optionality` from Task 1.
- Produces: `ProjectionChange` dataclass (fields: `dimension: str`, `kind: str`, `breaking: bool`, `field_name: str | None = None`, `message: str = ""`); `_compare_shape(mdl: MdlFile, old: ProjectionVersion, new: ProjectionVersion) -> list[ProjectionChange]` — used by Task 7's `compare_projection_versions`.

- [ ] **Step 1: Write the failing tests**

Create `cli/tests/test_projection_compatibility.py`:

```python
from modelable.compat.diff import ProjectionChange, _compare_shape
from modelable.parser.parse import parse_text_to_ir


def _projection(mdl_text: str, name: str = "OrderView"):
    mdl = parse_text_to_ir(mdl_text)
    domain = mdl.domains[0]
    return mdl, domain.projections[name][0]


def _two_versions(old_text: str, new_text: str, name: str = "OrderView"):
    """Parse two separately-authored .mdl snippets as if they were the same
    projection at two points in time. Each snippet must declare a domain
    with matching name so both resolve into one merged view for tests that
    need a single `mdl` (most shape/lineage/governance/wire/storage tests
    only need each side's ProjectionVersion in isolation, not merged)."""
    _, old = _projection(old_text, name)
    new_mdl, new = _projection(new_text, name)
    return new_mdl, old, new


def test_field_removed_is_breaking():
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            status: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            status <- o.status
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
          }
        }
        """,
    )

    changes = _compare_shape(mdl, old, new)

    assert any(c.kind == "field_removed" and c.breaking and c.field_name == "status" for c in changes)


def test_field_added_is_not_breaking():
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            status: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            status <- o.status
          }
        }
        """,
    )

    changes = _compare_shape(mdl, old, new)

    assert any(c.kind == "field_added" and not c.breaking and c.field_name == "status" for c in changes)


def test_type_changed_is_breaking():
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            quantity: int
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            quantity <- o.quantity
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            quantity: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            quantity <- o.quantity
          }
        }
        """,
    )

    changes = _compare_shape(mdl, old, new)

    assert any(c.kind == "type_changed" and c.breaking and c.field_name == "quantity" for c in changes)


def test_optional_to_required_is_breaking():
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            note?: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            note <- o.note
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            note: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            note <- o.note
          }
        }
        """,
    )

    changes = _compare_shape(mdl, old, new)

    assert any(
        c.kind == "optionality_changed" and c.breaking and c.field_name == "note"
        for c in changes
    )


def test_required_to_optional_is_not_breaking():
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            note: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            note <- o.note
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            note?: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            note <- o.note
          }
        }
        """,
    )

    changes = _compare_shape(mdl, old, new)

    assert any(
        c.kind == "optionality_changed" and not c.breaking and c.field_name == "note"
        for c in changes
    )


def test_unchanged_fields_produce_no_shape_changes():
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
          }
        }
        """,
    )

    assert _compare_shape(mdl, old, new) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cli && uv run pytest tests/test_projection_compatibility.py -v`
Expected: FAIL with `ImportError: cannot import name 'ProjectionChange' from 'modelable.compat.diff'`

- [ ] **Step 3: Write the implementation**

In `cli/src/modelable/compat/diff.py`, update the imports at the top of the file:

```python
from modelable.parser.ir import AnnDeprecated, EnumType, FieldDef, FieldType, IndexDecl, MdlFile, ModelVersion, ProjectionVersion
```

Add near the top of the file, after the `FieldChange` dataclass:

```python
@dataclass(frozen=True)
class ProjectionChange:
    dimension: str  # "shape" | "lineage" | "governance" | "wire" | "storage" | "source_version" | "materialisation"
    kind: str
    breaking: bool
    field_name: str | None = None
    message: str = ""


def _shape_type_signature(field_type: FieldType | None) -> str | None:
    if field_type is None:
        return None
    return json.dumps(field_type.model_dump(mode="json"), sort_keys=True)


def _compare_shape(
    mdl: MdlFile,
    old: ProjectionVersion,
    new: ProjectionVersion,
) -> list[ProjectionChange]:
    changes: list[ProjectionChange] = []
    old_fields = {f.name: f for f in old.fields}
    new_fields = {f.name: f for f in new.fields}

    for name in sorted(set(old_fields) - set(new_fields)):
        changes.append(
            ProjectionChange(
                dimension="shape",
                kind="field_removed",
                breaking=True,
                field_name=name,
                message=f"field '{name}' was removed",
            )
        )

    for name in sorted(set(new_fields) - set(old_fields)):
        changes.append(
            ProjectionChange(
                dimension="shape",
                kind="field_added",
                breaking=False,
                field_name=name,
                message=f"field '{name}' was added",
            )
        )

    for name in sorted(set(old_fields) & set(new_fields)):
        old_field = old_fields[name]
        new_field = new_fields[name]
        old_type, old_optional = resolve_projection_field_type_and_optionality(old_field, old, mdl)
        new_type, new_optional = resolve_projection_field_type_and_optionality(new_field, new, mdl)

        if _shape_type_signature(old_type) != _shape_type_signature(new_type):
            changes.append(
                ProjectionChange(
                    dimension="shape",
                    kind="type_changed",
                    breaking=True,
                    field_name=name,
                    message=f"field '{name}' changed type",
                )
            )

        if old_optional != new_optional:
            breaking = old_optional is True and new_optional is False
            changes.append(
                ProjectionChange(
                    dimension="shape",
                    kind="optionality_changed",
                    breaking=breaking,
                    field_name=name,
                    message=f"field '{name}' optionality changed: {old_optional} -> {new_optional}",
                )
            )

    return changes
```

Add this line to the imports block at the top of `diff.py` (as a normal top-level import — `projection_fields.py` only imports from `dependency_graph.py` and `parser.ir`, neither of which imports from `compat/`, so there is no circular-import risk here, unlike the checker.py/diff.py pair discussed in the Global Constraints section):

```python
from modelable.compat.projection_fields import resolve_projection_field_type_and_optionality
```

`diff.py` already has `import json` at line 3 of the existing file — do not add a duplicate.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cli && uv run pytest tests/test_projection_compatibility.py -v`
Expected: PASS (all 6 tests)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd cli && uv run pytest -q`
Expected: all previously-passing tests still pass

- [ ] **Step 6: Commit**

```bash
git add cli/src/modelable/compat/diff.py cli/tests/test_projection_compatibility.py
git commit -m "feat: add projection shape-dimension compatibility comparison

ProjectionChange is the projection-compat parallel to FieldChange —
kept separate rather than extending FieldChange, since projections
carry enough extra shape (joins, where, group_by) that force-fitting
them into the model type would be more confusing than a parallel one."
```

---

### Task 3: Lineage-dimension comparison

**Files:**
- Modify: `cli/src/modelable/compat/diff.py`
- Modify: `cli/tests/test_projection_compatibility.py`

**Interfaces:**
- Produces: `_compare_lineage(old: ProjectionVersion, new: ProjectionVersion) -> list[ProjectionChange]` — used by Task 7.

- [ ] **Step 1: Write the failing tests**

Append to `cli/tests/test_projection_compatibility.py`:

```python
from modelable.compat.diff import _compare_lineage


def test_remapped_source_field_is_visible_but_not_breaking():
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            legacyStatus: string
            status: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            status <- o.legacyStatus
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            legacyStatus: string
            status: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            status <- o.status
          }
        }
        """,
    )

    changes = _compare_lineage(old, new)

    assert any(c.kind == "source_remapped" and not c.breaking and c.field_name == "status" for c in changes)


def test_expression_text_changed_is_visible_but_not_breaking():
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            status: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            isShipped = o.status == "shipped"
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            status: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            isShipped = o.status == "delivered"
          }
        }
        """,
    )

    changes = _compare_lineage(old, new)

    assert any(
        c.kind == "expression_changed" and not c.breaking and c.field_name == "isShipped"
        for c in changes
    )


def test_unchanged_lineage_produces_no_changes():
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
          }
        }
        """,
    )

    assert _compare_lineage(old, new) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cli && uv run pytest tests/test_projection_compatibility.py -k lineage -v`
Expected: FAIL with `ImportError: cannot import name '_compare_lineage'`

- [ ] **Step 3: Write the implementation**

In `cli/src/modelable/compat/diff.py`, update the imports to add `ComputedMapping` and `DirectMapping`:

```python
from modelable.parser.ir import (
    AnnDeprecated,
    ComputedMapping,
    DirectMapping,
    EnumType,
    FieldDef,
    FieldType,
    IndexDecl,
    MdlFile,
    ModelVersion,
    ProjectionVersion,
)
```

Add after `_compare_shape`:

```python
def _compare_lineage(old: ProjectionVersion, new: ProjectionVersion) -> list[ProjectionChange]:
    changes: list[ProjectionChange] = []
    old_fields = {f.name: f for f in old.fields}
    new_fields = {f.name: f for f in new.fields}

    for name in sorted(set(old_fields) & set(new_fields)):
        old_mapping = old_fields[name].mapping
        new_mapping = new_fields[name].mapping

        if isinstance(old_mapping, DirectMapping) and isinstance(new_mapping, DirectMapping):
            if (old_mapping.source_alias, old_mapping.source_field) != (
                new_mapping.source_alias,
                new_mapping.source_field,
            ):
                changes.append(
                    ProjectionChange(
                        dimension="lineage",
                        kind="source_remapped",
                        breaking=False,
                        field_name=name,
                        message=(
                            f"field '{name}' source remapped: "
                            f"{old_mapping.source_alias}.{old_mapping.source_field} -> "
                            f"{new_mapping.source_alias}.{new_mapping.source_field}"
                        ),
                    )
                )
        elif isinstance(old_mapping, ComputedMapping) and isinstance(new_mapping, ComputedMapping):
            if old_mapping.expression != new_mapping.expression:
                changes.append(
                    ProjectionChange(
                        dimension="lineage",
                        kind="expression_changed",
                        breaking=False,
                        field_name=name,
                        message=f"field '{name}' computed expression changed",
                    )
                )
        elif old_mapping.kind != new_mapping.kind:
            changes.append(
                ProjectionChange(
                    dimension="lineage",
                    kind="mapping_kind_changed",
                    breaking=False,
                    field_name=name,
                    message=f"field '{name}' mapping changed from {old_mapping.kind} to {new_mapping.kind}",
                )
            )

    return changes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cli && uv run pytest tests/test_projection_compatibility.py -v`
Expected: PASS (all tests so far)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd cli && uv run pytest -q`
Expected: all previously-passing tests still pass

- [ ] **Step 6: Commit**

```bash
git add cli/src/modelable/compat/diff.py cli/tests/test_projection_compatibility.py
git commit -m "feat: add projection lineage-dimension compatibility comparison

Lineage changes (remapped source field, changed computed expression)
are always reported but never breaking on their own, per the plan's
'same-shape lineage changes remain visible' acceptance criterion."
```

---

### Task 4: Governance-dimension comparison

**Files:**
- Modify: `cli/src/modelable/compat/diff.py`
- Modify: `cli/tests/test_projection_compatibility.py`

**Interfaces:**
- Produces: `_compare_governance(old: ProjectionVersion, new: ProjectionVersion) -> list[ProjectionChange]` — used by Task 7.

- [ ] **Step 1: Write the failing tests**

Append to `cli/tests/test_projection_compatibility.py`:

```python
from modelable.compat.diff import _compare_governance


def test_access_grant_removed_is_breaking():
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            access {
              entity: [{ principal: "billing-team", permissions: ["read"] }]
            }
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
          }
        }
        """,
    )

    changes = _compare_governance(old, new)

    assert any(c.kind == "access_grant_removed" and c.breaking for c in changes)


def test_access_grant_added_is_not_breaking():
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            access {
              entity: [{ principal: "billing-team", permissions: ["read"] }]
            }
          }
        }
        """,
    )

    changes = _compare_governance(old, new)

    assert any(c.kind == "access_grant_added" and not c.breaking for c in changes)


def test_classification_tightened_is_breaking():
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            note: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            @classification("open")
            note <- o.note
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            note: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            @classification("confidential")
            note <- o.note
          }
        }
        """,
    )

    changes = _compare_governance(old, new)

    assert any(
        c.kind == "classification_changed" and c.breaking and c.field_name == "note" for c in changes
    )


def test_classification_loosened_is_not_breaking():
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            note: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            @classification("confidential")
            note <- o.note
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            note: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            @classification("open")
            note <- o.note
          }
        }
        """,
    )

    changes = _compare_governance(old, new)

    assert any(
        c.kind == "classification_changed" and not c.breaking and c.field_name == "note" for c in changes
    )


def test_pii_added_is_breaking():
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            note: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            note <- o.note
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            note: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            @pii
            note <- o.note
          }
        }
        """,
    )

    changes = _compare_governance(old, new)

    assert any(c.kind == "pii_changed" and c.breaking and c.field_name == "note" for c in changes)


def test_pii_removed_is_not_breaking():
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            note: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            @pii
            note <- o.note
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            note: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            note <- o.note
          }
        }
        """,
    )

    changes = _compare_governance(old, new)

    assert any(c.kind == "pii_changed" and not c.breaking and c.field_name == "note" for c in changes)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cli && uv run pytest tests/test_projection_compatibility.py -k governance -v`
Expected: FAIL with `ImportError: cannot import name '_compare_governance'`

- [ ] **Step 3: Write the implementation**

In `cli/src/modelable/compat/diff.py`, add `ClassificationLevel` to the imports:

```python
from modelable.parser.ir import (
    AnnDeprecated,
    ClassificationLevel,
    ComputedMapping,
    DirectMapping,
    EnumType,
    FieldDef,
    FieldType,
    IndexDecl,
    MdlFile,
    ModelVersion,
    ProjectionVersion,
)
```

Add after `_compare_lineage`:

```python
_CLASSIFICATION_ORDER = {level: index for index, level in enumerate(ClassificationLevel)}


def _classification_index(level: ClassificationLevel | None) -> int:
    if level is None:
        return -1
    return _CLASSIFICATION_ORDER[level]


def _access_grant_triples(access) -> set[tuple[str, str, str]]:
    """Flatten a projection's AccessBlock into (scope, principal, permission) triples.

    scope is "entity" for entity-level grants, or the property name for
    per-property grants.
    """
    if access is None:
        return set()
    triples: set[tuple[str, str, str]] = set()
    for grant in access.entity:
        for permission in grant.permissions:
            triples.add(("entity", grant.principal, permission))
    for property_name, grants in access.properties.items():
        for grant in grants:
            for permission in grant.permissions:
                triples.add((property_name, grant.principal, permission))
    return triples


def _compare_governance(old: ProjectionVersion, new: ProjectionVersion) -> list[ProjectionChange]:
    changes: list[ProjectionChange] = []

    old_grants = _access_grant_triples(old.access)
    new_grants = _access_grant_triples(new.access)

    for scope, principal, permission in sorted(old_grants - new_grants):
        changes.append(
            ProjectionChange(
                dimension="governance",
                kind="access_grant_removed",
                breaking=True,
                field_name=None if scope == "entity" else scope,
                message=f"access grant removed: {scope} principal '{principal}' permission '{permission}'",
            )
        )
    for scope, principal, permission in sorted(new_grants - old_grants):
        changes.append(
            ProjectionChange(
                dimension="governance",
                kind="access_grant_added",
                breaking=False,
                field_name=None if scope == "entity" else scope,
                message=f"access grant added: {scope} principal '{principal}' permission '{permission}'",
            )
        )

    old_fields = {f.name: f for f in old.fields}
    new_fields = {f.name: f for f in new.fields}
    for name in sorted(set(old_fields) & set(new_fields)):
        old_field = old_fields[name]
        new_field = new_fields[name]

        if old_field.is_pii != new_field.is_pii:
            changes.append(
                ProjectionChange(
                    dimension="governance",
                    kind="pii_changed",
                    breaking=new_field.is_pii,
                    field_name=name,
                    message=f"field '{name}' @pii changed: {old_field.is_pii} -> {new_field.is_pii}",
                )
            )

        old_level = old_field.classification
        new_level = new_field.classification
        if old_level != new_level:
            tightened = _classification_index(new_level) > _classification_index(old_level)
            changes.append(
                ProjectionChange(
                    dimension="governance",
                    kind="classification_changed",
                    breaking=tightened,
                    field_name=name,
                    message=f"field '{name}' classification changed: {old_level} -> {new_level}",
                )
            )

    return changes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cli && uv run pytest tests/test_projection_compatibility.py -v`
Expected: PASS (all tests so far)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd cli && uv run pytest -q`
Expected: all previously-passing tests still pass

- [ ] **Step 6: Commit**

```bash
git add cli/src/modelable/compat/diff.py cli/tests/test_projection_compatibility.py
git commit -m "feat: add projection governance-dimension compatibility comparison

Classification tightening uses ClassificationLevel's declaration order
(open, internal, confidential, restricted, secret) as its severity
order — already implicit elsewhere in the codebase, made explicit here."
```

---

### Task 5: Wire-dimension comparison

**Files:**
- Modify: `cli/src/modelable/compat/diff.py`
- Modify: `cli/tests/test_projection_compatibility.py`

**Interfaces:**
- Produces: `_compare_wire(old: ProjectionVersion, new: ProjectionVersion) -> list[ProjectionChange]` — used by Task 7.

- [ ] **Step 1: Write the failing tests**

Append to `cli/tests/test_projection_compatibility.py`:

```python
from modelable.compat.diff import _compare_wire


def test_wire_hint_value_changed_is_breaking():
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            createdAt: timestamp
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            @wire(json.fieldCase: "camelCase")
            createdAt <- o.createdAt
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            createdAt: timestamp
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            @wire(json.fieldCase: "snake_case")
            createdAt <- o.createdAt
          }
        }
        """,
    )

    changes = _compare_wire(old, new)

    assert any(
        c.kind == "wire_hint_changed" and c.breaking and c.field_name == "createdAt" for c in changes
    )


def test_wire_hint_added_where_none_existed_is_not_breaking():
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            createdAt: timestamp
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            createdAt <- o.createdAt
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            createdAt: timestamp
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            @wire(json.fieldCase: "snake_case")
            createdAt <- o.createdAt
          }
        }
        """,
    )

    changes = _compare_wire(old, new)

    assert any(
        c.kind == "wire_hint_added" and not c.breaking and c.field_name == "createdAt" for c in changes
    )


def test_wire_hint_removed_is_not_breaking():
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            createdAt: timestamp
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            @wire(json.fieldCase: "snake_case")
            createdAt <- o.createdAt
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            createdAt: timestamp
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            createdAt <- o.createdAt
          }
        }
        """,
    )

    changes = _compare_wire(old, new)

    assert any(
        c.kind == "wire_hint_removed" and not c.breaking and c.field_name == "createdAt" for c in changes
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cli && uv run pytest tests/test_projection_compatibility.py -k wire -v`
Expected: FAIL with `ImportError: cannot import name '_compare_wire'`

- [ ] **Step 3: Write the implementation**

Add to `cli/src/modelable/compat/diff.py`, after `_compare_governance`:

```python
def _compare_wire(old: ProjectionVersion, new: ProjectionVersion) -> list[ProjectionChange]:
    changes: list[ProjectionChange] = []
    old_fields = {f.name: f for f in old.fields}
    new_fields = {f.name: f for f in new.fields}

    for name in sorted(set(old_fields) & set(new_fields)):
        old_targets = old_fields[name].wire_targets()
        new_targets = new_fields[name].wire_targets()

        for target in sorted(set(old_targets) & set(new_targets)):
            if old_targets[target] != new_targets[target]:
                changes.append(
                    ProjectionChange(
                        dimension="wire",
                        kind="wire_hint_changed",
                        breaking=True,
                        field_name=name,
                        message=f"field '{name}' @wire hint for '{target}' changed",
                    )
                )

        for target in sorted(set(new_targets) - set(old_targets)):
            changes.append(
                ProjectionChange(
                    dimension="wire",
                    kind="wire_hint_added",
                    breaking=False,
                    field_name=name,
                    message=f"field '{name}' @wire hint added for '{target}'",
                )
            )

        for target in sorted(set(old_targets) - set(new_targets)):
            changes.append(
                ProjectionChange(
                    dimension="wire",
                    kind="wire_hint_removed",
                    breaking=False,
                    field_name=name,
                    message=f"field '{name}' @wire hint removed for '{target}'",
                )
            )

    return changes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cli && uv run pytest tests/test_projection_compatibility.py -v`
Expected: PASS (all tests so far)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd cli && uv run pytest -q`
Expected: all previously-passing tests still pass

- [ ] **Step 6: Commit**

```bash
git add cli/src/modelable/compat/diff.py cli/tests/test_projection_compatibility.py
git commit -m "feat: add projection wire-dimension compatibility comparison

Only a changed hint VALUE for a target already present in both
versions is breaking — added/removed hints can't be proven to change
the wire format without a prior value to compare against."
```

---

### Task 6: Storage-dimension comparison

**Files:**
- Modify: `cli/src/modelable/compat/diff.py`
- Modify: `cli/tests/test_projection_compatibility.py`

**Interfaces:**
- Produces: `_compare_storage(old: ProjectionVersion, new: ProjectionVersion) -> list[ProjectionChange]` — used by Task 7.

- [ ] **Step 1: Write the failing tests**

Append to `cli/tests/test_projection_compatibility.py`:

```python
from modelable.compat.diff import _compare_storage


def test_where_clause_changed_is_breaking():
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            status: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o where o.status == "open" {
            orderId <- o.orderId
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            status: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o where o.status == "closed" {
            orderId <- o.orderId
          }
        }
        """,
    )

    changes = _compare_storage(old, new)

    assert any(c.kind == "where_changed" and c.breaking for c in changes)


def test_group_by_changed_is_breaking():
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            status: string
            customerId: uuid
          }
          projection OrderCounts @ 1 from orders.Order @ 1 as o group by o.status {
            status <- o.status
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            status: string
            customerId: uuid
          }
          projection OrderCounts @ 1 from orders.Order @ 1 as o group by o.customerId {
            status <- o.status
          }
        }
        """,
        name="OrderCounts",
    )

    changes = _compare_storage(old, new)

    assert any(c.kind == "group_by_changed" and c.breaking for c in changes)


def test_join_added_is_breaking():
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerId: uuid
          }
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            name: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerId: uuid
          }
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            name: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o
            join orders.Customer @ 1 as c on o.customerId == c.customerId {
            orderId <- o.orderId
          }
        }
        """,
    )

    changes = _compare_storage(old, new)

    assert any(c.kind == "join_added" and c.breaking and c.field_name == "c" for c in changes)


def test_join_removed_is_breaking():
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerId: uuid
          }
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            name: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o
            join orders.Customer @ 1 as c on o.customerId == c.customerId {
            orderId <- o.orderId
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerId: uuid
          }
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            name: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
          }
        }
        """,
    )

    changes = _compare_storage(old, new)

    assert any(c.kind == "join_removed" and c.breaking and c.field_name == "c" for c in changes)


def test_join_predicate_changed_is_breaking():
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerId: uuid
            altCustomerId: uuid
          }
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            name: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o
            join orders.Customer @ 1 as c on o.customerId == c.customerId {
            orderId <- o.orderId
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerId: uuid
            altCustomerId: uuid
          }
          entity Customer @ 1 (additive) {
            @key customerId: uuid
            name: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o
            join orders.Customer @ 1 as c on o.altCustomerId == c.customerId {
            orderId <- o.orderId
          }
        }
        """,
    )

    changes = _compare_storage(old, new)

    assert any(c.kind == "join_changed" and c.breaking and c.field_name == "c" for c in changes)


def test_unchanged_storage_produces_no_changes():
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
          }
        }
        """,
    )

    assert _compare_storage(old, new) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cli && uv run pytest tests/test_projection_compatibility.py -k storage -v`
Expected: FAIL with `ImportError: cannot import name '_compare_storage'`

- [ ] **Step 3: Write the implementation**

Add to `cli/src/modelable/compat/diff.py`, after `_compare_wire`:

```python
def _compare_storage(old: ProjectionVersion, new: ProjectionVersion) -> list[ProjectionChange]:
    changes: list[ProjectionChange] = []

    if old.where != new.where:
        changes.append(
            ProjectionChange(
                dimension="storage",
                kind="where_changed",
                breaking=True,
                message=f"where clause changed: {old.where!r} -> {new.where!r}",
            )
        )

    if old.group_by != new.group_by:
        changes.append(
            ProjectionChange(
                dimension="storage",
                kind="group_by_changed",
                breaking=True,
                message=f"group by changed: {old.group_by!r} -> {new.group_by!r}",
            )
        )

    old_joins = {join.alias: join for join in old.joins}
    new_joins = {join.alias: join for join in new.joins}

    for alias in sorted(set(old_joins) - set(new_joins)):
        changes.append(
            ProjectionChange(
                dimension="storage",
                kind="join_removed",
                breaking=True,
                field_name=alias,
                message=f"join '{alias}' was removed",
            )
        )
    for alias in sorted(set(new_joins) - set(old_joins)):
        changes.append(
            ProjectionChange(
                dimension="storage",
                kind="join_added",
                breaking=True,
                field_name=alias,
                message=f"join '{alias}' was added",
            )
        )
    for alias in sorted(set(old_joins) & set(new_joins)):
        old_join = old_joins[alias]
        new_join = new_joins[alias]
        if (old_join.cardinality, old_join.join_kind, old_join.on) != (
            new_join.cardinality,
            new_join.join_kind,
            new_join.on,
        ):
            changes.append(
                ProjectionChange(
                    dimension="storage",
                    kind="join_changed",
                    breaking=True,
                    field_name=alias,
                    message=f"join '{alias}' cardinality/kind/predicate changed",
                )
            )

    return changes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cli && uv run pytest tests/test_projection_compatibility.py -v`
Expected: PASS (all tests so far)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd cli && uv run pytest -q`
Expected: all previously-passing tests still pass

- [ ] **Step 6: Commit**

```bash
git add cli/src/modelable/compat/diff.py cli/tests/test_projection_compatibility.py
git commit -m "feat: add projection storage-dimension compatibility comparison

where/group_by/join changes are all row-shape-affecting, so unlike the
shape dimension's asymmetric add/remove rule, every storage change is
classified breaking regardless of direction."
```

---

### Task 7: Top-level `compare_projection_versions`

**Files:**
- Modify: `cli/src/modelable/compat/diff.py`
- Modify: `cli/tests/test_projection_compatibility.py`

**Interfaces:**
- Consumes: `_compare_shape`, `_compare_lineage`, `_compare_governance`, `_compare_wire`, `_compare_storage` (Tasks 2–6).
- Produces: `compare_projection_versions(mdl: MdlFile, old: ProjectionVersion, new: ProjectionVersion) -> list[ProjectionChange]` — used by Task 8's `check_projection_version_compatibility`.

- [ ] **Step 1: Write the failing test**

Append to `cli/tests/test_projection_compatibility.py`:

```python
from modelable.compat.diff import compare_projection_versions


def test_compare_projection_versions_combines_all_dimensions():
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            status: string
            note?: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o where o.status == "open" {
            orderId <- o.orderId
            status <- o.status
            note <- o.note
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            status: string
            note: string
            extra: string
          }
          projection OrderView @ 1 from orders.Order @ 1 as o where o.status == "closed" {
            orderId <- o.orderId
            status <- o.status
            note <- o.note
            extra <- o.extra
          }
        }
        """,
    )

    changes = compare_projection_versions(mdl, old, new)
    kinds = {c.kind for c in changes}

    assert "field_added" in kinds  # extra
    assert "optionality_changed" in kinds  # note optional -> required
    assert "where_changed" in kinds
    assert any(c.dimension == "shape" for c in changes)
    assert any(c.dimension == "storage" for c in changes)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cli && uv run pytest tests/test_projection_compatibility.py::test_compare_projection_versions_combines_all_dimensions -v`
Expected: FAIL with `ImportError: cannot import name 'compare_projection_versions'`

- [ ] **Step 3: Write the implementation**

Add to `cli/src/modelable/compat/diff.py`, after `_compare_storage`:

```python
def compare_projection_versions(
    mdl: MdlFile, old: ProjectionVersion, new: ProjectionVersion
) -> list[ProjectionChange]:
    """Compare two published projection versions across the shape, lineage,
    governance, wire, and storage dimensions.

    Source-version comparison lives in compat/checker.py instead of here,
    since it delegates to check_model_version_compatibility() and this
    module must not import from checker.py (checker.py already imports
    from this module; the reverse would be circular).
    """
    changes: list[ProjectionChange] = []
    changes.extend(_compare_shape(mdl, old, new))
    changes.extend(_compare_lineage(old, new))
    changes.extend(_compare_governance(old, new))
    changes.extend(_compare_wire(old, new))
    changes.extend(_compare_storage(old, new))
    return changes
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cli && uv run pytest tests/test_projection_compatibility.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd cli && uv run pytest -q`
Expected: all previously-passing tests still pass

- [ ] **Step 6: Commit**

```bash
git add cli/src/modelable/compat/diff.py cli/tests/test_projection_compatibility.py
git commit -m "feat: add compare_projection_versions combining all 5 diff.py dimensions"
```

---

### Task 8: `ProjectionCompatibilityReport` + source-version delegation

**Files:**
- Modify: `cli/src/modelable/compat/checker.py`
- Modify: `cli/tests/test_projection_compatibility.py`

**Interfaces:**
- Consumes: `compare_projection_versions` (Task 7), `check_model_version_compatibility` (existing, same file).
- Produces: `ProjectionCompatibilityReport` dataclass (`domain_name: str`, `projection_name: str`, `from_version: int`, `to_version: int`, `status: str`, `findings: list[str]`, `changes: list[ProjectionChange]`); `check_projection_version_compatibility(mdl: MdlFile, domain_name: str, projection_name: str, from_version: int, to_version: int) -> ProjectionCompatibilityReport` — used by Task 9's `commands/diff.py`.

- [ ] **Step 1: Write the failing tests**

Append to `cli/tests/test_projection_compatibility.py`:

```python
from modelable.compat.checker import ProjectionCompatibilityReport, check_projection_version_compatibility


def test_check_projection_version_compatibility_reports_breaking_status():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
        status: string
      }
      projection OrderView @ 1 from orders.Order @ 1 as o {
        orderId <- o.orderId
        status <- o.status
      }
      projection OrderView @ 2 from orders.Order @ 1 as o {
        orderId <- o.orderId
      }
    }
    """)

    report = check_projection_version_compatibility(mdl, "orders", "OrderView", 1, 2)

    assert isinstance(report, ProjectionCompatibilityReport)
    assert report.status == "breaking"
    assert any("field_removed" in finding for finding in report.findings)


def test_check_projection_version_compatibility_reports_compatible_status():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
        status: string
      }
      projection OrderView @ 1 from orders.Order @ 1 as o {
        orderId <- o.orderId
      }
      projection OrderView @ 2 from orders.Order @ 1 as o {
        orderId <- o.orderId
        status <- o.status
      }
    }
    """)

    report = check_projection_version_compatibility(mdl, "orders", "OrderView", 1, 2)

    assert report.status == "compatible"


def test_check_projection_version_compatibility_raises_for_unknown_version():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
      }
      projection OrderView @ 1 from orders.Order @ 1 as o {
        orderId <- o.orderId
      }
    }
    """)

    import pytest

    with pytest.raises(LookupError):
        check_projection_version_compatibility(mdl, "orders", "OrderView", 1, 2)


def test_source_version_dimension_mirrors_model_compat_status():
    from modelable.compat.checker import check_model_version_compatibility

    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
        status: string
      }
      entity Order @ 2 (additive) {
        @key orderId: uuid
      }
      projection OrderView @ 1 from orders.Order @ 1 as o {
        orderId <- o.orderId
      }
      projection OrderView @ 2 from orders.Order @ 2 as o {
        orderId <- o.orderId
      }
    }
    """)

    model_report = check_model_version_compatibility(mdl, "orders", "Order", 1, 2)
    projection_report = check_projection_version_compatibility(mdl, "orders", "OrderView", 1, 2)

    source_version_changes = [c for c in projection_report.changes if c.dimension == "source_version"]
    assert len(source_version_changes) == 1
    assert source_version_changes[0].breaking == (model_report.status == "breaking")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cli && uv run pytest tests/test_projection_compatibility.py -k check_projection_version -v`
Expected: FAIL with `ImportError: cannot import name 'ProjectionCompatibilityReport'`

- [ ] **Step 3: Write the implementation**

In `cli/src/modelable/compat/checker.py`, update the imports:

```python
from modelable.compat.diff import (
    FieldChange,
    ProjectionChange,
    compare_index_decls,
    compare_model_versions,
    compare_projection_versions,
    is_optionality_breaking,
)
from modelable.dependency_graph import build_projection_dependencies, resolve_projection_aliases
from modelable.parser.ir import IndexDecl, MdlFile, ModelVersion, ProjectionVersion
from modelable.registry.resolver import find_dependents
```

Add after the existing `CompatibilityReport`/`ProjectionImpact` dataclasses:

```python
@dataclass(frozen=True)
class ProjectionCompatibilityReport:
    domain_name: str
    projection_name: str
    from_version: int
    to_version: int
    status: str
    findings: list[str] = field(default_factory=list)
    changes: list[ProjectionChange] = field(default_factory=list)
```

Add after `check_model_version_compatibility`:

```python
def check_projection_version_compatibility(
    mdl: MdlFile,
    domain_name: str,
    projection_name: str,
    from_version: int,
    to_version: int,
) -> ProjectionCompatibilityReport:
    """Compare two published versions of the same projection and classify the change set."""
    old_version = _find_projection_version(mdl, domain_name, projection_name, from_version)
    new_version = _find_projection_version(mdl, domain_name, projection_name, to_version)

    changes = compare_projection_versions(mdl, old_version, new_version)
    changes.extend(_compare_source_version(mdl, old_version, new_version))

    findings = [_format_projection_finding(change) for change in changes]
    status = "breaking" if any(change.breaking for change in changes) else "compatible"
    return ProjectionCompatibilityReport(
        domain_name=domain_name,
        projection_name=projection_name,
        from_version=from_version,
        to_version=to_version,
        status=status,
        findings=findings,
        changes=changes,
    )


def _compare_source_version(
    mdl: MdlFile,
    old: ProjectionVersion,
    new: ProjectionVersion,
) -> list[ProjectionChange]:
    changes: list[ProjectionChange] = []
    old_aliases = resolve_projection_aliases(old, mdl)
    new_aliases = resolve_projection_aliases(new, mdl)

    for alias in sorted(set(old_aliases) & set(new_aliases)):
        old_resolved = old_aliases[alias]
        new_resolved = new_aliases[alias]
        if old_resolved.model_name != new_resolved.model_name:
            continue  # different source entirely; the shape/lineage dimensions already cover this
        if old_resolved.version.version == new_resolved.version.version:
            continue

        model_report = check_model_version_compatibility(
            mdl,
            old_resolved.domain_name,
            old_resolved.model_name,
            old_resolved.version.version,
            new_resolved.version.version,
        )
        changes.append(
            ProjectionChange(
                dimension="source_version",
                kind="source_version_changed",
                breaking=model_report.status == "breaking",
                field_name=alias,
                message=(
                    f"source '{alias}' moved from {old_resolved.model_name}@{old_resolved.version.version} "
                    f"to {new_resolved.version.version} ({model_report.status})"
                ),
            )
        )

    return changes


def _find_projection_version(
    mdl: MdlFile,
    domain_name: str,
    projection_name: str,
    version: int,
) -> ProjectionVersion:
    for domain in mdl.domains:
        if domain.name != domain_name:
            continue
        versions = domain.projections.get(projection_name, [])
        for candidate in versions:
            if candidate.version == version:
                return candidate
        break
    raise LookupError(f"unknown projection version {domain_name}.{projection_name}@{version}")


def _format_projection_finding(change: ProjectionChange) -> str:
    subject = change.field_name or "-"
    return f"{change.kind} {subject} ({change.dimension}): {change.message}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cli && uv run pytest tests/test_projection_compatibility.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd cli && uv run pytest -q`
Expected: all previously-passing tests still pass

- [ ] **Step 6: Commit**

```bash
git add cli/src/modelable/compat/checker.py cli/tests/test_projection_compatibility.py
git commit -m "feat: add check_projection_version_compatibility with source-version delegation

Source-version comparison delegates entirely to
check_model_version_compatibility for the resolved model pair, so
there is exactly one implementation of 'is this model version bump
breaking' in the codebase, not two."
```

---

### Task 9: Wire into `modelable diff`

**Files:**
- Modify: `cli/src/modelable/commands/diff.py`
- Modify: `cli/tests/test_cli.py`

**Interfaces:**
- Consumes: `check_projection_version_compatibility` (Task 8), `ProjectionVersion` (existing IR type), `ResolvedModelRef` (existing).

- [ ] **Step 1: Write the failing tests**

Append to `cli/tests/test_cli.py`:

```python
def test_diff_supports_projection_refs(tmp_path):
    mdl = tmp_path / "orders.mdl"
    mdl.write_text(
        """
domain orders {
  owner: "test-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: string
  }
  projection OrderView @ 1 from orders.Order @ 1 as o {
    orderId <- o.orderId
    status <- o.status
  }
  projection OrderView @ 2 from orders.Order @ 1 as o {
    orderId <- o.orderId
  }
}
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        ["diff", "orders.OrderView@1", "orders.OrderView@2", "--path", str(tmp_path)],
    )

    assert result.exit_code == 1, result.output
    assert "breaking" in result.output.lower()
    assert "field_removed" in result.output.lower()


def test_diff_reports_compatible_projection_change(tmp_path):
    mdl = tmp_path / "orders.mdl"
    mdl.write_text(
        """
domain orders {
  owner: "test-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: string
  }
  projection OrderView @ 1 from orders.Order @ 1 as o {
    orderId <- o.orderId
  }
  projection OrderView @ 2 from orders.Order @ 1 as o {
    orderId <- o.orderId
    status <- o.status
  }
}
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        ["diff", "orders.OrderView@1", "orders.OrderView@2", "--path", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    assert "status: compatible" in result.output.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cli && uv run pytest tests/test_cli.py -k projection_refs -v`
Expected: FAIL — `test_diff_supports_projection_refs` fails because `run_diff` raises `LookupError: unknown model version` (caught and re-raised as `click.ClickException`), producing exit code 1 but NOT the expected "field_removed" output — the assertion `"field_removed" in result.output.lower()` fails.

- [ ] **Step 3: Write the implementation**

Replace the full contents of `cli/src/modelable/commands/diff.py`:

```python
from __future__ import annotations

from pathlib import Path

import click

from modelable.commands.common import console
from modelable.compat.checker import analyze_impact, check_model_version_compatibility, check_projection_version_compatibility
from modelable.compiler.workspace import Workspace, load_workspace
from modelable.llm.context import parse_model_ref_version_spec
from modelable.parser.ir import ProjectionVersion
from modelable.registry.resolver import ResolvedModelRef, find_dependents, resolve_model_ref


def register_diff_commands(cli_group: click.Group) -> None:
    cli_group.add_command(diff)


def run_diff(from_ref: str, to_ref: str, path: Path) -> None:
    """Compare two published model or projection versions and print the compatibility report."""
    workspace = load_workspace(path)
    try:
        from_domain, from_name, from_version_spec = parse_model_ref_version_spec(from_ref)
        to_domain, to_name, to_version_spec = parse_model_ref_version_spec(to_ref)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if from_domain != to_domain or from_name != to_name:
        raise click.ClickException("diff requires refs from the same domain and model")

    try:
        from_resolved = resolve_model_ref(workspace.mdl, f"{from_domain}.{from_name}", from_version_spec)
        to_resolved = resolve_model_ref(workspace.mdl, f"{to_domain}.{to_name}", to_version_spec)
    except LookupError as exc:
        raise click.ClickException(str(exc)) from exc

    if isinstance(from_resolved.version, ProjectionVersion):
        _run_projection_diff(workspace, from_ref, to_ref, from_resolved, to_resolved)
        return

    _run_model_diff(workspace, from_ref, to_ref, from_resolved, to_resolved)


def _run_model_diff(
    workspace: Workspace,
    from_ref: str,
    to_ref: str,
    from_model: ResolvedModelRef,
    to_model: ResolvedModelRef,
) -> None:
    try:
        report = check_model_version_compatibility(
            workspace.mdl,
            from_model.domain_name,
            from_model.model_name,
            from_model.version.version,
            to_model.version.version,
        )
    except LookupError as exc:
        raise click.ClickException(str(exc)) from exc

    console.print(f"{from_ref} -> {to_ref}")
    console.print(f"status: {report.status}")
    if report.findings:
        for finding in report.findings:
            console.print(f"- {finding}")
    else:
        console.print("- no changes")

    dependents = find_dependents(
        workspace.mdl, from_model.domain_name, from_model.model_name, from_model.version.version
    )
    if dependents:
        impacts = []
        for dep in dependents:
            impact = analyze_impact(workspace.mdl, report, dep)
            if impact.status != "compatible":
                impacts.append(impact)

        if impacts:
            console.print("\nImpacted Projections:")
            for impact in impacts:
                status_tag = f"[{impact.status.upper()}]"
                color = "red" if impact.status == "broken" else "yellow"
                line = (
                    f"- [{color}]{status_tag}[/{color}] {impact.domain_name}.{impact.projection_name}@{impact.version}"
                )
                if impact.reason:
                    line += f" ({impact.reason})"
                console.print(line)

    if report.status == "breaking":
        raise click.exceptions.Exit(1)


def _run_projection_diff(
    workspace: Workspace,
    from_ref: str,
    to_ref: str,
    from_projection: ResolvedModelRef,
    to_projection: ResolvedModelRef,
) -> None:
    # Downstream-impact analysis (find_dependents/analyze_impact) answers
    # "who depends on this model changing" and is not extended to
    # projection-of-projection dependents here — that's a distinct concern
    # from "did this projection's own definition change compatibly", and is
    # out of scope for Slice C1 (see the design doc's "Scope" section).
    try:
        report = check_projection_version_compatibility(
            workspace.mdl,
            from_projection.domain_name,
            from_projection.model_name,
            from_projection.version.version,
            to_projection.version.version,
        )
    except LookupError as exc:
        raise click.ClickException(str(exc)) from exc

    console.print(f"{from_ref} -> {to_ref}")
    console.print(f"status: {report.status}")
    if report.findings:
        for finding in report.findings:
            console.print(f"- {finding}")
    else:
        console.print("- no changes")

    if report.status == "breaking":
        raise click.exceptions.Exit(1)


@click.command()
@click.argument("from_ref")
@click.argument("to_ref")
@click.option("--path", "path", type=click.Path(exists=True, path_type=Path), required=True)
def diff(from_ref: str, to_ref: str, path: Path) -> None:
    """Compare two published model or projection versions."""
    run_diff(from_ref, to_ref, path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cli && uv run pytest tests/test_cli.py -k "diff" -v`
Expected: PASS (all `test_diff_*` tests, including the 2 new ones and the pre-existing model-diff ones — this proves no regression on the model path)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd cli && uv run pytest -q`
Expected: all previously-passing tests still pass

- [ ] **Step 6: Commit**

```bash
git add cli/src/modelable/commands/diff.py cli/tests/test_cli.py
git commit -m "feat: support projection refs in modelable diff

resolve_model_ref already resolved both models and projections
uniformly (ResolvedModelRef.version: ModelVersion | ProjectionVersion)
— run_diff just never branched on it. modelable diff domain.Proj@1
domain.Proj@2 previously raised 'unknown model version'; now works."
```

---

### Task 10: Capability manifest entry for event-operation-coverage gap

**Files:**
- Modify: `cli/src/modelable/capabilities.py`
- Modify: `cli/tests/test_capabilities.py`

- [ ] **Step 1: Write the failing test**

Append to `cli/tests/test_capabilities.py`:

```python
def test_manifest_deferred_features_include_projection_event_operation_coverage():
    manifest = build_capability_manifest()

    manifest_names = {capability.name for capability in manifest.deferred_features}
    assert "projection-event-operation-coverage-compatibility" in manifest_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cli && uv run pytest tests/test_capabilities.py::test_manifest_deferred_features_include_projection_event_operation_coverage -v`
Expected: FAIL — `AssertionError` (name not in manifest)

- [ ] **Step 3: Write the implementation**

In `cli/src/modelable/capabilities.py`, add to the end of the `_DEFERRED_FEATURES` tuple (inside the closing `)`, after the `binding-opaque-content` entry added in Slice B3):

```python
    Capability(
        name="projection-event-operation-coverage-compatibility",
        category="deferred_feature",
        status=CapabilityStatus.deferred,
        description="Comparing event operation coverage between two projection versions",
        notes=(
            "AutoProjectionTarget.operations only exists on the pre-expansion "
            "`auto projections {}` declaration and is discarded during "
            "expansion; it is not present on the resulting ProjectionVersion "
            "to diff. See Slice C1 in docs/correction-and-capability-plan.md."
        ),
    ),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cli && uv run pytest tests/test_capabilities.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd cli && uv run pytest -q`
Expected: all previously-passing tests still pass

- [ ] **Step 6: Commit**

```bash
git add cli/src/modelable/capabilities.py cli/tests/test_capabilities.py
git commit -m "docs: record event-operation-coverage as a deferred projection-compat feature"
```

---

### Task 11: Docs + full regression sweep

**Files:**
- Modify: `docs/cli-reference.md`
- Modify: `docs/correction-and-capability-plan.md`
- Modify: `cli/mypy-baseline.txt` (only if the ratchet check finds line-number shifts or genuinely new pre-existing-pattern errors — see Step 3)

- [ ] **Step 1: Update `docs/cli-reference.md`**

In `docs/cli-reference.md`, change the section header and description at (originally) line 178:

Old:
```markdown
### 5.4 `diff` — Compare two model versions

```text
modelable diff REF_A REF_B --path PATH
```

Compares two published model versions field by field and reports additions, removals, renames, nullability changes, identity changes, enum changes, and type changes. Intended to support compatibility review before publishing a new version.
If the comparison is breaking, the command prints the report and exits with code `1`.

**Arguments:**

| Argument | Description |
|:---------|:------------|
| `REF_A` | First model reference (`domain.ModelName@version`) |
| `REF_B` | Second model reference (`domain.ModelName@version`) |
```

New:
```markdown
### 5.4 `diff` — Compare two model or projection versions

```text
modelable diff REF_A REF_B --path PATH
```

Compares two published versions of the same model or the same projection and reports a compatibility finding per change. For models: field additions, removals, renames, nullability changes, identity changes, enum changes, and type changes. For projections: field shape changes (as for models), lineage changes (remapped source fields, changed computed expressions — always reported, never breaking on their own), access/classification/`@pii` changes, `@wire` hint changes, `where`/`group by`/join changes, and source-version changes (delegated to the same model-compatibility check). Intended to support compatibility review before publishing a new version.
If the comparison is breaking, the command prints the report and exits with code `1`.

**Arguments:**

| Argument | Description |
|:---------|:------------|
| `REF_A` | First model or projection reference (`domain.Name@version`) |
| `REF_B` | Second model or projection reference (`domain.Name@version`) |
```

- [ ] **Step 2: Update `docs/correction-and-capability-plan.md`**

Find the `## Slice C1 — projection-to-projection compatibility` section (search for that heading). After its `### Acceptance criteria` subsection (and its bullet list), add:

```markdown

### Outcome (2026-08-05)

Implemented as designed in
[the C1 design spec](superpowers/specs/2026-08-05-projection-compatibility-design.md):
`compare_projection_versions()`/`check_projection_version_compatibility()`
in `compat/diff.py`/`compat/checker.py`, wired into the existing
`modelable diff` command (`ResolvedModelRef.version` already resolved both
models and projections uniformly — `run_diff` just never branched on it).
Per-dimension tagging with a single overall rollup status. Source-version
comparison delegates entirely to `check_model_version_compatibility()` —
no independent "is this breaking" logic for model version bumps.
`materialisation` and `event operation coverage` are not populated (both
genuine IR gaps, not oversights — see the design doc and the
`projection-event-operation-coverage-compatibility` capability manifest
entry).
```

- [ ] **Step 3: Full regression sweep**

Run each of these from the `cli/` directory and confirm the stated result. If mypy reports new errors, use the same reconciliation approach as prior slices: compare by `(file, message)` ignoring line number against `cli/mypy-baseline.txt`, update only the entries that shifted or are genuinely new from this plan's changes, and do not touch unrelated pre-existing baseline entries.

```bash
cd cli
uv run pytest -q
uv run ruff format --check .
uv run ruff check .
rm -rf .mypy_cache
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short -q --cov=modelable --cov-report=term-missing --cov-report=xml
uv run python ../.github/scripts/check_coverage_ratchet.py --coverage-xml coverage.xml --baseline coverage-baseline.txt
```

Expected: pytest passes with the full new test count; ruff clean; mypy baseline ratchet passes (0 new errors beyond baseline, after any needed line-number reconciliation); coverage ratchet passes.

Then from the repository root:

```bash
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
rm -rf site
```

Expected: exit 0, no warnings.

- [ ] **Step 4: Commit**

```bash
git add docs/cli-reference.md docs/correction-and-capability-plan.md cli/mypy-baseline.txt
git commit -m "docs: document projection support in modelable diff and record C1 outcome"
```

(Omit `cli/mypy-baseline.txt` from the `git add` if Step 3 required no changes to it.)

---

## Self-Review Notes

- **Spec coverage:** every classification-rule table row from the spec has a corresponding test in Tasks 2–6; the two "not populated" dimensions are handled by Task 10 (capability manifest) and explicit code comments (Task 2's `ProjectionChange.dimension` type comment includes `"materialisation"` even though nothing produces it yet, matching the spec).
- **Circular import:** verified `compat/diff.py` must not import from `compat/checker.py` — Task 8 places `_compare_source_version` in `checker.py`, not `diff.py`, specifically because it needs `check_model_version_compatibility`.
- **Type consistency:** `ProjectionChange`, `resolve_projection_field_type_and_optionality`, `compare_projection_versions`, and `check_projection_version_compatibility` are used with identical signatures across every task that consumes them — Task 1 defines the resolver's exact return shape `tuple[FieldType | None, bool | None]`, and every later consumer (`_compare_shape`) unpacks it the same way.
- **CLI regression protection:** Task 9's test run explicitly includes the full `-k "diff"` selection, not just the 2 new tests, so any accidental change to the model-diff path's existing behavior is caught immediately.
