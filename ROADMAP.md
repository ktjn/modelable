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

## Priority 1 — advance the Playground

The Playground is now the immediate product priority. The shipped browser
compiler and single-file editor prove the delivery path; the next work must
replace the temporary single-file state model before language services,
visualization, analysis, or local AI build on it.

Work proceeds in phase order, with one active phase at a time:

1. **Shipped: browser compiler spike.**
   The static proof loads the pinned browser wheel in same-origin Pyodide and
   verifies validation, formatting, JSON Schema generation, native/browser
   conformance, and performance budgets. The completed design is archived in
   [Browser Compiler WASM Spike — Design](docs/superpowers/specs/archived/2026-07-18-browser-compiler-wasm-spike-design.md).
2. **Shipped: single-file editor MVP.**
   React and Monaco provide source diagnostics, formatting, generated-artifact
   preview, import/export, recovery, accessibility coverage, and static GitHub
   Pages delivery. The completed design is archived in
   [Browser Editor MVP — Design](docs/superpowers/specs/archived/2026-07-19-browser-editor-mvp-design.md).
3. **Shipped: multi-file workspace and IndexedDB persistence.**
   The Playground now has a versioned virtual workspace, safe `.mdl` file
   lifecycle operations, deterministic whole-workspace compiler requests,
   automatic local restoration, memory-only fallback, and explicit
   corrupt-state export/reset. The completed scope is archived in
   [Playground Workspace and Persistence — Design](docs/superpowers/specs/archived/2026-07-20-playground-workspace-persistence-design.md).
4. **Shipped: browser-native language services.**
   The Playground now provides completion, hover, definition, references, and
   rename over the durable multi-file workspace without running the desktop
   LSP transport in the browser. The completed design is archived in
   [Playground Browser Language Services — Design](docs/superpowers/specs/archived/2026-07-20-playground-browser-language-services-design.md).
5. **Active next slice: visualization and analysis.**
   Deliver stable graph DTOs, domain/entity views, source navigation, lineage,
   compatibility, and governance views in the phase order defined by
   [the Playground architecture](docs/playground-design.md).
6. **Then: local AI.**
   Add WebLLM model download and provider UX only after workspace editing and
   analysis boundaries are stable. Model output remains untrusted and must use
   typed planning, validation, preview, and explicit acceptance.
7. **Then: offline hardening and extensibility.**
   Add the service worker, offline workspace support, performance and security
   hardening, extension boundaries, and additional views after the core
   workspace and language-service contracts have shipped.

The next implementation slice is item 5. Completion means the Playground gains
stable graph DTOs, domain/entity views, source navigation, lineage,
compatibility, and governance views.

## Priority 2 — complete the Scalable and Rust contract path

The next non-Playground product track makes Modelable-generated identities and
transport contracts directly consumable by Scalable without parallel
handwritten metadata.

Work should proceed in dependency order:

1. **Shipped: emit stable Rust identity constants.**
   Registry-backed semantic newtypes now expose their allocated registry ID,
   and each versioned Rust model and projection exposes its declared version
   and canonical Modelable version signature. Target-specific wire
   fingerprints remain separate manifest metadata rather than canonical model
   identity. The accepted design is documented in
   [Rust Identity Constants — Design](docs/superpowers/specs/archived/2026-07-17-rust-identity-constants-design.md).
2. **Shipped: carry semantic identity into Protobuf.**
   The Protobuf and gRPC targets now emit stable declaring-domain semantic
   wrapper messages, preserve nominal identity in model and projection fields,
   and expose semantic refs, allocated registry IDs, canonical Modelable
   signatures, and target-specific wire fingerprints in schema manifests. The
   accepted design is documented in
   [Protobuf Semantic Identity — Design](docs/superpowers/specs/archived/2026-07-17-protobuf-semantic-identity-design.md).
3. **Shipped: close Protobuf schema-fidelity gaps.**
   Supported `map<K,V>` fields now render as native Protobuf maps instead of
   opaque `bytes`, unsupported map shapes fail clearly, and declared
   primary/secondary index metadata flows into schema and service manifests.
4. **Shipped: make the first wire-contract guard enforceable over time.**
   Descriptor artifacts now ship for Protobuf and gRPC through opt-in
   `--descriptor-set` generation. Source-level Protobuf reservations now
   preserve deleted field numbers and names, and
   `validate-compat --target protobuf|grpc` validates generated manifests for
   field-number reuse, deleted-field reservations, target type changes,
   requiredness changes, inline enum value reuse, and gRPC read-index changes.
   Remaining follow-ups are descriptor-binary diffing, explicit field-number
   pinning, enum reservations, explicit rebuild/migration declarations, and
   Scalable registration fixtures.
5. **Prove Scalable registration end to end.**
   Add consumer fixtures that register generated schema identity, command/read
   services, and index metadata without duplicating Modelable-owned constants.

The next dependency-ordered Scalable slice remains item 5: proving Scalable
registration end to end.

Completion means a Scalable consumer can compile generated Rust and Protobuf
artifacts, register them using generated identity metadata, and detect an
incompatible transport change in CI.

## Priority 3 — improve authoring, adoption, and cross-target consistency

After the active Playground foundation and Scalable/Rust path:

1. **Shipped:** safe conversational workspace management in the existing CLI
   chat. Natural-language requests use typed plans and a reusable workspace
   editor to answer grounded questions, create complete entities and
   projections, append compatibility-aware versions, and preview atomic
   multi-file changes with textual diffs and affected-definition explanations
   before explicit confirmation. The completed design is archived in
   [Conversational Workspace Management — Design](docs/superpowers/specs/archived/2026-07-18-conversational-workspace-management-design.md).
2. **Shipped:** reuse the conversational planner and workspace editor through
   the native VS Code `@modelable` participant and versioned language-server
   requests. The extension remains a thin UI: Python owns provider
   configuration, typed plans, validation, exact previews, writes, rollback,
   and reload. The completed design is archived in
   [VS Code Conversational Foundation — Design](docs/superpowers/specs/archived/2026-07-18-vscode-conversational-foundation-design.md).
3. **Shipped:** local Conversational Compilation Management through CLI chat
   and the native VS Code participant. A shared application service stages the
   real compiler output, reports exact text/binary file evidence and affected
   definitions, requires literal or native confirmation, checks source and
   destination freshness, promotes the staged bytes with rollback, and writes
   privacy-preserving audit records. The completed design is archived in
   [Conversational Compilation Management — Design](docs/superpowers/specs/archived/2026-07-19-conversational-compilation-management-design.md).
   Registry synchronization, publishing, and external-service operations remain
   separate follow-ups with their own authorization, credential, preview,
   confirmation, and audit policies.
4. Extend nominal semantic-type generation beyond Rust, prioritizing
   TypeScript, Go, Java, C#, Python, JSON Schema, and SQL according to concrete
   consumer demand. Targets that intentionally erase nominal identity must say
   so explicitly.
5. Extend `modelable inspect` with registry-ID and canonical-signature lookup so
   generated constants and registry state are easy to diagnose.
6. Publish the VS Code extension through the Marketplace once the release and
   support process is defined.
7. Continue conformance, documentation, diagnostics, and importer hardening
   where contributor or user reports expose real gaps.

Completion means a new team can install the CLI and editor tooling, understand
generated identity and compatibility behavior, and adopt a supported target
without relying on internal repository knowledge.

## Priority 4 — deepen external integrations

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
- An optional provider adapter for the VS Code Language Model API so users can
  select a model available in their editor. Native model output must still
  pass through Python-owned typed plan parsing, validation, preview, and
  workspace editing; the extension must not duplicate those safety boundaries
  in TypeScript.

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
