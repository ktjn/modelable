# Roadmap

Modelable is a local compiler and language-server toolchain for versioned,
domain-owned model contracts. This roadmap orders outcomes rather than assigning
unconfirmed release numbers. An item becomes committed work only when it has a
GitHub issue and an accepted design.

## Current baseline

The latest published release is 1.4.0. The stable 1.x surface includes:

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

### Known correctness and documentation gaps

Two verified gaps affect how much this baseline can be trusted at face value,
tracked in full in the
[compiler correction and capability plan](docs/correction-and-capability-plan.md):

- `docs/architecture.md` describes composite keys as supported, but
  `cli/src/modelable/validation/semantic.py` requires exactly one `@key`
  field per entity/aggregate, and `docs/language-reference.md` already says
  composite keys are not representable. Undecided until
  [Slice D5](docs/correction-and-capability-plan.md#slice-d5--resolve-composite-key-support).
- The model diff can emit `nullability_changed`, but compatibility reporting
  does not consistently classify `optional -> required` as breaking, so
  semantic validation and compatibility reports can disagree. Fix tracked as
  [Slice A1](docs/correction-and-capability-plan.md#slice-a1--correct-optionality-compatibility-under-the-current-model).

## Delivery lanes

Four lanes run in parallel rather than one strict priority queue:

| Lane | Covers | Priorities below |
|---|---|---|
| P1 | Playground | Priority 1 |
| P2 | Scalable/Rust integration | Priority 2 |
| C | Compiler correctness, compatibility, capability/doc consistency | Priority 3 |
| L | Language evolution, extensibility, gated target work | Priority 6 |

Priorities 4 and 5 (authoring/adoption, external integrations) draw from
whichever lane a given item belongs to as it becomes concrete.

Interleaving rules:

1. A confirmed false compatibility result is a release blocker.
2. Silent loss or ignored parsed content is a release blocker for the
   affected construct.
3. Incomplete diagnostics that do not change compiler output may proceed
   beside active roadmap work.
4. New broad language features do not preempt Priorities 1 and 2 without a
   concrete consumer and accepted design.
5. Every slice is rechecked against `main` immediately before design
   acceptance.

Full slice-level detail for lanes C and L lives in the
[compiler correction and capability plan](docs/correction-and-capability-plan.md).

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
5. **Shipped: visualization MVP.**
   The Playground renders compiler-owned semantic graphs with domain and entity
   visualization modes using ELK.js layout and React Flow rendering, with
   responsive layout, accessibility, and performance budgets. The completed
   design is archived in
   [Playground Visualization MVP — Design](docs/superpowers/specs/archived/2026-07-21-playground-visualization-design.md).
6. **Shipped: analysis views.**
   The Playground provides field lineage tracing, version compatibility
   visualization with downstream projection impacts, governance findings,
   and SVG/PNG diagram export. The completed designs are archived in
   [Playground Analysis Views — Design](docs/superpowers/specs/archived/2026-07-21-playground-analysis-views-design.md)
   and
   [Playground Analysis Views — Plan](docs/superpowers/plans/archived/2026-07-21-playground-analysis-views.md).
7. **Shipped: local AI.**
   The Playground provides WebLLM-powered local AI with model download UX,
   generate-entity and explain actions, validated preview with provenance
   tracking, and explicit user acceptance. The completed designs are archived
   in
   [Playground Local AI — Design](docs/superpowers/specs/archived/2026-07-22-playground-local-ai-design.md)
   and
   [Playground Local AI — Plan](docs/superpowers/plans/archived/2026-07-22-playground-local-ai.md).
8. **Shipped: offline and hardening.**
   The Playground registers a service worker for offline operation, validates
   against both Chromium and Firefox, enforces accessibility with axe-core
   scans and reduced-motion support, applies performance budgets to all asset
   categories including Monaco and the AI worker, and lazy-loads AI
   components. The completed designs are archived in
   [Playground Offline and Hardening — Design](docs/superpowers/specs/archived/2026-07-23-playground-offline-hardening-design.md)
   and
   [Playground Offline and Hardening — Plan](docs/superpowers/plans/archived/2026-07-23-playground-offline-hardening.md).
9. **Shipped: automatic chat documentation RAG.**
   CLI chat, the VS Code/LSP conversation participant, and the static
   Playground route high-confidence documentation questions through the shared
   deterministic intent classifier and retrieval pipeline when an index is
   configured. Mutation, compile, apply/discard, and slash-command turns stay
   on the ordinary planner path; explicit `/docs` remains a force-retrieve
   command, and automatic routing can be disabled per session. Structured
   binary browser shards, vector/hybrid retrieval, and user-supplied indexes
   remain deferred.
10. **Shipped: optional local Ollama provider for the Playground.**
   Users can select a local Ollama server as an alternative to WebLLM from
   the same provider dropdown, using the shared `LlmProvider` abstraction.
   Fixed to Ollama's default local address (no user-configurable base URL,
   to keep the CSP `connect-src` allowlist static and narrow); requires
   `OLLAMA_ORIGINS` configured on the Ollama server to accept requests from
   the Playground's origin.
11. **Active next phase: extensibility.**
   Add plugin contracts, additional visualization modes, and optional GitHub
   integration using explicit user authorization.

The next implementation slice is item 11. Completion means the Playground
supports third-party extensions through documented plugin contracts.

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

## Priority 3 — compiler correctness, compatibility, and capability integrity

Lane C. This priority does not wait behind Priorities 1 and 2 — A1–A4 and G1
below start immediately, in parallel with active Playground and Scalable
work, per interleaving rule 1: a confirmed false compatibility result is a
release blocker. Full slice detail, tests, and acceptance criteria are in the
[compiler correction and capability plan](docs/correction-and-capability-plan.md).

Work proceeds in three tranches:

1. **Correctness tranche (start immediately):**
   - **A1** — fix the optionality compatibility bug: `optional -> required`
     must be classified as breaking, and semantic validation and
     compatibility reporting must agree. Ships as an explicit stopgap for the
     current single-`optional`-flag model, superseded by presence/nullability
     work (Priority 6, D1) later.
   - **A2** — introduce one compiler-owned property-dependency graph covering
     direct mappings, computed expressions, join predicates, filters, and
     grouping, so compatibility, governance, lineage, and editor tooling stop
     duplicating source-property analysis.
   - **A3** — validate every expression-bearing position (computed fields,
     joins, `where`, `group by`) through the same CEL pipeline, so no parsed
     expression can bypass semantic validation.
   - **A4** — make semantic-type name resolution domain-aware and
     deterministic; add qualified references and reject cross-domain
     ambiguity as a compile error.
   - **G1** — add critical-path regression coverage for compatibility,
     dependency resolution, expression validation, lineage, governance,
     signatures, and target compatibility.
2. **Capability and documentation tranche (next):**
   - **B1** — add a `modelable capabilities` manifest so target/dialect/
     annotation/import support is compiler-owned, not hand-maintained across
     docs.
   - **B2** — reconcile verified documentation contradictions (composite
     keys, model lifecycle claims, deferred targets, classification
     vocabulary, browser language-service parity), resolving the composite-key
     status via an executable conformance test rather than assumption.
   - **B3** — audit every silently-parsed-but-ignored construct (registry
     peers/consumers/subscriptions, materialisation, opaque nested bindings)
     and give each one an explicit outcome: implemented, experimental IR with
     diagnostics, rejected as deferred, or removed from stable grammar.
   - **G3** — share conformance fixtures across the native compiler, browser
     compiler, LSP, Playground, compatibility, signatures, and manifests,
     with explicit coverage for every capability documentation disputes.
3. **Compatibility architecture tranche (after A2/A3 land):**
   - **C1** — treat versioned projections as first-class contracts: compare
     shape, lineage, governance, wire, storage, and materialisation impact
     between projection versions directly.
   - **C2** — extend the existing projection-source version-resolution rules
     (exact/range/minimum/pin) to `ref<>` type-reference positions.
   - **C3** — generalize the shipped Protobuf/gRPC compatibility guards into
     one target-agnostic compatibility result IR, extended to JSON, SQL/
     storage migration, projection rebuild, and governance review — without
     duplicating the existing Protobuf/gRPC rule logic.
   - **C4** — add a configurable compatibility/lint policy so teams can set
     enforcement severity per target axis without changing the underlying
     compiler-determined facts.

The first six pull requests implementing the correctness and capability
tranches are sequenced in the
[compiler correction and capability plan](docs/correction-and-capability-plan.md#first-pull-request-sequence).

Completion means compatibility reports can never contradict semantic
validation, every property dependency (including filters and joins) is
captured in one graph, all expressions are type-checked and traced, semantic
types resolve deterministically, documented capabilities match compiler
behavior, and no parsed syntax is silently discarded.

## Priority 4 — improve authoring, adoption, and cross-target consistency

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
   so explicitly. Tracked as
   [Slice F1](docs/correction-and-capability-plan.md#slice-f1--nominal-semantic-types-beyond-rust)
   in the correction and capability plan.
5. Extend `modelable inspect` with registry-ID and canonical-signature lookup so
   generated constants and registry state are easy to diagnose.
6. Publish the VS Code extension through the Marketplace once the release and
   support process is defined.
7. Continue conformance, documentation, diagnostics, and importer hardening
   where contributor or user reports expose real gaps.

Completion means a new team can install the CLI and editor tooling, understand
generated identity and compatibility behavior, and adopt a supported target
without relying on internal repository knowledge.

## Priority 5 — deepen external integrations

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

## Priority 6 — language evolution and extensibility

Lane L. Full slice detail lives in the
[compiler correction and capability plan](docs/correction-and-capability-plan.md).
These items require accepted designs and, for the syntax-changing ones,
concrete consumer demand; they do not automatically outrank Priorities 1–5.

Most items here were gated behind one decision, now made:

- **Decided: D0 — historical language interpretation.** Additive-syntax
  policy: old syntax never changes meaning; new semantics require new
  syntax. Chosen over language-version and compiler-version-snapshot
  policies since those exist to protect a large body of already-published
  `.mdl` text against reinterpretation, and that body doesn't exist yet.
  Outcome recorded in
  [the correction and capability plan](docs/correction-and-capability-plan.md#slice-d0--define-historical-language-interpretation).
  D1 and D6 below are now unblocked to scope and design (not yet
  implemented).

Gated on D0 (now decided), in dependency order:

1. **D1** — separate presence from nullability (`field?` keeps its current
   meaning or is interpreted under an explicit language version; never
   silently reinterpreted).
2. **D2** — first-class value constraints (min/max, length, pattern, format,
   uniqueness) with explicit lineage and no silent widening.
3. **D3** — named, version-aware enums.
4. **D4** — discriminated unions, depending on D3 and D1.
5. **D5** — resolve the composite-key contradiction: add a conformance test,
   then either implement composite entity identity or correct
   `docs/architecture.md` to match the compiler.
6. **D6** — model lifecycle status (draft/published/deprecated/retired),
   depending on D0.

Also in this lane, **not** gated behind D0 because it is purely additive
grammar that never reinterprets existing text:

- **Shipped: H1 — projection `pick(...)`/`omit(...)` clauses.** Lets a
  `projection` select or exclude a field subset from its source (including
  qualified `alias.field` selection across `join`s, and annotation filters
  like `@pii` reusing `auto projections ... exclude`'s existing matcher)
  without hand-writing a `<-` line per field. Expands to the same explicit
  IR a hand-written projection produces before compatibility/lineage
  analysis runs, so no downstream subsystem needs special-casing. Full
  design: [Projection Pick/Omit Clauses](docs/superpowers/specs/archived/2026-08-03-projection-pick-omit-design.md);
  outcome recorded in
  [the correction and capability plan](docs/correction-and-capability-plan.md#slice-h1--projection-pickomit-clauses).

Also extensibility work (Track E) that is additive but not yet prioritized
against a concrete consumer:

- **E1** — typed namespaced annotations (`@acme.retention("7y")`), a grammar
  prerequisite for any annotation-plugin system.
- **E2** — data-quality contract metadata (non-null, uniqueness, accepted
  values, ranges, referential integrity), surfaced through ODCS, dbt tests,
  and OpenMetadata.
- **E3** — freshness, SLA, and retention metadata for supported contract and
  catalog emitters.

Target work gated on the above language work (Track F, items 2-4):

- **F2** — OpenAPI emission, after D1-D4, C1, and C3.
- **F3** — AsyncAPI emission, after named enums, unions, reference-version
  semantics, and the event-envelope contract.
- **F4** — Avro emission, after defaults, nullability, named enums, unions,
  and target-specific reader/writer compatibility.

(Slice F1 — nominal types beyond Rust — is not gated; it is tracked under
Priority 4 above since it is already a concrete, unblocked roadmap item.)

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

Slice B3 made the specific grammar constructs behind this boundary visible
instead of silently discarded: `registry {}`, `peers: [...]`, `consumer {}`,
`subscription {}` (both forms), `materialisation {}`, and unrecognized
`binding {}` content now each emit a non-blocking `DEFERRED` diagnostic (see
`modelable capabilities`) citing this section. That diagnostic is the
correctness fix; it is not a design for the underlying features. Each
construct still needs its own product decision and a
`superpowers:brainstorming`-driven design pass before it can move out of
`deferred` status:

- **Registry and peers** — needs a federation model: how a registry is
  addressed, what a peer relationship means for resolution and compatibility
  checking, and how it relates to the existing `import domain ... from
  registry` syntax (already implemented) and the ad hoc peer-ID text scan in
  `lsp/federation.py` (editor-only today, not compiler-enforced).
- **Consumers** — needs a decision on what tracking a declared consumer
  should drive (impact analysis? notification? nothing beyond documentation?)
  before an IR shape makes sense.
- **Subscriptions and materialisation** — both presuppose a runtime execution
  model that does not exist yet (see "Outside the near-term compiler roadmap"
  above); design work here should follow, not precede, an explicit product
  decision to build that runtime.

Until each gets its own accepted design, `modelable capabilities` and the
`DEFERRED` diagnostic are the authoritative source on their status — not
docs prose, which is exactly the drift Slice B2 corrected.

Repository-health work is tracked separately in the
[engineering improvement roadmap](docs/engineering-roadmap.md). Compiler
correctness, capability-consistency, compatibility-architecture, and gated
language-evolution slice detail (Priorities 3 and 6 above) is tracked
separately in the
[compiler correction and capability plan](docs/correction-and-capability-plan.md).
See [architecture](docs/architecture.md) for the product boundary,
[integrations](docs/integrations.md) for external-tool research, and
[GitHub issues](https://github.com/ktjn/modelable/issues) for work that is ready
for discussion or implementation.
