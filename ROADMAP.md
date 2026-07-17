# Roadmap

Modelable is a local compiler and language-server toolchain for versioned,
domain-owned model contracts. This roadmap orders outcomes rather than assigning
unconfirmed release numbers. An item becomes committed work only when it has a
GitHub issue and an accepted design.

## Current baseline

The latest published release is 1.2.1. The stable 1.x surface includes:

- The `.mdl` language, semantic validation, compatibility and lineage reports,
  governance findings, the language server, and the VS Code extension distributed
  as a release artifact.
- Deterministic generation for JSON Schema, TypeScript, C#, Java, Python, Rust,
  Go, SQL DDL, dbt `schema.yml`, Markdown, FHIR R4 profiles, OpenMetadata,
  OpenLineage, ODCS, Protobuf, and Scalable-oriented gRPC services.
- Local dbt, FHIR, and ODCS import and tracked-spec drift workflows.
- Apicurio JSON Schema publish/pull and Marquez-compatible OpenLineage sync.
- Public conformance fixtures, hosted documentation, and external-validator
  smoke coverage for supported integration surfaces.

Recent compiler-contract additions are shipped but not yet complete across every
target:

- Fixed-width integers, fixed-length binary values, and `uuid(7)`.
- Rust nominal newtypes for `semantic` declarations.
- Deterministic small-integer allocation for `semantic ... { registry: true }`
  declarations through the git-tracked `registry-ids.lock` ledger.
- Primary and secondary index declarations, currently consumed by PostgreSQL
  generation.
- Protobuf payload schemas and generic Scalable command/read services.
- A documented Rust/Protobuf wire-format contract with golden fixtures.

The changelog records release-level detail. The archived
[Scalable feature-gaps response](docs/superpowers/specs/archived/2026-07-07-modelable-feature-gaps-response-design.md)
and
[Protobuf/gRPC design](docs/superpowers/specs/archived/2026-07-04-scalable-protobuf-grpc-support-design.md)
record the decisions behind the recent contract work.

## Priority 1 — complete the Scalable and Rust contract path

The next product work should make Modelable-generated identities and transport
contracts directly consumable by Scalable without parallel handwritten
metadata.

Work should proceed in dependency order:

1. **Emit stable Rust identity constants.**
   Emit an allocated registry ID constant for registry-backed semantic
   newtypes. Emit each versioned model and projection's declared version and
   canonical Modelable version signature as generated constants sourced from
   the existing registry signature machinery. Keep target-specific wire
   fingerprints in manifests rather than presenting them as canonical model
   identity. The accepted design is documented in
   [Rust Identity Constants — Design](docs/superpowers/specs/2026-07-17-rust-identity-constants-design.md).
2. **Carry semantic identity into Protobuf.**
   Add semantic-type resolution to the Protobuf emitter and expose registry IDs
   in the schema manifest. Preserve nominal identity where Protobuf supports it
   and document any representation that must remain structural.
3. **Close Protobuf schema-fidelity gaps.**
   Replace the current opaque `bytes` fallback for `map<K,V>` with a documented,
   deterministic mapping and carry declared primary/secondary index metadata
   into the schema and service manifests.
4. **Make the wire contract enforceable over time.**
   Produce descriptor sets, reserve deleted field numbers and names, and add
   Protobuf/gRPC compatibility validation before generated contracts are treated
   as long-lived transport APIs.
5. **Prove Scalable registration end to end.**
   Add consumer fixtures that register generated schema identity, command/read
   services, and index metadata without duplicating Modelable-owned constants.

Completion means a Scalable consumer can compile generated Rust and Protobuf
artifacts, register them using generated identity metadata, and detect an
incompatible transport change in CI.

## Priority 2 — improve adoption and cross-target consistency

After the Scalable/Rust path is complete:

1. Extend nominal semantic-type generation beyond Rust, prioritizing
   TypeScript, Go, Java, C#, Python, JSON Schema, and SQL according to concrete
   consumer demand. Targets that intentionally erase nominal identity must say
   so explicitly.
2. Extend `modelable inspect` with registry-ID and canonical-signature lookup so
   generated constants and registry state are easy to diagnose.
3. Publish the VS Code extension through the Marketplace once the release and
   support process is defined.
4. Continue conformance, documentation, diagnostics, and importer hardening
   where contributor or user reports expose real gaps.

Completion means a new team can install the CLI and editor tooling, understand
generated identity and compatibility behavior, and adopt a supported target
without relying on internal repository knowledge.

## Priority 3 — deepen external integrations

Integration work follows adoption work unless a concrete deployment provides a
stronger near-term requirement:

1. Add live OpenMetadata catalog synchronization for one explicitly supported
   deployment shape. Local export and container-backed validation remain the
   prerequisite evidence.
2. Add remote, authenticated tracked-spec sources for dbt, FHIR, and ODCS while
   preserving deterministic local snapshots and reviewable drift.
3. Harden complex FHIR structures, dbt semantic-layer constructs and model
   version selection, and ODCS field-level mappings as real inputs expose gaps.
4. Add lineage stitching for external dbt exposures and similar consumers when
   the external identity contract is concrete.

Completion means at least one real deployment can pull or synchronize external
contracts reproducibly without making an external service the source of truth
for Modelable models.

## Candidate pool

These ideas are intentionally unordered until a concrete consumer, issue, and
accepted design establish their value:

- Embedded Python authoring that statically extracts a small, deterministic
  subset into canonical `.mdl` without importing or executing user code.
- Distributed registry synchronization beyond the current file-first ledger
  and local registry cache.
- Additional artifact formats requested by a real consumer.
- A third compatibility signal for state-migration necessity.

## Outside the near-term compiler roadmap

Runtime subscriptions, adapters, replay, materialization, and hosted distributed
registry services are separate product concerns. They should not displace
compiler-contract, adoption, or integration work without an explicit product
decision and accepted architecture.

Repository-health work is tracked separately in the
[engineering improvement roadmap](docs/engineering-roadmap.md). See
[architecture](docs/architecture.md) for the product boundary,
[integrations](docs/integrations.md) for external-tool research, and
[GitHub issues](https://github.com/ktjn/modelable/issues) for work that is ready
for discussion or implementation.
