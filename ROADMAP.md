# Roadmap

Modelable's stabilization baseline is complete.

The latest published release is **1.13.2**.

The product already has broad language, compatibility, lineage, code generation, import, browser, and tooling capability. The next priority is not adding more surface area. It is making the semantic core stable enough that future capability can be added without repeatedly changing grammar, IR, compatibility logic, and every emitter.

## Current execution status

The stabilization completion criteria below are satisfied by the shipped
1.13.2 baseline. Modelable can now resume broader feature growth while the
conformance and repository-health checks remain release gates.

### Phase execution status

The phase headings below describe the architectural destination; they are not
an unstarted twelve-item queue. The shipped stabilization baseline already
delivered the following portions:

| Phase | Current state | Modelable evidence |
| --- | --- | --- |
| 1. Identity/path grammar | Baseline implemented; fixture hardening remains | `modelable.identity`, overlays, lineage, graph export, and usage validation share canonical identities and semantic paths; projection-chain lineage now resolves through projection sources to the ultimate canonical model path. |
| 2. Declaration/projection unification | Partial | `ResolvedDeclarationView` now covers model, projection, semantic-type, and enum-projection resolution; a private candidate boundary enumerates all four declaration families, semantic-type and enum-projection version selection share one helper, and auto-generated projections normalize into sorted ordinary projection versions. |
| 3. `plan/v0` | Baseline implemented | `modelable.planner.protocol` validates deterministic plans and rejects malformed or non-canonical references. |
| 4. Overlays | Baseline implemented | Version-aware overlay selectors, including full-segment semantic-path wildcards, are validated against canonical identities and paths. |
| 5. Extensions/capabilities/trust | Partial | Extension descriptors, capability admission, provenance pins, and deny-by-default trust policy are enforced; no third-party discovery or subprocess/WASM execution path exists yet. |
| 6. `plan/v1` | Mostly implemented; freeze follow-up remains | `plan/v1` migration, parser-free target consumers, checked-in JSON Schema, command admission defaults, and a subprocess import-isolation regression gate are covered; final v0 compatibility rules remain. |
| 7. Usage graph | Baseline implemented | Compiled usage manifests, application/package identity, field references, aggregation, and dependent queries are available. |
| 8. `lock/v1` | Baseline implemented | Deterministic registry snapshots, provenance, usage evidence, and compatibility-critical allocation ledgers are validated. |
| 9. Consequence graph | Baseline implemented | Structured causal nodes/edges and terminal actions are emitted for compatibility, projection, consumer, and policy findings. |
| 10. Layered compatibility | Baseline implemented | Target-neutral semantic changes are interpreted by target compatibility evaluators and admitted through extension capabilities. |
| 11. Policy boundary | Baseline implemented | External policy evaluators return structured findings and consequences without grammar or semantic-IR changes. |
| 12. Host/showcase conformance | Continuous gate | Browser/native conformance, generated-target smoke coverage, and external showcase validation remain release criteria. |

The next implementation slice is therefore a demand-driven extension of this
baseline, not a second pass over already-shipped stabilization plumbing. The
deferred Playground UI uplift remains intentionally outside the current queue.

The completed offline-registry/consequence and model-evolution programmes are
archived with their implementation plans and remain part of the shipped
stabilization baseline:

- [Offline registry and consequence delivery](docs/superpowers/plans/archived/2026-08-21-offline-registry-dx-delivery.md)
- [Model evolution slices](docs/superpowers/plans/archived/2026-08-22-model-evolution-slices-roadmap.md)

The ongoing release gates are deliberately narrower:

- Phase 12 host/showcase conformance and sibling-project validation remain
  continuous release gates.

The phase sections below are the canonical architectural roadmap; archived
plans provide the detailed delivery history and acceptance evidence for work
already completed.

The architecture source of truth is [docs/architecture.md](docs/architecture.md). The previous shipped-state roadmap has been retained as [docs/roadmap-archive-2026-08.md](docs/roadmap-archive-2026-08.md) so historical slice names and shipped decisions remain discoverable.

## Goal

Stabilize Modelable around this product boundary:

```text
semantic graph
    +
usage graph
    +
change graph
    ↓
consequence graph
    ↓
versioned plan
    ↓
extensions
```

The semantic graph and consequence graph are the durable product. Emitters, policies, adapters, registries, catalogs, framework integrations, and runtime consumers remain replaceable edges.

## Operating rules

1. **Correctness first.** Confirmed false compatibility results are release blockers.
2. **No silent loss.** Parsed content that is silently ignored or discarded without an explicit diagnostic is a release blocker for the affected construct.
3. **Language stability.** Old stable syntax never changes meaning silently. New semantics require new syntax, an explicitly versioned protocol change, or a compatibility-preserving migration path.
4. **Grammar freeze by default.** New broad grammar features are paused unless existing semantics cannot represent the requirement correctly.
5. **Target behavior stays at the edge.** New target/framework behavior should prefer overlays or extensions over core annotations.
6. **One normalized compiler boundary.** New emitters and analyzers consume normalized compiler output rather than duplicate semantic resolution.
7. **Browser/native equivalence.** Browser and native compilation remain semantically equivalent.
8. **Conformance before completion.** Significant semantic changes require realistic external conformance coverage in `modelable-showcase` or an equivalent cross-surface fixture.
9. **Runtime stays external.** Runtime execution features remain outside the core roadmap.
10. **Security is part of extensibility.** Executable extensions, dependency refresh, and generated-code-affecting configuration require explicit provenance/trust rules.

## Delivery model

This roadmap is **dependency-ordered, not a twelve-step serial queue**. Work can run in parallel when dependencies are satisfied.

```text
Phase 1 identity/path grammar
        ↓
Phase 2 declaration/projection unification
        ↓
Phase 3 plan/v0 ───────────────┐
        ↓                      │
Phase 4 overlays               │
        ↓                      │
Phase 5 extension capabilities │
        ↓                      │
Phase 6 plan/v1 ◀──────────────┘

Phase 1 ──▶ Phase 7 usage graph ──▶ Phase 8 lock/v1

Phase 2 + Phase 7 ──▶ Phase 9 consequence graph
Phase 2 + Phase 5 + Phase 9 ──▶ Phase 10 layered compatibility
Phase 5 + Phase 9 ──▶ Phase 11 policy extensions

Phase 3 onward ──▶ Phase 12 showcase/host conformance (continuous)
```

Parallel work allowed:

- conformance and documentation cleanup can proceed throughout;
- emitter migration to `plan/v0` can start while overlays/capabilities are being designed;
- usage-graph work can proceed beside overlay/extension work after identity is stable;
- security hardening for extension execution should proceed with Phase 5, not after it;
- repository-health ratchets remain continuous and do not wait for product phases.

## Phase 1 — Freeze semantic identity and path grammar

### Outcome

One canonical identity/path model for every reusable declaration and nested semantic location.

### Work

- Define canonical qualified declaration identities.
- Define the semantic path grammar used by overlays, plans, lockfiles, lineage, usage, and diagnostics.
- Cover nested value/object fields, arrays, maps, enum members where applicable, and projection-of-projection lineage.
- Define normalization/case rules and future escaping rules before escaped identifiers can ship.
- Ensure identity is independent of source file location and emitter naming.
- Unify resolution rules for entities, aggregates, events, values, enums, semantic types, and projections.
- Continue nominal enum/semantic-type references rather than copying structural definitions.
- Add parse/render round-trip and collision fixtures.

### Acceptance

The compiler can deterministically parse/render identities such as:

```text
customer.Customer@4
customer.Customer@4#email
customer.Customer@4#address.street
customer.Customer@4#orders[]
customer.Customer@4#attributes{}
```

No overlay/plan/lock consumer needs to invent its own path syntax.

## Phase 2 — Unify declarations and projections

### Outcome

Avoid parallel implementations for each semantic declaration kind before freezing an external plan.

### Work

- Establish a common declaration abstraction for entity, aggregate, event, value, enum, semantic type, and projection.
- Centralize ownership, versioning, reference, identity, compatibility, and deprecation behavior where semantics are shared.
- Treat projections as the universal named/versioned derivation mechanism.
- Support enum and other declaration projections without separate subset systems.
- Normalize auto projections into ordinary projection semantics early.
- Remove declaration-kind-specific resolution paths where equivalent generic logic can be used.

### Acceptance

Adding a declaration capability does not recreate version resolution, identity, lineage, and compatibility infrastructure.

## Phase 3 — Introduce unstable `modelable.plan/v0`

### Outcome

Emitters/analyzers stop depending on parser/internal Python classes without prematurely promising a stable v1 schema.

### Work

- Define deterministic JSON-compatible `modelable.plan/v0`.
- Include resolved declarations, versions, nominal references, projections, lineage, and target-neutral generation facts.
- Add golden conformance fixtures.
- Ensure browser and native hosts produce equivalent plans.
- Migrate representative emitters/analyzers to consume the plan boundary.
- Permit breaking v0 revisions while Phases 4–5 reveal missing target-neutral facts.

### Acceptance

A standalone tool can consume `plan/v0` without importing parser/semantic-validation internals, with the explicit understanding that v0 is unstable.

## Phase 4 — Separate target configuration from semantics

### Outcome

Target representation choices stop expanding `.mdl` and semantic IR.

### Work

- Adopt the TOML overlay direction in [docs/emitter-extension-overlays.md](docs/emitter-extension-overlays.md).
- Key overlays by the canonical identity/path grammar from Phase 1.
- Define deterministic selector inheritance and precedence:
  - target defaults;
  - declaration wildcard;
  - compatible version range;
  - exact declaration version;
  - wildcard/range semantic path;
  - exact semantic path.
- Reject equal-specificity conflicts rather than rely on file order.
- Expose overlay configuration schemas through target descriptors.
- Keep overlays non-executable and schema validated.
- Keep compatibility-critical allocation state out of overlays.
- Plan migration/deprecation of `@wire` without changing existing syntax meaning.

Example:

```toml
[sql-postgres."customer.Customer@*"]
table = "customers"

[csharp."customer.Customer@>=4,<7#customerId"]
property_name = "CustomerId"
```

### `@wire` deprecation rule

`@wire` keeps its current stable meaning. New target-specific capabilities prefer overlays. Deprecation diagnostics may begin only after equivalent overlay support and migration tooling exist. Removal is not part of stabilization and would require a major language-version decision after at least one full stable deprecation cycle.

### Acceptance

A framework-specific integration such as Unity-specific C# generation can be configured without adding a Unity/framework keyword to `.mdl`, and a version bump does not require blindly copying every overlay entry.

## Phase 5 — Introduce extension descriptors, capabilities, and trust policy

### Outcome

Targets become discoverable components rather than entries in centralized conditionals, with an explicit execution trust model.

### Work

- Define `modelable.extension/v1`.
- Define extension descriptors containing id, version, supported plan versions, capabilities, configuration schema, output kinds, and compatibility support.
- Define standard semantic capabilities such as records, enums, semantic types, maps, unions, constraints, lineage, and compatibility.
- Validate plans against target capabilities before emission.
- Move target capability ownership toward target implementations.
- Keep an in-process Python extension path while defining language-neutral subprocess/WASM boundaries.
- Define provenance pins for third-party extensions: id + exact version + implementation hash + source/provenance.
- Define explicit allow/trust policy for subprocess extensions.
- Make no-network/least-filesystem capability the default for sandboxable extension hosts.
- Never auto-execute an extension merely because it is discoverable on PATH or in a workspace.

### Acceptance

Unsupported constructs fail through one compiler-owned capability check, and reproducible compilation can prove exactly which extension implementation ran.

## Phase 6 — Freeze `modelable.plan/v1`

### Dependencies

Phases 1, 2, 3, and 5.

### Outcome

Emitters/analyzers depend on a stable normalized contract rather than parser/internal Python classes.

### Work

- Incorporate lessons from `plan/v0` emitter migrations.
- Freeze canonical identity/path representation.
- Freeze normalized declaration/projection shape.
- Freeze the target-neutral facts required for capability negotiation and compatibility evaluators.
- Version the JSON schema and migration rules.
- Keep parser/Pydantic implementation classes internal.

### Acceptance

`modelable.plan/v1` can evolve additively under documented compatibility rules without requiring lockstep compiler/emitter releases.

## Phase 7 — Build the usage graph

### Dependencies

Phase 1; Phase 2 where declaration normalization affects usage evidence.

### Outcome

Impact analysis is based on actual consumers rather than only theoretical references or manually maintained consumer declarations.

### Work

- Produce usage evidence from compilation.
- Define stable application/workspace/package identity.
- Track exact declaration, projection, and field/path use where observable.
- Aggregate usage snapshots across applications/repositories.
- Keep `consumer {}` non-authoritative unless a future concrete purpose needs it.
- Expose usage queries to CLI, CI, IDE, and agent surfaces.

### Acceptance

Given a declaration version/path, Modelable can identify known compiled consumers and distinguish actual blast radius from theoretical compatibility.

## Phase 8 — Formalize `modelable.lock/v1`

### Dependencies

Phases 1 and 7. Extension pins from Phase 5 are incorporated when available.

### Outcome

Registry state becomes reproducible dependency/usage/allocation evidence rather than infrastructure.

### Work

Define deterministic lock state containing:

- exact declaration versions;
- content hashes;
- source provenance;
- transitive dependencies;
- canonical semantic identities;
- actual usage evidence;
- extension id/version/hash/provenance;
- compatibility-critical target allocations;
- optional plan/generation fingerprints.

The local SQLite registry/index must be reconstructable from version-controlled inputs and lock data.

### Protobuf allocation rule

**Protobuf field numbers belong in lock state, not optional overlays.** Missing/drifted representation configuration must never silently cause wire-incompatible field-number reassignment. Use a deterministic allocator/ledger model analogous to the existing git-tracked `registry-ids.lock` precedent.

The same mechanism should generalize to future persistent target identifiers that cannot safely be recomputed.

### Acceptance

A clean offline checkout can reproduce resolution, verify extension provenance, reproduce compatibility-critical allocations, and prove exactly which semantic contracts a consumer compiled against.

## Phase 9 — Replace flat consequences with a consequence graph

### Dependencies

Phases 2 and 7.

### Outcome

Model evolution produces explainable causal paths and actionable downstream work.

### Work

- Replace growing string-only consequence statuses with structured nodes/edges.
- Represent chains such as:

```text
field removal
  ↓
projection affected
  ↓
generated schema changes
  ↓
known consumer affected
  ↓
consumer update required
```

- Preserve causal paths for every terminal action.
- Support actions including regenerate, recompile, storage migration, data backfill, projection rebuild, event replay, governance review, consumer update, and breaking/manual intervention.
- Keep simple CLI summaries as views over the graph.

### Acceptance

Every reported impact can be traced from root semantic change to affected consumer action.

## Phase 10 — Separate semantic and target compatibility

### Dependencies

Phases 2, 5, and 9.

### Outcome

Core compatibility produces target-neutral facts; extensions interpret them for wire/storage/API constraints.

### Work

- Define a canonical semantic change vocabulary.
- Keep generic diff logic free of Protobuf field numbers, SQL migration strategy, Avro reader/writer rules, and generated-language syntax.
- Move target rules to target compatibility evaluators.
- Feed target results into the consequence graph.
- Keep compatibility deterministic and independently testable.

### Acceptance

Adding a target compatibility evaluator does not modify semantic diff algorithms.

## Phase 11 — Policy extension boundary

### Dependencies

Phase 5; Phase 9 when policy findings should become consequences.

### Outcome

Governance grows without adding permanent language annotations for every regulation or organization.

### Work

- Define a policy evaluator interface over semantic/usage/consequence data.
- Keep facts such as PII, classification, ownership, and lineage in core semantics.
- Implement organization/regulation-specific checks outside the fixed annotation set.
- Allow policies to produce diagnostics and consequences.
- Define severity/configuration handling outside source semantics where appropriate.

### Acceptance

A custom enterprise policy can be added without grammar or semantic-IR change.

## Phase 12 — Showcase and host conformance (continuous)

### Outcome

Real consumer builds and every host detect semantic regressions before release.

### Work

Make `modelable-showcase` an executable conformance suite covering:

- canonical models;
- semantic types;
- enums and enum projections;
- nested/value types;
- API request/reply projections;
- events;
- persistence projections;
- multiple programming-language emitters;
- Protobuf/OpenAPI/Avro/SQL;
- version evolution;
- compatibility/consequence analysis;
- generated conversions;
- browser/native compilation;
- real generated consumer compilation.

Continue reducing filesystem/network/process assumptions in compiler-core APIs so CLI, browser, LSP, CI, build plugins, MCP, and future server surfaces remain thin hosts around one semantic engine.

### Acceptance

A semantic feature is not complete until realistic cross-boundary scenarios validate it, and a new host can be built without duplicating parsing/resolution/compatibility/lineage semantics.

## Current/deferred syntax disposition

Runtime-adjacent syntax already exists and cannot simply disappear under the new runtime boundary.

During stabilization:

- `subscription` remains parsed but explicitly `DEFERRED`; no runtime execution is added.
- projection `materialisation` remains parsed but explicitly `DEFERRED`.
- workspace `registry {}` / `peers` forms that have no semantic effect remain explicitly `DEFERRED`.
- `consumer {}` remains deferred/non-authoritative; usage evidence is the preferred future mechanism.
- `binding {}` retains its implemented compile-time subset; unsupported opaque content remains explicitly `DEFERRED`.

No parsed construct may be silently discarded. Future removal/replacement requires an explicit language migration under Operating rule 3.

## Shipped product record retained during stabilization

The old roadmap mixed shipped history with future work. That history is now retained in [docs/roadmap-archive-2026-08.md](docs/roadmap-archive-2026-08.md) rather than deleted.

### Conversational Compilation Management

Conversational Compilation Management is shipped through CLI chat and the native VS Code participant. The completed design remains archived at:

`docs/superpowers/specs/archived/2026-07-19-conversational-compilation-management-design.md`

This remains a supported shipped surface while stabilization changes compiler internals beneath it.

## Legacy slice compatibility index

Historical code comments, tests, and documentation still refer to old roadmap slices. Those references remain valid as shipped-state/history identifiers. New implementation planning should use the phases above.

### Slice A1 — correct optionality compatibility under the current model

Shipped correctness work. Maps to continuous correctness gates and Phase 10.

### Slice A2 — create one property-dependency graph

Shipped dependency-graph work. Foundational to Phases 7, 9, and 10.

### Slice A3 — validate all expression positions

Shipped correctness work. Continues under Operating rules 1–2.

### Slice A4 — fix semantic-type resolution ambiguity

Shipped resolution work. Foundational to Phases 1–2.

### Slice B1 — add a canonical capability manifest

Shipped current-state capability manifest. Phase 5 evolves capability ownership toward extensions.

### Slice B2 — reconcile current documentation claims

Historical documentation/capability consistency slice. Current architecture now explicitly states composite-key, lifecycle, and runtime-adjacent implementation status.

### Slice B3 — eliminate silently ignored syntax

Shipped `DEFERRED` diagnostic behavior. Preserved by Operating rule 2 and the current/deferred syntax disposition above.

### Slice C1 — projection-to-projection compatibility

Shipped projection compatibility work. Phase 10 separates semantic facts from target evaluators without removing this behavior.

### Slice C2 — extend existing version resolution to `ref<>` types

Shipped resolution work. Folded into Phase 1–2 identity/resolution invariants.

### Slice C3 — generalize existing target compatibility

Shipped target-compatibility abstraction. Phase 10 completes the separation.

### Slice C4 — configurable compatibility and lint policy

Shipped policy foundation. Phase 11 generalizes the extension boundary.

### Slice D1 — separate presence and nullability

Historical language-evolution slice. Any remaining work is subject to Operating rules 3–4.

### Slice D2 — value and semantic type evolution

Historical language-evolution work; maps to Phase 2.

### Slice D3 — enum declaration convergence

Historical enum work; maps to Phase 2 declaration unification.

### Slice D4 — discriminated unions

Historical/future language capability; only proceeds if existing semantics/extensions cannot represent concrete consumer needs.

### Slice D5 — resolve composite-key support

Composite keys remain deferred. The current architecture explicitly records the one-key invariant.

### Slice D6 — model lifecycle status

Lifecycle status remains deferred and is not represented in the current stable grammar/IR.

### Slice F1 — nominal semantic types beyond Rust

Target coverage remains demand-driven. Phase 5 capability negotiation makes intentional structural erasure/nominal preservation explicit per target.

### Slice F2 — OpenAPI emission

OpenAPI emission is shipped. This legacy heading is retained so existing deep links remain valid.

### Slice G1 — critical compatibility coverage

Continuous coverage ratchet; remains active throughout stabilization.

### Slice G2 — strict typing baseline reduction

Continuous typing ratchet; remains active throughout stabilization.

### Slice G3 — conformance fixtures

Shipped/continuous conformance foundation. Phase 12 broadens it into external showcase/host conformance.

## Deferred product areas

The following remain outside the core roadmap unless the product thesis changes:

- streaming execution engine;
- subscription runtime;
- materialization runtime;
- broker abstraction;
- database synchronization service;
- retry/dead-letter execution;
- distributed Modelable registry service.

Modelable may generate contracts, plans, mappings, migrations, validation packages, or consequence actions for these systems.

## Future-use design tests

| Use | Expected mechanism |
|---|---|
| GraphQL | emitter + compatibility evaluator |
| AsyncAPI | emitter |
| additional wire/schema formats | emitter |
| Iceberg/Delta | emitter |
| ORM/framework bindings | overlay + emitter |
| Unity | C# emitter extension + overlay |
| SDK generation | emitter |
| industry standards | extension package |
| enterprise governance | policy evaluator |
| catalog integration | adapter |
| schema registry integration | adapter |
| API migration tooling | consequence graph + action generator |
| AI-assisted refactoring | semantic/usage/consequence query API |
| code migrations | action generator |
| cross-repo blast radius | lock snapshots + usage graph |
| runtime validation | generated package |
| MCP/agent integration | host/query protocol |

## Explicit non-goals for stabilization

Do not spend stabilization capacity on:

- adding emitters solely for breadth;
- adding grammar syntax for target configuration;
- making SQLite registry state authoritative;
- building a remote registry service;
- implementing runtime materialization/subscriptions;
- creating duplicate semantic implementations for browser or integrations.

## Contribution decision rule

Before extending the language:

```text
Can existing semantic constructs represent this correctly?
  │
  ├─ yes → extension / overlay / emitter / analyzer / policy
  │
  └─ no  → propose a semantic-model change
```

A semantic-model proposal must document why projections, semantic types, overlays, extension capabilities, and action/policy mechanisms are insufficient.

## Completion criteria for stabilization

Stabilization is complete when:

- canonical declaration identity and nested semantic path grammar are defined and used consistently;
- declarations/projections share common resolution/version/lineage infrastructure;
- `plan/v0` migration has validated the boundary and `modelable.plan/v1` is frozen;
- external target configuration has deterministic version-aware overlays;
- extension capability negotiation and provenance/trust rules are implemented;
- usage evidence precedes and feeds deterministic `modelable.lock/v1`;
- compatibility-critical target allocations are lock state, not optional config;
- consequences form an explainable graph;
- semantic and target compatibility are separated;
- browser/native semantic conformance is enforced;
- showcase provides realistic cross-target conformance;
- significant new integrations can be added without changing `.mdl`.

Modelable can resume broad feature growth with substantially lower
architectural cost.
