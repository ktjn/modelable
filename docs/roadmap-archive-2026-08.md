# Roadmap Archive — August 2026

> **Status:** Historical snapshot/index. The active roadmap is [`ROADMAP.md`](../ROADMAP.md).
>
> This file preserves the shipped-state record, legacy priority/slice vocabulary, and migration context from the roadmap that existed immediately before the stabilization rewrite at commit `2d47f38bd169394901fcfc8ee57573ce1fb8d2b9`.
>
> Git history remains the byte-for-byte source for the previous 2,196-line roadmap. This archive intentionally keeps the durable decisions and anchors without carrying the old document's full narrative into the active roadmap.

## Historical baseline

The latest published release recorded by the previous roadmap was **1.11.0**.

The stable 1.x surface included:

- `.mdl` language, semantic validation, compatibility and lineage reporting, governance findings, LSP and VS Code support;
- deterministic generation for JSON Schema, OpenAPI, Avro, TypeScript, C#, Java, Python, Rust, Go, SQL DDL, dbt, Markdown, FHIR R4, OpenMetadata, OpenLineage, ODCS, Protobuf, event-sink contracts, and Scalable-oriented gRPC services;
- deterministic import/migration support for the supported schema/data-contract formats;
- local/offline registry/index behavior;
- browser compiler/playground using the same compiler semantics;
- public conformance fixtures and external-validator smoke coverage;
- multi-package Rust generation and release automation.

The old roadmap also recorded shipped fixed-width integer/binary support, `uuid(7)`, Rust nominal semantic newtypes, `registry-ids.lock`, index declarations, Protobuf/gRPC fidelity work, OpenAPI 3.1 generation/compatibility, Avro export, and related contract hardening.

## Historical delivery lanes

The previous roadmap used these lanes/priorities:

- **Priority 1:** Playground — paused after substantial browser/compiler/tooling delivery.
- **Priority 2:** Scalable/Rust contract path — paused after Rust/Protobuf/gRPC identity and compatibility work.
- **Priority 3:** compiler correctness, compatibility, and capability integrity.
- **Priority 4:** offline registry, consequence-driven developer experience, generated conversions/defaults, adoption.
- **Priority 5:** external integrations and format interoperability.
- **Priority 6:** language evolution and extensibility.
- **Priority 7:** repository-health/engineering ratchets.

The stabilization roadmap replaces this priority model with explicit dependency edges, but shipped work remains valid.

## Historical operating invariants

The previous roadmap established several rules that remain active:

1. Confirmed false compatibility results are release blockers.
2. Parsed/supported content must not be silently lost or ignored.
3. New broad language features require a concrete consumer and accepted design.
4. New importers/emitters require deterministic representative regression fixtures before becoming stable.
5. Browser/native semantics must not diverge.
6. Runtime-adjacent grammar that has no implementation must be reported explicitly rather than silently discarded.

## Priority 1 — Playground

Shipped browser work included:

- Pyodide/browser compiler using the same compiler source;
- React/Monaco editor;
- IndexedDB workspace persistence;
- browser-native language services;
- visualization and analysis views;
- local AI/WebLLM and optional Ollama provider;
- offline/service-worker hardening;
- documentation RAG integration;
- browser/native conformance coverage.

Further expansion was paused pending concrete product need.

## Priority 2 — Scalable and Rust contract path

Shipped work included:

- stable Rust identity constants;
- nominal semantic identity carried into Protobuf;
- Protobuf map/schema fidelity improvements;
- descriptor artifacts and source reservations;
- Protobuf/gRPC compatibility validation.

Scalable-specific registration/runtime work was postponed.

## Priority 3 — compiler correctness, compatibility, and capability integrity

### Slice A1 — correct optionality compatibility under the current model

Shipped. `optional -> required` is breaking while `required -> optional` is compatible under the current model.

### Slice A2 — create one property-dependency graph

Shipped. Direct mappings, expressions, joins, filters, grouping, and projection chains converge on one dependency graph consumed by compatibility, governance, lineage, graph export, and tooling.

### Slice A3 — validate all expression positions

Shipped. CEL/expression validation covers computed fields, joins, filters, grouping, and supported expression-bearing annotations.

### Slice A4 — fix semantic-type resolution ambiguity

Shipped. Resolution is domain-aware and deterministic; ambiguous workspace-wide bare references are errors.

### Slice B1 — add a canonical capability manifest

Shipped as `modelable capabilities` / `cli/src/modelable/capabilities.py`.

### Slice B2 — reconcile current documentation claims

Partially historical/continuous. Composite-key and optionality contradictions were corrected. Remaining rule: compiler capability state is authoritative over stale prose.

### Slice B3 — eliminate silently ignored syntax

Shipped. Workspace registry/peers, consumer declarations, subscriptions, materialisation, and unsupported binding content produce explicit `DEFERRED` diagnostics instead of being silently discarded.

### Slice C1 — projection-to-projection compatibility

Shipped. Projections are first-class versioned contracts and compare both direct projection changes and source-version effects.

### Slice C2 — extend existing version resolution to `ref<>` types

Shipped. Type references use the canonical version resolver rather than a separate path.

### Slice C3 — generalize existing target compatibility

Shipped. Protobuf/gRPC-specific compatibility concepts were generalized into target compatibility axes/severity data.

### Slice C4 — configurable compatibility and lint policy

Shipped policy foundation.

### Slice G1 — critical compatibility coverage

Shipped and continuous. Critical compatibility/resolution/expression/lineage/governance/signature/target paths use a coverage ratchet.

### Slice G2 — strict typing baseline reduction

Continuous. `mypy --strict` is enforced through a baseline ratchet that may only improve.

### Slice G3 — conformance fixtures

Shipped and continuous. Shared native/browser/LSP/Playground/signature/compatibility fixtures protect disputed and critical semantics.

## Priority 4 — consequence-driven developer experience and adoption

The previous roadmap established the offline-registry/consequence direction that the stabilization architecture keeps and generalizes.

Shipped/active items included:

1. conversational workspace management;
2. VS Code conversational foundation;
3. Conversational Compilation Management;
4. durable offline registry snapshot work;
5. derived application usage/consequence graph direction;
6. staged consequence-aware registry updates;
7. proof-driven generated conversions;
8. deterministic defaults/override hierarchy;
9. nominal semantic-type generation beyond Rust;
10. registry/signature inspection DX;
11. VS Code Marketplace publication as a product/distribution follow-up;
12. ongoing conformance/documentation/importer hardening.

### Conversational Compilation Management

Shipped through CLI chat and the native VS Code participant.

Archived design:

`docs/superpowers/specs/archived/2026-07-19-conversational-compilation-management-design.md`

The implementation stages real compiler output, presents exact affected artifacts/definitions, requires confirmation, checks freshness, promotes staged bytes with rollback, and records privacy-preserving audit evidence.

## Priority 5 — external integrations and format interoperability

The old roadmap emphasized format-adapter normalization, representative real-world fixtures, deterministic offline regression data, round-trip/equivalence testing where practical, clear unsupported-feature diagnostics, and reference-validator smoke tests.

OpenAPI hardening/export was shipped. Other format work remained demand/prerequisite driven.

### Slice F2 — OpenAPI emission

Shipped. OpenAPI 3.1 full-document generation and compatibility support became part of the stable target surface.

## Priority 6 — language evolution and extensibility

The old roadmap collected language prerequisites and emitter propagation work here. Stabilization now makes the contribution rule stricter: prefer existing semantics + extensions/overlays before grammar expansion.

### Slice D1 — separate presence and nullability

Historical language-evolution item. Any remaining implementation must preserve already-shipped optionality compatibility behavior.

### Slice D2 — value and semantic type evolution

Historical semantic-type/value evolution work.

### Slice D3 — enum declaration convergence

Historical enum work that led toward nominal, versioned enum-backed semantic declarations and enum projections.

### Slice D4 — discriminated unions

Historical/future language item. Not automatically committed under stabilization.

### Slice D5 — resolve composite-key support

Composite keys were not implemented in the stable compiler at archive time. Entities/aggregates require exactly one `@key` field.

### Slice D6 — model lifecycle status

Draft/published/deprecated/retired lifecycle state was not represented in the stable grammar/IR at archive time.

### Slice F1 — nominal semantic types beyond Rust

Rust, Protobuf, and gRPC preserved nominal semantic identity; broader target support remained demand-driven.

## Priority 7 — repository health

Continuous engineering work included strict typing reduction, per-critical-path coverage ratchets, pinned/verified release actions, dependency audits, documentation consistency tests, and conformance fixtures.

These are not superseded by the stabilization roadmap.

## Historical registry direction

The previous roadmap had already moved away from a mandatory hosted registry:

```text
source adapters
   ↓
deterministic dependency snapshot / lock
   ↓
content-addressed normalized contracts
   ↓
rebuildable local registry.db index/cache
```

Normal validate/compile/diff/impact/lineage/editor operations were intended to run entirely from local source plus exact snapshot state. Same logical version with different canonical content is an error, not an implicit update.

The stabilization roadmap formalizes this direction as `modelable.lock/v1` after usage semantics are defined.

## Historical consequence direction

The old roadmap proposed deriving application usage from actual contract references and producing machine-readable impact actions such as:

- regenerate;
- recompile;
- consumer update;
- storage migration;
- data backfill;
- projection rebuild;
- event replay;
- governance review;
- breaking/manual intervention.

The stabilization roadmap promotes this into a first-class usage graph and consequence graph.

## Historical runtime boundary

The old roadmap explicitly treated the following as outside the near-term compiler roadmap:

- subscription runtime;
- general materialization engine;
- broker abstraction;
- database synchronization runtime;
- retry/dead-letter engine;
- distributed mutation registry service.

Existing syntax without implementation was retained with explicit deferred diagnostics. The stabilization architecture keeps that disposition.

## Migration from legacy slices to stabilization phases

| Legacy area | Stabilization destination |
|---|---|
| A1/A3 correctness | Operating rules 1–3 + continuous conformance |
| A2 dependency graph | Phases 7, 9, 10 |
| A4 resolution | Phases 1–2 |
| B1 capabilities | Phase 5 |
| B2 docs/capability consistency | architecture current-status sections + continuous tests |
| B3 deferred syntax | current/deferred syntax disposition |
| C1–C4 compatibility/policy | Phases 9–11 |
| D1–D6 language evolution | Phase 2 or deferred under grammar-freeze rule |
| F1 nominal target identity | Phase 5 target capabilities |
| F2 OpenAPI | shipped target; maintained through Phase 10/12 conformance |
| G1–G3 engineering safeguards | continuous throughout all phases |
| Priority 4 registry/usage/consequence | Phases 7–9 |
| format interoperability | extensions/emitters after stabilization prerequisites |

## Source record

For exact historical wording and every old priority/slice detail, use Git history at:

`2d47f38bd169394901fcfc8ee57573ce1fb8d2b9:ROADMAP.md`

This archive exists so normal documentation navigation does not depend on reconstructing that commit and so legacy terminology remains explainable after the active roadmap rewrite.