# Offline Registry and Consequence-Driven DX Delivery Plan

This plan decomposes the proposed design in
`docs/superpowers/specs/2026-08-16-offline-registry-dx-design.md` into
reviewable implementation slices. The repository already contains an initial
foundation for local snapshots, staged snapshot updates, usage manifests, and
model/projection consequence reports. This plan closes the gaps between that
foundation and the full external-dependency workflow.

No ADR is added in this planning slice: it refines sequencing and acceptance
boundaries for the existing proposed design without making a new architectural
decision. Source-adapter, lock-format, and application-identity decisions are
explicitly listed for acceptance before implementation.

## Current baseline

- `modelable registry resolve|verify|status|prune` can write and validate a
  deterministic content-addressed snapshot of a validated local workspace.
- `modelable registry diff|update` can compare and atomically install a local
  candidate snapshot.
- `modelable registry usage` exports the current compiler-owned usage graph.
- `modelable impact` reports existing model/projection compatibility
  consequences and causal paths.
- These slices do not yet resolve external source registries or transitive
  dependency ranges, aggregate usage across applications, or enforce an
  update policy over a candidate snapshot.

## Design decisions required before implementation

1. Define the dependency declaration syntax and source adapter boundary for
   local workspaces, Git sources, HTTP artifacts, and registry clients. Each
   source must have an explicit authorization and network boundary.
2. Freeze the `registry.lock` and content-addressed object schema, including
   canonical signatures, source provenance, transitive dependency closure, and
   same-version/different-content rejection.
3. Define how external snapshot objects enter the compiler workspace without
   being mistaken for editable local `.mdl` source.
4. Define stable application identity and the usage-manifest schema before
   adding cross-application aggregation.
5. Define policy inputs separately from compiler facts: policies may block or
   require review, but must not change compatibility or consequence semantics.
6. Define the compatibility/migration path for the existing snapshot format
   and preserve offline reproducibility for historical checkouts.

## Slice 0 — reconcile the foundation

- [x] Update capability and CLI documentation to distinguish local snapshot
  creation from external dependency resolution.
- [x] Add machine-readable capability facts for snapshot provenance,
  transitive closure, offline-only operation, and consequence coverage.
- [x] Add an invariant test that ordinary `validate`, `compile`, `diff`,
  `impact`, lineage, and editor operations do not invoke a source adapter or
  network operation.
- [x] Retain the existing `registry.db` as the derived index name in the public
  CLI; durable dependency state remains in `registry.lock` and its objects.

## Slice 1 — complete the durable offline registry snapshot

- [x] Introduce a source-adapter interface with explicit resolution commands;
  ordinary compiler services receive only a resolved snapshot.
- [ ] Parse dependency requirements, resolve direct and transitive ranges, and
  record the exact selected identity and canonical signature in the lock.
- [ ] Store normalized external contract objects with provenance and reject a
  mutable logical version whose canonical content changes.
- [x] Rebuild the derived registry index from local source plus the exact lock
  and objects, with no implicit refresh.
- [x] Add resolve/verify/status fixtures for missing objects, hash mismatch,
  source drift, transitive closure, and historical checkout reproducibility.

## Slice 2 — complete cross-application usage and consequence analysis

- [x] Add stable workspace/package application identity.
- [ ] Derive usage edges from model references, projections, API operations,
  events, and persistence surfaces.
- [x] Derive generated-artifact usage edges from compiler artifact manifests.
- [ ] Export a compact versioned usage manifest that can be aggregated without
  loading every application source tree.
- [ ] Generalize existing compatibility findings into consequence facts with
  causal paths and actions such as regeneration, consumer update, migration,
  backfill, projection rebuild, replay, review, and breaking change.
- [x] Extend `modelable impact --from OLD --to NEW` to consume local snapshots
  and aggregated usage manifests in both human and JSON output.

## Slice 3 — make registry updates consequence-aware

- [ ] Resolve and stage a candidate snapshot without changing durable state.
- [ ] Compare current and candidate semantic graphs plus affected application
  usage manifests.
- [ ] Calculate consequences and apply configured policy to the staged result.
- [x] Show generated-artifact regeneration consequences from usage manifests.
- [ ] Show exact dependency and remaining required-action changes.
- [ ] Replace lock/object state atomically only after validation and policy
  acceptance; retain the candidate for review when rejected.
- [ ] Add failure-injection tests proving that rejected or interrupted updates
  leave the prior snapshot unchanged.

## Feature qualification — prove the complete generated-contract path

Unit tests for snapshot hashes and consequence records are necessary but not
sufficient. Every completed snapshot/usage/update slice must pass one small
feature fixture that exercises every implemented code-generation target. The
fixture must be generated once and its outputs reused; it must not create a
separate modelable compile scenario per target.

- [ ] Prepare producer v1 and v2 Modelable workspaces plus a consumer workspace
  that resolves the producer contract through the local snapshot.
- [ ] Keep the fixture intentionally tiny: one producer domain, one referenced
  model, one projection, and one Rust consumer crate. Do not turn this into a
  second golden-artifact matrix.
- [ ] Resolve the exact dependency, rebuild the local registry index from the
  lock and objects, and run ordinary `validate`, `compile`, `diff`, and
  `impact` with network access disabled.
- [ ] Generate the consumer's Rust package from the resolved snapshot,
  including model/projection types, semantic identity constants, canonical
  version signatures, and any generated conversion surface covered by the
  fixture.
- [ ] Enumerate `list_implemented_codegen_targets()` and generate every
  implemented target from the same fixture. A newly implemented target must
  either join this feature matrix or be explicitly marked as exempt with a
  documented validator.
- [ ] Run fast structural contract checks over every generated artifact:
  parse JSON/YAML/Avro/OpenAPI/manifest outputs, validate required identity and
  signature fields, parse SQL/Markdown/ODCS/dbt outputs, and run the available
  schema/protocol validators without network access.
- [ ] Run cached compiler smoke tests for every generated language target:
  Python import/test, TypeScript `tsc`, C# build/test, Java compile/run, Go
  `go test`, and a small Rust consumer crate with one `cargo test
  --locked --offline` invocation. Each test must exercise representative
  generated types and assert the generated identity metadata; Rust must also
  exercise serialization or conversion behavior.
- [ ] Update the producer snapshot to v2 and verify that the feature fixture
  produces the expected causal impact report before lock replacement; include
  at least one compatible and one breaking change.
- [ ] Treat contract compatibility as an acceptance assertion, not an output
  inspection: the additive v2 must preserve the consumer-visible contract and
  the breaking v2 must be rejected or marked breaking before durable snapshot
  replacement. Exercise the existing semantic compatibility and, where the
  fixture emits them, Protobuf/gRPC target-compatibility checks.
- [ ] Regenerate the complete implemented target set for the compatible v2 and
  rerun the structural checks plus the language smoke matrix against that
  candidate. Compile/test only the candidate version; compare it with the v1
  baseline for compatibility. The breaking v2 must not reach any generation or
  consumer step. This proves that a compatible contract remains usable across
  the target surface while an incompatible contract cannot silently become a
  generated dependency.
- [ ] Reuse the existing pinned Docker codegen-smoke environment for language
  compilers where the host toolchain is not guaranteed. Run those checks in
  parallel against the same generated output, extending
  `cli/tests/test_codegen_docker_smoke.py` or adding a dedicated feature test
  rather than relying only on string assertions.
- [ ] Keep the network-isolation assertion independent from Cargo dependency
  acquisition: use a locked/vendorable fixture or a prepared Cargo cache so
  `cargo test --offline` validates generated code without making the compiler's
  offline guarantee ambiguous.
- [ ] Keep the fast PR lane bounded: one Modelable load/validation, one
  baseline generation pass plus one compatible-candidate generation pass for
  all targets, one snapshot transition, one impact report, and cached
  structural checks, with a 30-second warm-run budget. Run the language
  compiler smoke matrix in parallel with cached dependencies and give that
  separate matrix a recorded CI budget; investigate regressions rather than
  adding duplicate scenarios.

This is an acceptance gate for Slices 1–3, not a replacement for focused unit
tests. A slice is not complete if the Python-side snapshot and impact tests
pass while the generated Rust consumer does not compile and execute its tests.

## Later plans, deliberately separate

The following are not part of the first implementation plan and require their
own acceptance criteria and consumer evidence:

- proof-driven conversion helpers and stable user hooks;
- defaults, inheritance, and `modelable.toml` explainability;
- migration, backfill, projection-rebuild, and event-replay semantics;
- API convenience expansion over explicit operation IR;
- semantic-fidelity and trusted-plugin extensions.

## Verification and handoff

Each slice must add focused CLI/fixture coverage, update the capability and
CLI references, and run the four required checks from `cli/`. Codegen output
changes require golden-artifact regeneration and review. The design remains
proposed until the decisions above are accepted; no hosted registry or runtime
execution engine is implied by this plan.
