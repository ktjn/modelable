# Conversational Workspace Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe, reusable conversational management layer that answers grounded workspace questions, previews complete entity and projection changes with textual impact reports, and applies an explicitly confirmed multi-file change set.

**Architecture:** A schema-constrained conversational planner produces closed typed plans. A provider-independent `WorkspaceEditor` applies those operations to copied IR documents, renders and validates a staged workspace, calculates compatibility and dependency impact, and owns fingerprinted preview/apply behavior. The CLI chat is a thin adapter over a reusable conversation service; future language-server and VS Code clients consume the same service boundary.

**Tech Stack:** Python 3.14, Pydantic v2, Lark-backed Modelable parser, Click/Rich CLI, pytest, existing compatibility and workspace services.

**Design:** [Conversational Workspace Management — Design](../../specs/archived/2026-07-18-conversational-workspace-management-design.md)

## Global Constraints

- Existing model and projection versions are immutable by default; changes append the next version unless `edit_mode="draft"` is explicit.
- Provider output may select typed operations but may not contain raw source patches, filesystem paths, shell commands, or validation overrides.
- Only one pending change set exists per chat session, and confirmation applies only to its exact ID and source fingerprints.
- Every preview is plain text and includes assumptions, changed definitions, downstream impact, compatibility/validation findings, and unified diffs.
- Every multi-file application stages all output, checks fingerprints, revalidates, replaces files with rollback protection, and reloads the workspace before reporting success.
- The first slice excludes VS Code UI, compilation, registry synchronization, publishing, and external-service actions.
- Do not change the public behavior of the standalone `modelable update` command while migrating chat.
- Before every commit, run from `cli/`: `uv run ruff format .`, `uv run ruff check .`, `uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes`, and `uv run pytest --tb=short`.

## Planned File Structure

- `cli/src/modelable/llm/render.py`: complete semantic rendering of existing IR so editor rewrites do not discard declarations.
- `cli/src/modelable/llm/conversation_plan.py`: closed Pydantic schemas for query, clarification, unsupported, and mutation plans.
- `cli/src/modelable/llm/workspace_editor.py`: provider-independent staging, typed operation execution, impact calculation, diffing, fingerprint checks, and rollback-protected application.
- `cli/src/modelable/llm/conversation_planner.py`: provider request construction, structured parsing, one repair attempt, and offline routing.
- `cli/src/modelable/llm/workspace_query.py`: deterministic execution of typed ownership, summary, lineage, dependency, index, compatibility, and validation queries.
- `cli/src/modelable/llm/conversation.py`: session state, pending proposal lifecycle, refinement, `/apply`, `/discard`, reload, and textual rendering.
- `cli/src/modelable/llm/chat.py`: compatibility wrapper and slash-command routing onto the new conversation service.
- `cli/src/modelable/commands/llm.py`: construct one conversation session for interactive and single-message CLI use.
- `cli/tests/test_llm_render_roundtrip.py`: semantic renderer round-trip coverage.
- `cli/tests/test_conversation_plan.py`: closed plan-schema and provider-planner tests.
- `cli/tests/test_workspace_editor.py`: editor operations, versioning, staging, impact, stale-state, and rollback tests.
- `cli/tests/test_workspace_query.py`: deterministic typed query tests.
- `cli/tests/test_conversation.py`: end-to-end session, preview, refinement, confirmation, and offline tests.
- `cli/tests/test_llm_provider_integration.py`: CLI/provider regression and new chat integration cases.
- `docs/architecture.md`, `docs/cli-reference.md`, `CHANGELOG.md`, `ROADMAP.md`: public behavior, reusable editor boundary, release note, and shipped-state updates.

---

### Task 1: Make `.mdl` rendering semantically lossless

**Files:**
- Create: `cli/tests/test_llm_render_roundtrip.py`
- Modify: `cli/src/modelable/llm/render.py:1-260`

**Interfaces:**
- Consumes: `parse_text_to_ir(text: str) -> MdlFile`
- Produces: `render_mdl(mdl: MdlFile) -> str` whose reparsed IR is equal to the input IR for every parser-supported construct used by workspace editing

- [ ] **Step 1: Write the failing representative round-trip test**

```python
from modelable.llm.render import render_mdl
from modelable.parser.parse import parse_text_to_ir


def test_render_mdl_preserves_editor_relevant_ir() -> None:
    source = """
domain customer {
  owner: "customer-team"
  contact: "customer@example.com"
  description: "Customer contracts"

  semantic CustomerId: uuid {
    registry: true
  }

  entity Customer @ 1 (additive) {
    reserved protobuf {
      numbers: [9]
      names: ["legacy_name"]
    }
    access {
      entity: billing [read, project]
      property email: support [read]
    }
    @key customerId: CustomerId
    @pii @classification("confidential") email?: string
    address: object { street: string city: string postalCode: string country: string }
  }

  index Customer @ 1 {
    primary customerId
    secondary byEmail {
      key: [email]
      sort: [customerId desc]
      unique: true
    }
  }
}

domain billing {
  owner: "billing-team"
  projection BillingCustomer @ 1
    from customer.Customer @ 1 as c
    left join customer.Customer @ 1 as parent on c.customerId == parent.customerId
      cardinality: many_to_one
    where c.email != ""
    group by c.customerId
  {
    reserved protobuf {
      numbers: [4]
      names: ["old_email"]
    }
    access {
      entity: reporting [read]
    }
    customerId <- c.customerId
    emailCount = count(c.email)
  }
}

workspace default {
  ai {
    provider: "ollama"
    model: "llama3.1"
    repair_attempts: 2
  }
}
"""
    parsed = parse_text_to_ir(source)
    reparsed = parse_text_to_ir(render_mdl(parsed))

    assert reparsed == parsed
```

- [ ] **Step 2: Run the test and verify the current renderer is lossy**

Run: `cd cli; uv run pytest tests/test_llm_render_roundtrip.py::test_render_mdl_preserves_editor_relevant_ir -v`

Expected: FAIL because `render_mdl()` currently omits at least contact, semantic types, indexes, access blocks, reservations, join metadata, source filters, and AI repair attempts.

- [ ] **Step 3: Add focused renderer helpers for every missing IR field**

Update `render.py` imports to include `AccessBlock`, `AccessGrant`,
`FixedBinaryType`, `IndexDecl`, `JoinRef`, `ProtobufReservations`,
`SecondaryIndexDecl`, `SemanticTypeDecl`, `SortField`, and `VersionPinned`.
Extend `_render_domain()` in this deterministic order:

```python
def _render_domain(domain: DomainDef) -> list[str]:
    lines = [f"domain {domain.name} {{"]
    if domain.owner:
        lines.append(f'  owner: "{domain.owner}"')
    if domain.contact:
        lines.append(f'  contact: "{domain.contact}"')
    if domain.description:
        lines.append(f'  description: "{domain.description}"')
    for semantic in domain.semantic_types:
        lines.extend(_indent(_render_semantic_type(semantic), 2))
    for model_name in sorted(domain.models):
        for version in domain.models[model_name]:
            lines.extend(_indent(_render_model(model_name, version), 2))
    for projection_name in sorted(domain.projections):
        for version in domain.projections[projection_name]:
            if not version.auto_generated:
                lines.extend(_indent(_render_projection(projection_name, version), 2))
    for declaration in domain.index_decls:
        lines.extend(_indent(_render_index(declaration), 2))
    for declaration in domain.auto_projections:
        lines.extend(_indent(_render_auto_projection(declaration), 2))
    for target in domain.generate_targets:
        lines.extend(_indent([_render_generate_target(target)], 2))
    lines.append("}")
    return lines
```

Add concrete helpers:

```python
def _render_semantic_type(declaration: SemanticTypeDecl) -> list[str]:
    header = f"semantic {declaration.name}: {_render_type(declaration.underlying)}"
    if not declaration.registry:
        return [header]
    return [f"{header} {{", "  registry: true", "}"]


def _render_index(declaration: IndexDecl) -> list[str]:
    lines = [f"index {declaration.model} @ {declaration.version} {{"]
    if declaration.primary:
        lines.append(f"  primary {', '.join(declaration.primary)}")
    for secondary in declaration.secondary:
        lines.append(f"  secondary {secondary.name} {{")
        lines.append(f"    key: [{', '.join(secondary.key)}]")
        if secondary.sort:
            rendered_sort = ", ".join(f"{item.field} {item.direction}" for item in secondary.sort)
            lines.append(f"    sort: [{rendered_sort}]")
        lines.append(f"    unique: {'true' if secondary.unique else 'false'}")
        lines.append("  }")
    lines.append("}")
    return lines
```

Render `reserved protobuf` and `access` blocks immediately after each model or
projection opening brace. Render projection join kind, `cardinality`, `where`,
and `group by` from their IR fields. Extend `_render_type()` for
`FixedBinaryType` and `uuid(7)`, `_render_version_spec()` for `VersionPinned`,
and `_render_workspace()` for label/name/description and `repair_attempts`.

- [ ] **Step 4: Add narrow round-trip tests for annotations and version specs**

Add tests that parse, render, and reparse:

```python
def test_render_mdl_preserves_pinned_projection_source_and_wire_annotations() -> None:
    source = """
domain metrics {
  owner: "metrics-team"
  entity Span @ 1 (additive) {
    @key spanId: uuid(7)
    @wire(json: "string", rust.type: "u64") count: u64
    digest: binary(32)
  }
  projection SpanView @ 1
    from metrics.Span @ 1#a3f8b2c1d4e5f6a7 as s
  {
    spanId <- s.spanId
  }
}
"""
    parsed = parse_text_to_ir(source)
    assert parse_text_to_ir(render_mdl(parsed)) == parsed
```

- [ ] **Step 5: Run renderer and existing LLM rendering tests**

Run: `cd cli; uv run pytest tests/test_llm_render_roundtrip.py tests/test_serialization_hints.py tests/test_protobuf_reservations.py tests/test_llm_features.py -v`

Expected: PASS.

- [ ] **Step 6: Run the mandatory gate and commit**

Run from `cli/`:

```text
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

Expected: all four commands pass.

Then:

```text
git add cli/src/modelable/llm/render.py cli/tests/test_llm_render_roundtrip.py
git commit -m "fix: preserve mdl semantics during rendering"
```

### Task 2: Define the closed conversational plan protocol

**Files:**
- Create: `cli/src/modelable/llm/conversation_plan.py`
- Create: `cli/tests/test_conversation_plan.py`

**Interfaces:**
- Consumes: `FieldType`, annotation values, projection source and mapping concepts from `modelable.parser.ir`
- Produces: `ConversationPlan`, `QueryPlan`, `ChangeSetPlan`, `ClarificationPlan`, `UnsupportedPlan`, `Operation`, and `parse_conversation_plan(text: str) -> ConversationPlan`

- [ ] **Step 1: Write failing schema tests**

```python
import json

import pytest
from pydantic import ValidationError

from modelable.llm.conversation_plan import ChangeSetPlan, QueryPlan, parse_conversation_plan


def test_parse_create_model_plan_with_nested_address() -> None:
    payload = {
        "kind": "change_set",
        "summary": "Create customer.Customer@1",
        "assumptions": ["Address is inline", "Owner comes from domain customer"],
        "edit_mode": "append_versions",
        "operations": [
            {
                "kind": "create_model",
                "domain": "customer",
                "name": "Customer",
                "model_kind": "entity",
                "version": 1,
                "fields": [
                    {
                        "name": "customerId",
                        "type": {"kind": "uuid", "version": 4},
                        "annotations": [{"kind": "key"}],
                    },
                    {
                        "name": "address",
                        "type": {
                            "kind": "object",
                            "fields": [
                                {"name": "street", "type": {"kind": "string", "version": 4}},
                                {"name": "city", "type": {"kind": "string", "version": 4}},
                                {"name": "postalCode", "type": {"kind": "string", "version": 4}},
                                {"name": "country", "type": {"kind": "string", "version": 4}},
                            ],
                        },
                    },
                ],
            }
        ],
    }

    plan = parse_conversation_plan(json.dumps(payload))

    assert isinstance(plan, ChangeSetPlan)
    assert plan.operations[0].kind == "create_model"
    assert plan.operations[0].fields[1].name == "address"


def test_query_plan_is_closed_to_known_query_kinds() -> None:
    with pytest.raises(ValidationError):
        QueryPlan(kind="query", query_kind="run_shell", refs=[], question="delete files")


def test_change_plan_rejects_raw_patch_and_path_fields() -> None:
    payload = {
        "kind": "change_set",
        "summary": "unsafe",
        "assumptions": [],
        "edit_mode": "append_versions",
        "operations": [
            {
                "kind": "create_model",
                "domain": "customer",
                "name": "Customer",
                "model_kind": "entity",
                "version": 1,
                "fields": [],
                "path": "customer.mdl",
                "patch": "@@",
            }
        ],
    }

    with pytest.raises(ValidationError):
        parse_conversation_plan(json.dumps(payload))
```

- [ ] **Step 2: Run tests and verify the module is missing**

Run: `cd cli; uv run pytest tests/test_conversation_plan.py -v`

Expected: FAIL with `ModuleNotFoundError: modelable.llm.conversation_plan`.

- [ ] **Step 3: Implement strict Pydantic plan models**

Create all models with `ConfigDict(extra="forbid")`. Reuse the IR `FieldType`
and `Annotation` discriminated unions in `FieldSpec`:

```python
class FieldSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: FieldType
    optional: bool = False
    default: str | None = None
    annotations: list[Annotation] = Field(default_factory=list)

    def to_field_def(self) -> FieldDef:
        return FieldDef(
            name=self.name,
            type=self.type.model_copy(deep=True),
            optional=self.optional,
            default=self.default,
            annotations=[
                annotation.model_copy(deep=True)
                for annotation in self.annotations
            ],
        )


class CreateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["create_model"] = "create_model"
    domain: str
    name: str
    model_kind: ModelKind
    version: int = 1
    fields: list[FieldSpec]
```

Define strict models for every operation named in the design:
`CreateProjection`, `AppendModelVersion`, `AppendProjectionVersion`,
`AddField`, `RenameField`, `RemoveField`, `ChangeFieldType`,
`SetFieldOptionality`, `SetFieldAnnotations`, `SetPrimaryIndex`,
`AddSecondaryIndex`, `RemoveSecondaryIndex`, `SetProjectionSource`,
`AddProjectionField`, `SetProjectionMapping`, `AddProjectionJoin`,
`SetProjectionFilter`, `SetProjectionGrouping`, `RenameDefinition`, and
`RetireDefinition`.

Use exact logical refs, never paths:

```python
class AddField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["add_field"] = "add_field"
    target: str
    field: FieldSpec


class AppendModelVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["append_model_version"] = "append_model_version"
    source: str
    version: int


Operation = Annotated[
    CreateModel
    | CreateProjection
    | AppendModelVersion
    | AppendProjectionVersion
    | AddField
    | RenameField
    | RemoveField
    | ChangeFieldType
    | SetFieldOptionality
    | SetFieldAnnotations
    | SetPrimaryIndex
    | AddSecondaryIndex
    | RemoveSecondaryIndex
    | SetProjectionSource
    | AddProjectionField
    | SetProjectionMapping
    | AddProjectionJoin
    | SetProjectionFilter
    | SetProjectionGrouping
    | RenameDefinition
    | RetireDefinition,
    Field(discriminator="kind"),
]
```

Define plan results:

```python
class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["query"] = "query"
    query_kind: Literal[
        "summary",
        "ownership",
        "lineage",
        "dependents",
        "indexes",
        "compatibility",
        "validation",
    ]
    refs: list[str] = Field(default_factory=list)
    question: str


class ChangeSetPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["change_set"] = "change_set"
    summary: str
    assumptions: list[str] = Field(default_factory=list)
    edit_mode: Literal["append_versions", "draft"] = "append_versions"
    operations: list[Operation]


class ClarificationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["clarification"] = "clarification"
    question: str
    reason: str


class UnsupportedPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["unsupported"] = "unsupported"
    request: str
    reason: str
    roadmap_area: Literal["vscode", "operations"] | None = None
```

Create `ConversationPlan` as a discriminated union and parse JSON through a
`TypeAdapter(ConversationPlan)`.

- [ ] **Step 4: Add tests for every operation discriminator and forbidden extras**

Parameterize one minimal valid payload for each operation kind. Assert duplicate
or unknown kinds fail, empty change-set operations fail through a
`model_validator`, and `edit_mode` only accepts `append_versions` or `draft`.

- [ ] **Step 5: Run the focused plan-schema tests**

Run: `cd cli; uv run pytest tests/test_conversation_plan.py -v`

Expected: PASS.

- [ ] **Step 6: Run the mandatory gate and commit**

Run the four mandatory commands from `cli/`, then:

```text
git add cli/src/modelable/llm/conversation_plan.py cli/tests/test_conversation_plan.py
git commit -m "feat: define conversational management plans"
```

### Task 3: Build workspace staging and complete-entity creation

**Files:**
- Create: `cli/src/modelable/llm/workspace_editor.py`
- Create: `cli/tests/test_workspace_editor.py`

**Interfaces:**
- Consumes: `ChangeSetPlan` and `Operation` from Task 2; `load_workspace()` and `load_workspace_from_sources()`; lossless `render_mdl()` from Task 1
- Produces: `WorkspaceEditor.preview(plan: ChangeSetPlan) -> PendingChangeSet`, `PendingChangeSet`, `ChangedDefinition`, `AffectedDefinition`, and `WorkspaceEditError`

- [ ] **Step 1: Write a failing complete-entity preview test**

```python
from modelable.llm.conversation_plan import ChangeSetPlan, CreateModel, FieldSpec
from modelable.llm.workspace_editor import WorkspaceEditor
from modelable.parser.ir import AnnKey, ObjectType, PrimitiveType


def test_preview_creates_complete_entity_without_writing(tmp_path) -> None:
    source = tmp_path / "customer.mdl"
    original = 'domain customer {\n  owner: "customer-team"\n}\n'
    source.write_text(original, encoding="utf-8")
    plan = ChangeSetPlan(
        summary="Create customer.Customer@1",
        assumptions=["Address is an inline object"],
        operations=[
            CreateModel(
                domain="customer",
                name="Customer",
                model_kind="entity",
                version=1,
                fields=[
                    FieldSpec(
                        name="customerId",
                        type=PrimitiveType(kind="uuid"),
                        annotations=[AnnKey()],
                    ),
                    FieldSpec(
                        name="address",
                        type=ObjectType(
                            fields=[
                                FieldSpec(name="street", type=PrimitiveType(kind="string")).to_field_def(),
                                FieldSpec(name="city", type=PrimitiveType(kind="string")).to_field_def(),
                                FieldSpec(name="postalCode", type=PrimitiveType(kind="string")).to_field_def(),
                                FieldSpec(name="country", type=PrimitiveType(kind="string")).to_field_def(),
                            ]
                        ),
                    ),
                ],
            )
        ],
    )

    pending = WorkspaceEditor(tmp_path).preview(plan)

    assert pending.changed == [
        ChangedDefinition(ref="customer.Customer@1", reason="created entity")
    ]
    assert "entity Customer @ 1 (additive)" in pending.candidate_sources[source]
    assert "address: object" in pending.candidate_sources[source]
    assert "--- " in pending.diff_text
    assert "+++ " in pending.diff_text
    assert source.read_text(encoding="utf-8") == original
```

After the test passes, extract the exact `ChangeSetPlan` construction above
into a module-level `create_customer_plan() -> ChangeSetPlan` helper in
`test_workspace_editor.py`; Task 6 reuses that helper.

- [ ] **Step 2: Run the test and verify the editor module is missing**

Run: `cd cli; uv run pytest tests/test_workspace_editor.py::test_preview_creates_complete_entity_without_writing -v`

Expected: FAIL with `ModuleNotFoundError: modelable.llm.workspace_editor`.

- [ ] **Step 3: Implement editor result types and source cloning**

Define immutable public results:

```python
@dataclass(frozen=True)
class ChangedDefinition:
    ref: str
    reason: str


@dataclass(frozen=True)
class AffectedDefinition:
    ref: str
    status: str
    reason: str


@dataclass(frozen=True)
class CompatibilityFinding:
    ref: str
    status: str
    message: str


@dataclass(frozen=True)
class PendingChangeSet:
    change_set_id: str
    plan: ChangeSetPlan
    assumptions: tuple[str, ...]
    source_fingerprints: dict[Path, str]
    candidate_sources: dict[Path, str]
    changed: list[ChangedDefinition]
    affected: list[AffectedDefinition]
    compatibility: list[CompatibilityFinding]
    diagnostics: list[Diagnostic]
    diff_text: str
    focus_ref: str | None
```

`WorkspaceEditor.__init__(root: Path)` loads the workspace and rejects existing
errors. `_copy_source_documents()` uses `source.mdl.model_copy(deep=True)` for
each path-backed source. `_find_domain_document(domain_name)` requires exactly
one source document containing the domain; no plan operation supplies a path.

- [ ] **Step 4: Implement `CreateModel` and candidate validation**

Convert every `FieldSpec` with:

```python
def to_field_def(self) -> FieldDef:
    return FieldDef(
        name=self.name,
        type=self.type.model_copy(deep=True),
        optional=self.optional,
        default=self.default,
        annotations=[annotation.model_copy(deep=True) for annotation in self.annotations],
    )
```

`_apply_create_model()` rejects an unknown domain, duplicate model/projection
name, non-positive version, empty fields, and an entity or aggregate without
exactly one `@key`. It adds a `ModelVersion` with
`change_kind=ChangeKind.additive`.

Render changed documents, combine unchanged and changed text as
`WorkspaceDocumentSource` values, call `load_workspace_from_sources()`, and
raise `WorkspaceEditError` if candidate diagnostics contain an error.

- [ ] **Step 5: Generate deterministic IDs and textual diffs**

Compute SHA-256 source fingerprints from the exact UTF-8 bytes. Compute
`change_set_id` from canonical JSON containing the validated plan dump,
sorted source fingerprints, and sorted candidate text hashes. Render diffs
with `difflib.unified_diff()` in source-path order.

- [ ] **Step 6: Add rejection tests**

Test unknown domains, duplicate definitions, invalid keys, invalid nested
fields, and a multi-operation plan where the second operation fails. In every
case assert all source bytes remain unchanged.

- [ ] **Step 7: Run editor tests**

Run: `cd cli; uv run pytest tests/test_workspace_editor.py -v`

Expected: PASS.

- [ ] **Step 8: Run the mandatory gate and commit**

Run the four mandatory commands from `cli/`, then:

```text
git add cli/src/modelable/llm/conversation_plan.py cli/src/modelable/llm/workspace_editor.py cli/tests/test_workspace_editor.py
git commit -m "feat: stage complete entity changes"
```

### Task 4: Add immutable model versioning, field edits, indexes, and impact

**Files:**
- Modify: `cli/src/modelable/llm/workspace_editor.py`
- Modify: `cli/tests/test_workspace_editor.py`
- Modify: `cli/src/modelable/compat/checker.py:1-170`
- Test: `cli/tests/test_compat.py`

**Interfaces:**
- Consumes: `AppendModelVersion`, model field operations, and index operations from Task 2
- Produces: compatibility-aware model previews and reusable `find_projection_dependents(mdl: MdlFile, ref: str) -> list[tuple[str, str, int]]`

- [ ] **Step 1: Write a failing immutable-version and impact test**

Create `customer.mdl` with `Customer@1` and `billing.mdl` with a
`BillingCustomer@1` projection. Preview this plan:

```python
plan = ChangeSetPlan(
    summary="Add required loyaltyTier",
    operations=[
        AppendModelVersion(
            source="customer.Customer@1",
            version=2,
        ),
        AddField(
            target="customer.Customer@2",
            field=FieldSpec(
                name="loyaltyTier",
                type=PrimitiveType(kind="string"),
                optional=False,
            ),
        ),
    ],
)
```

Assert:

```python
assert "entity Customer @ 1 (additive)" in candidate
assert "entity Customer @ 2 (breaking)" in candidate
assert any(item.ref == "billing.BillingCustomer@1" for item in pending.affected)
assert any(item.status == "breaking" for item in pending.compatibility)
```

- [ ] **Step 2: Run the test and verify version operations are unsupported**

Run: `cd cli; uv run pytest tests/test_workspace_editor.py::test_append_model_version_classifies_and_reports_dependents -v`

Expected: FAIL because `AppendModelVersion` is not executed yet.

- [ ] **Step 3: Implement append-version and model field operations**

`AppendModelVersion` deep-copies the exact source version, rejects a non-next
version number, clears version-local Protobuf reservations unless the plan
explicitly sets them in a later supported operation, and initially preserves
the source change kind. Field and annotation operations target the newly staged
version.

After all operations, compare each appended version to its source using
`check_model_version_compatibility()`. Set
`new_version.change_kind = ChangeKind.breaking` when the report is breaking,
otherwise `ChangeKind.additive`, then rerender and revalidate.

Implement private handlers named `_apply_add_field`,
`_apply_rename_field`, `_apply_remove_field`, `_apply_change_field_type`,
`_apply_set_field_optionality`, and `_apply_set_field_annotations`. Each
handler receives the staged document map plus its concrete operation and
returns the changed logical ref.

Reject field operations against an existing version unless the plan has
`edit_mode="draft"` or that ref was created by a preceding append/create
operation.

- [ ] **Step 4: Implement index operations**

When appending a model version, deep-copy its matching `IndexDecl` to the new
version. Implement primary/secondary set, add, and remove operations against
the staged domain's `index_decls`. Rely on semantic validation for field-name
and model-kind checks, but reject duplicate secondary index names before
mutation.

- [ ] **Step 5: Extract reusable dependent discovery**

Add to `compat/checker.py`:

```python
def find_projection_dependents(mdl: MdlFile, ref: str) -> list[tuple[str, str, int]]:
    model_ref, version_text = ref.rsplit("@", 1)
    version = int(version_text)
    dependents: list[tuple[str, str, int]] = []
    for domain in mdl.domains:
        for projection_name, versions in domain.projections.items():
            for projection in versions:
                sources = [(projection.source.model, projection.source.version)]
                sources.extend((join.model, join.version) for join in projection.joins)
                if any(
                    source_model == model_ref
                    and getattr(source_version, "version", None) == version
                    for source_model, source_version in sources
                ):
                    dependents.append((domain.name, projection_name, projection.version))
    return sorted(dependents)
```

Use `analyze_impact()` for every dependent and add stable
`AffectedDefinition` entries with the exact reason.

- [ ] **Step 6: Add draft-edit safety tests**

Assert a direct field mutation of `Customer@1` fails in
`append_versions` mode, succeeds with `edit_mode="draft"`, and the preview
contains an assumption/warning stating that local publication state is not
known.

- [ ] **Step 7: Run model editor and compatibility tests**

Run: `cd cli; uv run pytest tests/test_workspace_editor.py tests/test_compat.py -v`

Expected: PASS.

- [ ] **Step 8: Run the mandatory gate and commit**

Run the four mandatory commands from `cli/`, then:

```text
git add cli/src/modelable/compat/checker.py cli/src/modelable/llm/workspace_editor.py cli/tests/test_compat.py cli/tests/test_workspace_editor.py
git commit -m "feat: preview versioned model changes"
```

### Task 5: Add complete projection authoring and multi-file staging

**Files:**
- Modify: `cli/src/modelable/llm/workspace_editor.py`
- Modify: `cli/tests/test_workspace_editor.py`

**Interfaces:**
- Consumes: projection operations from Task 2 and staged workspace mechanics from Task 3
- Produces: complete projection creation, immutable projection versioning, structure edits, and projection-to-projection impact traversal

- [ ] **Step 1: Write a failing complete-projection test**

Preview a plan that creates `billing.BillingCustomer@1` from
`customer.Customer@1` in an existing billing domain:

```python
plan = ChangeSetPlan(
    summary="Create a billing customer projection",
    operations=[
        CreateProjection(
            domain="billing",
            name="BillingCustomer",
            version=1,
            source=ProjectionSourceSpec(
                model="customer.Customer",
                version=1,
                alias="c",
            ),
            fields=[
                ProjectionFieldSpec(
                    name="customerId",
                    mapping=DirectMappingSpec(source_alias="c", source_field="customerId"),
                ),
                ProjectionFieldSpec(
                    name="normalizedEmail",
                    mapping=ComputedMappingSpec(expression="lower(c.email)"),
                ),
            ],
        )
    ],
)
```

Assert the candidate contains the complete projection, validates without
diagnostics, and reports the created ref.

- [ ] **Step 2: Run the test and verify projection creation is unsupported**

Run: `cd cli; uv run pytest tests/test_workspace_editor.py::test_preview_creates_complete_projection -v`

Expected: FAIL at operation dispatch.

- [ ] **Step 3: Implement projection creation and append-version operations**

Convert `ProjectionSourceSpec`, `ProjectionJoinSpec`,
`DirectMappingSpec`, `ComputedMappingSpec`, and `ProjectionFieldSpec` into the
corresponding IR types. Resolve source aliases and refs against the staged
workspace before rendering.

`AppendProjectionVersion` deep-copies the source projection and requires the
next version number. Direct edits of an existing projection require
`edit_mode="draft"` or a preceding create/append operation.

- [ ] **Step 4: Implement projection field and structure operations**

Implement exact handlers for:

```python
SetProjectionSource
AddProjectionField
SetProjectionMapping
AddProjectionJoin
SetProjectionFilter
SetProjectionGrouping
RenameField
RemoveField
SetFieldAnnotations
```

After each plan completes, candidate workspace validation is authoritative for
alias, CEL expression, field lineage, group-by, and join correctness.

- [ ] **Step 5: Implement explicit definition lifecycle boundaries**

`RenameDefinition` is permitted only with `edit_mode="draft"`. Rename the
model or projection key in its owning `DomainDef`, update same-change-set
logical targets, and report every existing dependent as affected. Reject a
rename that collides with another model, projection, semantic type, or generated
auto-projection name.

`RetireDefinition` returns:

```text
Cannot retire <ref>: the current .mdl language has no published-contract retirement declaration.
```

It must stage nothing. Add tests for a successful draft rename, an implicit
published rename rejection, a collision, and the explicit retirement message.

- [ ] **Step 6: Add cross-file and transitive impact tests**

Use three files:

```text
customer.Customer@1
  -> billing.BillingCustomer@1
  -> analytics.CustomerSummary@1
```

Append a breaking `Customer@2`, update `BillingCustomer` in the same change
set, and assert:

- both changed files appear in `candidate_sources`;
- each file has its own unified diff;
- both direct and transitive projections appear once in `affected`;
- the plan either validates entirely or stages nothing;
- original files are unchanged before apply.

Add this module-level helper for Task 6's rollback test:

```python
def two_file_plan() -> ChangeSetPlan:
    return ChangeSetPlan(
        summary="Create customer and invoice entities",
        operations=[
            CreateModel(
                domain="customer",
                name="Customer",
                model_kind="entity",
                fields=[
                    FieldSpec(
                        name="customerId",
                        type=PrimitiveType(kind="uuid"),
                        annotations=[AnnKey()],
                    )
                ],
            ),
            CreateModel(
                domain="billing",
                name="Invoice",
                model_kind="entity",
                fields=[
                    FieldSpec(
                        name="invoiceId",
                        type=PrimitiveType(kind="uuid"),
                        annotations=[AnnKey()],
                    )
                ],
            ),
        ],
    )
```

- [ ] **Step 7: Run projection and full editor tests**

Run: `cd cli; uv run pytest tests/test_workspace_editor.py -v`

Expected: PASS.

- [ ] **Step 8: Run the mandatory gate and commit**

Run the four mandatory commands from `cli/`, then:

```text
git add cli/src/modelable/llm/conversation_plan.py cli/src/modelable/llm/workspace_editor.py cli/tests/test_workspace_editor.py
git commit -m "feat: preview projection change sets"
```

### Task 6: Apply fingerprinted change sets with rollback protection

**Files:**
- Modify: `cli/src/modelable/llm/workspace_editor.py`
- Modify: `cli/tests/test_workspace_editor.py`

**Interfaces:**
- Consumes: `PendingChangeSet`
- Produces: `WorkspaceEditor.apply(pending: PendingChangeSet) -> AppliedChangeSet`, `StaleChangeSetError`, and `WorkspaceApplyError`

- [ ] **Step 1: Write failing success, stale-state, and rollback tests**

```python
def test_apply_writes_exact_preview_and_reloads_workspace(tmp_path) -> None:
    editor = WorkspaceEditor(tmp_path)
    pending = editor.preview(create_customer_plan())

    applied = editor.apply(pending)

    assert applied.change_set_id == pending.change_set_id
    assert applied.changed == pending.changed
    assert applied.workspace.errors == []
    assert (tmp_path / "customer.mdl").read_text(encoding="utf-8") == pending.candidate_sources[
        tmp_path / "customer.mdl"
    ]


def test_apply_rejects_changed_source_fingerprint(tmp_path) -> None:
    editor = WorkspaceEditor(tmp_path)
    pending = editor.preview(create_customer_plan())
    source = tmp_path / "customer.mdl"
    source.write_text(source.read_text(encoding="utf-8") + "\n// concurrent\n", encoding="utf-8")

    with pytest.raises(StaleChangeSetError):
        editor.apply(pending)


def test_apply_rolls_back_when_second_replace_fails(tmp_path, monkeypatch) -> None:
    editor = WorkspaceEditor(tmp_path)
    pending = editor.preview(two_file_plan())
    originals = {path: path.read_bytes() for path in pending.candidate_sources}
    real_replace = os.replace
    calls = 0

    def fail_second_replace(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected replace failure")
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_second_replace)

    with pytest.raises(WorkspaceApplyError, match="rolled back"):
        editor.apply(pending)

    assert {path: path.read_bytes() for path in originals} == originals
```

- [ ] **Step 2: Run tests and verify `apply()` is missing**

Run: `cd cli; uv run pytest tests/test_workspace_editor.py -k "apply_" -v`

Expected: FAIL because `WorkspaceEditor.apply()` is not defined.

- [ ] **Step 3: Implement fingerprint verification and deterministic restaging**

`apply()` recomputes every fingerprint in `pending.source_fingerprints`,
rejects missing/newly changed files, and calls `preview(pending.plan)` again.
Reject the apply if the recomputed `change_set_id`, candidate text, findings,
or diffs differ from the confirmed pending object.

- [ ] **Step 4: Implement rollback-protected replacement**

For each changed path in sorted order:

1. Write candidate UTF-8 text to a same-directory temporary file.
2. Flush and `os.fsync()` the temporary file.
3. Save the original bytes and whether the destination existed.
4. Replace destinations with `os.replace()`.
5. On failure, restore replaced originals in reverse order and remove files
   newly created by this apply.
6. Delete remaining temporary files in `finally`.
7. Reload with `load_workspace(root)` and treat reload errors as an apply
   failure requiring rollback.

Return:

```python
@dataclass(frozen=True)
class AppliedChangeSet:
    change_set_id: str
    written_paths: tuple[Path, ...]
    changed: list[ChangedDefinition]
    compatibility: list[CompatibilityFinding]
    workspace: Workspace
    focus_ref: str | None
```

- [ ] **Step 5: Test a new file and recovery artifact cleanup**

Although normal operations resolve an existing domain document, cover a staged
new destination through an internal fixture. Assert rollback removes a newly
created destination and no `.modelable-edit-*` temporary files remain after
success or handled failure.

- [ ] **Step 6: Run editor tests**

Run: `cd cli; uv run pytest tests/test_workspace_editor.py -v`

Expected: PASS.

- [ ] **Step 7: Run the mandatory gate and commit**

Run the four mandatory commands from `cli/`, then:

```text
git add cli/src/modelable/llm/workspace_editor.py cli/tests/test_workspace_editor.py
git commit -m "feat: apply confirmed workspace changes safely"
```

### Task 7: Add typed query execution and provider-backed intent planning

**Files:**
- Create: `cli/src/modelable/llm/workspace_query.py`
- Create: `cli/src/modelable/llm/conversation_planner.py`
- Create: `cli/tests/test_workspace_query.py`
- Modify: `cli/tests/test_conversation_plan.py`
- Modify: `cli/src/modelable/llm/qa.py:1-130`

**Interfaces:**
- Consumes: `ConversationPlan`, `LLMProvider`, `LLMRequest`, workspace compatibility/lineage services
- Produces: `WorkspaceQueryService.execute(plan: QueryPlan) -> QueryResult` and `ConversationPlanner.plan(message: str, context: PlannerContext) -> ConversationPlan`

- [ ] **Step 1: Write failing deterministic query tests**

Create a fixture with a model, index, projection, and a breaking next version.
Assert:

```python
service = WorkspaceQueryService(load_workspace(tmp_path))

assert "customer-team" in service.execute(
    QueryPlan(kind="query", query_kind="ownership", refs=["customer.Customer@1"], question="Who owns it?")
).text
assert "byEmail" in service.execute(
    QueryPlan(kind="query", query_kind="indexes", refs=["customer.Customer@1"], question="How can I look it up?")
).text
assert "billing.BillingCustomer@1" in service.execute(
    QueryPlan(kind="query", query_kind="dependents", refs=["customer.Customer@1"], question="What depends on it?")
).text
assert "breaking" in service.execute(
    QueryPlan(
        kind="query",
        query_kind="compatibility",
        refs=["customer.Customer@1", "customer.Customer@2"],
        question="Is v2 compatible?",
    )
).text
```

- [ ] **Step 2: Run query tests and verify the service is missing**

Run: `cd cli; uv run pytest tests/test_workspace_query.py -v`

Expected: FAIL with `ModuleNotFoundError: modelable.llm.workspace_query`.

- [ ] **Step 3: Implement typed query execution**

Define:

```python
@dataclass(frozen=True)
class QueryResult:
    text: str
    refs: tuple[str, ...]


class WorkspaceQueryService:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def execute(self, plan: QueryPlan) -> QueryResult:
        handlers = {
            "summary": self._summary,
            "ownership": self._ownership,
            "lineage": self._lineage,
            "dependents": self._dependents,
            "indexes": self._indexes,
            "compatibility": self._compatibility,
            "validation": self._validation,
        }
        return handlers[plan.query_kind](plan.refs)
```

Reuse existing `build_*_summary()`, `build_projection_lineage()`,
`find_projection_dependents()`, `check_model_version_compatibility()`, and
rendered diagnostics. Require the exact ref counts each query kind needs and
return an actionable error rather than guessing.

Update `qa.answer_question()` to call this service for deterministic legacy
questions so `ask`, offline chat, and typed query execution share facts.

- [ ] **Step 4: Write failing planner request and repair tests**

Use a fake provider that captures `LLMRequest` and returns:

1. a malformed plan;
2. a valid `CreateModel` plan.

Assert the second request includes the schema validation error, the plan schema
contains no raw patch/path fields, and the returned plan is typed.

- [ ] **Step 5: Implement `ConversationPlanner`**

Define:

```python
@dataclass(frozen=True)
class PlannerContext:
    workspace_summary: str
    focused_ref: str | None
    history: tuple[tuple[str, str], ...]
    pending_plan: ChangeSetPlan | None


class ConversationPlanner:
    def __init__(self, provider: LLMProvider | None, *, repair_attempts: int = 1) -> None:
        self.provider = provider
        self.repair_attempts = repair_attempts

    def plan(self, message: str, context: PlannerContext) -> ConversationPlan:
        if self.provider is None:
            return self._offline_plan(message, context)
        request = build_conversation_request(message=message, context=context)
        response = self.provider.complete(request)
        try:
            return parse_conversation_plan(response.content)
        except Exception as error:
            return self._repair(message, context, error)
```

The system prompt explicitly lists the four plan kinds, requires clarification
for ownership/identity/reusable-address/source ambiguity, defaults existing
contract changes to append-version operations, and returns
`UnsupportedPlan(roadmap_area="operations")` for compile/sync/publish/external
requests.

Offline routing recognizes slash commands and delegates legacy deterministic
questions. A mutation requiring synthesis returns `UnsupportedPlan` with clear
provider configuration guidance.

- [ ] **Step 6: Run planner, query, and legacy Q&A tests**

Run: `cd cli; uv run pytest tests/test_conversation_plan.py tests/test_workspace_query.py tests/test_llm_features.py -v`

Expected: PASS.

- [ ] **Step 7: Run the mandatory gate and commit**

Run the four mandatory commands from `cli/`, then:

```text
git add cli/src/modelable/llm/conversation_planner.py cli/src/modelable/llm/conversation_plan.py cli/src/modelable/llm/workspace_query.py cli/src/modelable/llm/qa.py cli/tests/test_conversation_plan.py cli/tests/test_workspace_query.py
git commit -m "feat: plan grounded conversational requests"
```

### Task 8: Build the reusable conversation session and textual preview

**Files:**
- Create: `cli/src/modelable/llm/conversation.py`
- Create: `cli/tests/test_conversation.py`
- Modify: `cli/src/modelable/llm/chat.py:1-205`

**Interfaces:**
- Consumes: `ConversationPlanner`, `WorkspaceQueryService`, and `WorkspaceEditor`
- Produces: `ConversationSession.turn(message: str) -> ConversationReply`, stable preview rendering, `/apply`, `/discard`, natural confirmation, refinement, and workspace reload

- [ ] **Step 1: Write a failing end-to-end session test**

Use a fake provider that returns a complete `CreateModel` plan for
"add a customer entity with address":

```python
class FakeProvider:
    def __init__(self, plan: ChangeSetPlan) -> None:
        self.plan = plan

    def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            content=self.plan.model_dump_json(),
            provider="fake",
            model="test-model",
        )


source = tmp_path / "customer.mdl"
original = 'domain customer {\n  owner: "customer-team"\n}\n'
source.write_text(original, encoding="utf-8")
plan = ChangeSetPlan(
    summary="Create customer.Customer@1",
    assumptions=["Address is inline"],
    operations=[
        CreateModel(
            domain="customer",
            name="Customer",
            model_kind="entity",
            fields=[
                FieldSpec(
                    name="customerId",
                    type=PrimitiveType(kind="uuid"),
                    annotations=[AnnKey()],
                ),
                FieldSpec(
                    name="address",
                    type=ObjectType(
                        fields=[
                            FieldDef(name="street", type=PrimitiveType(kind="string")),
                            FieldDef(name="city", type=PrimitiveType(kind="string")),
                            FieldDef(name="postalCode", type=PrimitiveType(kind="string")),
                            FieldDef(name="country", type=PrimitiveType(kind="string")),
                        ]
                    ),
                ),
            ],
        )
    ],
)
session = ConversationSession(
    path=tmp_path,
    provider=FakeProvider(plan),
)

preview = session.turn("add a customer entity with address")

assert preview.kind == "preview"
assert "Summary" in preview.text
assert "Assumptions" in preview.text
assert "Changed definitions" in preview.text
assert "Affected definitions" in preview.text
assert "Compatibility and validation" in preview.text
assert "Unified diff" in preview.text
assert "customer.Customer@1" in preview.text
assert "Address is inline" in preview.text
assert session.pending is not None
assert source.read_text(encoding="utf-8") == original

applied = session.turn("apply")

assert applied.kind == "applied"
assert "customer.Customer@1" in applied.text
assert session.pending is None
assert session.focused_ref == "customer.Customer@1"
assert "entity Customer @ 1" in source.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the test and verify the conversation service is missing**

Run: `cd cli; uv run pytest tests/test_conversation.py::test_preview_and_apply_complete_entity -v`

Expected: FAIL with `ModuleNotFoundError: modelable.llm.conversation`.

- [ ] **Step 3: Implement session state and routing**

Define:

```python
@dataclass(frozen=True)
class ConversationReply:
    kind: Literal["answer", "clarification", "preview", "applied", "discarded", "unsupported", "error"]
    text: str
    change_set_id: str | None = None


class ConversationSession:
    def __init__(
        self,
        *,
        path: Path,
        provider: LLMProvider | None,
        focused_ref: str | None = None,
        repair_attempts: int = 1,
    ) -> None:
        self.path = path
        self.provider = provider
        self.focused_ref = focused_ref
        self.history: list[tuple[str, str]] = []
        self.pending: PendingChangeSet | None = None
        self.workspace = load_workspace(path)
        self.planner = ConversationPlanner(provider, repair_attempts=repair_attempts)

    def turn(self, message: str) -> ConversationReply:
        normalized = message.strip()
        if normalized.lower() in {"apply", "apply it", "confirm"} or normalized == "/apply":
            return self._apply_pending()
        if normalized.lower() in {"discard", "discard it", "cancel"} or normalized == "/discard":
            return self._discard_pending()
        return self._plan_and_execute(normalized)
```

Queries execute immediately. Clarification and unsupported plans render without
staging. Change plans call `WorkspaceEditor.preview()`.

- [ ] **Step 4: Implement stable textual rendering**

Create pure functions:

```python
def render_query_result(result: QueryResult) -> str
def render_pending_change_set(pending: PendingChangeSet) -> str
def render_applied_change_set(applied: AppliedChangeSet) -> str
```

`render_pending_change_set()` uses the exact section order from the design and
sorts paths and refs. Empty affected/compatibility sections render `- none`
instead of disappearing. End with:

```text
Apply change set <id> with /apply or refine it with another request. Use /discard to cancel.
```

- [ ] **Step 5: Implement pending refinement and replacement**

Include `pending.plan` in `PlannerContext`. A new `ChangeSetPlan` replaces the
pending preview and prefixes the reply with:

```text
Replaced pending change set <old-id> with <new-id>.
```

Read-only queries leave `pending` untouched. `/discard` clears it. `/apply`
with no pending result returns an error and writes nothing.

- [ ] **Step 6: Implement post-apply reload and history**

After `editor.apply()`, assign `self.workspace = applied.workspace`, recreate
the query/editor services from the new workspace, update `focused_ref`, clear
pending, and append the user/assistant messages to history. Never append a
success response before `AppliedChangeSet` exists.

- [ ] **Step 7: Adapt `chat.py` without changing standalone update**

Keep `ChatState`, `chat_turn()`, and slash commands used by existing tests, but
store a lazily created `ConversationSession` on state and delegate `/ask`,
free-form messages, `/apply`, and `/discard`. Keep `/update` preview-only for
backward compatibility and route its result through the existing
`update_definition(path, ref, instruction, provider=provider, write=False)`
path.

- [ ] **Step 8: Add failure and lifecycle tests**

Cover:

- natural-language apply and explicit `/apply`;
- `/discard`;
- a query while a change set is pending;
- replacement/refinement warning;
- ambiguous plan with no staged change;
- unsupported operational plan;
- stale fingerprint after preview;
- rollback failure response;
- post-apply questions seeing the new entity; and
- empty apply with no write.

- [ ] **Step 9: Run conversation and existing chat tests**

Run: `cd cli; uv run pytest tests/test_conversation.py tests/test_llm_provider_integration.py -v`

Expected: PASS.

- [ ] **Step 10: Run the mandatory gate and commit**

Run the four mandatory commands from `cli/`, then:

```text
git add cli/src/modelable/llm/conversation.py cli/src/modelable/llm/chat.py cli/tests/test_conversation.py cli/tests/test_llm_provider_integration.py
git commit -m "feat: manage workspace changes through chat"
```

### Task 9: Wire the CLI session and preserve provider behavior

**Files:**
- Modify: `cli/src/modelable/commands/llm.py:1-40`
- Modify: `cli/src/modelable/commands/llm.py:510-580`
- Modify: `cli/tests/test_llm_provider_integration.py:350-720`

**Interfaces:**
- Consumes: `ConversationSession`
- Produces: one persistent session per `modelable chat` invocation in both interactive and `--message` modes

- [ ] **Step 1: Write failing CLI tests**

Add tests asserting:

```python
result = runner.invoke(
    cli,
    [
        "chat",
        "--path",
        str(tmp_path),
        "--message",
        "add a customer entity with address",
        "--provider",
        "ollama",
        "--model",
        "llama3.1",
    ],
)
assert result.exit_code == 0
assert "Apply change set" in result.output
assert source.read_text(encoding="utf-8") == original
```

For interactive mode, feed
`add a customer entity with address\n/apply\n/exit\n` and assert the same
session retains the pending change and writes after confirmation.

- [ ] **Step 2: Run CLI tests and verify current command lacks persistence**

Run: `cd cli; uv run pytest tests/test_llm_provider_integration.py -k "chat" -v`

Expected: at least the new interactive apply test fails.

- [ ] **Step 3: Construct and retain one conversation session**

Replace direct workspace/state orchestration inside the Click command with:

```python
session = ConversationSession(
    path=path,
    provider=llm_provider,
    focused_ref=ref,
    repair_attempts=config.repair_attempts,
)
```

Single-message mode prints `session.turn(message).text`. Interactive mode calls
the same object for every turn. Preserve `/exit`, EOF, prompt text, provider
resolution, and exception-to-Click-error behavior.

- [ ] **Step 4: Add offline regression tests**

With no provider:

- `/describe`, `/context`, ownership, lineage, and dependents still work;
- a rich entity-creation prompt explains that a provider is required;
- no source file changes;
- `update` standalone behavior and provenance sidecars remain unchanged.

- [ ] **Step 5: Run all LLM and CLI tests**

Run: `cd cli; uv run pytest tests/test_llm_features.py tests/test_conversation.py tests/test_llm_provider_integration.py tests/test_cli.py -v`

Expected: PASS.

- [ ] **Step 6: Run the mandatory gate and commit**

Run the four mandatory commands from `cli/`, then:

```text
git add cli/src/modelable/commands/llm.py cli/tests/test_llm_provider_integration.py
git commit -m "feat: expose conversational workspace management"
```

### Task 10: Document the feature and close the implementation slice

**Files:**
- Modify: `docs/architecture.md:710-750`
- Modify: `docs/cli-reference.md:1100-1145`
- Modify: `CHANGELOG.md`
- Modify: `ROADMAP.md:88-120`
- Archive after the implementation PR merges:
  - Move: `docs/superpowers/specs/2026-07-18-conversational-workspace-management-design.md`
  - To: `docs/superpowers/specs/archived/2026-07-18-conversational-workspace-management-design.md`
  - Move: `docs/superpowers/plans/2026-07-18-conversational-workspace-management.md`
  - To: `docs/superpowers/plans/archived/2026-07-18-conversational-workspace-management.md`

**Interfaces:**
- Consumes: shipped CLI behavior and public service boundary
- Produces: accurate user documentation, architecture documentation, changelog entry, and roadmap state

- [ ] **Step 1: Update CLI documentation**

Document:

- supported information questions;
- complete entity/projection prompts;
- immutable-version default and explicit draft editing;
- preview section order;
- textual unified diffs and affected-definition explanations;
- natural-language confirmation and `/apply`;
- refinement and `/discard`;
- stale-source behavior;
- provider-required versus offline behavior; and
- operational requests that remain unsupported.

Include a complete terminal example beginning with:

```text
you> add a customer entity with address
assistant> Proposed change set 4f83a912
```

and ending with `/apply` plus the written ref.

- [ ] **Step 2: Document the reusable editor architecture**

Add the dependency direction:

```text
CLI chat / future VS Code chat
  -> conversational planner
  -> workspace editor
  -> parser, IR, renderer, validator, compatibility and dependency analysis
```

State that the language server will be the future VS Code transport and that
the compiler never depends on provider/chat modules.

- [ ] **Step 3: Update changelog and roadmap**

Add the user-visible feature to the current unreleased changelog section. Mark
only Priority 2 item 1 as shipped. Keep the VS Code integration and operational
management items unshipped and explicitly ordered after the CLI foundation.

- [ ] **Step 4: Run doc/spec review**

Perform all four phases:

1. Markdown structure and placeholder scan.
2. Cross-reference existence and consistency.
3. Coverage check, including the spec's explicit no-ADR rationale.
4. Contradiction and quality review across CLI, architecture, changelog, and
   roadmap text.

Expected: all phases PASS. Fix and rerun from Phase 1 on any failure.

- [ ] **Step 5: Run strict documentation validation**

Run:

```text
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
```

Expected: PASS, allowing only the repository's known informational note about
pages not present in nav and the upstream Material warning.

- [ ] **Step 6: Run the mandatory final gate**

Run from `cli/`:

```text
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

Expected: all four commands pass.

- [ ] **Step 7: Commit implementation documentation**

```text
git add docs/architecture.md docs/cli-reference.md CHANGELOG.md ROADMAP.md
git commit -m "docs: document conversational workspace management"
```

- [ ] **Step 8: Archive completed planning documents after merge**

Do not archive the spec or plan before the implementation PR merges. After the
merge is confirmed on `main`, move both files into their respective
`archived/` directories, repair relative links, run doc review plus the full
mandatory gate, and publish the archive move as the prompt follow-up required
by `AGENTS.md`.

## Final Verification

Before opening the implementation PR:

1. Run the focused chat scenario:

```text
uv run modelable chat --path <fixture> --message "add a customer entity with address" --provider ollama --model <configured-model>
```

Verify the command prints assumptions, affected definitions, validation,
compatibility, and textual diffs without writing.

2. Run an interactive fake-provider integration test that previews, refines,
applies, reloads, and then answers a question about the new entity.

3. Run the strict docs build.

4. Run the four mandatory CLI commands from `cli/`.

5. Inspect `git diff main...HEAD` and confirm no raw provider patch path, direct
LLM file write, silent existing-version mutation, unsupported operational
execution, or stale planning document remains.
