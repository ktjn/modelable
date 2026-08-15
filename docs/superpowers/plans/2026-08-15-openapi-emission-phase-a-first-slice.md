# OpenAPI Emission (Phase A) — Schema-Only Target Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Context

`docs/superpowers/specs/2026-08-14-openapi-emission-design.md` is an accepted
design closing a real gap: `.mdl` sources can already declare `generate {
openapi -> "./generated/api/" }` and the compiler parses/validates/formats
it, but nothing consumes that declaration — `openapi` has grammar acceptance
with no emitter behind it (`docs/compiler-reference.md` §2: `OpenAPI | 5 |
Deferred`). `ROADMAP.md` Priority 5 names hardening OpenAPI import and
adding export as **P0**, ahead of Avro/AsyncAPI/XSD/GraphQL, while a
separate ROADMAP entry (Slice F2) wrongly gates *all* OpenAPI export work on
four unstarted language slices (D1-D4: presence/nullability, constraints,
named enums, discriminated unions). The design doc resolves that tension by
splitting the work into independently shippable phases (§5) and shows that
Phase A — emitting `components.schemas` from the request/reply/hand-authored
projections the compiler already produces — needs none of D1-D4. It only
needs compiler surface that exists today.

This plan implements exactly Phase A (design §6), following the same
design/plan split the Protobuf/gRPC feature used
(`docs/superpowers/specs/archived/2026-07-04-scalable-protobuf-grpc-support-design.md`
+
`docs/superpowers/plans/archived/2026-07-04-protobuf-target-first-slice.md`).
The intended outcome: `modelable compile --target openapi` produces a
deterministic, structurally valid OpenAPI 3.1 document that downstream
tooling (linters, `openapi-generator`, Redocly) can consume today for
schema/client generation, even before Phase B adds paths/operations.

**Goal:** Add a first usable `modelable compile --target openapi` path that
emits a single deterministic `openapi.json` document (OpenAPI 3.1 envelope
with `openapi`/`info`/`components.schemas`/`paths: {}`) covering
request/reply/event auto-projections and hand-authored projections, per
design §6.

**Architecture:** Implement `openapi` as a normal local artifact target
beside JSON Schema, ODCS, and Protobuf. Extract the type/field-mapping logic
that `emitters/json_schema.py` already owns into a new shared internal
module, `emitters/_schema_mapping.py`, parameterized so both emitters call
the same functions and stay correct together (design §3: "reuse the
existing JSON Schema emitter's type-mapping logic rather than re-deriving
it"). `json_schema.py`'s public behavior and byte-for-byte output must not
change — this is an extract-and-reimport refactor, not a rewrite.

The one deliberate behavioral divergence between the two emitters is
`RefType` resolution (design §6.3): JSON Schema keeps its existing lossy
stringified-ref stub (`{"type": "string", "x-modelable-ref": target}`),
while OpenAPI must resolve `ref<>` to a real `{"$ref":
"#/components/schemas/Domain.Model.vN"}`. This is resolved as follows:

- The shared `_schema_mapping.py` module's core type-dispatch function gains
  two new optional, keyword-only parameters: `mdl: MdlFile | None = None`
  and `ref_base: str = "#/$defs/"`. `RefType` handling becomes: if `mdl is
  not None`, resolve via the existing
  `modelable.registry.resolver.resolve_ref_type(field_type, mdl) ->
  ResolvedModelRef` helper (registry/resolver.py:66, already used
  identically by `emitters/typescript.py:91` for the same problem — no new
  resolution logic needs inventing) and emit `{"$ref":
  f"{ref_base}{resolved.domain_name}.{resolved.model_name}.v{resolved.version.version}"}`;
  if `mdl is None`, fall back to the current stringified stub unchanged.
  `json_schema.py`'s call sites keep passing `mdl=None` (or omitting it) and
  the default `ref_base="#/$defs/"`, so its output is provably unchanged.
  `openapi.py`'s call sites pass `mdl=workspace.mdl` and
  `ref_base="#/components/schemas/"`.
- Ref-resolution stays *inside* the shared module (not layered outside it)
  because the rest of the type-dispatch tree (`ArrayType`/`MapType`/
  `ObjectType` recursion) needs to thread `mdl`/`ref_base` down to nested
  `RefType` occurrences anyway (e.g. `array<ref<Domain.Model>>`), and
  duplicating that recursion outside the shared module just to special-case
  `RefType` would reintroduce exactly the "solve the mapping problem twice"
  cost this refactor exists to avoid.

**`{projection_name: kind}` classification** (design §6.2) is computed by
`openapi.py` itself, not the planner: for each `DomainDef`, build a lookup
from `domain.auto_projections: list[AutoProjectionDecl]` (`parser/ir.py`
~517) × each decl's `targets: list[AutoProjectionTarget]` (`kind`,
`excluded_fields`, `excluded_annotations`; ir.py ~446-450), using a
**locally duplicated** copy of `planner/planner.py::_generated_projection_name`'s
5-line suffix map (`{"db": "Db", "request": "Request", "reply": "Reply",
"event": "Event"}`) rather than importing the private planner symbol.
Duplicating five lines of pure, unlikely-to-change logic is cleaner than
coupling an emitter to a private planner internal — if the naming
convention ever changes, both call sites need updating anyway since the
*emitted artifact names* and the *planner's expansion* must stay in
lockstep, and importing a `_`-prefixed planner symbol would be a worse
contract than two independently-tested five-line functions. Any
`ProjectionVersion` whose name isn't in the lookup is hand-authored (always
included per design §6.2 — "unless explicitly excluded"; exclusion syntax
is explicitly out of scope, see Scope below).

**Tech Stack:** Python 3.14, Click CLI, existing Modelable compiler IR,
`EmittedArtifact`, `jsonschema` (`Draft202012Validator`), pytest, ruff,
mypy.

---

## Scope And Version Boundary

This implements exactly design §6 ("Phase A"). Per the design document's own
phasing table (§5), the following are explicitly **out of scope** and must
not be implemented, even partially:

- `paths`/operations generation, HTTP verbs, status codes (§7, Phase B —
  proposed, not accepted).
- Any new `.mdl` grammar (`api { }` block, route declarations) — none
  exists today for this feature and none is added.
- Deterministic OpenAPI **import** hardening (§8, Phase C) —
  `llm/importers.py::_import_openapi` is untouched.
- Fidelity follow-ups gated on D1–D4 (presence/nullability, value
  constraints, named enum reuse, discriminated unions) — nothing in this
  plan depends on or blocks on those slices.
- `generate { }`-block-scoped inclusion/exclusion syntax for opting a
  `db`-kind projection in, or opting a `request`/`reply`/hand-authored
  projection out (design §6.2 explicitly leaves exact syntax as an
  implementation-plan decision). This plan implements **only** the default
  inclusion/exclusion rule; the opt-in/opt-out mechanism is a flagged
  follow-up, noted in the CHANGELOG entry.
- Security scheme declaration, webhooks section — reserved for Phase B.
- Adding OpenAPI Phase A to `cli/coverage-baseline.txt` (design §9: "not
  required for initial acceptance").
- `supports_compat_check=True` for `openapi` — stays `False` per design
  §6.5.
- Adding a new dependency (e.g. `openapi-spec-validator`) to validate the
  full document against the official OpenAPI 3.1 meta-schema. This plan
  validates `components.schemas` as JSON Schema 2020-12 (which is what
  those definitions actually are) and asserts the document envelope's shape
  structurally, but does not add a new package — `cli/pyproject.toml`
  currently declares only `jsonschema>=4.23`. Flag this as a documented gap
  in the PR description, not a silent skip of design §9's intent.

There is no Protobuf-style "declaration order is the contract" caveat here
— JSON/OpenAPI schemas have no wire-position concept.

## File Structure

- Create `cli/src/modelable/emitters/_schema_mapping.py`: shared type/field-
  mapping logic extracted from `json_schema.py`, parameterized by `mdl` and
  `ref_base`.
- Create `cli/src/modelable/emitters/openapi.py`:
  `emit_openapi(workspace, out_dir) -> list[EmittedArtifact]`, projection-
  kind classification, document envelope assembly.
- Create `cli/tests/test_emit_openapi.py`: emitter and CLI tests.
- Modify `cli/src/modelable/emitters/json_schema.py`: replace inlined
  type/field-mapping functions (and `_resolve_projection_field_type`) with
  imports from `_schema_mapping.py`; behavior and output must stay
  byte-identical.
- Modify `cli/tests/test_emit_json_schema.py`: add a regression test proving
  pre/post-refactor byte-identical output.
- Modify `cli/src/modelable/emitters/targets.py`: register `openapi` as an
  implemented artifact target with default output `./dist/openapi`.
- Modify `cli/src/modelable/operations/compilation.py`: import
  `emit_openapi` and add the `if target == "openapi":` dispatch branch in
  `_emit_target`.
- Modify `cli/tests/test_codegen_targets.py`: add `"openapi"` to the target
  inventory list.
- Modify `docs/compiler-reference.md`, `docs/architecture.md`,
  `docs/language-reference.md`, `ROADMAP.md`: document the new target.
- Modify `CHANGELOG.md`: `### Added` entry under `## [Unreleased]`.
- Move `docs/superpowers/specs/2026-08-14-openapi-emission-design.md` →
  `docs/superpowers/specs/archived/2026-08-14-openapi-emission-design.md`,
  and this plan file → `docs/superpowers/plans/archived/`, in the PR that
  completes Task 8, per `AGENTS.md`'s archival policy.

---

## Task 1: Extract Shared Schema-Mapping Module With A Byte-Identical Regression Test

**Files:**
- Create: `cli/src/modelable/emitters/_schema_mapping.py`
- Modify: `cli/src/modelable/emitters/json_schema.py`
- Modify: `cli/tests/test_emit_json_schema.py`

- [x] **Step 1: Write the failing byte-identical regression test**

Append this test to `cli/tests/test_emit_json_schema.py`, exercising every
mapped `FieldType` variant:

```python
def test_emit_json_schema_output_unchanged_after_schema_mapping_extraction(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "customer-team"
  contact: "customer-team@example.com"
  description: "Customer identity and lifecycle."
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
    age?: int
    marketingConsent: bool = false
    address: object {
      line1: string
      line2?: string
    }
    active: bool
    balance: decimal(12, 2)
    tags: array<string>
    meta: map<string, int>
    status: enum(active, blocked)
    createdAt: timestamp
    birthDate: date
    wakeTime: time
    ttl: duration
    avatar: binary
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_json_schema(workspace, tmp_path / "out")
    assert len(artifacts) == 1
    rendered = render_artifact_text(artifacts[0])
    Draft202012Validator.check_schema(artifacts[0].content)
    # Pin the exact serialized shape so the extraction refactor in this task
    # cannot silently change json_schema.py's output.
    assert artifacts[0].content["properties"]["balance"] == {
        "type": "string",
        "pattern": r"^-?\d+(\.\d+)?$",
        "x-modelable-field": {"decimalPrecision": 12, "decimalScale": 2},
    }
    assert artifacts[0].content["properties"]["avatar"] == {
        "type": "string",
        "contentEncoding": "base64",
    }
    assert artifacts[0].content["properties"]["tags"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert artifacts[0].content["properties"]["meta"] == {
        "type": "object",
        "additionalProperties": {"type": "integer", "format": "int64"},
    }
    assert artifacts[0].content["properties"]["status"] == {
        "type": "string",
        "enum": ["active", "blocked"],
    }
    assert rendered.endswith("\n")
```

(`meta: map<string, int>`'s value type resolves through
`_primitive_to_json_schema("int")` which is `{"type": "integer", "format":
"int64"}` — confirmed against `json_schema.py:447` — not the
`_INTEGER_BOUNDS` table, which is keyed by `u8`..`i128`, not bare `int`.)

- [x] **Step 2: Verify the test passes against current (pre-refactor) code**

Run from `cli/`:

```bash
uv run pytest tests/test_emit_json_schema.py::test_emit_json_schema_output_unchanged_after_schema_mapping_extraction -q
```

Expected: pass. This is a baseline pin, not a red step — it must pass
*before* the extraction, proving the literals are correct against current
behavior, and must still pass *after* Step 3's extraction.

- [x] **Step 3: Extract the shared module**

Create `cli/src/modelable/emitters/_schema_mapping.py` by moving these
functions out of `json_schema.py` verbatim, except for the two added
parameters described in the plan's Architecture section:

- `_INTEGER_BOUNDS`
- `_primitive_to_json_schema`
- `_definition_name`, `_pascalize_part`
- `_resolve_projection_field_type` (moved here because it is shared
  type-resolution logic `openapi.py` also needs — see Task 2)
- `_type_to_json_schema(field_type, defs=None, path=None, *, mdl=None, ref_base="#/$defs/")` —
  add the `mdl`/`ref_base` keyword-only params; only the `RefType` branch
  changes:
  ```python
  if isinstance(field_type, RefType):
      if mdl is not None:
          from modelable.registry.resolver import resolve_ref_type

          resolved = resolve_ref_type(field_type, mdl)
          return {
              "$ref": f"{ref_base}{resolved.domain_name}.{resolved.model_name}.v{resolved.version.version}"
          }
      return {"type": "string", "x-modelable-ref": field_type.target}
  ```
  Every recursive call within this function (`ArrayType.item`,
  `MapType.value`, `ObjectType` fields via `_object_type_to_json_schema`,
  `NamedType`'s `$ref` construction) must thread `mdl=mdl, ref_base=ref_base`
  through so a `ref<>` nested inside an array/map/object resolves
  consistently. `NamedType`'s own `$ref` construction (currently hardcoded
  `f"#/$defs/{def_name}"`) must also use `ref_base` instead of the literal
  string, since OpenAPI's shared defs live under `#/components/schemas/`.
- `_object_type_to_json_schema(field_type, defs=None, path=None, *, mdl=None, ref_base="#/$defs/")` —
  same threading.
- `_field_to_json_schema(field, field_type=None, defs=None, path=None, *, mdl=None, ref_base="#/$defs/")` —
  annotation/wire-hint logic unchanged; forwards the two new params to
  `_type_to_json_schema`.
- `_wire_hint_to_json`.

Rewrite `json_schema.py` to `from modelable.emitters._schema_mapping import
(...)` these names. `_emit_model_version`, `_emit_projection_version`,
`_validate_schema`, `_add_domain_metadata`, `_add_lineage`,
`_version_spec_to_json`, `_field_default`, `emit_json_schema`,
`emit_json_schema_artifacts` all stay in `json_schema.py` verbatim, calling
the imported functions without passing `mdl`/`ref_base` so they keep using
the defaults (`mdl=None, ref_base="#/$defs/"`).

- [x] **Step 4: Verify the regression test and the full existing json_schema suite still pass**

Run from `cli/`:

```bash
uv run pytest tests/test_emit_json_schema.py -q
```

Expected: all pass, including the new regression test from Step 1, proving
the extraction changed no observable output.

## Task 2: Register The Target And Emit `components.schemas` For Request/Reply Auto-Projections

**Files:**
- Modify: `cli/tests/test_codegen_targets.py`
- Modify: `cli/src/modelable/emitters/targets.py`
- Create: `cli/src/modelable/emitters/openapi.py`
- Create: `cli/tests/test_emit_openapi.py`

- [x] **Step 1: Write the failing target-inventory test**

Update the target-list assertion in `cli/tests/test_codegen_targets.py`
(e.g. `test_codegen_formats_list_supported_and_deferred_targets`) so the
expected list includes `"openapi"` appended after `"grpc"` (read the file
first to get the exact current list and assertion name before editing).

- [x] **Step 2: Verify the test fails**

Run from `cli/`:

```bash
uv run pytest tests/test_codegen_targets.py -k "list_supported_and_deferred" -q
```

Expected: failure — actual target list does not include `"openapi"`.

- [x] **Step 3: Register the target**

Append to `CODEGEN_TARGETS` in `cli/src/modelable/emitters/targets.py`:

```python
    CodegenTarget(
        name="openapi",
        description="OpenAPI 3.1 component schemas generated from API-facing projections",
        status="implemented",
        kind="artifact",
        default_out_dir=Path("./dist/openapi"),
    ),
```

`supports_compat_check` is omitted (defaults to `False`) per design §6.5.

- [x] **Step 4: Verify the target-inventory test passes**

Run from `cli/`:

```bash
uv run pytest tests/test_codegen_targets.py -k "list_supported_and_deferred" -q
```

Expected: pass.

- [x] **Step 5: Write the failing request/reply emission test**

Create `cli/tests/test_emit_openapi.py`:

```python
from __future__ import annotations

import json

from click.testing import CliRunner
from jsonschema import Draft202012Validator

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.emitters.openapi import emit_openapi

_AUTO_PROJECTION_FIXTURE = """
domain customer {
  owner: "customer-platform"

  entity Customer @ 1 (additive) {
    @key
    customerId: uuid
    legalName: string
    @pii
    email: string
    @classification("secret")
    internalRiskNotes?: string
    status: enum(active, suspended, deleted)
    @server
    createdAt: timestamp
    @server
    updatedAt?: timestamp
  }

  auto projections Customer @ 1 {
    db

    request exclude [internalRiskNotes]

    reply exclude [@pii, @classification("secret")]

    event on [created, deleted]
  }
}
"""


def test_emit_openapi_emits_one_document_with_request_and_reply_schemas(tmp_path):
    (tmp_path / "customer.mdl").write_text(_AUTO_PROJECTION_FIXTURE, encoding="utf-8")
    workspace = load_workspace(tmp_path)

    artifacts = emit_openapi(workspace, tmp_path / "out")

    assert len(artifacts) == 1
    doc = artifacts[0]
    assert doc.target == "openapi"
    assert doc.path == tmp_path / "out" / "openapi.json"
    assert doc.artifact_id == "openapi"

    schemas = doc.content["components"]["schemas"]
    assert "customer.CustomerRequest.v1" in schemas
    assert "customer.CustomerReply.v1" in schemas
    assert doc.content["openapi"] == "3.1.0"
    assert doc.content["paths"] == {}

    request_props = schemas["customer.CustomerRequest.v1"]["properties"]
    assert "createdAt" not in request_props  # @server field excluded from request
    assert "internalRiskNotes" not in request_props  # explicit exclude
    assert "customerId" in request_props
    assert "email" in request_props  # @pii allowed in request, only excluded from reply

    reply_props = schemas["customer.CustomerReply.v1"]["properties"]
    assert "email" not in reply_props  # @pii excluded from reply
    assert "internalRiskNotes" not in reply_props  # @classification("secret") excluded
    assert "customerId" in reply_props
    assert "createdAt" in reply_props  # @server fields ARE included in reply

    assert schemas["customer.CustomerRequest.v1"]["x-modelable"]["kind"] == "request"
    assert schemas["customer.CustomerReply.v1"]["x-modelable"]["kind"] == "reply"
    assert schemas["customer.CustomerRequest.v1"]["x-modelable"]["domain"] == "customer"
    assert "customer.CustomerDb.v1" not in schemas  # db kind excluded by default
```

Before writing this fixture for real, read
`cli/tests/fixtures/auto_projection_complex.mdl` and
`cli/tests/test_auto_projection.py` to confirm the exact `auto projections`
block grammar (the `exclude [...]`/`on [...]` syntax above is a
best-effort reconstruction and must be checked against real fixtures).

- [x] **Step 6: Verify the test fails**

Run from `cli/`:

```bash
uv run pytest tests/test_emit_openapi.py::test_emit_openapi_emits_one_document_with_request_and_reply_schemas -q
```

Expected: failure with `ModuleNotFoundError: No module named 'modelable.emitters.openapi'`.

- [x] **Step 7: Implement `openapi.py`**

Create `cli/src/modelable/emitters/openapi.py`:

```python
from __future__ import annotations

from pathlib import PurePath

from jsonschema import Draft202012Validator

from modelable.compiler.workspace import Workspace
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.diagnostics import validation_failed
from modelable.emitters._schema_mapping import (
    _field_to_json_schema,
    _resolve_projection_field_type,
)
from modelable.governance.por import build_por_reference
from modelable.parser.ir import DomainDef, ProjectionVersion

_REF_BASE = "#/components/schemas/"

# Duplicated from planner/planner.py::_generated_projection_name rather than
# imported, because that symbol is private and this emitter needs only the
# five-entry suffix table, not the rest of expansion. Keep in sync if the
# planner's naming convention changes.
_AUTO_PROJECTION_SUFFIXES: dict[str, str] = {
    "db": "Db",
    "request": "Request",
    "reply": "Reply",
    "event": "Event",
}

_EMITTED_AUTO_KINDS = {"request", "reply", "event"}  # "db" excluded by default


def emit_openapi(workspace: Workspace, out_dir: PurePath) -> list[EmittedArtifact]:
    """Emit a single OpenAPI 3.1 document with `components.schemas` for every
    API-facing projection in the workspace."""
    mdl = workspace.mdl
    schemas: dict[str, dict] = {}
    warnings: list[str] = []

    for domain in mdl.domains:
        kind_lookup = _projection_kind_lookup(domain)
        for projection_name, versions in domain.projections.items():
            projection_kind = kind_lookup.get(projection_name)
            for version in versions:
                if not _should_emit(version, projection_kind):
                    continue
                schema_id, schema, field_warnings = _projection_to_schema(
                    domain, projection_name, version, projection_kind, mdl, schemas
                )
                schemas[schema_id] = schema
                warnings.extend(field_warnings)

    document: dict = {
        "openapi": "3.1.0",
        "info": {
            "title": getattr(getattr(mdl, "workspace", None), "name", None) or "Modelable API",
            "version": "1.0.0",
        },
        "components": {"schemas": schemas},
        "paths": {},
    }

    artifact = EmittedArtifact(
        target="openapi",
        ref="workspace",
        artifact_id="openapi",
        path=out_dir / "openapi.json",
        content=document,
        content_hash=compute_content_hash(document),
        warnings=warnings,
    )
    _validate_components_schemas(artifact)
    return [artifact]


def _projection_kind_lookup(domain: DomainDef) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for decl in domain.auto_projections:
        for target in decl.targets:
            name = f"{decl.model}{_AUTO_PROJECTION_SUFFIXES[target.kind]}"
            lookup[name] = target.kind
    return lookup


def _should_emit(version: ProjectionVersion, kind: str | None) -> bool:
    if kind is None:
        return True  # hand-authored: always included by default (design §6.2)
    return kind in _EMITTED_AUTO_KINDS


def _projection_to_schema(
    domain, projection_name, version: ProjectionVersion, projection_kind, mdl, defs: dict
) -> tuple[str, dict, list[str]]:
    """Build a components.schemas entry for one projection version, reusing
    _field_to_json_schema/_resolve_projection_field_type from
    _schema_mapping.py. Mirrors json_schema.py::_emit_projection_version's
    schema shape (title, x-modelable, x-modelable-por, properties/required),
    with two differences: `x-modelable.kind` is the specific
    request/reply/event kind (falling back to "projection" for
    hand-authored projections) instead of json_schema.py's hardcoded
    "projection", and nested NamedType/ObjectType sub-schemas are written
    into `defs` (a view onto the same `schemas` dict emit_openapi is
    building) so they become sibling components.schemas entries instead of
    a separate $defs block.
    """
    warnings: list[str] = []
    properties: dict = {}
    required: list[str] = []
    for field in version.fields:
        field_type = _resolve_projection_field_type(field, version, mdl)
        properties[field.name] = _field_to_json_schema(
            field, field_type, defs, [field.name], mdl=mdl, ref_base=_REF_BASE
        )
        required.append(field.name)  # projection fields have no `?` syntax yet

    schema = {
        "type": "object",
        "title": projection_name,
        "x-modelable": {
            "domain": domain.name,
            "name": projection_name,
            "kind": projection_kind or "projection",
            "sourceEntity": f"{version.source.model}@{version.source.version}",
            "version": version.version,
            "changeKind": getattr(version, "change_kind", None),
        },
        "x-modelable-por": build_por_reference(domain, projection_name, version),
        "properties": properties,
        "required": required,
    }
    schema_id = f"{domain.name}.{projection_name}.v{version.version}"
    return schema_id, schema, warnings


def _validate_components_schemas(artifact: EmittedArtifact) -> None:
    fragment = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": artifact.content["components"]["schemas"],
    }
    try:
        Draft202012Validator.check_schema(fragment)
    except Exception as exc:
        artifact.warnings.append(validation_failed(str(artifact.path), str(exc)))
```

Before finalizing, read `json_schema.py::_emit_projection_version` (~line
124-203) side-by-side and correct any field-name/signature mismatch in the
sketch above (e.g. the exact `build_por_reference` call signature and
`version.source`'s attribute names) — this sketch is written from the
research summary, not from re-reading the function at implementation time,
and must be reconciled against the real source before being treated as
final.

- [x] **Step 8: Verify the request/reply emission test passes**

Run from `cli/`:

```bash
uv run pytest tests/test_emit_openapi.py::test_emit_openapi_emits_one_document_with_request_and_reply_schemas -q
```

Expected: pass.

## Task 3: Hand-Authored Projection Inclusion, Event-Kind Inclusion, Db-Kind Exclusion

**Files:**
- Modify: `cli/tests/test_emit_openapi.py`
- Modify: `cli/src/modelable/emitters/openapi.py` (only if gaps found)

- [ ] **Step 1: Write the failing hand-authored + event + db test**

Append to `cli/tests/test_emit_openapi.py`:

```python
def test_emit_openapi_includes_hand_authored_and_event_excludes_db(tmp_path):
    (tmp_path / "customer.mdl").write_text(_AUTO_PROJECTION_FIXTURE, encoding="utf-8")
    (tmp_path / "billing.mdl").write_text(
        """
domain billing {
  owner: "billing-team"

  projection BillingCustomer @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    legalName <- c.legalName
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    artifacts = emit_openapi(workspace, tmp_path / "out")
    schemas = artifacts[0].content["components"]["schemas"]

    assert "billing.BillingCustomer.v1" in schemas
    assert schemas["billing.BillingCustomer.v1"]["x-modelable"]["kind"] == "projection"

    assert "customer.CustomerEvent.v1" in schemas
    assert schemas["customer.CustomerEvent.v1"]["x-modelable"]["kind"] == "event"

    assert "customer.CustomerDb.v1" not in schemas


def test_compile_openapi_writes_single_document(tmp_path):
    mdl = tmp_path / "customer.mdl"
    mdl.write_text(_AUTO_PROJECTION_FIXTURE, encoding="utf-8")

    out = tmp_path / "dist"
    runner = CliRunner()
    result = runner.invoke(cli, ["compile", str(mdl), "--target", "openapi", "--out", str(out)])

    assert result.exit_code == 0, result.output
    doc_path = out / "openapi.json"
    assert doc_path.exists()
    doc = json.loads(doc_path.read_text(encoding="utf-8"))
    assert doc["openapi"] == "3.1.0"
    assert "customer.CustomerRequest.v1" in doc["components"]["schemas"]
```

Read `cli/tests/test_emit_protobuf.py`'s `test_compile_protobuf_*` tests
first to match the exact `CliRunner` invocation pattern this project uses
(e.g. whether it runs inside `runner.isolated_filesystem()`).

`test_compile_openapi_writes_single_document` depends on Task 6's CLI
dispatch wiring and will fail with `Unknown compilation target: openapi`
until that lands — that's expected; it's re-verified at the end of Task 6.

- [ ] **Step 2: Verify the hand-authored/event/db test fails**

Run from `cli/`:

```bash
uv run pytest tests/test_emit_openapi.py::test_emit_openapi_includes_hand_authored_and_event_excludes_db -q
```

Expected: failure if Task 2's `_projection_to_schema` has any gap in
`x-modelable.kind` (should be `projection_kind or "projection"`); otherwise
this may already pass by construction, since `_should_emit` and
`_projection_kind_lookup` already implement the correct rule.

- [ ] **Step 3: Fix any gap found**

Fix `x-modelable.kind` in `_projection_to_schema` if needed; classification
logic itself (`_should_emit`/`_projection_kind_lookup`) should not need
changes.

- [ ] **Step 4: Verify the test passes**

Run from `cli/`:

```bash
uv run pytest tests/test_emit_openapi.py::test_emit_openapi_includes_hand_authored_and_event_excludes_db -q
```

Expected: pass.

## Task 4: Type Mapping Edge Cases — Decimal, Fixed Binary, Map, `ref<>` as `$ref`, Enum

**Files:**
- Modify: `cli/tests/test_emit_openapi.py`
- Modify: `cli/src/modelable/emitters/openapi.py` (only if gaps found)

- [ ] **Step 1: Write the failing type-mapping tests**

Append to `cli/tests/test_emit_openapi.py`:

```python
def test_emit_openapi_type_mapping_matches_design_table(tmp_path):
    (tmp_path / "catalog.mdl").write_text(
        """
domain catalog {
  owner: "catalog-team"

  entity Product @ 1 (additive) {
    @key productId: uuid
    price: decimal(10, 2)
    thumbnailHash: binary(32)
    tags: array<string>
    attributes: map<string, string>
    status: enum(draft, published, archived)
  }

  projection ProductSummary @ 1
    from catalog.Product @ 1 as p
  {
    productId <- p.productId
    price <- p.price
    thumbnailHash <- p.thumbnailHash
    tags <- p.tags
    attributes <- p.attributes
    status <- p.status
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    artifacts = emit_openapi(workspace, tmp_path / "out")
    props = artifacts[0].content["components"]["schemas"]["catalog.ProductSummary.v1"]["properties"]

    assert props["price"]["type"] == "string"
    assert props["price"]["pattern"] == r"^-?\d+(\.\d+)?$"
    assert props["thumbnailHash"] == {
        "type": "string",
        "contentEncoding": "base64",
        "x-modelable-fixed-length": 32,
    }
    assert props["tags"] == {"type": "array", "items": {"type": "string"}}
    assert props["attributes"] == {"type": "object", "additionalProperties": {"type": "string"}}
    assert props["status"] == {"type": "string", "enum": ["draft", "published", "archived"]}


def test_emit_openapi_ref_type_resolves_to_dollar_ref(tmp_path):
    (tmp_path / "catalog.mdl").write_text(
        """
domain catalog {
  owner: "catalog-team"

  entity Brand @ 1 (additive) {
    @key brandId: uuid
    name: string
  }

  entity Product @ 1 (additive) {
    @key productId: uuid
    brand: ref<catalog.Brand @ 1>
  }

  projection ProductSummary @ 1
    from catalog.Product @ 1 as p
  {
    productId <- p.productId
    brand <- p.brand
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    artifacts = emit_openapi(workspace, tmp_path / "out")
    schemas = artifacts[0].content["components"]["schemas"]
    brand_prop = schemas["catalog.ProductSummary.v1"]["properties"]["brand"]

    assert brand_prop == {"$ref": "#/components/schemas/catalog.Brand.v1"}
```

The `ref<catalog.Brand @ 1>` syntax is confirmed against
`cli/tests/test_emit_typescript.py:798` (`customerRef: ref<customer.Customer
@ 1>`) — no further grammar verification needed.

- [ ] **Step 2: Verify tests fail or pass depending on what's already implemented**

Run from `cli/`:

```bash
uv run pytest tests/test_emit_openapi.py::test_emit_openapi_type_mapping_matches_design_table tests/test_emit_openapi.py::test_emit_openapi_ref_type_resolves_to_dollar_ref -q
```

Expected: the decimal/binary/array/map/enum assertions should already pass
(Task 1/2 wired `_field_to_json_schema` through unchanged for these types).
The `$ref` test is the one most likely to fail if `mdl=mdl,
ref_base=_REF_BASE` isn't threaded correctly from `_projection_to_schema`
through to the `_field_to_json_schema` call.

- [ ] **Step 3: Fix any gap found**

Most likely fix: a missing `mdl=mdl, ref_base=_REF_BASE` keyword pair on the
`_field_to_json_schema` call site inside `_projection_to_schema`.

- [ ] **Step 4: Verify all type-mapping tests pass**

Run from `cli/`:

```bash
uv run pytest tests/test_emit_openapi.py -q
```

Expected: pass.

## Task 5: Document Envelope Assembly, Determinism, Self-Validation

**Files:**
- Modify: `cli/tests/test_emit_openapi.py`
- Modify: `cli/src/modelable/emitters/openapi.py` (only if gaps found)

- [ ] **Step 1: Write the failing determinism + envelope-shape tests**

Append to `cli/tests/test_emit_openapi.py`:

```python
def test_emit_openapi_is_deterministic_across_runs(tmp_path):
    (tmp_path / "customer.mdl").write_text(_AUTO_PROJECTION_FIXTURE, encoding="utf-8")
    workspace = load_workspace(tmp_path)

    first = emit_openapi(workspace, tmp_path / "out")
    second = emit_openapi(workspace, tmp_path / "out")

    assert first[0].content_hash == second[0].content_hash
    assert json.dumps(first[0].content, sort_keys=True) == json.dumps(second[0].content, sort_keys=True)


def test_emit_openapi_document_envelope_is_minimal_and_valid(tmp_path):
    (tmp_path / "customer.mdl").write_text(_AUTO_PROJECTION_FIXTURE, encoding="utf-8")
    workspace = load_workspace(tmp_path)

    artifacts = emit_openapi(workspace, tmp_path / "out")
    doc = artifacts[0].content

    assert set(doc.keys()) == {"openapi", "info", "components", "paths"}
    assert doc["paths"] == {}
    assert "title" in doc["info"]
    assert "version" in doc["info"]
    assert artifacts[0].warnings == []


def test_emit_openapi_components_schemas_validate_as_json_schema_2020_12(tmp_path):
    (tmp_path / "customer.mdl").write_text(_AUTO_PROJECTION_FIXTURE, encoding="utf-8")
    workspace = load_workspace(tmp_path)

    artifacts = emit_openapi(workspace, tmp_path / "out")
    fragment = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": artifacts[0].content["components"]["schemas"],
    }
    Draft202012Validator.check_schema(fragment)  # raises on failure
```

- [ ] **Step 2: Verify the tests pass**

Run from `cli/`:

```bash
uv run pytest tests/test_emit_openapi.py::test_emit_openapi_is_deterministic_across_runs tests/test_emit_openapi.py::test_emit_openapi_document_envelope_is_minimal_and_valid tests/test_emit_openapi.py::test_emit_openapi_components_schemas_validate_as_json_schema_2020_12 -q
```

Expected: these should already pass given Task 2's `emit_openapi`
implementation (dict construction is deterministic given stable
domain/projection iteration order, and `_validate_components_schemas` is
already wired). If `warnings == []` fails, treat it as a signal that an
earlier task's implementation isn't fully correct, not new work — debug
back into Task 2/3/4 rather than patching around it here.

- [ ] **Step 3: Fix any gap found, then re-verify**

Run from `cli/`:

```bash
uv run pytest tests/test_emit_openapi.py -q
```

Expected: pass.

## Task 6: Wire The Compile Command Dispatch

**Files:**
- Modify: `cli/src/modelable/operations/compilation.py`

- [ ] **Step 1: Verify the CLI test still fails**

Run from `cli/`:

```bash
uv run pytest tests/test_emit_openapi.py::test_compile_openapi_writes_single_document -q
```

Expected: failure — `Unknown compilation target: openapi` (or equivalent;
confirm exact error text in `compilation.py`'s `_emit_target` before relying
on it in review).

- [ ] **Step 2: Import and dispatch the emitter**

In `cli/src/modelable/operations/compilation.py`, add near the other
emitter imports:

```python
from modelable.emitters.openapi import emit_openapi
```

Add a dispatch branch in `_emit_target` (~line 1352-1404), after the
`odcs` branch and before `protobuf`/`grpc` (matching the append-after-most-
recently-shipped-target convention already visible there):

```python
    if target == "openapi":
        return emit_openapi(workspace, output)
```

Confirm `_DEFAULT_OUT_DIRS` (derived from `list_implemented_codegen_targets()`,
`compilation.py` ~line 59-63) picks up `Path("./dist/openapi")`
automatically from Task 2's registration — no separate edit needed.

- [ ] **Step 3: Verify the CLI test passes, then the full openapi test file**

Run from `cli/`:

```bash
uv run pytest tests/test_emit_openapi.py -q
```

Expected: pass, all tests from Tasks 2-6.

## Task 7: Documentation And Changelog

**Files:**
- Modify: `docs/compiler-reference.md`
- Modify: `docs/architecture.md`
- Modify: `docs/language-reference.md`
- Modify: `ROADMAP.md`
- Modify: `CHANGELOG.md`
- Move: `docs/superpowers/specs/2026-08-14-openapi-emission-design.md` →
  `docs/superpowers/specs/archived/2026-08-14-openapi-emission-design.md`
- Move: this plan file → `docs/superpowers/plans/archived/`

- [ ] **Step 1: Update `docs/compiler-reference.md`**

Line 37, replace:

```
| OpenAPI | 5 | Deferred |
```

with:

```
| OpenAPI | 5 | Implemented local artifact (schema-only; paths/operations deferred to a future phase) |
```

- [ ] **Step 2: Update `docs/architecture.md`**

Line 1207-1208, replace:

```
- Avro, OpenAPI, and AsyncAPI generation (Phase 5) — import-only support exists
  via LLM-assisted generators.
```

with:

```
- Avro and AsyncAPI generation (Phase 5) — import-only support exists via
  LLM-assisted generators. OpenAPI export is implemented (schema-only;
  paths/operations are a deferred follow-up — see
  docs/superpowers/specs/archived/2026-08-14-openapi-emission-design.md).
  OpenAPI import remains LLM-assisted only.
```

- [ ] **Step 3: Update `docs/language-reference.md` §4.3**

Line 711, remove `openapi` from the "no implemented emitter" list — current
text:

```
these names also have no implemented emitter behind them at all yet
(`openapi`, `avro`, `asyncapi`, and the `mysql`/`sqlite` SQL dialects — only
`postgres` and `clickhouse` are implemented). See Slice B3 in
```

becomes:

```
these names also have no implemented emitter behind them at all yet
(`avro`, `asyncapi`, and the `mysql`/`sqlite` SQL dialects — only
`postgres` and `clickhouse` are implemented; `openapi` is implemented, see
`modelable compile --target openapi`, though it currently emits schemas
only, not paths/operations). See Slice B3 in
```

- [ ] **Step 4: Update `ROADMAP.md` Slice F2**

Lines 769-772, replace:

```
#### Slice F2 — OpenAPI emission

After D1-D4, C1 (shipped), and C3 (shipped). Do not treat grammar acceptance
of `openapi` as implemented emitter support.
```

with:

```
#### Slice F2 — OpenAPI emission

Phase A (schema-only `components.schemas` emission) is implemented; see
`docs/superpowers/specs/archived/2026-08-14-openapi-emission-design.md`.
Only Phase D (fidelity follow-ups: constraints, presence/nullability, named
enum reuse, discriminated unions) remains gated on D1-D4. Phase B (paths and
operations) needs its own accepted grammar design (§7 of the linked design
document) before implementation.
```

- [ ] **Step 5: Add the CHANGELOG entry**

Read the current `## [Unreleased]` section of `CHANGELOG.md` first to match
its exact bullet style, then add under `### Added`:

```
- `modelable compile --target openapi` emits a deterministic OpenAPI 3.1
  document (`components.schemas` plus a minimal valid `paths: {}` envelope)
  from `request`/`reply`/`event` auto-projections and hand-authored
  projections. `{Entity}Db` projections are excluded by default; there is no
  opt-in/opt-out syntax yet (deferred follow-up). Paths/operations
  generation is out of scope for this slice.
```

- [ ] **Step 6: Verify doc references**

Run from repo root:

```bash
rg -n "compile --target openapi|openapi target|2026-08-14-openapi-emission-design" ROADMAP.md docs CHANGELOG.md
```

Expected: matches in compiler reference, architecture, language reference,
roadmap, and changelog.

- [ ] **Step 7: Archive the design doc and this plan**

Move `docs/superpowers/specs/2026-08-14-openapi-emission-design.md` to
`docs/superpowers/specs/archived/2026-08-14-openapi-emission-design.md`
(same filename), per `AGENTS.md`'s policy of moving a plan and any spec it
implements into `.../archived/` in the same PR once merged. Move this plan
file into `docs/superpowers/plans/archived/` as part of Task 8's final
commit.

## Task 8: Final Verification

**Files:** all touched files

- [ ] **Step 1: Run focused tests**

Run from `cli/`:

```bash
uv run pytest tests/test_emit_openapi.py tests/test_emit_json_schema.py tests/test_codegen_targets.py --tb=short -q
```

Expected: pass.

- [ ] **Step 2: Run the required four-command pre-commit gate**

Run from `cli/`:

```bash
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

Expected: all four pass cleanly. If the mypy baseline check reports new
errors, check whether they're real typing gaps (most likely candidate: the
new `mdl`/`ref_base` keyword params on `_schema_mapping.py` functions, or
`openapi.py`'s `_projection_to_schema` needing concrete parameter types
instead of implicit `Any`) before assuming a baseline regeneration is safe.

- [ ] **Step 3: Inspect the final diff**

Run from repo root:

```bash
git diff --stat
git diff -- cli/src/modelable/emitters/openapi.py cli/src/modelable/emitters/_schema_mapping.py cli/src/modelable/emitters/json_schema.py cli/src/modelable/emitters/targets.py cli/src/modelable/operations/compilation.py cli/tests/test_emit_openapi.py cli/tests/test_emit_json_schema.py cli/tests/test_codegen_targets.py docs/compiler-reference.md docs/architecture.md docs/language-reference.md ROADMAP.md CHANGELOG.md
```

Expected: diff contains only the OpenAPI Phase A target, the
`json_schema.py` extraction refactor (unchanged behavior), and
documentation. Confirm `git status` shows the design spec and this plan
moved into their respective `archived/` directories.

- [ ] **Step 4: Confirm json_schema.py's behavior is provably unchanged**

Run from `cli/`:

```bash
git diff main -- src/modelable/emitters/json_schema.py
```

Confirm every removed line is a straight function-body relocation into
`_schema_mapping.py` with no logic changes. The actual proof is
`test_emit_json_schema_output_unchanged_after_schema_mapping_extraction`
(Task 1) plus the full pre-existing `test_emit_json_schema.py` suite
passing — the diff review is a sanity check, not the proof.

## Self-Review

**Spec coverage:**

- Covered: `compile --target openapi` registration (§6.1); single
  workspace-wide `openapi.json` with `openapi`/`info`/`components.schemas`/
  `paths: {}` envelope (§6.1); inclusion rule for request/reply/event
  auto-projections and hand-authored projections with db-kind exclusion by
  default (§6.2); full type-mapping table reuse via the shared
  `_schema_mapping.py` module including the `RefType` → `$ref` divergence
  from JSON Schema (§6.3); `x-modelable`/`x-modelable-por` metadata on every
  schema (§6.4); `supports_compat_check=False` (§6.5); determinism;
  self-validation of `components.schemas` as JSON Schema 2020-12; and
  documentation/CHANGELOG/archival per `AGENTS.md` (§10).
- Deferred by design and explicitly not implemented here: paths/operations
  (§7, Phase B), import hardening (§8, Phase C), D1-D4 fidelity follow-ups
  (Phase D), `generate {}`-block-scoped inclusion/exclusion opt-in/opt-out
  syntax (§6.2 — resolved as "default rule only, no syntax yet"), full
  OpenAPI 3.1 document meta-schema validation via a new dependency (§9 —
  resolved as "validate `components.schemas` as JSON Schema 2020-12 only,
  flag the gap explicitly").

**Placeholder scan:**

- Task 2 Step 7's `openapi.py` sketch is explicitly flagged as needing
  reconciliation against `json_schema.py::_emit_projection_version`'s real
  source (exact `build_por_reference` signature, `version.source` attribute
  names) before being treated as final — called out inline, not silently
  guessed.
- Task 2 Step 5's fixture grammar (`auto projections ... exclude [...] on
  [...]`) is flagged as needing verification against
  `cli/tests/fixtures/auto_projection_complex.mdl` before being trusted
  verbatim.
- The `ref<>` fixture in Task 4 was independently confirmed against
  `cli/tests/test_emit_typescript.py:798`, so no placeholder risk remains
  there.
- No other placeholder or "TBD" steps remain; every other step has literal
  test code, an exact pytest invocation, and an exact expected outcome.

**Type consistency:**

- `emit_openapi(workspace: Workspace, out_dir: PurePath) -> list[EmittedArtifact]`
  matches the existing `emit_<target>(workspace, out_dir) -> list[EmittedArtifact]`
  convention used by every other emitter.
- The shared `_schema_mapping.py` functions gain
  `mdl: MdlFile | None = None, ref_base: str = "#/$defs/"` keyword-only
  parameters with defaults that preserve `json_schema.py`'s exact current
  behavior — no call site in `json_schema.py` needs to change its call
  shape, only its imports.
- `RefType` resolution reuses the existing, already-typed
  `modelable.registry.resolver.resolve_ref_type(field_type: RefType, mdl: MdlFile) -> ResolvedModelRef`
  helper (confirmed at `registry/resolver.py:66`) rather than inventing new
  resolution logic, matching its existing use in `emitters/typescript.py:91`.

---

### Critical Files for Implementation

- `cli/src/modelable/emitters/json_schema.py`
- `cli/src/modelable/emitters/_schema_mapping.py` (new)
- `cli/src/modelable/emitters/openapi.py` (new)
- `cli/src/modelable/parser/ir.py`
- `cli/src/modelable/registry/resolver.py`
- `cli/src/modelable/planner/planner.py`
- `cli/src/modelable/operations/compilation.py`
- `cli/src/modelable/emitters/targets.py`
- `cli/tests/test_emit_json_schema.py`
- `cli/tests/test_emit_typescript.py`
- `cli/tests/test_auto_projection.py`
