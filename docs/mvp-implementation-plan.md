# Modelable MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement milestone tasks. Keep task checkboxes current as work is completed.

**Date:** 2026-05-14
**Status:** Ready for execution
**Scope:** Phase 1 local modelling compiler

---

## Goal

Deliver a usable local Modelable compiler that can parse `.mdl` files, validate domain-owned canonical models and projections, compile a derived registry index, answer compatibility, lineage, and governance questions, and emit JSON Schema, Markdown documentation, and TypeScript types.

The MVP is successful when the acceptance criteria in `modelable-system-spec.md` section 20 pass through CLI workflows against representative local `.mdl` files.

## Source Documents

This plan is intentionally a delivery plan, not a replacement specification. The implementation must follow:

- `modelable-system-spec.md` - product source of truth and Phase 1 scope.
- `idl-design-spec.md` - `.mdl` syntax, auto projections, version ranges, and target catalog.
- `idl-parser-implementation-plan.md` - detailed parser, IR, semantic validator, and initial CLI `validate` work.
- `cli-spec.md` - command behavior, arguments, output directories, and exit codes.
- `cli-tooling-spec.md` - Python, uv, Hatchling, package layout, and bootstrap expectations.
- `emitter-spec.md` - JSON Schema, TypeScript, and Markdown output requirements.
- `cel-integration-spec.md` - Phase 1 CEL validation and lineage extraction.
- `ownership-permissions-spec.md` - MVP ownership, access, and POR requirements.

## MVP Boundary

### Included

- Python CLI package under `cli/` using uv and Hatchling.
- Lark parser and Pydantic IR for local `.mdl` files.
- Semantic validation for domains, model versions, fields, projections, auto projections, version references, ownership metadata, access metadata, and supported CEL expressions.
- Local file-first registry compiler that derives `.modelable/registry.db`.
- Plan documents under `.modelable/plans/` for projections and auto projections.
- Field-level lineage graph for canonical fields, direct mappings, computed expressions, and auto projection expansion.
- Compatibility checks for additive and breaking model changes.
- Governance findings that detect structurally unsafe or insufficiently documented projection of governed fields without claiming to enforce real-world organizational authorization.
- JSON Schema 2020-12 emitter with `x-modelable-*` extensions.
- Markdown documentation emitter.
- First-class codegen architecture with TypeScript generation via `json-schema-to-typescript` as the Phase 1 generated-language target.
- CLI commands required for MVP workflows: `validate`, `resolve`, `lineage`, `diff`, `compile`, `docs`, `inspect <Entity>@<v> --auto`, and `codegen`.
- A minimal `samples/mvp/` happy-path sample that avoids Phase 5 runtime-only constructs.
- Focused `cli/tests/fixtures/` coverage for parser, IR, validation, planner, compatibility, lineage, governance findings, emitters, CLI commands, and edge cases.

### Deferred

- Runtime materialization, subscriptions, stream processing, replay, and dead-letter handling.
- PostgreSQL, Kafka, CDC, and other runtime adapters.
- Apicurio, OpenMetadata, ODCS, Avro, Protobuf, OpenAPI, AsyncAPI, SQL DDL outputs, and generated-language targets beyond TypeScript.
- Distributed registry peer sync and consumer write-back execution.
- LSP implementation.
- AI commands such as `generate`, `describe`, `transform`, and `suggest-projection`.
- Cryptographic POR signing and ownership transfer workflow.

## Delivery Strategy

Use a vertical-slice sequence. Each milestone should add a user-visible CLI capability backed by tests, instead of building all internals before any command works.

Three strategies were considered:

| Strategy | Trade-off | Decision |
|---|---|---|
| Parser-first foundation | Fastest way to stabilize syntax and IR; user-visible value begins with `validate`. | Use this as the starting point because `idl-parser-implementation-plan.md` is already detailed. |
| Emitter-first prototype | Produces visible artifacts quickly but risks ad hoc parsing and weak lineage. | Reject for MVP because it weakens contract semantics. |
| Registry-first architecture | Strong internal shape but too much infrastructure before feedback. | Use after parser validation, when the normalized graph exists. |

## Milestone 0: Tooling Baseline

**Goal:** Make the repository executable as a Python CLI project.

**Primary files:**

- `cli/pyproject.toml`
- `cli/.python-version`
- `cli/uv.lock`
- `bin/modelable`
- `.github/workflows/ci.yml`

**Tasks:**

- [x] Create the `cli/` package scaffold described in `cli-tooling-spec.md`.
- [x] Add runtime dependencies: `click`, `lark`, `pydantic`, `rich`, `jsonschema`, `referencing`.
- [x] Add development dependencies: `pytest`, `pytest-cov`.
- [x] Add the root `bin/modelable` bootstrap script.
- [x] Add CI that runs `uv sync --extra dev --frozen` and `uv run pytest --tb=short`.
- [x] Verify `uv run modelable --help` exits `0`.

**Acceptance checks:**

```bash
cd cli
uv sync --extra dev
uv run modelable --help
uv run pytest
```

## Milestone 1: Parser, IR, and Base Validation

**Goal:** Parse local `.mdl` files into a typed normalized IR and reject basic invalid definitions.

**Primary files:**

- `cli/src/modelable/grammar/modelable.lark`
- `cli/src/modelable/parser/ir.py`
- `cli/src/modelable/parser/transformer.py`
- `cli/src/modelable/parser/parse.py`
- `cli/src/modelable/validation/semantic.py`
- `cli/src/modelable/compiler/compiler.py`
- `cli/src/modelable/cli.py`
- `cli/tests/test_grammar.py`
- `cli/tests/test_transformer.py`
- `cli/tests/test_semantic.py`
- `cli/tests/test_compiler.py`
- `cli/tests/test_cli.py`

**Tasks:**

- [ ] Execute `idl-parser-implementation-plan.md` through the `validate` command.
- [ ] Ensure grammar covers domains, owners, descriptions, model kinds, field annotations, primitive and composite types, projections, joins, aggregations, version ranges, generate blocks, bindings, workspace blocks, and auto projection declarations.
- [ ] Represent immutable model and projection versions explicitly in Pydantic IR.
- [ ] Preserve source location metadata for diagnostics.
- [ ] Validate entity and aggregate keys, event and value key absence, version ordering, projection mappings, aggregation usage, known annotations, and known types.
- [ ] Add parse and validation coverage for the minimal `samples/mvp/` happy-path sample.

**Acceptance checks:**

```bash
cd cli
uv run pytest tests/test_grammar.py tests/test_transformer.py tests/test_semantic.py tests/test_compiler.py tests/test_cli.py
uv run modelable validate ../samples/mvp
```

## Milestone 2: Local Registry Graph and Resolver

**Goal:** Compile all local `.mdl` files into a deterministic model graph and derived SQLite registry index.

**Primary files:**

- `cli/src/modelable/registry/schema.sql`
- `cli/src/modelable/registry/index.py`
- `cli/src/modelable/registry/resolver.py`
- `cli/src/modelable/registry/references.py`
- `cli/src/modelable/compiler/workspace.py`
- `cli/tests/test_registry_index.py`
- `cli/tests/test_resolver.py`

**Tasks:**

- [x] Add workspace discovery that loads all `.mdl` files from a file or directory path.
- [x] Merge definitions across files while preserving domain ownership boundaries.
- [x] Detect duplicate domains, duplicate model versions, duplicate projection versions, and generated-name conflicts.
  - Completed: duplicate domains, duplicate model versions, duplicate projection versions, and generated-name conflicts.
- [x] Resolve references in the form `domain.Model@version` and `domain.Model@>=min<max`.
- [x] Resolve version ranges to the highest matching published version at compile time.
- [x] Create `.modelable/registry.db` as a rebuildable artifact.
- [ ] Populate registry tables for domains, models, model versions, fields, projections, projection versions, projection sources, projection fields, field mappings, lineage edges, adapter bindings, compatibility reports, and access policies.
  - Completed: schema creation for the minimum logical tables; population for domains, models, model versions, fields, projections, projection versions, projection sources, projection fields, field mappings, and adapter bindings supported by the current IR.
  - Remaining: populated lineage edges, compatibility reports, and access policies after planner, compatibility, and governance behavior exists.
- [x] Keep source `.mdl` files as the only source of truth.

**Acceptance checks:**

```bash
cd cli
uv run pytest tests/test_registry_index.py tests/test_resolver.py
uv run modelable compile ../samples/mvp --target markdown --out ../dist/docs
```

## Milestone 3: Planner, Auto Projections, CEL, and Lineage

**Goal:** Turn validated definitions into inspectable plan documents with deterministic field-level lineage.

**Primary files:**

- `cli/src/modelable/planner/planner.py`
- `cli/src/modelable/planner/auto_projection.py`
- `cli/src/modelable/planner/lineage.py`
- `cli/src/modelable/expressions/cel.py`
- `cli/src/modelable/expressions/lineage.py`
- `cli/tests/test_planner.py`
- `cli/tests/test_auto_projection.py`
- `cli/tests/test_cel_validation.py`
- `cli/tests/test_lineage.py`

**Tasks:**

- [ ] Expand auto projections into explicit generated projection versions for `db`, `request`, `reply`, and `event`.
- [ ] Enforce generated projection name reservations.
- [ ] Apply auto projection exclusions for field names, `@pii`, and `@classification("level")`.
- [ ] Validate `event on [created, updated, deleted]` operation subsets.
- [ ] Build projection plan documents containing resolved source versions, field mappings, CEL expressions, join descriptors, aggregation descriptors, and planner metadata.
- [ ] Parse or validate the MVP CEL subset enough to reject unknown aliases, unknown fields, unsupported functions, aggregate misuse, and non-deterministic expressions.
- [ ] Extract source field references from computed fields, joins, filters, and aggregate arguments.
- [ ] Write `.modelable/plans/<domain>.<Projection>.v<version>.plan.json`.
- [ ] Implement `modelable inspect <Entity>@<v> --auto` to display generated projections.

**Acceptance checks:**

```bash
cd cli
uv run pytest tests/test_planner.py tests/test_auto_projection.py tests/test_cel_validation.py tests/test_lineage.py
uv run modelable inspect customer.Customer@1 --auto --path ../samples/mvp
```

## Milestone 4: Compatibility and Governance

**Goal:** Enforce published-contract semantics and surface governance findings for unsafe or insufficiently documented projection of governed fields.

**Primary files:**

- `cli/src/modelable/compat/diff.py`
- `cli/src/modelable/compat/checker.py`
- `cli/src/modelable/governance/ownership.py`
- `cli/src/modelable/governance/permissions.py`
- `cli/src/modelable/governance/por.py`
- `cli/tests/test_compatibility.py`
- `cli/tests/test_governance.py`
- `cli/tests/test_por.py`

**Tasks:**

- [ ] Compare consecutive model versions for additions, removals, renames, type changes, enum changes, identity changes, and nullability changes.
- [ ] Verify `(additive)` declarations only contain compatible changes.
- [ ] Verify `(breaking)` declarations mark affected projections as requiring re-validation.
- [ ] Implement `modelable diff REF_A REF_B --path PATH`.
- [ ] Preserve default same-domain access assumptions when no `access` block exists.
- [ ] Parse and record entity and property grants for `read`, `project`, `subscribe`, and `write`.
- [ ] Emit governance findings when a projection lacks documented `project` or `read` grants, or lacks derivation policy metadata for computed use of referenced source fields.
- [ ] Emit governance findings when a projection exposes `@pii`, restricted, or higher-classification fields without preserving governance metadata.
- [ ] Preserve source classification on projected fields and emit governance findings for attempts to lower or omit classification.
- [ ] Generate unsigned POR metadata and embed POR references in registry metadata for JSON Schema emission.

**Acceptance checks:**

```bash
cd cli
uv run pytest tests/test_compatibility.py tests/test_governance.py tests/test_por.py
uv run modelable diff customer.Customer@1 customer.Customer@2 --path ../samples/scenarios/01-ecommerce-data-warehouse
```

## Milestone 5: Phase 1 Emitters

**Goal:** Generate deterministic external artifacts from the normalized graph without weakening Modelable semantics.

**Primary files:**

- `cli/src/modelable/emitters/base.py`
- `cli/src/modelable/emitters/json_schema.py`
- `cli/src/modelable/emitters/markdown.py`
- `cli/src/modelable/emitters/typescript.py`
- `cli/src/modelable/emitters/diagnostics.py`
- `cli/tests/test_emit_json_schema.py`
- `cli/tests/test_emit_markdown.py`
- `cli/tests/test_emit_typescript.py`

**Tasks:**

- [ ] Define a deterministic emitter interface returning artifact metadata and diagnostics.
- [ ] Emit JSON Schema draft 2020-12 for models and projections.
- [ ] Map all MVP Modelable types to JSON Schema according to `emitter-spec.md`.
- [ ] Mark non-optional fields as required and optional fields as nullable or absent from `required` according to JSON Schema 2020-12 conventions.
- [ ] Add `x-modelable`, `x-modelable-field`, `x-modelable-classification`, `x-modelable-lineage`, `x-modelable-ref`, and `x-modelable-por`.
- [ ] Validate generated JSON Schema with `jsonschema`.
- [ ] Emit Markdown docs with domain metadata, field tables, projection source tables, and lineage tables.
- [ ] Generate TypeScript from JSON Schema through `json-schema-to-typescript`.
- [ ] Return clear deferred-target diagnostics for targets outside Phase 1.

**Acceptance checks:**

```bash
cd cli
uv run pytest tests/test_emit_json_schema.py tests/test_emit_markdown.py tests/test_emit_typescript.py
uv run modelable compile ../samples/mvp --target json-schema --out ../dist/jsonschema
uv run modelable compile ../samples/mvp --target markdown --out ../dist/docs
uv run modelable compile ../samples/mvp --target typescript --out ../dist/types
```

## Milestone 6: CLI Workflows

**Goal:** Provide the complete local authoring workflow described for MVP.

**Primary files:**

- `cli/src/modelable/cli.py`
- `cli/src/modelable/commands/validate.py`
- `cli/src/modelable/commands/resolve.py`
- `cli/src/modelable/commands/lineage.py`
- `cli/src/modelable/commands/diff.py`
- `cli/src/modelable/commands/compile.py`
- `cli/src/modelable/commands/docs.py`
- `cli/src/modelable/commands/inspect.py`
- `cli/src/modelable/commands/codegen.py`
- `cli/src/modelable/commands/scenario.py`
- `cli/tests/test_cli_workflows.py`

**Tasks:**

- [ ] Split command implementations into focused command modules once `cli.py` becomes too large.
- [ ] Implement `validate [PATH] [--strict]`.
- [ ] Implement `resolve REF [--path PATH]`.
- [ ] Implement `lineage REF [--path PATH]`.
- [ ] Implement `diff REF_A REF_B [--path PATH]`.
- [ ] Implement `compile SOURCE --target TARGET [--out DIR] [--path PATH]`.
- [ ] Implement `docs SOURCE [--out DIR]` as a wrapper around markdown compilation.
- [ ] Implement `inspect <Entity>@<version> --auto [--path PATH]`.
- [ ] Implement `codegen formats` and `codegen types [--format FORMAT]`.
- [ ] Implement `scenario list`, `scenario show`, and `scenario load` for bundled local samples.
- [ ] Ensure exit codes match `cli-spec.md`.

**Acceptance checks:**

```bash
cd cli
uv run pytest tests/test_cli_workflows.py
uv run modelable validate ../samples/mvp --strict
uv run modelable resolve customer.Customer@1 --path ../samples/mvp
uv run modelable lineage customer.CustomerReply@1 --path ../samples/mvp
uv run modelable docs ../samples/mvp --out ../dist/docs
uv run modelable codegen formats
uv run modelable scenario list
```

## Milestone 7: MVP Hardening and Release Candidate

**Goal:** Make the MVP reliable enough for local use and future phase work.

**Primary files:**

- `README.md`
- `docs/README.md`
- `samples/README.md`
- `samples/mvp/*`
- `samples/scenarios/*`
- `cli/tests/test_samples.py`
- `.gitignore`

**Tasks:**

- [ ] Add an MVP smoke test that validates and compiles the minimal `samples/mvp/` happy-path sample.
- [ ] Document existing `samples/scenarios/` examples as illustrative scenarios and mark future-phase exceptions rather than requiring Phase 1 strict validation.
- [ ] Ensure `.modelable/`, `dist/`, `.venv/`, and generated TypeScript output directories are ignored unless explicitly documented otherwise.
- [ ] Document the MVP quick-start workflow in `README.md`.
- [ ] Document the known deferred commands and targets in CLI help.
- [ ] Run the full test suite and sample smoke workflow from a clean checkout.

**Acceptance checks:**

```bash
cd cli
uv sync --extra dev --frozen
uv run pytest --tb=short
uv run modelable validate ../samples/mvp --strict
uv run modelable compile ../samples/mvp --target json-schema --out ../dist/jsonschema
uv run modelable compile ../samples/mvp --target markdown --out ../dist/docs
uv run modelable compile ../samples/mvp --target typescript --out ../dist/types
```

## MVP Acceptance Matrix

| System spec acceptance criterion | Milestone coverage |
|---|---|
| A domain can publish a model version. | Milestones 1, 2, 6 |
| Another domain can define and publish a projection over that model. | Milestones 1, 2, 3, 6 |
| The system can validate the projection before runtime. | Milestones 1, 3, 4, 6 |
| The system can detect whether a model change breaks existing projections. | Milestone 4 |
| The system can show lineage from projection fields to source fields. | Milestones 3, 6 |
| The model and projection can be exported as JSON Schema and TypeScript types. | Milestones 5, 6 |
| Projection of restricted or insufficiently governed fields is detected and reported. | Milestone 4 |

## Suggested Implementation Order

1. Complete `idl-parser-implementation-plan.md` unchanged unless a contradiction with the current specs is found.
2. Add local graph resolution and SQLite indexing before emitters.
3. Add planner and lineage before compatibility and governance, because governance depends on resolved source fields.
4. Add JSON Schema first, then Markdown, then TypeScript.
5. Finish CLI workflows after internals are stable enough to avoid command-specific behavior forks.
6. Harden with the minimal `samples/mvp/` workflow, focused edge-case fixtures, and clean-checkout CI.

## Verification Policy

Before claiming an MVP milestone complete:

- Run the milestone-specific tests.
- Run any CLI acceptance commands listed for the milestone.
- Review generated artifacts for deterministic names, version metadata, lineage metadata, and absence of runtime-only commitments.
- Check `git status --short` and avoid committing generated artifacts.

Before claiming MVP complete:

- Run the full CLI test suite.
- Validate `samples/mvp/` with `--strict`.
- Compile JSON Schema, Markdown, and TypeScript from `samples/mvp/`.
- Confirm the generated JSON Schema validates with `jsonschema`.
- Confirm governance fixture tests emit clear findings for restricted, insufficiently documented, or classification-lowering projections.

## Risks and Decisions to Track

| Topic | Current decision | Risk |
|---|---|---|
| CEL implementation | Validate the MVP subset and extract lineage during Phase 1. | A full CEL parser may be larger than needed; keep the supported subset explicit. |
| Published state | Use version declarations in `.mdl` as immutable published contracts for MVP. | A future publish workflow may add registry state, but must not mutate source files. |
| Governance findings | Preserve ownership and access metadata in IR, registry metadata, POR metadata, and generated artifacts. Detect structural governance issues as findings rather than claiming to enforce organizational authorization. | Findings must be clear enough for process governance and CI policy wrappers to act on later. |
| Codegen architecture | Make codegen a first-class extensible boundary. Implement TypeScript in Phase 1 through `json-schema-to-typescript`; treat Java, .NET, Rust, Python, and framework targets as future first-class targets. | The Phase 1 interface must not bake in TypeScript-only assumptions. |
| Samples | Add a minimal `samples/mvp/` happy-path sample for strict acceptance. Use `cli/tests/fixtures/` for governance, compatibility, and edge-case coverage. | The MVP sample must stay approachable while tests still cover meaningful compiler risk. |

## Out of Scope

Do not add runtime adapters, streaming execution, materializers, external registries, catalog sync, LSP, or AI authoring commands while completing this MVP unless the product direction changes explicitly.
