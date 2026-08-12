# `ref<>` Version Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `ref<Domain.Model>` type references to carry version syntax (`ref<Domain.Model @ 2>`, `@ >=2 <3`, `@ 2#hash>`), resolve them through the canonical resolver, validate them, participate in signatures/compat, and consolidate the 3 places that already reimplement "unversioned ref → latest version" onto one function.

**Architecture:** Grammar/IR changes are purely additive (`RefType.version: VersionSpec | None = None`). One new canonical resolver function (`resolve_ref_type`) becomes the single place "unversioned → latest" is decided; every existing ad hoc implementation of that rule (typescript.py's codegen, definition.py's and hover.py's independent `max()` calls) is repointed at it instead of gaining a fourth copy.

**Tech Stack:** Python 3.14, Lark (Earley), Pydantic v2 IR models, pytest.

**Spec:** [docs/superpowers/specs/2026-08-05-ref-version-resolution-design.md](../../specs/archived/2026-08-05-ref-version-resolution-design.md)

## Global Constraints

- Grammar reuses the existing `version_spec` rule (`version_exact | version_pinned | version_range | version_min`) — never the separate `version_expr`/`VERSION_RANGE` mini-grammar used only by `import_domain_stmt`.
- `RefType.version: VersionSpec | None = None` — `None` means unversioned/legacy, resolves via `VersionMin(min_inclusive=1)` ("latest matching").
- Compat classification: a `ref<>` field's **target** changing is breaking; its **version alone** changing (target unchanged) is never breaking. This is a deliberately simpler rule than C1's `source_version` dimension (no delegation to `check_model_version_compatibility`) — confirmed with the user, not an oversight.
- Only `emitters/typescript.py` gains version-aware codegen (it's the only emitter that already resolves `ref<>` targets). No other emitter changes.
- `language/references.py` gets no `ref<>` support in this plan — out of scope, not a regression.
- `dependency_graph.py` does not gain field-level `ref<>` tracking — out of scope.
- Work happens on branch `c2-ref-version-resolution` (already created and checked out from `main`, with the design-spec commit `193e93a` already on it). Do not create a new branch.

---

### Task 1: Grammar, IR, and transformer support for versioned `ref<>`

**Files:**
- Modify: `cli/src/modelable/grammar/modelable.lark:121` (`ref_type` rule)
- Modify: `cli/src/modelable/parser/ir.py:201-203` (`RefType`)
- Modify: `cli/src/modelable/parser/transformer.py:560-561` (`ref_type` method)
- Test: `cli/tests/test_grammar.py` (append)

**Interfaces:**
- Produces: `RefType(kind="ref", target: str, version: VersionSpec | None = None)` — used by every later task.

- [ ] **Step 1: Write the failing tests**

Append to `cli/tests/test_grammar.py`:

```python
def test_ref_type_without_version_has_none_version():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
        customerRef: ref<customer.Customer>
      }
    }
    """)
    field = mdl.domains[0].models["Order"][0].fields[1]
    assert field.type.kind == "ref"
    assert field.type.target == "customer.Customer"
    assert field.type.version is None


def test_ref_type_with_exact_version():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
        customerRef: ref<customer.Customer @ 2>
      }
    }
    """)
    field = mdl.domains[0].models["Order"][0].fields[1]
    assert field.type.version.kind == "exact"
    assert field.type.version.version == 2


def test_ref_type_with_pinned_version():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
        customerRef: ref<customer.Customer @ 2#deadbeef>
      }
    }
    """)
    field = mdl.domains[0].models["Order"][0].fields[1]
    assert field.type.version.kind == "pinned"
    assert field.type.version.version == 2
    assert field.type.version.content_hash == "deadbeef"


def test_ref_type_with_version_range():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
        customerRef: ref<customer.Customer @ >=2 <3>
      }
    }
    """)
    field = mdl.domains[0].models["Order"][0].fields[1]
    assert field.type.version.kind == "range"
    assert field.type.version.min_inclusive == 2
    assert field.type.version.max_exclusive == 3


def test_ref_type_with_version_min():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
        customerRef: ref<customer.Customer @ >=2>
      }
    }
    """)
    field = mdl.domains[0].models["Order"][0].fields[1]
    assert field.type.version.kind == "min"
    assert field.type.version.min_inclusive == 2


def test_ref_type_with_version_nested_in_array():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
        items: array<ref<catalog.Item @ >=1>>
      }
    }
    """)
    field = mdl.domains[0].models["Order"][0].fields[1]
    assert field.type.kind == "array"
    assert field.type.item.kind == "ref"
    assert field.type.item.version.kind == "min"
    assert field.type.item.version.min_inclusive == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cli && uv run pytest tests/test_grammar.py -k ref_type -v`
Expected: FAIL — `test_ref_type_without_version_has_none_version` fails with `AttributeError: 'RefType' object has no attribute 'version'`; the other 5 fail with a Lark parse error (`UnexpectedCharacters` or similar) since the grammar doesn't accept `@` inside `ref<>` yet.

- [ ] **Step 3: Write the implementation**

In `cli/src/modelable/grammar/modelable.lark`, change line 121:

```
ref_type: "ref" "<" dotted_ref ("@" version_spec)? ">"
```

In `cli/src/modelable/parser/ir.py`, change lines 201-203:

```python
class RefType(BaseModel):
    kind: Literal["ref"] = "ref"
    target: str
    version: VersionSpec | None = None
```

Note: `VersionSpec` is defined later in the same file (line 342) than `RefType` (line 201) — Pydantic v2 with `from __future__ import annotations` (already at the top of this file) handles forward references fine here since it's all one module; no import reordering needed.

In `cli/src/modelable/parser/transformer.py`, change lines 560-561:

```python
    def ref_type(self, items: list[object]) -> RefType:
        version = items[1] if len(items) > 1 else None
        return RefType(target=str(items[0]), version=version)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cli && uv run pytest tests/test_grammar.py -k ref_type -v`
Expected: PASS (all 6 tests)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd cli && uv run pytest -q`
Expected: all previously-passing tests still pass (this is a purely additive grammar/IR change — no existing `ref<>` usage anywhere in the test suite or samples uses the new syntax, so nothing should break)

- [ ] **Step 6: Commit**

```bash
git add cli/src/modelable/grammar/modelable.lark cli/src/modelable/parser/ir.py cli/src/modelable/parser/transformer.py cli/tests/test_grammar.py
git commit -m "feat: add version syntax to ref<> type references

ref<Domain.Model @ 2>, @ >=2 <3, and @ 2#hash now parse, reusing the
same version_spec grammar rule source_clause/join_prefix already use.
Unversioned ref<Domain.Model> still parses (version=None)."
```

---

### Task 2: Canonical `ref<>` resolver

**Files:**
- Modify: `cli/src/modelable/registry/resolver.py`
- Test: `cli/tests/test_ref_resolution.py` (new)

**Interfaces:**
- Consumes: `RefType` (Task 1), existing `resolve_model_ref`, `ResolvedModelRef`, `VersionMin`.
- Produces: `resolve_ref_type(field_type: RefType, mdl: MdlFile) -> ResolvedModelRef` — used by Tasks 3, 4, 6, 7, 8.

- [ ] **Step 1: Write the failing tests**

Create `cli/tests/test_ref_resolution.py`:

```python
import pytest

from modelable.parser.ir import VersionExact
from modelable.parser.parse import parse_text_to_ir
from modelable.registry.resolver import resolve_ref_type

DOMAIN = """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
  entity Customer @ 2 (additive) {
    @key customerId: uuid
    name: string
  }
}
"""


def _ref_field(mdl_text: str):
    mdl = parse_text_to_ir(mdl_text)
    return mdl, mdl.domains[0].models["Order"][0].fields[1].type


def test_unversioned_ref_resolves_to_latest():
    mdl, field_type = _ref_field(
        DOMAIN
        + """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerRef: ref<customer.Customer>
          }
        }
        """
    )

    resolved = resolve_ref_type(field_type, mdl)

    assert resolved.domain_name == "customer"
    assert resolved.model_name == "Customer"
    assert resolved.version.version == 2


def test_exact_versioned_ref_resolves_to_that_version():
    mdl, field_type = _ref_field(
        DOMAIN
        + """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerRef: ref<customer.Customer @ 1>
          }
        }
        """
    )

    resolved = resolve_ref_type(field_type, mdl)

    assert resolved.version.version == 1


def test_unresolvable_target_raises_lookup_error():
    mdl, field_type = _ref_field(
        DOMAIN
        + """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerRef: ref<customer.MissingEntity>
          }
        }
        """
    )

    with pytest.raises(LookupError):
        resolve_ref_type(field_type, mdl)


def test_unresolvable_version_raises_lookup_error():
    mdl, field_type = _ref_field(
        DOMAIN
        + """
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerRef: ref<customer.Customer @ 99>
          }
        }
        """
    )

    with pytest.raises(LookupError):
        resolve_ref_type(field_type, mdl)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cli && uv run pytest tests/test_ref_resolution.py -v`
Expected: FAIL with `ImportError: cannot import name 'resolve_ref_type' from 'modelable.registry.resolver'`

- [ ] **Step 3: Write the implementation**

In `cli/src/modelable/registry/resolver.py`, add `RefType` to the existing import block (lines 5-15):

```python
from modelable.parser.ir import (
    MdlFile,
    ModelVersion,
    ProjectionVersion,
    RefType,
    SemanticTypeDecl,
    VersionExact,
    VersionMin,
    VersionPinned,
    VersionRange,
    VersionSpec,
)
```

Add this function immediately after `resolve_model_ref` (after line 62, before `resolved_version_spec` at line 65):

```python
def resolve_ref_type(field_type: RefType, mdl: MdlFile) -> ResolvedModelRef:
    """Resolve a ref<> field's target to a concrete model version.

    Unversioned ref<Domain.Model> resolves via VersionMin(1) ("latest
    matching") — the documented interpretation for existing files, and the
    same rule already implicit in emitters/typescript.py's codegen and the
    LSP's definition/hover "unversioned ref" handling.
    """
    version_spec = field_type.version if field_type.version is not None else VersionMin(min_inclusive=1)
    return resolve_model_ref(mdl, field_type.target, version_spec)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cli && uv run pytest tests/test_ref_resolution.py -v`
Expected: PASS (all 4 tests)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd cli && uv run pytest -q`
Expected: all previously-passing tests still pass

- [ ] **Step 6: Commit**

```bash
git add cli/src/modelable/registry/resolver.py cli/tests/test_ref_resolution.py
git commit -m "feat: add resolve_ref_type as the canonical ref<> resolver

Unversioned ref<> resolves via VersionMin(1) — this is not a new rule,
it's the exact behavior emitters/typescript.py and the LSP's
definition/hover already independently reimplement; this is the one
place all of them will be repointed at in later tasks."
```

---

### Task 3: Semantic validation for `ref<>` targets

**Files:**
- Modify: `cli/src/modelable/validation/semantic.py`
- Test: `cli/tests/test_semantic.py` (append)

**Interfaces:**
- Consumes: `resolve_ref_type` (Task 2).
- Produces: SEM error for an unresolvable `ref<>`; new `REF` warning diagnostic for an unversioned `ref<>`, naming the concrete resolved version.

- [ ] **Step 1: Write the failing tests**

**IMPORTANT — corrected from an earlier version of this plan:** `ref<>` can legitimately point at a model declared in a *different* source file within the same workspace (e.g. `commerce.mdl` referencing `customer.Customer` declared in a sibling `customer.mdl` — this is the normal pattern used throughout `samples/scenarios/`). Resolving a `ref<>` therefore must happen against the fully **merged** multi-file workspace, never against one source file's own `MdlFile` in isolation — exactly like the existing `validate_references`/`_validate_merged_workspace` machinery already does for projection source/join references. This means `ref<>` validation does **not** go through `validate(mdl)`/`validate_diagnostics(mdl)` (which are inherently single-file) at all — it is a workspace-merge-level concern only, wired into `compiler/workspace.py`, same as `_validate_merged_workspace`.

Append to `cli/tests/test_semantic.py`:

```python
from modelable.compiler.workspace import load_workspace_from_sources, WorkspaceDocumentSource
from pathlib import Path


def test_unresolvable_ref_target_is_a_sem_error():
    source = WorkspaceDocumentSource(
        path=Path("orders.mdl"),
        uri="file:///orders.mdl",
        text="""
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerRef: ref<customer.MissingEntity>
          }
        }
        """,
    )

    workspace = load_workspace_from_sources([source])

    assert any("customerRef" in e.message and "ref<" in e.message for e in workspace.errors)


def test_unresolvable_ref_version_is_a_sem_error():
    source = WorkspaceDocumentSource(
        path=Path("orders.mdl"),
        uri="file:///orders.mdl",
        text="""
        domain orders {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
          }
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerRef: ref<orders.Customer @ 99>
          }
        }
        """,
    )

    workspace = load_workspace_from_sources([source])

    assert any("customerRef" in e.message for e in workspace.errors)


def test_resolvable_ref_produces_no_sem_error():
    source = WorkspaceDocumentSource(
        path=Path("orders.mdl"),
        uri="file:///orders.mdl",
        text="""
        domain orders {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
          }
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerRef: ref<orders.Customer @ 1>
          }
        }
        """,
    )

    workspace = load_workspace_from_sources([source])

    assert workspace.errors == []


def test_ref_across_source_files_resolves_correctly():
    """The scenario that broke an earlier version of this plan: a ref<> in
    one file pointing at a model declared in a sibling file. This must
    resolve cleanly — it is the normal pattern in samples/scenarios/."""
    customer_source = WorkspaceDocumentSource(
        path=Path("customer.mdl"),
        uri="file:///customer.mdl",
        text="""
        domain customer {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
          }
        }
        """,
    )
    orders_source = WorkspaceDocumentSource(
        path=Path("orders.mdl"),
        uri="file:///orders.mdl",
        text="""
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerRef: ref<customer.Customer @ 1>
          }
        }
        """,
    )

    workspace = load_workspace_from_sources([customer_source, orders_source])

    assert workspace.errors == []


def test_unversioned_ref_produces_a_non_blocking_warning_naming_resolved_version():
    source = WorkspaceDocumentSource(
        path=Path("orders.mdl"),
        uri="file:///orders.mdl",
        text="""
        domain orders {
          owner: "test-team"
          entity Customer @ 1 (additive) {
            @key customerId: uuid
          }
          entity Customer @ 2 (additive) {
            @key customerId: uuid
            name: string
          }
          entity Order @ 1 (additive) {
            @key orderId: uuid
            customerRef: ref<orders.Customer>
          }
        }
        """,
    )

    workspace = load_workspace_from_sources([source])

    assert workspace.errors == []
    ref_warnings = [w for w in workspace.warnings if w.code == "REF"]
    assert len(ref_warnings) == 1
    assert "customerRef" in ref_warnings[0].message
    assert "version 2" in ref_warnings[0].message


def test_ref_nested_in_array_is_validated():
    source = WorkspaceDocumentSource(
        path=Path("orders.mdl"),
        uri="file:///orders.mdl",
        text="""
        domain orders {
          owner: "test-team"
          entity Order @ 1 (additive) {
            @key orderId: uuid
            items: array<ref<catalog.MissingItem>>
          }
        }
        """,
    )

    workspace = load_workspace_from_sources([source])

    assert any("items" in e.message for e in workspace.errors)
```

Verify `WorkspaceDocumentSource` and `load_workspace_from_sources` are correctly imported (as shown above) — check `cli/tests/test_semantic.py`'s existing imports first in case some are already present, and don't duplicate an import line.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cli && uv run pytest tests/test_semantic.py -k "ref_target or ref_version or resolvable_ref or ref_across_source_files or unversioned_ref or ref_nested" -v`
Expected: FAIL — every test fails, since none of the underlying validation exists yet (`workspace.errors`/`workspace.warnings` won't contain anything ref<>-related).

- [ ] **Step 3: Write the implementation**

In `cli/src/modelable/validation/semantic.py`, update the import block (lines 8-25) to add `ArrayType`, `MapType`, `RefType`, `VersionMin`:

```python
from modelable.parser.ir import (
    AnnWire,
    ArrayType,
    ChangeKind,
    ClassificationLevel,
    ComputedMapping,
    DecimalType,
    DomainDef,
    EnumType,
    FieldDef,
    FieldType,
    FixedBinaryType,
    MapType,
    MdlFile,
    ModelKind,
    ModelVersion,
    NamedType,
    ObjectType,
    PrimitiveType,
    RefType,
    VersionMin,
)
from modelable.registry.resolver import resolve_model_ref, resolve_semantic_type_ref
```

Add `resolve_ref_type` to the resolver import:

```python
from modelable.registry.resolver import resolve_model_ref, resolve_ref_type, resolve_semantic_type_ref
```

Add this recursive walker and validator function near the bottom of the file (a good spot is right before `_diag` at line 890, or any other top-level function — exact position doesn't matter since Python doesn't require forward-declaration order for module-level functions called from within other functions defined earlier in the same module):

```python
def _iter_ref_types(field_type: FieldType) -> list[RefType]:
    if isinstance(field_type, RefType):
        return [field_type]
    if isinstance(field_type, ArrayType):
        return _iter_ref_types(field_type.item)
    if isinstance(field_type, MapType):
        return _iter_ref_types(field_type.value)
    if isinstance(field_type, ObjectType):
        found: list[RefType] = []
        for nested_field in field_type.fields:
            found.extend(_iter_ref_types(nested_field.type))
        return found
    return []


def validate_ref_type_field(
    fqn: str,
    field: FieldDef,
    mdl: MdlFile,
    diagnostics: list[Diagnostic],
    warnings: list[Diagnostic],
    path: str | Path | None,
) -> None:
    """Validate every ref<> nested anywhere in one field's type.

    `mdl` must be the fully MERGED multi-file workspace, never a single
    source file's own MdlFile — a ref<> can legitimately point at a model
    declared in a different source file (the normal pattern throughout
    samples/scenarios/), so resolution has to happen after all sources are
    merged. This function is intentionally NOT wired into
    validate_diagnostics/_validate_models (which only ever see one source
    file at a time) — it is called from compiler/workspace.py instead,
    exactly like the existing validate_references/_validate_merged_workspace
    machinery already does for projection source/join references. It is
    public (no leading underscore) because it is called across the
    validation/semantic.py -> compiler/workspace.py module boundary.
    """
    for ref_type in _iter_ref_types(field.type):
        try:
            resolved = resolve_ref_type(ref_type, mdl)
        except LookupError as exc:
            diagnostics.append(
                _diag(
                    "SEM",
                    f"{fqn}: field '{field.name}' has an unresolvable ref<{ref_type.target}>: {exc}",
                    path,
                )
            )
            continue

        if ref_type.version is None:
            warnings.append(
                Diagnostic(
                    code="REF",
                    message=(
                        f"{fqn}: field '{field.name}' has ref<{ref_type.target}> with no version "
                        f"constraint; resolved to version {resolved.version.version} at compile time. "
                        f"Add '@ {resolved.version.version}' (or a version range) where durable "
                        f"identity matters."
                    ),
                    severity="warning",
                    path=str(path or "<workspace>"),
                )
            )
```

Do **not** modify `validate_diagnostics` or `_validate_models` — leave both exactly as they are today. `ref<>` validation is entirely a workspace-merge-level concern, wired in Step 3b below, not a per-source-file one.

- [ ] **Step 3b: Wire `validate_ref_type_field` into the merged workspace loader**

This is where the actual iteration + call to `validate_ref_type_field` happens — mirroring the existing `_validate_merged_workspace` function's shape exactly (iterate per-source for correct path attribution, but resolve against the merged `mdl`).

In `cli/src/modelable/compiler/workspace.py`, update the import line that currently reads:
```python
from modelable.validation.semantic import validate_diagnostics
```
to:
```python
from modelable.validation.semantic import validate_diagnostics, validate_ref_type_field
```

Add this new function right after `_validate_merged_workspace` (find that function in the file — it returns `list[Diagnostic]` and takes `(sources: list[WorkspaceSource], merged: MdlFile)`; add the new function immediately after it, before whatever function comes next):

```python
def _validate_ref_types_in_merged_workspace(
    sources: list[WorkspaceSource],
    merged: MdlFile,
) -> tuple[list[Diagnostic], list[Diagnostic]]:
    """Validate every ref<> field across all sources against the fully
    merged workspace — see validate_ref_type_field's docstring for why this
    can't happen per-source-file."""
    errors: list[Diagnostic] = []
    warnings: list[Diagnostic] = []
    for source in sources:
        source_location = str(source.path) if source.path is not None else source.uri
        for domain in source.mdl.domains:
            for model_name, versions in domain.models.items():
                fqn = f"{domain.name}.{model_name}"
                for version in versions:
                    for field in version.fields:
                        validate_ref_type_field(
                            f"{fqn}@{version.version}", field, merged, errors, warnings, source_location
                        )
    return errors, warnings
```

In `load_workspace_from_sources`, find this existing line:
```python
    errors.extend(_validate_merged_workspace(workspace_sources, merged))
```
and add immediately after it (before the existing `errors.extend(_validate_cel(merged))` line):
```python
    errors.extend(_validate_merged_workspace(workspace_sources, merged))
    ref_errors, ref_warnings = _validate_ref_types_in_merged_workspace(workspace_sources, merged)
    errors.extend(ref_errors)
    warnings.extend(ref_warnings)
    errors.extend(_validate_cel(merged))
```

(`warnings` is already an existing local variable in this function, populated earlier in the per-source loop from `find_deferred_syntax_diagnostics` — just extend it, don't redeclare it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cli && uv run pytest tests/test_semantic.py -k "ref_target or ref_version or resolvable_ref or ref_across_source_files or unversioned_ref or ref_nested" -v`
Expected: PASS (all 6 tests)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd cli && uv run pytest -q`
Expected: all previously-passing tests still pass. If any existing test's `.mdl` fixture happens to use `ref<>` without a version (unlikely but check `samples/` and `cli/tests/fixtures/`), a new `REF` warning would appear in that scenario's `workspace.warnings` — this is additive and should not break any assertion that doesn't specifically check `workspace.warnings == []`; if something does, that's a legitimate new warning, not a bug — update the assertion rather than suppressing the warning.

- [ ] **Step 6: Commit**

```bash
git add cli/src/modelable/validation/semantic.py cli/src/modelable/compiler/workspace.py cli/tests/test_semantic.py
git commit -m "feat: validate ref<> targets, warn on unversioned refs

A ref<> pointing at a nonexistent domain/model/version is now a SEM
error instead of silently passing validation. An unversioned ref<>
gets a non-blocking REF warning naming the concrete version it
resolved to, making 'compilation records the concrete resolved
identity' an observable effect rather than a slogan.

Validation happens at the merged-workspace level (compiler/workspace.py),
not per-source-file, since a ref<> can legitimately point at a model
declared in a different source file within the same workspace — the
same reason validate_references/_validate_merged_workspace already
work this way for projection source/join references."
```

---

### Task 4: Compat classification — target changes are breaking, version-only changes are not

**Files:**
- Modify: `cli/src/modelable/compat/diff.py`
- Test: `cli/tests/test_compatibility.py` (append), `cli/tests/test_projection_compatibility.py` (append)

**Interfaces:**
- Consumes: `RefType` (Task 1).
- Produces: `_ref_aware_type_dump(field_type: FieldType) -> object`, used internally by `_type_signature` and `_shape_type_signature`.

- [ ] **Step 1: Write the failing tests**

Append to `cli/tests/test_compatibility.py` (check the existing file for its `_model_version` helper pattern first — reuse it; if the helper is named differently, adapt the calls below to match, but keep the test bodies and assertions identical):

```python
def test_ref_target_change_is_breaking():
    old_version = _model_version(
        """
        domain orders {
          owner: "test-team"
          entity Customer @ 1 (additive) { @key customerId: uuid }
          entity Shipment @ 1 (additive) { @key shipmentId: uuid }
          entity Order @ 1 (additive) {
            @key orderId: uuid
            targetRef: ref<orders.Customer>
          }
        }
        """,
        "Order",
        1,
    )
    new_version = _model_version(
        """
        domain orders {
          owner: "test-team"
          entity Customer @ 1 (additive) { @key customerId: uuid }
          entity Shipment @ 1 (additive) { @key shipmentId: uuid }
          entity Order @ 1 (additive) {
            @key orderId: uuid
            targetRef: ref<orders.Shipment>
          }
        }
        """,
        "Order",
        1,
    )

    changes = compare_model_versions(old_version, new_version)

    assert any(c.kind == "type_changed" and c.field_name == "targetRef" for c in changes)


def test_ref_version_only_change_is_not_a_type_change():
    old_version = _model_version(
        """
        domain orders {
          owner: "test-team"
          entity Customer @ 1 (additive) { @key customerId: uuid }
          entity Order @ 1 (additive) {
            @key orderId: uuid
            targetRef: ref<orders.Customer @ 1>
          }
        }
        """,
        "Order",
        1,
    )
    new_version = _model_version(
        """
        domain orders {
          owner: "test-team"
          entity Customer @ 1 (additive) { @key customerId: uuid }
          entity Customer @ 2 (additive) { @key customerId: uuid }
          entity Order @ 1 (additive) {
            @key orderId: uuid
            targetRef: ref<orders.Customer @ 2>
          }
        }
        """,
        "Order",
        1,
    )

    changes = compare_model_versions(old_version, new_version)

    assert not any(c.field_name == "targetRef" for c in changes)
```

If `test_compatibility.py`'s existing helper is called something other than `_model_version(text, model_name, version_number)`, read the file, find its actual name/signature, and adapt these two test bodies to call it correctly — do not invent a second helper.

Append to `cli/tests/test_projection_compatibility.py` (near the other `_compare_shape` tests):

```python
def test_ref_target_change_is_breaking_for_projection_shape():
    mdl, old, new = _two_versions(
        """
        domain orders {
          owner: "test-team"
          entity Customer @ 1 (additive) { @key customerId: uuid }
          entity Shipment @ 1 (additive) { @key shipmentId: uuid }
          entity Order @ 1 (additive) {
            @key orderId: uuid
            targetRef: ref<orders.Customer>
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            targetRef <- o.targetRef
          }
        }
        """,
        """
        domain orders {
          owner: "test-team"
          entity Customer @ 1 (additive) { @key customerId: uuid }
          entity Shipment @ 1 (additive) { @key shipmentId: uuid }
          entity Order @ 1 (additive) {
            @key orderId: uuid
            targetRef: ref<orders.Shipment>
          }
          projection OrderView @ 1 from orders.Order @ 1 as o {
            orderId <- o.orderId
            targetRef <- o.targetRef
          }
        }
        """,
    )

    changes = _compare_shape(mdl, old, new)

    assert any(c.kind == "type_changed" and c.breaking and c.field_name == "targetRef" for c in changes)


def test_ref_version_only_change_is_not_breaking_for_projection_shape():
    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Customer @ 1 (additive) { @key customerId: uuid }
      entity Customer @ 2 (additive) { @key customerId: uuid }
      entity Order @ 1 (additive) {
        @key orderId: uuid
        targetRef: ref<orders.Customer @ 1>
      }
      entity Order @ 2 (additive) {
        @key orderId: uuid
        targetRef: ref<orders.Customer @ 2>
      }
      projection OrderView @ 1 from orders.Order @ 1 as o {
        orderId <- o.orderId
        targetRef <- o.targetRef
      }
      projection OrderView @ 2 from orders.Order @ 2 as o {
        orderId <- o.orderId
        targetRef <- o.targetRef
      }
    }
    """)
    domain = mdl.domains[0]
    old = domain.projections["OrderView"][0]
    new = domain.projections["OrderView"][1]

    changes = _compare_shape(mdl, old, new)

    assert not any(c.field_name == "targetRef" for c in changes)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cli && uv run pytest tests/test_compatibility.py -k ref_ -v tests/test_projection_compatibility.py -k ref_`
Expected: `test_ref_target_change_is_breaking*` tests PASS already (a target change already changes `model_dump()`'s output today, so `type_changed` already fires) — that's fine, they serve as regression-proof for the "stays breaking" half. `test_ref_version_only_change_is_not*` tests FAIL, since today ANY change to `RefType`'s dumped JSON (including a future `.version` field) is treated as a type change.

- [ ] **Step 3: Write the implementation**

In `cli/src/modelable/compat/diff.py`, add `RefType` to the existing import block (already has `FieldType`, add `RefType` alphabetically):

```python
from modelable.parser.ir import (
    AccessBlock,
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
    RefType,
)
```

Add this shared helper right before `_type_signature` (line 191):

```python
def _ref_aware_type_dump(field_type: FieldType) -> object:
    """Serialize a field type for breaking-change detection.

    For ref<> specifically, only .target participates — pointing a ref at a
    different model is a real type change, but bumping the version it
    points at (target unchanged) is not breaking on its own.
    """
    if isinstance(field_type, RefType):
        return {"kind": "ref", "target": field_type.target}
    return field_type.model_dump(mode="json")
```

Replace `_type_signature` (line 191-192):

```python
def _type_signature(field: FieldDef) -> str:
    return json.dumps(_ref_aware_type_dump(field.type), sort_keys=True)
```

Replace `_shape_type_signature` (line 227-230):

```python
def _shape_type_signature(field_type: FieldType | None) -> str | None:
    if field_type is None:
        return None
    return json.dumps(_ref_aware_type_dump(field_type), sort_keys=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cli && uv run pytest tests/test_compatibility.py -k ref_ -v tests/test_projection_compatibility.py -k ref_`
Expected: PASS (all 4 tests)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd cli && uv run pytest -q`
Expected: all previously-passing tests still pass — no existing test relies on a `ref<>` field's version participating in the type signature (the concept didn't exist before this plan), so this is safe.

- [ ] **Step 6: Commit**

```bash
git add cli/src/modelable/compat/diff.py cli/tests/test_compatibility.py cli/tests/test_projection_compatibility.py
git commit -m "fix: ref<> version-only changes are not breaking

One shared _ref_aware_type_dump helper used by both _type_signature
(model fields) and Slice C1's _shape_type_signature (projection
fields) — a ref<>'s target changing is still a breaking type change;
its version alone changing, target unchanged, is not."
```

---

### Task 5: Signature rendering for versioned `ref<>`

**Files:**
- Modify: `cli/src/modelable/compiler/render.py`
- Test: `cli/tests/test_render.py` or equivalent existing render/signature test file (search for one; if none exists, create `cli/tests/test_render_ref_types.py`)

**Interfaces:**
- Consumes: `RefType.version` (Task 1), existing `_render_version_spec`/`_render_signature_version_spec`.

- [ ] **Step 1: Write the failing tests**

First, run `grep -rn "_render_type\|render_model_version\|render_signature_model_version" cli/tests/*.py` to find the existing test file(s) that exercise `render.py`'s rendering functions (likely `test_render.py`, `test_canonical_render.py`, or similar — these are indirectly exercised via `render_model_version`/`compute_version_signature`, not `_render_type` directly, since it's a private function). Add the following two tests to whichever file already imports `parse_text_to_ir` and a public render entry point like `render_model_version` or `compute_version_signature`:

```python
def test_versioned_ref_round_trips_through_canonical_rendering():
    from modelable.compiler.render import render_model_version

    mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Customer @ 1 (additive) { @key customerId: uuid }
      entity Order @ 1 (additive) {
        @key orderId: uuid
        customerRef: ref<orders.Customer @ 1>
      }
    }
    """)
    domain = mdl.domains[0]
    version = domain.models["Order"][0]

    rendered = render_model_version(domain.name, "Order", version, domain.owner, domain.description)

    assert "ref<orders.Customer @ 1>" in rendered


def test_ref_target_change_alters_canonical_signature():
    from modelable.registry.signature import compute_version_signature

    old_mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Customer @ 1 (additive) { @key customerId: uuid }
      entity Shipment @ 1 (additive) { @key shipmentId: uuid }
      entity Order @ 1 (additive) {
        @key orderId: uuid
        targetRef: ref<orders.Customer>
      }
    }
    """)
    new_mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Customer @ 1 (additive) { @key customerId: uuid }
      entity Shipment @ 1 (additive) { @key shipmentId: uuid }
      entity Order @ 1 (additive) {
        @key orderId: uuid
        targetRef: ref<orders.Shipment>
      }
    }
    """)

    old_version = old_mdl.domains[0].models["Order"][0]
    new_version = new_mdl.domains[0].models["Order"][0]

    old_sig = compute_version_signature("orders", "Order", old_version)
    new_sig = compute_version_signature("orders", "Order", new_version)

    assert old_sig != new_sig


def test_ref_version_only_change_does_not_alter_canonical_signature():
    from modelable.registry.signature import compute_version_signature

    old_mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Customer @ 1 (additive) { @key customerId: uuid }
      entity Customer @ 2 (additive) { @key customerId: uuid }
      entity Order @ 1 (additive) {
        @key orderId: uuid
        targetRef: ref<orders.Customer @ 1>
      }
    }
    """)
    new_mdl = parse_text_to_ir("""
    domain orders {
      owner: "test-team"
      entity Customer @ 1 (additive) { @key customerId: uuid }
      entity Customer @ 2 (additive) { @key customerId: uuid }
      entity Order @ 1 (additive) {
        @key orderId: uuid
        targetRef: ref<orders.Customer @ 2>
      }
    }
    """)

    old_version = old_mdl.domains[0].models["Order"][0]
    new_version = new_mdl.domains[0].models["Order"][0]

    old_sig = compute_version_signature("orders", "Order", old_version)
    new_sig = compute_version_signature("orders", "Order", new_version)

    assert old_sig == new_sig
```

Note: `test_ref_version_only_change_does_not_alter_canonical_signature` is a DELIBERATE choice — it asserts the canonical signature (used for content-pinned refs like `@ 2#hash`, and for detecting "did this published version's content change") is NOT sensitive to what a `ref<>` field's *own* declared version constraint is, only to which *target model* it points at. This mirrors the compat classification rule from Task 4 at the signature layer.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cli && uv run pytest tests/test_render.py -k "versioned_ref or ref_target_change or ref_version_only" -v` (adjust the file name to whatever you found in Step 1)
Expected: FAIL — `test_versioned_ref_round_trips_through_canonical_rendering` fails because the rendered text is `ref<orders.Customer>` (version dropped); the two signature tests currently PASS already by coincidence (since `.version` isn't rendered into the signature text at all yet, changing it has no effect — but wait, this means `test_ref_version_only_change_does_not_alter_canonical_signature` may already pass before your fix). Verify this explicitly: if that particular test already passes at this step, that's fine — it's still a legitimate regression-guard for after Step 3's change, and Step 3 must keep it passing, not break it.

- [ ] **Step 3: Write the implementation**

In `cli/src/modelable/compiler/render.py`, change the `RefType` branch in `_render_type` (currently line 387-388):

```python
    if isinstance(field_type, RefType):
        if field_type.version is not None:
            return f"ref<{field_type.target} @ {_render_version_spec(field_type.version)}>"
        return f"ref<{field_type.target}>"
```

Change the `RefType` branch in `_render_signature_type` (currently line 408-409) — note this one deliberately does NOT include the version, per the compat-classification rule from Task 4 (a ref's own version constraint must not affect the canonical signature, only its target):

```python
    if isinstance(field_type, RefType):
        return f"ref<{field_type.target}>"
```

(This second branch is unchanged from today — leaving it exactly as-is is the correct implementation, since including the version here would break `test_ref_version_only_change_does_not_alter_canonical_signature`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cli && uv run pytest tests/test_render.py -k "versioned_ref or ref_target_change or ref_version_only" -v`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd cli && uv run pytest -q`
Expected: all previously-passing tests still pass — check specifically for any existing render/round-trip test involving `ref<>` (unversioned) to confirm its output text is unchanged (`ref<Domain.Model>` with no version, since `field_type.version is None` for all pre-existing test fixtures).

- [ ] **Step 6: Commit**

```bash
git add cli/src/modelable/compiler/render.py cli/tests/test_render.py
git commit -m "feat: render ref<> version in canonical source rendering

_render_type now round-trips a ref<>'s version constraint through
canonical rendering. _render_signature_type deliberately does NOT —
the canonical signature stays insensitive to a ref's own version
constraint, matching the compat rule that a version-only change isn't
breaking."
```

(Adjust the `git add` path for the test file to match whatever file you actually edited in Step 1.)

---

### Task 6: TypeScript emitter uses the ref's own version

**Files:**
- Modify: `cli/src/modelable/emitters/typescript.py`
- Test: `cli/tests/test_emit_typescript.py`

**Interfaces:**
- Consumes: `resolve_ref_type` (Task 2).

- [ ] **Step 1: Write the failing tests**

Read `cli/tests/test_emit_typescript.py` first to find its existing test-setup conventions (how it constructs a `Workspace`/calls `emit_typescript`, and its output-directory/artifact-reading pattern) and match that style exactly for these two new tests — do not invent a different setup pattern. Using whatever pattern you find, add two tests asserting:

1. A field `customerRef: ref<customer.Customer @ 1>` in a domain where `Customer` has versions 1 and 2 published generates an import of the **V1** interface (`CustomerV1`), not `CustomerV2` (which is what today's `VersionMin(1)`-always-latest logic would incorrectly produce).
2. A field `customerRef: ref<customer.Customer>` (unversioned) in the same domain still imports the **latest** (`CustomerV2`) — unchanged behavior, regression guard.
3. A model with two DIFFERENT ref<> fields pointing at two DIFFERENT versions of the SAME target model (`ref<customer.Customer @ 1>` and `ref<customer.Customer @ 2>` in the same entity) generates TWO separate imports (`CustomerV1` and `CustomerV2`), each field typed with its own correct interface — this is the caching-key correctness case described in Step 3 below.

Example test bodies (adapt setup/assertions to match the actual file's existing helper functions):

```python
def test_versioned_ref_imports_the_pinned_version_not_latest(tmp_path):
    mdl = parse_text_to_ir("""
    domain customer {
      owner: "test-team"
      entity Customer @ 1 (additive) { @key customerId: uuid }
      entity Customer @ 2 (additive) { @key customerId: uuid name: string }
    }
    domain orders {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
        customerRef: ref<customer.Customer @ 1>
      }
    }
    """)
    workspace = Workspace(sources=[], mdl=mdl, errors=[])

    artifacts = emit_typescript(workspace, tmp_path)

    order_artifact = next(a for a in artifacts if a.id == "orders.Order.v1")
    assert "CustomerV1" in order_artifact.content
    assert "CustomerV2" not in order_artifact.content


def test_unversioned_ref_still_imports_latest(tmp_path):
    mdl = parse_text_to_ir("""
    domain customer {
      owner: "test-team"
      entity Customer @ 1 (additive) { @key customerId: uuid }
      entity Customer @ 2 (additive) { @key customerId: uuid name: string }
    }
    domain orders {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
        customerRef: ref<customer.Customer>
      }
    }
    """)
    workspace = Workspace(sources=[], mdl=mdl, errors=[])

    artifacts = emit_typescript(workspace, tmp_path)

    order_artifact = next(a for a in artifacts if a.id == "orders.Order.v1")
    assert "CustomerV2" in order_artifact.content


def test_two_ref_fields_to_different_versions_of_same_target_both_resolve_correctly(tmp_path):
    mdl = parse_text_to_ir("""
    domain customer {
      owner: "test-team"
      entity Customer @ 1 (additive) { @key customerId: uuid }
      entity Customer @ 2 (additive) { @key customerId: uuid name: string }
    }
    domain orders {
      owner: "test-team"
      entity Order @ 1 (additive) {
        @key orderId: uuid
        oldCustomerRef: ref<customer.Customer @ 1>
        newCustomerRef: ref<customer.Customer @ 2>
      }
    }
    """)
    workspace = Workspace(sources=[], mdl=mdl, errors=[])

    artifacts = emit_typescript(workspace, tmp_path)

    order_artifact = next(a for a in artifacts if a.id == "orders.Order.v1")
    assert "oldCustomerRef" in order_artifact.content
    assert "newCustomerRef" in order_artifact.content
    assert "CustomerV1" in order_artifact.content
    assert "CustomerV2" in order_artifact.content
```

If `Workspace` requires different/additional constructor arguments than shown (check `cli/src/modelable/compiler/workspace.py`'s dataclass fields, and whatever the existing tests in `test_emit_typescript.py` pass), match the real signature rather than the placeholder above.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cli && uv run pytest tests/test_emit_typescript.py -k "pinned_version or still_imports_latest or different_versions_of_same_target" -v`
Expected: FAIL — `test_versioned_ref_imports_the_pinned_version_not_latest` fails because today's code always resolves to latest (`CustomerV2` appears instead of `CustomerV1`); the third test fails because `resolved_refs` is keyed by bare `target` string, so the second `ref<>` field's resolution overwrites/collides with the first in the cache, and one of the two fields ends up with the wrong interface.

- [ ] **Step 3: Write the implementation**

In `cli/src/modelable/emitters/typescript.py`, the `resolved_refs` cache must be keyed by `(target, version)` — not `target` alone — since two different fields can now legitimately reference different versions of the same target model. Add this key-building helper right before `_collect_ref_imports` (line 74):

```python
def _ref_cache_key(field_type: RefType) -> tuple:
    version = field_type.version
    if version is None:
        return (field_type.target, None)
    if isinstance(version, VersionExact):
        return (field_type.target, "exact", version.version)
    if isinstance(version, VersionRange):
        return (field_type.target, "range", version.min_inclusive, version.max_exclusive)
    if isinstance(version, VersionMin):
        return (field_type.target, "min", version.min_inclusive)
    if isinstance(version, VersionPinned):
        return (field_type.target, "pinned", version.version, version.content_hash)
    return (field_type.target, None)
```

Replace `_collect_ref_imports` (lines 74-93) — change the type annotation, the cache key, and the resolution call:

```python
def _collect_ref_imports(field_type, mdl, resolved_refs: dict[tuple, str]) -> None:
    """Recursively collect resolved RefType targets into resolved_refs, keyed by (target, version)."""
    if isinstance(field_type, RefType):
        key = _ref_cache_key(field_type)
        if key not in resolved_refs:
            try:
                resolved: ResolvedModelRef = resolve_ref_type(field_type, mdl)
                iface = _stable_interface_name(resolved.domain_name, resolved.model_name, resolved.version.version)
                resolved_refs[key] = iface
            except (LookupError, ValueError):
                pass
    elif isinstance(field_type, ArrayType):
        _collect_ref_imports(field_type.item, mdl, resolved_refs)
    elif isinstance(field_type, MapType):
        _collect_ref_imports(field_type.value, mdl, resolved_refs)
    elif isinstance(field_type, ObjectType):
        for f in field_type.fields:
            _collect_ref_imports(f.type, mdl, resolved_refs)
```

Note: the original code had `except LookupError, ValueError:` (valid Python 3 syntax here — parsed as a bare tuple, equivalent to `except (LookupError, ValueError):` — but write it with explicit parentheses as shown above for clarity, since this is new code, not preserving an existing oddity).

Update the import block (lines 9-30) to add `resolve_ref_type`:

```python
from modelable.registry.resolver import ResolvedModelRef, resolve_model_ref, resolve_ref_type
```

(Keep `resolve_model_ref` — it's likely still used elsewhere in this file for `NamedType` resolution or similar; do not remove it if so. Check before removing any existing import.)

Update the two call sites in `_emit_model` that build `resolved_refs: dict[str, str] = {}` (line 123) — change the type annotation to `dict[tuple, str]`:

```python
    resolved_refs: dict[tuple, str] = {}  # (target, version-key) → stable interface name
```

Finally, update `_type_to_ts`'s lookup (lines 366-368) to use the same cache key:

```python
    if isinstance(field_type, RefType):
        if resolved_refs is not None:
            key = _ref_cache_key(field_type)
            if key in resolved_refs:
                return resolved_refs[key]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cli && uv run pytest tests/test_emit_typescript.py -k "pinned_version or still_imports_latest or different_versions_of_same_target" -v`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd cli && uv run pytest -q`
Expected: all previously-passing TypeScript emitter tests still pass — every pre-existing `ref<>` fixture is unversioned, so `_ref_cache_key` returns `(target, None)` for all of them, identical in effect to today's plain `target` key.

- [ ] **Step 6: Commit**

```bash
git add cli/src/modelable/emitters/typescript.py cli/tests/test_emit_typescript.py
git commit -m "feat: typescript emitter resolves ref<> to its own version

ref<customer.Customer @ 1> now imports CustomerV1, not whatever
happens to be latest. Fixed the resolved_refs cache to key by
(target, version) instead of target alone, since two fields can now
legitimately reference different versions of the same target model —
keying by target alone would have made the second field's resolution
silently overwrite the first's in the cache."
```

---

### Task 7: Shared LSP ref-version resolution helper

**Files:**
- Create: `cli/src/modelable/language/ref_lookup.py`
- Test: `cli/tests/test_ref_lookup.py` (new)

**Interfaces:**
- Consumes: `resolve_model_ref`, `VersionExact`, `VersionRange`, `VersionMin`, `VersionPinned`.
- Produces: `REF_TYPE_PATTERN` (compiled regex, replaces the duplicated `_REF_TYPE_PATTERN` in `definition.py`/`hover.py`), `resolve_ref_match_version(workspace: Workspace, domain_name: str, name: str, version_text: str | None) -> int | None` — used by Tasks 8 and 9.

- [ ] **Step 1: Write the failing tests**

Create `cli/tests/test_ref_lookup.py`:

```python
from modelable.compiler.workspace import load_workspace_from_sources, WorkspaceDocumentSource
from modelable.language.ref_lookup import REF_TYPE_PATTERN, resolve_ref_match_version
from pathlib import Path


def _workspace(text: str):
    source = WorkspaceDocumentSource(path=Path("test.mdl"), uri="file:///test.mdl", text=text)
    return load_workspace_from_sources([source])


DOMAIN = """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) { @key customerId: uuid }
  entity Customer @ 2 (additive) { @key customerId: uuid name: string }
}
"""


def test_pattern_matches_unversioned_ref():
    match = REF_TYPE_PATTERN.search("customerRef: ref<customer.Customer>")
    assert match is not None
    assert match.group("domain") == "customer"
    assert match.group("name") == "Customer"
    assert match.group("version") is None


def test_pattern_matches_exact_version():
    match = REF_TYPE_PATTERN.search("customerRef: ref<customer.Customer @ 2>")
    assert match is not None
    assert match.group("version") == "2"


def test_pattern_matches_range_version():
    match = REF_TYPE_PATTERN.search("customerRef: ref<customer.Customer @ >=1 <3>")
    assert match is not None
    assert match.group("version").replace(" ", "") == ">=1<3"


def test_pattern_matches_pinned_version():
    match = REF_TYPE_PATTERN.search("customerRef: ref<customer.Customer @ 2#deadbeef>")
    assert match is not None
    assert match.group("version") == "2#deadbeef"


def test_resolve_unversioned_returns_latest():
    workspace = _workspace(DOMAIN)
    version = resolve_ref_match_version(workspace, "customer", "Customer", None)
    assert version == 2


def test_resolve_exact_version_text():
    workspace = _workspace(DOMAIN)
    version = resolve_ref_match_version(workspace, "customer", "Customer", "1")
    assert version == 1


def test_resolve_unresolvable_returns_none():
    workspace = _workspace(DOMAIN)
    version = resolve_ref_match_version(workspace, "customer", "Customer", "99")
    assert version is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cli && uv run pytest tests/test_ref_lookup.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'modelable.language.ref_lookup'`

- [ ] **Step 3: Write the implementation**

Create `cli/src/modelable/language/ref_lookup.py`:

```python
from __future__ import annotations

import re

from modelable.compiler.workspace import Workspace
from modelable.parser.ir import VersionExact, VersionMin, VersionPinned, VersionRange, VersionSpec
from modelable.registry.resolver import resolve_model_ref

REF_TYPE_PATTERN = re.compile(
    r"ref\s*<\s*(?P<domain>[A-Za-z_][A-Za-z0-9_]*)\.(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\s*@\s*(?P<version>"
    r">=\s*\d+\s*<\s*\d+"
    r"|>=\s*\d+"
    r"|\d+\s*#\s*[A-Za-z0-9_]+"
    r"|\d+"
    r"))?"
    r"\s*>"
)


def _parse_version_text(version_text: str | None) -> VersionSpec | None:
    """Parse a ref<>'s captured '@ ...' text into a VersionSpec, or None if absent."""
    if version_text is None:
        return None
    text = version_text.replace(" ", "")
    range_match = re.fullmatch(r">=(\d+)<(\d+)", text)
    if range_match:
        return VersionRange(min_inclusive=int(range_match.group(1)), max_exclusive=int(range_match.group(2)))
    min_match = re.fullmatch(r">=(\d+)", text)
    if min_match:
        return VersionMin(min_inclusive=int(min_match.group(1)))
    pinned_match = re.fullmatch(r"(\d+)#([A-Za-z0-9_]+)", text)
    if pinned_match:
        return VersionPinned(version=int(pinned_match.group(1)), content_hash=pinned_match.group(2))
    exact_match = re.fullmatch(r"(\d+)", text)
    if exact_match:
        return VersionExact(version=int(exact_match.group(1)))
    return None


def resolve_ref_match_version(
    workspace: Workspace,
    domain_name: str,
    name: str,
    version_text: str | None,
) -> int | None:
    """Resolve a ref<> match's (domain, name, optional version text) to a concrete version number.

    version_text=None resolves to the latest matching version (VersionMin(1))
    — the same "unversioned ref" rule resolve_ref_type uses for parsed IR
    fields. Returns None if the reference doesn't resolve at all (unknown
    domain/model/version) — callers should fall back to their existing
    "not found" handling rather than raise.
    """
    version_spec = _parse_version_text(version_text)
    if version_spec is None:
        version_spec = VersionMin(min_inclusive=1)
    try:
        resolved = resolve_model_ref(workspace.mdl, f"{domain_name}.{name}", version_spec)
    except LookupError:
        return None
    return resolved.version.version
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cli && uv run pytest tests/test_ref_lookup.py -v`
Expected: PASS (all 7 tests)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd cli && uv run pytest -q`
Expected: all previously-passing tests still pass (this task only adds a new, not-yet-consumed module)

- [ ] **Step 6: Commit**

```bash
git add cli/src/modelable/language/ref_lookup.py cli/tests/test_ref_lookup.py
git commit -m "feat: add shared ref<> version-aware resolution for the LSP

REF_TYPE_PATTERN recognizes the new @ version syntax;
resolve_ref_match_version wraps resolve_model_ref with the same
'unversioned -> latest' fallback resolve_ref_type uses for parsed IR.
Not yet wired into definition.py/hover.py — that's the next two tasks."
```

---

### Task 8: `definition.py` uses the shared ref-lookup helper

**Files:**
- Modify: `cli/src/modelable/language/definition.py`
- Test: `cli/tests/test_language_definition.py`

**Interfaces:**
- Consumes: `REF_TYPE_PATTERN`, `resolve_ref_match_version` (Task 7).

- [ ] **Step 1: Write the failing tests**

Read `cli/tests/test_language_definition.py` first to find its existing setup pattern (how it builds a `LanguageWorkspace`, synchronizes a document, and calls `definition(...)`) and match it exactly. Add tests asserting:

1. Go-to-definition on `ref<customer.Customer @ 1>` (a specific version) jumps to the `Customer @ 1` declaration, not whatever's latest.
2. Go-to-definition on unversioned `ref<customer.Customer>` still jumps to latest (regression guard, matching today's `_definition_for_unversioned_ref` behavior).

Example (adapt setup calls to match the file's actual existing helpers/fixtures):

```python
def test_definition_for_versioned_ref_jumps_to_that_version():
    text = """
    domain customer {
      owner: "test-team"
      entity Customer @ 1 (additive) { @key customerId: uuid }
      entity Customer @ 2 (additive) { @key customerId: uuid name: string }
      entity Order @ 1 (additive) {
        @key orderId: uuid
        customerRef: ref<customer.Customer @ 1>
      }
    }
    """
    workspace = LanguageWorkspace()
    document = LanguageDocument.from_text("file:///test.mdl", text, 1)
    workspace.synchronize(1, (document,))

    ref_line = next(i for i, line in enumerate(text.splitlines()) if "customerRef: ref<" in line)
    ref_column = text.splitlines()[ref_line].index("ref<") + 6  # inside "Customer"

    result = definition(workspace, "file:///test.mdl", LanguagePosition(line=ref_line, character=ref_column))

    assert result is not None
    # The definition should land on the `entity Customer @ 1` line, not `@ 2`.
    target_line_text = text.splitlines()[result.range.start.line]
    assert "@ 1" in target_line_text
```

Adjust the exact position-finding/assertion mechanics to match whatever conventions `test_language_definition.py` already uses for its other `ref<>`-related tests (there should be at least one existing unversioned-ref test to model this on).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cli && uv run pytest tests/test_language_definition.py -k versioned_ref -v`
Expected: FAIL — today's code ignores any `@ version` suffix entirely (the old `_REF_TYPE_PATTERN` doesn't even capture it, and `_definition_for_unversioned_ref` always resolves to latest), so it jumps to `Customer @ 2` instead of `@ 1`.

- [ ] **Step 3: Write the implementation**

In `cli/src/modelable/language/definition.py`:

Remove the old `_REF_TYPE_PATTERN` definition (line 16) and import the shared one instead. Change the import block (lines 1-11) to add:

```python
from modelable.language.ref_lookup import REF_TYPE_PATTERN, resolve_ref_match_version
```

Delete line 16 (`_REF_TYPE_PATTERN = re.compile(...)`) — the import above replaces it. Every other use of `_REF_TYPE_PATTERN` in this file should now refer to `REF_TYPE_PATTERN` (the imported one) — update the reference at line 79 (`for match in _REF_TYPE_PATTERN.finditer(text_line):`) to `for match in REF_TYPE_PATTERN.finditer(text_line):`.

Replace `_definition_for_unversioned_ref` (lines 126-136) — despite the name, it now handles both versioned and unversioned matches, so rename it to `_definition_for_ref_type_match` and add a `version_text` parameter:

```python
def _definition_for_ref_type_match(
    workspace: Workspace, domain_name: str, name: str, version_text: str | None
) -> LanguageLocation | None:
    domain = next((d for d in workspace.mdl.domains if d.name == domain_name), None)
    if domain is None:
        return None
    resolved_version = resolve_ref_match_version(workspace, domain_name, name, version_text)
    if resolved_version is None:
        return None
    if name in domain.models:
        return _definition_for_decl(workspace, domain_name, "model", name, resolved_version)
    if name in domain.projections:
        return _definition_for_decl(workspace, domain_name, "projection", name, resolved_version)
    return None
```

Update the call site (lines 79-83) to pass the new `version` capture group and use the renamed function:

```python
    for match in REF_TYPE_PATTERN.finditer(text_line):
        if _contains(match.start(), match.end(), character):
            location = _definition_for_ref_type_match(
                semantic, match.group("domain"), match.group("name"), match.group("version")
            )
            if location is not None:
                return location
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cli && uv run pytest tests/test_language_definition.py -v`
Expected: PASS, including the new test and every pre-existing test in this file (the unversioned case now goes through `resolve_ref_match_version(..., version_text=None)`, which resolves to latest — identical behavior to the old `max()` call).

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd cli && uv run pytest -q`
Expected: all previously-passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add cli/src/modelable/language/definition.py cli/tests/test_language_definition.py
git commit -m "feat: go-to-definition resolves versioned ref<> targets

Repoints definition.py at the shared REF_TYPE_PATTERN/
resolve_ref_match_version from Task 7 instead of its own regex + ad
hoc max() 'latest version' logic. Unversioned refs keep identical
behavior (still resolve to latest)."
```

---

### Task 9: `hover.py` uses the shared ref-lookup helper

**Files:**
- Modify: `cli/src/modelable/language/hover.py`
- Test: `cli/tests/test_language_hover.py`

**Interfaces:**
- Consumes: `REF_TYPE_PATTERN`, `resolve_ref_match_version` (Task 7).

- [ ] **Step 1: Write the failing test**

Read `cli/tests/test_language_hover.py` first to find its existing setup pattern (mirroring Task 8's approach). Add one test:

```python
def test_hover_for_versioned_ref_shows_that_version():
    text = """
    domain customer {
      owner: "test-team"
      entity Customer @ 1 (additive) { @key customerId: uuid }
      entity Customer @ 2 (additive) { @key customerId: uuid name: string }
      entity Order @ 1 (additive) {
        @key orderId: uuid
        customerRef: ref<customer.Customer @ 1>
      }
    }
    """
    workspace = LanguageWorkspace()
    document = LanguageDocument.from_text("file:///test.mdl", text, 1)
    workspace.synchronize(1, (document,))

    ref_line = next(i for i, line in enumerate(text.splitlines()) if "customerRef: ref<" in line)
    ref_column = text.splitlines()[ref_line].index("ref<") + 6

    result = hover(workspace, "file:///test.mdl", LanguagePosition(line=ref_line, character=ref_column))

    assert result is not None
    assert "@ 1" in result.markdown or "customer.Customer@1" in result.markdown
```

Adjust exact assertion text to match whatever `build_model_summary`'s actual markdown format is (check an existing passing hover test in the same file for the real format string, e.g. does it render `domain.Name@version` or `domain.Name @ version`).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cli && uv run pytest tests/test_language_hover.py -k versioned_ref -v`
Expected: FAIL — hovers on `@ 2` (latest) instead of `@ 1`.

- [ ] **Step 3: Write the implementation**

In `cli/src/modelable/language/hover.py`, same pattern as Task 8:

Change the import block to add:
```python
from modelable.language.ref_lookup import REF_TYPE_PATTERN, resolve_ref_match_version
```

Delete the local `_REF_TYPE_PATTERN = re.compile(...)` definition (line 28).

Update the call site (lines 84-96) to reference the imported `REF_TYPE_PATTERN` and pass the new version group:

```python
    for match in REF_TYPE_PATTERN.finditer(text_line):
        if _contains(match.start(), match.end(), character):
            result = _make_ref_type_hover(
                semantic,
                match.group("domain"),
                match.group("name"),
                match.group("version"),
                text_line,
                position.line,
                match.start(),
                match.end(),
            )
            if result is not None:
                return result
```

Rename `_make_unversioned_ref_hover` (lines 170-193ish — read the full function first, since the plan brief only showed lines 170-189) to `_make_ref_type_hover`, adding a `version_text` parameter, and use `resolve_ref_match_version` instead of the local `max()` calls:

```python
def _make_ref_type_hover(
    workspace: Workspace,
    domain_name: str,
    name: str,
    version_text: str | None,
    text_line: str,
    line: int,
    start: int,
    end: int,
) -> LanguageHover | None:
    domain = next(
        (domain for domain in workspace.mdl.domains if domain.name == domain_name),
        None,
    )
    if domain is None:
        return None
    resolved_version = resolve_ref_match_version(workspace, domain_name, name, version_text)
    if resolved_version is None:
        return None
    if name in domain.models or name in domain.projections:
        ref = f"{domain_name}.{name}@{resolved_version}"
        return _make_ref_hover(workspace, ref, text_line, line, start, end)
    return None
```

Read the rest of the original `_make_unversioned_ref_hover` function (past line 189, up to wherever it ends) before deleting it — if it has any additional branches beyond the `domain.models`/`domain.projections` check shown in the design research (e.g. different handling for models vs projections beyond just building the `ref` string), preserve that behavior in the replacement above rather than assuming the simplified version shown here is complete. If the two branches (`models` vs `projections`) genuinely do identical work (build the same `ref` string format and call `_make_ref_hover` the same way), the single unified branch above is correct and simpler; if they differ, keep them separate but apply the same `resolve_ref_match_version` change to both.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cli && uv run pytest tests/test_language_hover.py -v`
Expected: PASS, including the new test and every pre-existing test in this file.

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `cd cli && uv run pytest -q`
Expected: all previously-passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add cli/src/modelable/language/hover.py cli/tests/test_language_hover.py
git commit -m "feat: hover resolves versioned ref<> targets

Repoints hover.py at the shared REF_TYPE_PATTERN/
resolve_ref_match_version from Task 7, consolidating the second (of
two) independent 'unversioned ref -> latest' implementations. Now
exactly one implementation of that rule exists in the codebase."
```

---

### Task 10: Docs + full regression sweep

**Files:**
- Modify: `docs/language-reference.md` (the `ref<>` type documentation section)
- Modify: `docs/correction-and-capability-plan.md` (Slice C2's outcome note)
- Modify: `cli/mypy-baseline.txt` (only if the sweep requires it)

- [ ] **Step 1: Update `docs/language-reference.md`**

Find the section documenting `ref<Domain.Model>` as a type (search for `` ref< `` or "Ref type" or similar — likely in a "Types" or "Field types" section). Add documentation for the new version syntax, modeled on how projection `source_clause` version syntax is already documented elsewhere in the same file (find that section and match its style/table format):

- Document all 4 forms: `ref<Domain.Model @ 2>` (exact), `ref<Domain.Model @ >=2 <3>` (range), `ref<Domain.Model @ >=2>` (min), `ref<Domain.Model @ 2#hash>` (pinned).
- Document that unversioned `ref<Domain.Model>` still parses, resolves to the latest matching version, and produces a non-blocking `REF` diagnostic recommending a version constraint.
- Document that an unresolvable ref<> target/version is a `SEM` validation error.

Write the exact prose/table addition based on what you find in the existing file's style — do not invent a different documentation format than what's already there.

- [ ] **Step 2: Update `docs/correction-and-capability-plan.md`**

Find the `## Slice C2 — extend existing version resolution to \`ref<>\` types` section (search for that heading). After its `### Acceptance criteria` subsection, add an outcome note following the exact pattern Slice C1 used (find Slice C1's `### Outcome` subsection in the same file and match its structure/tone):

```markdown

### Outcome (2026-08-05)

Implemented as designed in
[the C2 design spec](superpowers/specs/2026-08-05-ref-version-resolution-design.md):
grammar/IR support for `ref<Domain.Model @ version_spec>`, one canonical
`resolve_ref_type()` resolver, new SEM validation for unresolvable refs and
a non-blocking `REF` advisory for unversioned ones, compat/signature rules
that separate a ref's target (breaking if changed) from its version
(never breaking alone), TypeScript codegen using the ref's own version
instead of always-latest, and consolidation of the LSP's two independently
duplicated "unversioned ref → latest" implementations onto one shared
helper.
```

- [ ] **Step 3: Full regression sweep**

From `cli/`:

```bash
uv run pytest -q
uv run ruff format --check .
uv run ruff check .
rm -rf .mypy_cache
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short -q --cov=modelable --cov-report=term-missing --cov-report=xml
uv run python ../.github/scripts/check_coverage_ratchet.py --coverage-xml coverage.xml --baseline coverage-baseline.txt
```

If the mypy baseline check reports new errors, use the established reconciliation pattern from prior slices: search `cli/mypy-baseline.txt` for a same-file, same-message entry at a different line number (a shift from inserted/deleted code — update the line number) versus a genuinely new error (fix the code; only baseline it if truly unavoidable, and explain why in your report).

From the repository root:

```bash
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
rm -rf site
```

Expected: pytest full pass; ruff clean; mypy 0 new errors; coverage ratchet passes; mkdocs exit 0 with no warnings.

- [ ] **Step 4: Commit**

```bash
git add docs/language-reference.md docs/correction-and-capability-plan.md cli/mypy-baseline.txt
git commit -m "docs: document ref<> version syntax and record C2 outcome"
```

(Omit `cli/mypy-baseline.txt` from `git add` if the sweep required no changes to it.)

---

## Self-Review Notes

- **Spec coverage:** grammar/IR (Task 1), canonical resolver (Task 2), semantic validation (Task 3), compat classification for both model and projection fields (Task 4), signature rendering (Task 5), TypeScript codegen (Task 6), LSP consolidation (Tasks 7-9), docs (Task 10) — every section of the design spec has a corresponding task.
- **Placeholder scan:** Tasks 5, 6, 8, 9 each include an explicit "read the existing test file first, match its conventions" instruction rather than a fabricated test-setup pattern, since those files' exact fixture/helper conventions weren't independently re-verified line-by-line during planning (unlike Tasks 1-4, 7, which were grounded against exact current file contents read during design). This is a deliberate, bounded uncertainty — not a placeholder — the *behavior* to test is fully specified in every case; only the *setup mechanics* are left for the implementer to match against real file contents, exactly as the plan instructs them to do before writing the test.
- **Type consistency:** `RefType.version: VersionSpec | None` (Task 1) is consumed identically by `resolve_ref_type` (Task 2, via `field_type.version`), the SEM/REF validators (Task 3), the compat helper (Task 4, via `_ref_aware_type_dump`), the render functions (Task 5), the TypeScript cache key (Task 6), and `resolve_ref_match_version`'s parsed `VersionSpec` (Task 7, consumed identically by Tasks 8-9) — one type, one shape, used the same way everywhere.
