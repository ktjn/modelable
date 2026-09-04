# Typed Semantic Facets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add parser-independent, typed, namespaced semantic facets that are validated, propagated, preserved, and exposed consistently to policy, plan, query, browser, and native consumers.

**Architecture:** Add a small `modelable.facets` domain module containing canonical identities, subjects, schemas, values, sidecar loading, and deterministic validation. `Workspace` owns the normalized facet set; semantic graph traversal computes inherited/projected facets from existing dependency and lineage data. Plan, query, policy, and browser outputs serialize read-only projections of that same set, while target overlays remain independent.

**Tech Stack:** Python 3.14, Pydantic IR models, deterministic JSON serialization, Click CLI, JSON Schema protocol fixtures, TypeScript browser protocol, pytest/xdist, and existing showcase conformance scripts.

**Spec:** `docs/superpowers/specs/2026-09-04-typed-semantic-facets-design.md`

## Global Constraints

- Do not add `.mdl` grammar or organization-specific parser annotations for facets.
- Facet identity is the exact canonical string `namespace/name@schema_version`.
- Supported value-schema keywords are exactly `type`, `const`, `enum`, `properties`, `required`, `items`, `minItems`, `maxItems`, `minimum`, `maximum`, `pattern`, and `additionalProperties`.
- Unknown schemas preserve raw facets and mark them `unknown`; they never satisfy typed policy predicates or propagate semantically.
- Propagation modes are exactly `none`, `inherit`, and `project`.
- Facets may target only `declaration`, `field`, `projection`, or `projection_field` subjects.
- Target-specific representation metadata remains in overlays.
- No facet path performs network access; schema loading is local and explicit.
- All emitted facet arrays and object keys use deterministic canonical ordering.
- Every user-facing change adds an entry under `## [Unreleased]` in `CHANGELOG.md`.
- Before every commit, from `cli/`, run the repository’s four required commands: `uv run ruff format .`, `uv run ruff check .`, the mypy baseline ratchet, and `uv run pytest --tb=short`.

---

### Task 1: Define the facet value, identity, subject, and schema contracts

**Files:**
- Create: `cli/src/modelable/facets.py`
- Test: `cli/tests/test_facets.py`

**Interfaces:**
- Produces `FacetIdentity(namespace: str, name: str, schema_version: int)`, with `canonical: str` and `from_canonical(value: str) -> FacetIdentity`.
- Produces `FacetSubject(kind: Literal["declaration", "field", "projection", "projection_field"], reference: str)` with `canonical: str` and `parse(value: str) -> FacetSubject`.
- Produces `FacetSchema(identity: FacetIdentity, value_schema: dict[str, object], allowed_subjects: tuple[str, ...], propagation: Literal["none", "inherit", "project"])`.
- Produces `Facet(identity, value, subject, propagation, source, interpretation)` and `Facet.as_dict() -> dict[str, object]`.
- Produces `FacetRegistry(schemas: Mapping[FacetIdentity, FacetSchema])` with `schema_for(identity) -> FacetSchema | None` and `validate(facet: Facet) -> Facet`.

- [ ] **Step 1: Write failing contract tests.** Cover canonical identity parsing, invalid namespace/name/version, all four subject kinds, malformed subjects, exact schema keyword allow-list, scalar/object/array/enum constraints, and unknown-schema classification.

```python
def test_identity_round_trips_canonically() -> None:
    identity = FacetIdentity.from_canonical("org.example/retention-class@1")
    assert identity.canonical == "org.example/retention-class@1"


def test_registry_marks_missing_schema_unknown_without_dropping_value() -> None:
    facet = Facet.from_document({
        "identity": "org.example/new-fact@1",
        "value": {"enabled": True},
        "subject": "field:orders@1#customer_id",
        "propagation": "none",
    })
    assert FacetRegistry({}).validate(facet).interpretation == "unknown"
```

- [ ] **Step 2: Run the focused tests and verify they fail.**

Run: `uv run pytest -q tests/test_facets.py`

Expected: FAIL because the facet module and its contract types do not exist.

- [ ] **Step 3: Implement the minimal immutable models and validators.** Use frozen dataclasses where the surrounding domain uses dataclasses, copy JSON values defensively, reject non-finite numbers, sort object keys only at serialization, and validate the finite schema vocabulary recursively. Do not import or invoke the parser.

- [ ] **Step 4: Run focused tests and verify they pass.**

Run: `uv run pytest -q tests/test_facets.py`

Expected: PASS, including negative tests for unsupported schema keywords, invalid types, duplicate enum values, and invalid subject kinds.

- [ ] **Step 5: Run the four required repository gates and commit.**

```bash
cd cli
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
git add src/modelable/facets.py tests/test_facets.py src/modelable/__init__.py
git commit -m "feat: add typed facet contracts"
```

### Task 2: Add the explicit local facet sidecar and workspace normalization

**Files:**
- Modify: `cli/src/modelable/compiler/workspace.py`
- Modify: `cli/src/modelable/facets.py`
- Create: `cli/src/modelable/data/modelable.facets.v1.schema.json`
- Test: `cli/tests/test_workspace.py`
- Test: `cli/tests/test_facets.py`
- Modify: `cli/CHANGELOG.md`

**Interfaces:**
- Produces `FACET_SCHEMA = "modelable.facets/v1"`.
- Produces `load_facet_document(path: Path) -> tuple[FacetRegistry, tuple[Facet, ...]]`.
- Extends `Workspace` with `facets: tuple[Facet, ...] = ()` and `facet_registry: FacetRegistry | None = None`.
- Extends `load_workspace(path)` to load `modelable.facets.json` from the workspace directory, or no sidecar when absent.
- Extends `load_workspace_from_sources(..., facets_document: Mapping[str, object] | None = None)` for browser/in-memory callers.

- [ ] **Step 1: Write failing sidecar and workspace tests.** Use a temporary workspace containing one `.mdl` file and `modelable.facets.json` with two schemas and three facets. Assert deterministic ordering, source URI preservation, missing-sidecar compatibility, malformed JSON diagnostics, duplicate identities, and invalid values.

```python
def test_load_workspace_reads_facets_without_changing_mdl_syntax(tmp_path: Path) -> None:
    (tmp_path / "orders.mdl").write_text(MINIMAL_MODEL, encoding="utf-8")
    (tmp_path / "modelable.facets.json").write_text(json.dumps(FACETS_DOCUMENT), encoding="utf-8")
    workspace = load_workspace(tmp_path)
    assert [facet.identity.canonical for facet in workspace.facets] == [
        "org.example/confidentiality@1",
        "org.example/retention-class@1",
    ]
```

- [ ] **Step 2: Run the focused tests and verify they fail.**

Run: `uv run pytest -q tests/test_facets.py tests/test_workspace.py -k facet`

Expected: FAIL because workspace loading does not discover the sidecar.

- [ ] **Step 3: Implement the sidecar contract.** The top-level document must have exactly `$schema`, `schemas`, and `facets`; each schema has `identity`, `value_schema`, `allowed_subjects`, and `propagation`; each facet has `identity`, `value`, `subject`, and `propagation`, plus optional `source`. Validate schemas before values, resolve known identities locally, retain unknown facets, reject path traversal by treating the sidecar as a fixed sibling file, and return errors through the existing workspace diagnostic pattern.

- [ ] **Step 4: Add and validate the checked-in JSON Schema.** Require deterministic protocol fields and reject executable or network-bearing values. Add a fixture proving the sidecar itself does not alter parser grammar or target overlay documents.

- [ ] **Step 5: Run focused tests, then the four required gates, and commit.**

```bash
cd cli
uv run pytest -q tests/test_facets.py tests/test_workspace.py -k facet
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
git add src/modelable/compiler/workspace.py src/modelable/facets.py src/modelable/data/modelable.facets.v1.schema.json tests/test_facets.py tests/test_workspace.py CHANGELOG.md
git commit -m "feat: load typed facets from local sidecars"
```

### Task 3: Validate subjects and compute deterministic inheritance and projection

**Files:**
- Modify: `cli/src/modelable/facets.py`
- Modify: `cli/src/modelable/compiler/workspace.py`
- Modify: `cli/src/modelable/dependency_graph.py` only at the existing projection dependency boundary
- Test: `cli/tests/test_facets.py`
- Test: `cli/tests/test_dependency_graph.py`

**Interfaces:**
- Produces `normalize_workspace_facets(workspace: Workspace) -> tuple[Facet, ...]`.
- Produces `facets_for_subject(workspace: Workspace, subject: FacetSubject) -> tuple[Facet, ...]`.
- Produces `FacetPropagationError` using the existing semantic diagnostic conversion path.

- [ ] **Step 1: Write failing propagation tests.** Cover direct model fields, declaration subjects, projection fields, chained projections, joins/computed mappings with multiple sources, `none`, `inherit`, `project`, explicit destination replacement, duplicate explicit identities, illegal subjects, and stable source ordering.

```python
def test_project_propagation_keeps_all_computed_sources_in_semantic_order(workspace: Workspace) -> None:
    facets = facets_for_subject(workspace, FacetSubject("projection_field", "orders.summary@1#customer_id"))
    assert [facet.source.subject.canonical for facet in facets] == [
        "field:customers@1#id",
        "field:orders@1#customer_id",
    ]
```

- [ ] **Step 2: Run the focused tests and verify they fail.**

Run: `uv run pytest -q tests/test_facets.py tests/test_dependency_graph.py -k propagation`

Expected: FAIL because no normalized propagation pass exists.

- [ ] **Step 3: Implement normalization over resolved semantic subjects.** Use canonical declaration and field paths, the existing `resolve_projection_aliases` and dependency graph, and deterministic sorting by `(subject.canonical, identity.canonical, source.subject.canonical)`. `inherit` follows eligible descendants; `project` follows only actual field lineage; computed fields retain every contributing source; unknown facets remain local and uninterpreted.

- [ ] **Step 4: Verify focused propagation tests pass and that existing projection tests remain green.**

Run: `uv run pytest -q tests/test_facets.py tests/test_dependency_graph.py tests/test_projection_lineage.py`

Expected: PASS with no changes to existing built-in PII/classification behavior.

- [ ] **Step 5: Run the four required gates and commit.**

```bash
cd cli
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
git add src/modelable/facets.py src/modelable/compiler/workspace.py src/modelable/dependency_graph.py tests/test_facets.py tests/test_dependency_graph.py
git commit -m "feat: propagate semantic facets deterministically"
```

### Task 4: Expose facets to policy and plan output

**Files:**
- Modify: `cli/src/modelable/compat/policy.py`
- Modify: `cli/src/modelable/planner/plans.py`
- Modify: `cli/src/modelable/planner/protocol.py`
- Modify: `cli/src/modelable/schemas/plan-v1.schema.json`
- Test: `cli/tests/test_compat_policy.py`
- Test: `cli/tests/test_planner_protocol.py`
- Test: `cli/tests/test_plans.py`
- Modify: `cli/CHANGELOG.md`

**Interfaces:**
- Produces `facet_documents(facets: Iterable[Facet]) -> list[dict[str, object]]`.
- Extends `CompatibilityPolicy` with `facet_requirements: tuple[FacetRequirement, ...] = ()`.
- Produces `FacetRequirement(identity: str, subject_kind: str | None, value: object)` and deterministic `evaluate_facets(...)` results.
- Adds `facets` arrays to plan declaration/field blocks, preserving plan-v1 additive compatibility.

- [ ] **Step 1: Write failing tests.** Verify a known facet requirement passes only with a matching typed value, unknown facets never satisfy it, plan serialization preserves facets, and overlay fields do not appear in the facet array.

- [ ] **Step 2: Run focused tests and verify failure.**

Run: `uv run pytest -q tests/test_compat_policy.py tests/test_planner_protocol.py tests/test_plans.py -k facet`

Expected: FAIL because policy and plan protocols have no facet fields or predicates.

- [ ] **Step 3: Implement policy requirements as external configuration.** Extend the existing policy YAML parser with an explicit `facets:` section; reject unsupported keys and invalid identities, evaluate only `interpretation == "known"`, and include causal facet identity/subject/value in findings. Keep existing compatibility thresholds unchanged.

- [ ] **Step 4: Add plan-v1 facet definitions and populate resolved declaration, source, join, and field blocks from the normalized workspace.** Keep deterministic ordering and preserve v0 migration behavior.

- [ ] **Step 5: Run focused protocol/golden tests, the four required gates, and commit.**

```bash
cd cli
uv run pytest -q tests/test_compat_policy.py tests/test_planner_protocol.py tests/test_plans.py -k facet
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
git add src/modelable/compat/policy.py src/modelable/planner/plans.py src/modelable/planner/protocol.py src/modelable/schemas/plan-v1.schema.json tests/test_compat_policy.py tests/test_planner_protocol.py tests/test_plans.py CHANGELOG.md
git commit -m "feat: expose facets to policy and plans"
```

### Task 5: Expose facets through query/v1 and browser/native equivalence

**Files:**
- Modify: `cli/src/modelable/query_service.py`
- Modify: `cli/src/modelable/query_protocol.py`
- Modify: `cli/src/modelable/data/modelable.query.v1.schema.json`
- Modify: `cli/src/modelable/browser/dto.py`
- Modify: `cli/src/modelable/browser/api.py`
- Modify: `cli/src/modelable/browser/dispatch.py`
- Test: `cli/tests/test_query_protocol.py`
- Test: `cli/tests/test_query_service.py`
- Test: `cli/tests/test_browser_api.py`
- Test: `web/tests/conformance.spec.ts`

**Interfaces:**
- Adds query family `facets` with request `id` and optional `limit`/`cursor`.
- Produces `WorkspaceQueryProtocolService._facet_query(ref: str, limit: int, cursor: str | None) -> dict[str, object]`.
- Adds `facets: tuple[dict[str, object], ...]` to browser plan/graph/query DTO projections without changing native semantics.

- [ ] **Step 1: Write failing native and browser conformance tests.** Assert identical canonical JSON for a workspace with known, unknown, inherited, and projected facets; assert pagination order and unknown-facet visibility.

- [ ] **Step 2: Run focused tests and verify failure.**

Run: `uv run pytest -q tests/test_query_protocol.py tests/test_query_service.py tests/test_browser_api.py -k facet`

Expected: FAIL because query/v1 and browser DTOs do not expose facets.

- [ ] **Step 3: Implement the additive query response and browser conversion.** Reuse `facet_documents`, do not duplicate propagation or validation, include facets on declaration responses and field nodes, and keep response serialization deterministic.

- [ ] **Step 4: Run native tests, TypeScript checks, and the focused Chromium conformance test after rebuilding browser assets.**

```bash
cd cli
uv run pytest -q tests/test_query_protocol.py tests/test_query_service.py tests/test_browser_api.py -k facet
cd ../web
npm run check
npm run build
npm run test:e2e -- tests/conformance.spec.ts --project chromium --grep "facet"
```

Expected: all commands PASS; native and browser facet JSON must compare equal.

- [ ] **Step 5: Run focused tests, the four required CLI gates, and commit.**

```bash
cd cli
uv run pytest -q tests/test_query_protocol.py tests/test_query_service.py tests/test_browser_api.py -k facet
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
git add src/modelable/query_service.py src/modelable/query_protocol.py src/modelable/data/modelable.query.v1.schema.json src/modelable/browser/dto.py src/modelable/browser/api.py src/modelable/browser/dispatch.py tests/test_query_protocol.py tests/test_query_service.py tests/test_browser_api.py ../web/tests/conformance.spec.ts
git commit -m "feat: expose facets through query and browser protocols"
```

### Task 6: Add governance examples, showcase conformance, and documentation

**Files:**
- Create: `cli/tests/fixtures/facets/modelable.facets.json`
- Create: `cli/tests/fixtures/facets/retention-class.mdl`
- Create: `cli/tests/fixtures/facets/jurisdiction.mdl`
- Create: `cli/tests/fixtures/facets/data-subject.mdl`
- Create: `cli/tests/fixtures/facets/confidentiality.mdl`
- Create: `cli/tests/fixtures/facets/showcase-conformance.json`
- Modify: `cli/tests/test_facets.py`
- Modify: `web/tests/conformance.spec.ts`
- Modify: `ROADMAP.md`
- Modify: `docs/cli-reference.md`
- Modify: `docs/language-reference.md` only to document that arbitrary facets are sidecar data, not grammar
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces four executable examples covering scalar enum, object, subject restriction, projection propagation, and policy predicates.
- Produces a checked-in conformance manifest that the existing `modelable-showcase` validation can execute without changing parser grammar.

- [ ] **Step 1: Add the four fixtures and tests without modifying `.mdl` grammar.** Each fixture must compile with the shared sidecar and demonstrate one acceptance criterion from the spec.

- [ ] **Step 2: Run fixture, native, and browser conformance tests.**

Run: `uv run pytest -q tests/test_facets.py -k examples`; from `web/`, `npm run test:e2e -- tests/conformance.spec.ts --project chromium --grep "facet"`.

Expected: PASS with identical canonical facet output.

- [ ] **Step 3: Update documentation and mark only completed K checklist items in `ROADMAP.md`.** Do not mark K complete until all preceding tasks and cross-cutting gates pass.

- [ ] **Step 4: Run documentation review, all repository gates, coverage ratchet, browser/native conformance, and commit.**

Run `doc-review` against the changed documentation, then from `cli/` run the four required commands plus the coverage ratchet; from `web/` run `npm run check`, `npm run build`, and the facet Chromium conformance test. Run the existing `C:\git\modelable-showcase` conformance command against the checked-in manifest and record its result in the PR description.

- [ ] **Step 5: Open the PR from `roadmap/typed-semantic-facets`, wait for all required checks to pass, and stop before merge for review.**

## Plan self-review

- Spec coverage: Tasks 1–2 cover identity, typing, subjects, unknown preservation, and local schema/versioning; Task 3 covers propagation and deterministic lineage; Task 4 covers policy, plans, and overlay separation; Task 5 covers query and browser/native equivalence; Task 6 covers examples, schemas, conformance, documentation, and roadmap gates.
- No parser changes are planned; sidecar loading is explicit and network-independent.
- All cross-task interfaces are named above and use one normalized `Facet` representation.
- Unknown facets are never used for propagation or policy satisfaction.
- Existing built-in governance facts and overlay metadata remain separate.
