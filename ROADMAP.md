# Roadmap

> **Status:** Sole source of forward-looking product work as of 2026-09-12.
> Shipped behavior belongs in the references and changelog; historical plans
> belong in archives.

Modelable's stabilization programme is complete. The product is now a local,
offline-first semantic compiler/platform with stable identity, compatibility,
lineage, consequence, package, query, extension, lifecycle, migration, facet,
browser, and editor surfaces.

Release history is intentionally **not** duplicated here. Use
[CHANGELOG.md](CHANGELOG.md) and GitHub Releases for the current published
version.

The architecture source of truth is
[docs/architecture.md](docs/architecture.md). Historical roadmap vocabulary is
retained in [docs/roadmap-archive-2026-08.md](docs/roadmap-archive-2026-08.md)
and completed implementation plans under
[docs/superpowers/plans/archived/](docs/superpowers/plans/archived/).

## Product boundary

```text
semantic packages
      │
      ▼
semantic graph
  + usage graph
  + change graph
      │
      ▼
consequence graph
      │
      ├──────────────► modelable.query/v1 ─► CLI / browser / agents / CI
      │
      └──────────────► modelable.plan/v1 ──► built-ins / trusted native WASM
```

The durable product is semantic identity plus explainable change impact.
Emitters, policies, adapters, package transports, registries, catalogs, and
runtime consumers remain replaceable edges.

## Shipped baseline

The following are complete product capabilities, not roadmap work:

- canonical declaration/path identity and generic declaration resolution;
- stable `modelable.plan/v1`, `modelable.lock/v1`, and read-only
  `modelable.query/v1` boundaries;
- semantic packages, deterministic local package resolution, package-aware lock
  state, and local `modelable.package/v1` pack/verify/unpack;
- usage, change, consequence, migration, lifecycle, and typed-facet metadata;
- layered compatibility plus named backward/forward/full profiles;
- ordered composite identities with per-target capability admission;
- deterministic target overlays outside `.mdl`;
- built-in extension descriptors plus a pinned, least-capability native WASM
  extension host;
- browser/native compiler parity, Playground, VS Code language services, and
  conversational authoring/compilation.

Conversational Compilation Management remains a supported shipped surface. Its
completed design is archived at
`docs/superpowers/specs/archived/2026-07-19-conversational-compilation-management-design.md`.

## Active roadmap

Only work with a concrete product outcome belongs here.

### P0 — OCI distribution for semantic packages

**Goal:** distribute `modelable.package/v1` through existing OCI registries
without creating a Modelable-hosted registry service or weakening offline
reproducibility.

- [ ] Define OCI media types and the transport mapping for
  `modelable.package/v1` without changing the logical package digest.
- [ ] Implement explicit `package push` / `package pull` operations.
- [ ] Allow tags only as discovery inputs; resolve them to an immutable digest
  before admission and lock the exact digest.
- [ ] Verify package content and transport digest before unpack/admission.
- [ ] Record OCI source/provenance and the exact pulled digest in
  `modelable.lock/v1`.
- [ ] Use standard OCI credentials/credential helpers; never persist credentials
  in source, package artifacts, plans, or lock state.
- [ ] Make normal validate/compile/diff/query paths remain network-independent.
- [ ] Cache pulled content so a verified locked package can be consumed offline.
- [ ] Add corruption, digest mismatch, tag substitution, auth failure, and
  clean-offline-checkout conformance tests.

**Done when:** a local package can be packed, pushed, pulled by immutable digest,
verified, locked, and consumed offline with the same semantic/package digest as
the original.

### P0 — Release artifact preflight parity

**Goal:** anything the release workflow packages must already have been packaged
successfully in pull-request CI.

The v1.15.0 release exposed a concrete gap: normal validation did not package
the VS Code extension, so an `@types/vscode` / `engines.vscode` mismatch was
discovered only during release.

- [ ] Package the Python wheel and sdist in validation CI.
- [ ] Run the same VSIX packaging/preflight command used by release CI.
- [ ] Build/package the static browser artifact using the release dependency
  versions and asset checks.
- [ ] Validate the release artifact inventory/manifest without publishing.
- [ ] Keep preflight side-effect free: no registry upload, tag, release, or
  deployment operation.
- [ ] Fail validation when release-only packaging constraints diverge from the
  ordinary build/test path.

**Done when:** release creation contains publishing/signing/deployment work, not
new compilation or packaging validation.

### P1 — Package attestations and verification policy

**Goal:** add optional supply-chain verification without coupling package
identity to one signing product.

- [ ] Define a verifier interface keyed by immutable package digest.
- [ ] Support detached signature/attestation metadata without changing semantic
  identity or package content.
- [ ] Make trust policy explicit and host-owned; unsigned packages remain
  admissible unless configured policy requires verification.
- [ ] Preserve enough verified metadata for subsequent offline admission.
- [ ] Add substitution, stale-attestation, wrong-subject, and untrusted-signer
  tests.

**Dependency:** build on the OCI digest/provenance work above.

## Continuous engineering gates

These are invariants, not finishable programme phases.

1. **Correctness first.** A confirmed false compatibility result is a release
   blocker.
2. **No silent loss.** Parsed content that is ignored or discarded without an
   explicit diagnostic is a release blocker for that construct.
3. **Language stability.** Existing stable syntax never changes meaning
   silently. New semantics require additive syntax, an explicitly versioned
   protocol, or a compatibility-preserving migration.
4. **Grammar freeze by default.** Prefer facets, policies, overlays, extensions,
   analyzers, and external metadata unless the semantic model genuinely cannot
   express the requirement.
5. **One normalized semantic boundary.** Emitters/analyzers consume normalized
   compiler contracts rather than parser/internal implementation classes.
6. **Conformance before completion.** New semantic behavior requires realistic
   cross-surface fixtures; browser/native behavior must remain semantically
   equivalent where both surfaces expose the feature.
7. **Truthful capabilities.** `modelable capabilities`, target descriptors,
   docs, samples, and tests must agree. Unsupported target behavior fails
   explicitly rather than degrading silently.
8. **Protocol discipline.** Stable machine-readable protocols keep checked-in
   schemas/golden fixtures and evolve additively or under a new version.
9. **Offline by default.** Network access is explicit. Locked compilation and
   analysis remain reproducible without network access.
10. **Supply-chain inputs are pinned.** Packages, executable extensions, and
    generation-affecting configuration carry immutable identity/provenance.
11. **Security is part of extensibility.** No executable auto-discovery, ambient
    network, ambient filesystem, or secret material in semantic artifacts.
12. **Release parity.** PR validation must exercise all packaging constraints
    required to create release artifacts.

## Parsed-but-deferred syntax

These stable forms remain accepted for language compatibility but are not
runtime commitments:

- `subscription` — explicit `DEFERRED`; no subscription runtime;
- projection `materialisation` — explicit `DEFERRED`; no materializer;
- workspace `registry {}` / `peers` — explicit `DEFERRED` where they have
  no compiler semantics;
- `consumer {}` — deferred/non-authoritative; compiled usage evidence is the
  preferred source;
- unsupported opaque `binding {}` content — explicit `DEFERRED`; the
  implemented compile-time subset remains supported.

Do not silently remove these forms. Removal or reinterpretation requires an
explicit language migration.

## Explicitly not planned

The following are intentionally outside the active roadmap unless a concrete
consumer demonstrates a requirement that existing boundaries cannot satisfy:

- streaming/runtime execution, subscriptions, materialization, broker
  abstraction, database synchronization, retries, or dead-letter handling;
- a mandatory hosted/distributed Modelable registry service;
- arbitrary third-party WASM execution inside the browser Playground;
- a subprocess extension host; native sandboxed WASM is the executable
  third-party boundary;
- generic external-extension overlay handoff when versioned extension
  configuration already represents the requirement;
- target/framework concepts in `.mdl` when overlays/extensions suffice;
- emitter breadth solely to increase target count;
- duplicate browser/agent semantic implementations;
- new grammar for governance facts that fit typed namespaced facets.

## Candidate directions — not committed

These are intentionally kept in this single roadmap instead of separate
future-direction documents. Promotion requires a concrete consumer, issue,
accepted design, security review where relevant, and a reviewable first slice.

### Richer consumer evidence

Extend the shipped compiled usage manifest with optional static/build/runtime
evidence for exact fields, operations, or variants. Evidence must preserve
provenance and confidence. Absence of observed evidence must never prove a
dependency safe to remove.

### Deployment/evolution action plans

Derive prerequisite/action graphs from semantic consequences and explicit
migration intent. Modelable may describe required ordering, but CI/CD and
migration systems execute it.

### Verification adapter protocol

Emit stable assertions for external systems to verify (schema existence,
types, nullability, enum values, constraints, freshness, wire conformance).
Adapters own credentials, network I/O, retries, and system-specific execution.

### Generated conformance corpus

Generate data-first valid/invalid/boundary/compatibility/migration/wire fixtures
that consumer repositories can adapt to JUnit, xUnit, pytest, Vitest, proptest,
or other frameworks.

### Organization graph export

Export package/application/ownership/usage/consequence relations to existing
catalogs such as Backstage, OpenMetadata, or DataHub. Do not build a second
organization catalog inside Modelable.

## Decision rule

For each new requirement:

```text
Can existing semantics represent it correctly?
  │
  ├─ yes → facet / policy / overlay / extension / analyzer / adapter
  │
  └─ no  → consider a semantic-model or language change
```

Historical slice names and completed programme checklists are intentionally
absent from this file. Use the archived roadmap and implementation plans when
their original terminology is needed.
