# Roadmap

Modelable is a local compiler and language-server toolchain for versioned,
domain-owned model contracts. This roadmap orders outcomes rather than assigning
unconfirmed release numbers. An item becomes committed work only when it has a
GitHub issue and an accepted design.

This single document now holds everything that used to be split across three
files: this product roadmap, the compiler correctness/capability slice detail
(formerly `docs/correction-and-capability-plan.md`), and the repository-health
findings (formerly `docs/engineering-roadmap.md`). They were merged on
2026-08-12 because the split was mostly historical — the correction plan's own
header already said it had been "folded into ROADMAP.md as Priority 3 and part
of Priority 6," and the engineering roadmap explicitly complemented this one.
One document, reordered so shipped work is compact and open work is prominent,
replaces the indirection of jumping between three files to answer "what's
next."

## Current baseline

The latest published release is 1.9.3. The stable 1.x surface includes:

- The `.mdl` language, semantic validation, compatibility and lineage reports,
  governance findings, the language server, and the VS Code extension distributed
  as a release artifact.
- Deterministic generation for JSON Schema, TypeScript, C#, Java, Python, Rust,
  Go, SQL DDL, dbt `schema.yml`, Markdown, FHIR R4 profiles, OpenMetadata,
  OpenLineage, ODCS, Protobuf, and Scalable-oriented gRPC services.
- Import/migration support for JSON Schema, OpenAPI, Avro, Protobuf, SQL DDL,
  dbt, FHIR, and ODCS. Import fidelity varies by format and is explicitly part
  of the external-integration hardening roadmap below.
- Local dbt, FHIR, and ODCS import and tracked-spec drift workflows.
- Apicurio JSON Schema publish/pull and Marquez-compatible OpenLineage sync.
- Public conformance fixtures, hosted documentation, and external-validator
  smoke coverage for supported integration surfaces.
- Multi-package Rust code generation (`package {}` blocks in `workspace {}`,
  `modelable compile --package NAME`) and a one-click manual release workflow.

Recent compiler-contract additions are shipped but not yet complete across every
target:

- Fixed-width integers, fixed-length binary values, and `uuid(7)`.
- Rust nominal newtypes for `semantic` declarations.
- Deterministic small-integer allocation for `semantic ... { registry: true }`
  declarations through the git-tracked `registry-ids.lock` ledger.
- Primary and secondary index declarations, consumed by PostgreSQL generation
  (as `CREATE INDEX` statements) and ClickHouse generation (as inline
  `bloom_filter` data-skipping indexes; declared `unique` constraints are
  accepted but flagged as unenforceable on MergeTree tables).
- Protobuf payload schemas and generic Scalable command/read services.
- A documented Rust/Protobuf wire-format contract with golden fixtures.

The changelog records release-level detail. The archived
[Scalable feature-gaps response](docs/superpowers/specs/archived/2026-07-07-modelable-feature-gaps-response-design.md)
and
[Protobuf/gRPC design](docs/superpowers/specs/archived/2026-07-04-scalable-protobuf-grpc-support-design.md)
record the decisions behind the recent contract work.

### Documentation status

The verified documentation contradictions this roadmap used to track as open
gaps are now resolved:

- **Composite keys.** `docs/architecture.md` now correctly states that every
  entity/aggregate requires exactly one `@key` field, matching
  `cli/src/modelable/validation/semantic.py` and `docs/language-reference.md`.
  The claim is backed by an executable conformance fixture
  (`cli/tests/test_semantic.py::test_composite_key_is_not_yet_supported`), not
  just prose. Implementing composite entity identity itself remains undecided
  future work — see [Slice D5](#slice-d5--resolve-composite-key-support).
- **Optionality compatibility.** `optional -> required` is now classified as
  breaking, and semantic validation and compatibility reporting agree
  (`cli/src/modelable/compat/diff.py`, PR #279). See
  [Slice A1](#slice-a1--correct-optionality-compatibility-under-the-current-model).

`modelable capabilities` (Slice B1, shipped) is the authoritative live source
for target/format/annotation support status going forward — prefer it over
docs prose for anything not covered here.

## Delivery lanes

Four lanes run in parallel rather than one strict priority queue:

| Lane | Covers | Priorities below |
|---|---|---|
| P1 | Playground | Priority 1 |
| P2 | Scalable/Rust integration | Priority 2 |
| C | Compiler correctness, compatibility, capability/doc consistency | Priority 3 |
| L | Language evolution, extensibility, gated target work | Priority 6 |

Priorities 4 and 5 (authoring/adoption, external integrations) draw from
whichever lane a given item belongs to as it becomes concrete. Priority 7
(repository health) is engineering-quality work found by direct code/CI
inspection rather than product feature requests, and runs beside all four
lanes without displacing them.

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
6. A new importer or emitter does not become stable until representative
   real-world fixture data is covered by deterministic regression tests.

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
   remain deferred. Design docs:
   [chat/RAG intent routing](docs/superpowers/specs/archived/2026-08-01-chat-rag-intent-routing-design.md),
   [LSP adapter](docs/superpowers/specs/archived/2026-08-01-rag-lsp-adapter-design.md),
   [Playground adapter](docs/superpowers/specs/archived/2026-08-01-rag-playground-adapter-design.md).
10. **Shipped: optional local Ollama provider for the Playground.**
   Users can select a local Ollama server as an alternative to WebLLM from
   the same provider dropdown, using the shared `LlmProvider` abstraction.
   Fixed to Ollama's default local address (no user-configurable base URL,
   to keep the CSP `connect-src` allowlist static and narrow); requires
   `OLLAMA_ORIGINS` configured on the Ollama server to accept requests from
   the Playground's origin.
11. **Active next phase: extensibility.**
   The first slice adds host-registered artifact-viewer plugin contracts with
   deterministic validation and a safe built-in fallback. Additional
   visualization modes and optional GitHub integration still require separate
   contracts with explicit user authorization.

The artifact-viewer contract is the first implementation slice of item 11.
The remaining extensibility work is not complete until visualization and
GitHub boundaries have their own accepted designs and tests.

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
   Remaining follow-ups are descriptor-binary semantic diffing, explicit field-number
   pinning, enum reservations, explicit rebuild/migration declarations, and
   Scalable registration fixtures.
5. **Prove Scalable registration end to end.**
   Add consumer fixtures that register generated schema identity, command/read
   services, and index metadata without duplicating Modelable-owned constants.
   The first Modelable-side fixture now validates this generated contract bundle
   and checks protobuf/gRPC compatibility outcomes; a Scalable runtime registry
   fixture remains the next integration slice.

The next dependency-ordered Scalable slice remains item 5: proving Scalable
registration end to end.

Completion means a Scalable consumer can compile generated Rust and Protobuf
artifacts, register them using generated identity metadata, and detect an
incompatible transport change in CI.

## Priority 3 — compiler correctness, compatibility, and capability integrity

Lane C. This priority does not wait behind Priorities 1 and 2 — per
interleaving rule 1, a confirmed false compatibility result is a release
blocker, so this lane runs in parallel with active Playground and Scalable
work.

Almost the entire correctness and capability programme below has shipped.
What's genuinely still open is the non-composite-key half of
[Slice B2](#slice-b2--reconcile-current-documentation-claims) and the ongoing,
never-"done" ratchets in [Slice G1](#slice-g1--critical-compatibility-coverage)
and [Slice G2](#slice-g2--strict-typing-baseline-reduction).

### Track A — correctness fixes (all shipped)

#### Slice A1 — correct optionality compatibility under the current model

Fixed the bug where the model diff could emit `nullability_changed` but the
compatibility summary didn't consistently classify `optional -> required` as
breaking. **Shipped:** PR #279, "classify optional-to-required field changes
as breaking." `required -> optional` is compatible, `optional -> required` is
breaking, and semantic version validation and compatibility reporting call the
same rule (`cli/src/modelable/compat/diff.py`). This is an explicit **stopgap
for the current single-`optional`-flag model** — [Slice D1](#slice-d1--separate-presence-and-nullability)
must preserve these results for equivalent transitions when presence and
nullability separate.

#### Slice A2 — create one property-dependency graph

Replaced duplicated, incomplete source-property analysis (direct mappings,
computed expressions, join predicates, filters, grouping, projection-as-source
chains, and all source-version-reference forms) with one compiler-owned graph
used by compatibility, governance, lineage, graph export, and editor tooling.
**Shipped:** `cli/src/modelable/dependency_graph.py` (Slice A2 plan, archived).

#### Slice A3 — validate all expression positions

Runs the same CEL pipeline for computed fields, join predicates, `where`
clauses, `group by` expressions, and supported expression-bearing annotations,
validating result shape (booleans for filters/joins, resolved scalar types for
grouping) so no parsed expression can bypass semantic validation. **Shipped**
(Slice A3 plan, archived).

#### Slice A4 — fix semantic-type resolution ambiguity

Made semantic-type identity domain-aware and deterministic: a bare name
resolves in the current domain first, a qualified name (`orders.Id`) resolves
across domains, a bare name falls back to a workspace-wide match only when
exactly one declaration exists, and ambiguity is a compile error. **Shipped:**
`resolve_semantic_type_ref()` in `cli/src/modelable/registry/resolver.py`
(Slice A4 plan, archived).

### Track B — capability and documentation consistency

#### Slice B1 — add a canonical capability manifest

`modelable capabilities` (and `--format json`) exposes compiler-owned data —
output targets and status, SQL dialects, model kinds, annotations, wire hints,
projection features, import formats, integrations, and experimental/deferred
grammar constructs — so CLI, Playground, and documentation-consistency checks
stop hand-maintaining what Modelable supports. **Shipped:**
`cli/src/modelable/capabilities.py` and `cli/src/modelable/commands/capabilities.py`.

#### Slice B2 — reconcile current documentation claims

**Done:** the composite-key subtask. A conformance fixture with two `@key`
fields (`cli/tests/test_semantic.py::test_composite_key_is_not_yet_supported`)
recorded the real validator behavior, and `docs/architecture.md` was corrected
to match it and `docs/language-reference.md` instead of assuming the
architecture doc was right — see
[Slice D5](#slice-d5--resolve-composite-key-support). The optionality
contradiction closed the same way via Slice A1.

**Still open:** the remaining reconciliation topics — model lifecycle claims
beyond what [Slice D6](#slice-d6--model-lifecycle-status) already documents as
not implemented, target listings drifting from `modelable capabilities`,
federation/runtime-adjacent description strength, and classification
vocabulary consistency across all docs. Each capability should end up with
exactly one status (implemented, experimental, deferred, candidate, removed);
unsupported examples should be clearly labelled. `modelable capabilities` and
the `DEFERRED` diagnostic (Slice B3) are the authoritative source on status
today — treat any docs prose that disagrees with them as the bug.

#### Slice B3 — eliminate silently ignored syntax

Reviewed registry/peers, consumers, subscriptions (both forms),
materialisation, and opaque `binding {}` content. **Outcome chosen
(2026-08-05):** all of the above are "reject as deferred" — a non-blocking
warning-severity `DEFERRED` diagnostic
(`cli/src/modelable/validation/deferred_syntax.py`) rather than full
implementation, since none has an accepted runtime design yet (see
["Outside the near-term compiler roadmap"](#outside-the-near-term-compiler-roadmap)
below). Stable syntax is never silently discarded as ignored text anymore.

### Track C — compatibility architecture (all shipped)

#### Slice C1 — projection-to-projection compatibility

Treats versioned projections as first-class contracts: compares shape,
lineage, governance, wire, storage, and materialisation impact between
projection versions directly, wired into `modelable diff`. **Shipped:** PR
#291, `cli/src/modelable/compat/projection_fields.py`,
`compare_projection_versions()`/`check_projection_version_compatibility()` in
`compat/diff.py`/`compat/checker.py`. Source-version comparison delegates to
`check_model_version_compatibility()`; a projection change is compatible only
when both the shape delta and the source-version delta are compatible.

#### Slice C2 — extend existing version resolution to `ref<>` types

Extended the projection-source version-resolution rules (exact/range/minimum/
pin) to `ref<Domain.Model @ version_spec>` type-reference positions, so type
references use the same canonical resolver as projection sources instead of a
separate mechanism. **Shipped:** PR #292 (Slice C2), `RefType` in
`cli/src/modelable/parser/ir.py`.

#### Slice C3 — generalize existing target compatibility

Generalized the Protobuf/gRPC-specific compatibility guards into one
target-agnostic `TargetCompatibilityReport` axis/severity IR, extended to
JSON, SQL/storage migration, projection rebuild, and governance review,
without duplicating the existing Protobuf/gRPC rule logic. **Shipped:** PR
#294, `cli/src/modelable/compat/targets.py`.

#### Slice C4 — configurable compatibility and lint policy

Added a configurable compatibility/lint policy so teams can set enforcement
severity per target axis without changing the underlying compiler-determined
facts. **Shipped:** `cli/src/modelable/compat/policy.py`.

### Track G — engineering safeguards (compiler-specific)

#### Slice G1 — critical compatibility coverage

**Shipped, ongoing ratchet.**

Protects model compatibility, projection compatibility, dependency
resolution, expression validation, lineage, governance, signatures, and
target compatibility via a per-critical-path coverage ratchet rather than a
repository-wide percentage. **Shipped:** `cli/coverage-baseline.txt` lists 12
files covering all eight categories — `compat/checker.py`, `compat/diff.py`
(compatibility); `dependency_graph.py`, `registry/resolver.py` (dependency
resolution); `expressions/cel.py`, `compiler/workspace.py` (expression
validation); `planner/lineage.py` (lineage); `governance/checker.py`
(governance); `registry/signature.py` (signatures); `emitters/protobuf.py`,
`emitters/grpc.py`, `commands/validate_compat.py` (target compatibility) — and
`.github/scripts/check_coverage_ratchet.py` fails CI if any of them regresses.
This is a ratchet, not a one-time deliverable: raise individual baseline
numbers as their tests improve (never lower one to make a change pass), and
add files if a future slice identifies another critical path. See also
[Priority 7, finding 2](#2-ci-enforces-a-per-critical-path-coverage-ratchet-not-a-repository-wide-threshold).

#### Slice G2 — strict typing baseline reduction

**Ongoing ratchet, not one-shot.**

`mypy --strict` is enforced as a baseline ratchet
(`cli/mypy-baseline.txt`, `.github/scripts/check_mypy_baseline.py`) — see
[Priority 7, finding 1](#1-mypy---strict-is-enforced-as-a-baseline-ratchet)
for the full evidence. **Remaining work**, in critical-path priority order:
compatibility and dependency graph, resolver and signatures, semantic
validation, parser/IR, emitters, importers, conversational surfaces. Burn the
baseline down by module; when it reaches zero, replace the ratchet wrapper
with a direct `uv run mypy src/modelable` step and delete
`cli/mypy-baseline.txt`.

#### Slice G3 — conformance fixtures

**Shipped across four tranches, 2026-08-05–06.**

Goal: share fixtures across the native compiler, browser compiler, LSP,
Playground, compatibility, signatures, and manifests, with explicit coverage
for every capability documentation disputes (especially composite keys and
deferred constructs).

- **Tranche 1 (2026-08-05):** extended the existing native/browser/Playground
  shared-fixture pipeline (`cli/tests/conformance/browser/` →
  `vendor-python-assets.mjs` → `conformance.spec.ts`) with `composite-key` and
  `deferred-constructs` scenarios verified against the real Pyodide browser
  compiler. Found and fixed a real gap along the way:
  `language/workspace.py`'s `synchronize()` only read `workspace.errors`, so
  Slice B3's `DEFERRED` warnings were invisible in the browser/Playground
  despite working in the CLI.
- **Tranche 2 (2026-08-06):** closed signature fixtures
  (`cli/tests/conformance/signature/scenarios.py`, one canonical
  `ModelVersion`-fixture source for the registry resolver and LSP federation
  diagnostics) and capability-manifest-to-test linkage (`Capability.test_refs`
  + `test_capability_manifest_linkage.py`, enforced in CI; 9 of 11 deferred
  features linked, 2 explicitly acknowledged as unlinked pending their own
  scoping pass).
- **Tranche 3 (2026-08-06):** closed LSP fixture sharing (minus the full
  31-file migration of already-passing independent fixtures, explicitly out
  of scope). `test_lsp_conformance_fixture.py` drives the same shared fixture
  through a real `pygls` subprocess server, exercising completion, hover,
  definition, references, prepareRename, and rename against the same
  expectations the browser dispatch tests assert.
- **Tranche 4 (2026-08-06):** closed compatibility fixtures — the one area
  that had been blocked on Playwright/Pyodide network access.
  `cli/tests/conformance/browser/compatibility.mdl` plus a `compatibility`
  scenario in `write_browser_conformance.py` exercises
  `BrowserCompiler.compatibility()` end to end with a matching snapshot on
  both the native generator and `web/tests/conformance.spec.ts`.

External-format fixtures (Priority 5's forthcoming format-adapter work) must
record source and license/provenance, be pinned locally for offline CI, and
include stable expected output or semantic-equivalence assertions — the same
standard this track set.

Completion means compatibility reports can never contradict semantic
validation, every property dependency (including filters and joins) is
captured in one graph, all expressions are type-checked and traced, semantic
types resolve deterministically, documented capabilities match compiler
behavior, and no parsed syntax is silently discarded. Every point in that list
is satisfied today except the remaining half of Slice B2.

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
4. Extend nominal semantic-type generation beyond Rust (Slice F1), prioritizing
   TypeScript, Go, Java, C#, Python, JSON Schema, and SQL according to concrete
   consumer demand. Targets that intentionally erase nominal identity must say
   so explicitly. See [Slice F1](#slice-f1--nominal-semantic-types-beyond-rust)
   below.
5. Extend `modelable inspect` with registry-ID and canonical-signature lookup so
   generated constants and registry state are easy to diagnose.
6. Publish the VS Code extension through the Marketplace once the release and
   support process is defined.
7. Continue conformance, documentation, diagnostics, and importer hardening
   where contributor or user reports expose real gaps.

Completion means a new team can install the CLI and editor tooling, understand
generated identity and compatibility behavior, and adopt a supported target
without relying on internal repository knowledge.

## Priority 5 — deepen external integrations and format interoperability

Integration work follows adoption work unless a concrete deployment provides a
stronger near-term requirement. Format work should make Modelable a strong
migration and contract-interop boundary without turning generated formats into
alternate sources of truth.

### Format adapter and regression-test foundation

Before adding several more formats, normalize the importer/exporter boundary:

1. Move deterministic format import out of `modelable.llm` ownership and define
   a compiler/application-level format-adapter registry parallel to codegen
   targets. Each adapter declares its name, extensions/media types, import and
   export capabilities, semantic limitations, and round-trip metadata.
2. Make `modelable capabilities` the authoritative list of supported import and
   export formats and their maturity.
3. Create a checked-in real-world regression corpus, organized by format, for
   all supported importers and interoperability emitters. Prefer representative
   public examples from standards bodies, vendors, or established open-source
   projects; retain only data whose redistribution/license permits it and keep
   a provenance manifest with source URL, upstream version/commit, license, and
   any sanitization performed.
4. Keep regression test data local and pinned so CI never depends on network
   availability or mutable upstream files. Synthetic minimal fixtures remain
   useful for unit tests but do not substitute for the real-world corpus.
5. For every stable format adapter, require the relevant subset of:
   - parse/import -> normalized graph -> semantic validation;
   - deterministic golden output;
   - import -> emit -> re-import semantic-equivalence tests when both
     directions are supported;
   - upstream or reference-validator smoke tests when practical;
   - malformed, unsupported-feature, and edge-case fixtures that verify clear
     diagnostics instead of silent information loss;
   - compatibility regression fixtures across representative schema versions.

### Format delivery sequence

Work should then proceed in this order, subject to the language prerequisites in
Priority 6:

1. **Shipped — harden OpenAPI import and add OpenAPI export.**
   - Accept both YAML and JSON OpenAPI documents.
   - Stop treating the first `components.schemas` entry as the whole API.
   - Map reusable component schemas deliberately to value/entity candidates,
     request bodies and parameters to request projections, responses to reply
     projections, `$ref` to named references, and operation/security metadata
     where Modelable has a corresponding concept.
   - Add deterministic OpenAPI generation from API-facing projections, with
     stable schema and operation ordering.
   - Preserve Modelable-specific round-trip metadata through namespaced
     extensions where doing so does not change OpenAPI semantics.
2. **P0 — add Avro export and harden Avro import.** Avro record export is
   shipped as a deterministic local target for models and event projections;
   deterministic import hardening remains.
   Treat records as model/event contracts, map arrays/enums/logical types and
   optional unions, preserve Modelable identity/governance metadata through
   legal custom attributes, and add reader/writer compatibility regression
   fixtures before declaring the target stable.
3. **P1 — add AsyncAPI import/export.**
   Map Modelable events/projections to messages, bindings/topics to channels,
   producer/consumer intent to operations, and JSON Schema/Avro/Protobuf payload
   schemas without duplicating those schema emitters. Kafka is the first
   binding to harden; other protocol bindings follow concrete demand.
4. **P1 — add XSD import.**
   XSD is primarily an enterprise migration source. Map complex/simple types,
   enumerations, cardinality, restrictions, namespaces, and obvious identities;
   issue explicit lossy-import diagnostics for substitution groups, wildcards,
   mixed content, inheritance shapes, and XML-specific constructs that have no
   faithful Modelable representation. XSD export remains optional and should
   require a concrete consumer.
5. **P1/P2 — add GraphQL SDL/Federation interoperability.**
   Start with GraphQL/Federation export because Modelable domain ownership,
   entities, references, and API projections map naturally to subgraphs,
   `@key` identities, relationships, and operation shapes. Add SDL import after
   export semantics are stable and backed by representative federated schemas.
6. **P2 — add migration-only importers for TypeSpec and Smithy.**
   Consider LinkML and CUE in the same class if real migration demand appears.
   These are source migration paths into canonical `.mdl`, not reasons to emit
   another source-language artifact by default.
7. **P2 — add lakehouse schema targets.**
   Start with Iceberg schema emission and evaluate Delta schema interoperability
   after the type/field-identity mapping is proven. Emit schema/contract
   artifacts only; table lifecycle and runtime materialization stay outside the
   compiler boundary.
8. Continue existing integration work: live OpenMetadata synchronization,
   remote authenticated tracked-spec sources for dbt/FHIR/ODCS, complex FHIR
   and dbt/ODCS hardening, and lineage stitching for external dbt exposures and
   similar consumers.

The intended interoperability surface is asymmetric by design:

- Bidirectional where semantic round-tripping is useful and defensible: JSON
  Schema, Protobuf, Avro, ODCS, FHIR, OpenAPI, AsyncAPI, and eventually GraphQL.
- Primarily import/migration: SQL DDL, XSD, TypeSpec, Smithy, and potentially
  LinkML/CUE.
- Primarily output/platform integration: dbt, OpenMetadata, OpenLineage,
  PostgreSQL/ClickHouse, Iceberg/Delta, and generated programming languages.

Completion means at least one real deployment can pull or synchronize external
contracts reproducibly without making an external service the source of truth
for Modelable models, and every stable format adapter is exercised against
representative real-world regression data rather than only hand-written toy
fixtures.

## Priority 6 — language evolution and extensibility

Lane L. These items require accepted designs and, for the syntax-changing
ones, concrete consumer demand; they do not automatically outrank
Priorities 1–5.

Most items here were gated behind one decision, now made:

#### Slice D0 — define historical language interpretation

**Shipped/decided, 2026-08-06.**

**Decided:** additive-syntax policy — old syntax never changes meaning; new
semantics require new syntax. Chosen over language-version and
compiler-version-snapshot policies since those exist to protect a large body
of already-published `.mdl` text against reinterpretation, and that body
doesn't exist yet. A guardrail test pins this:
`cli/tests/test_language_stability.py` exact-matches the canonical signature
and formatted output of a small, representative set of already-shipped
constructs, so any accidental reinterpretation of historical syntax fails
there first. D1 and D6 below are unblocked to scope and design (not yet
implemented).

Gated on D0 (now decided), in dependency order:

#### Slice D1 — separate presence and nullability

**Purpose:** represent absence and explicit null independently — required
non-null, optional non-null, required nullable, optional nullable. **Design
and implementation:** `field?` remains the legacy presence marker and a post-type `?`
marks nullability, as specified in
[`docs/superpowers/specs/archived/2026-08-16-presence-nullability-design.md`](docs/superpowers/specs/archived/2026-08-16-presence-nullability-design.md).
**Shipped:** PR #364. The parser, canonical renderer, compatibility model,
and JSON Schema/OpenAPI emitters preserve both dimensions. Remaining
target-specific emitter coverage is tracked as target work. Requires D0 (done).
Acceptance:
existing
published text keeps a deterministic meaning; compatibility reports
distinguish presence from nullability; every emitter declares exact or lossy
representation. [Slice A1](#slice-a1--correct-optionality-compatibility-under-the-current-model)'s
stopgap results must still hold for equivalent transitions once this lands.

#### Slice D2 — first-class value constraints

**Purpose:** track valid property values (numeric min/max, length limits,
pattern, format, item-count limits, uniqueness) in addition to structural
shape, with explicit lineage and no silent widening. **Shipped:** PRs #379
and #380 added the constraint IR, compatibility semantics, JSON Schema/OpenAPI
mapping, projection propagation, and target support/loss coverage. Remaining
target-specific refinements are tracked with the relevant emitter work.
Each constraint must define valid source types, propagation through direct
projections, narrowing/widening rules, compatibility impact, and target
support/loss diagnostics.

#### Slice D3 — named, version-aware enums

**Purpose:** reusable vocabularies with domain-qualified identity, value
evolution, wire values, Protobuf numbering/reservations, and compatibility
across targets. **Shipped:** PRs #381 and #382 added reusable semantic enum
identity, schema reuse, version evolution, conversion behavior, and
compatibility checks. Depended on by D4.

#### Slice D4 — discriminated unions

**Purpose:** represent variant-based contracts, especially event families,
with stable variant identity and discriminator values; adding/removing
variants is compatibility-classified; every emitter preserves semantics or
emits an explicit loss diagnostic. **Core schema slice shipped:** PR #384
added the grammar/IR, canonical rendering, JSON Schema/OpenAPI `oneOf` plus
discriminator output, and JSON Schema round-trip import. **Next:** classify
union compatibility changes, add explicit target-loss diagnostics, and extend
preservation beyond schema-oriented targets. Depends on D3, D1, and stable
target-compatibility semantics.

#### Slice D5 — resolve composite-key support

**Phase 1 (decision and conformance) — shipped.** Added the executable
`test_composite_key_is_not_yet_supported` fixture, verified the current
validation failure, and corrected `docs/architecture.md` to match the
compiler and `docs/language-reference.md` instead of implementing composite
identity speculatively. See [Documentation status](#documentation-status)
above.

**Phase 2 (implementation) — not decided.** If composite entity identity is
ever accepted: allow one or more key fields for entities/aggregates, require
deterministic ordering, reuse `index { primary ... }` where present, define
fallback ordering otherwise, and update canonical signatures, compatibility,
SQL, Protobuf/gRPC manifests, generated languages, event envelopes, `ref<>`
identity, and join/relation validation. Multi-column join predicates and
composite entity identity are separate features — supporting a join over
several properties does not imply multiple `@key` fields are supported.

#### Slice D6 — model lifecycle status

**Purpose:** either implement or remove architecture claims for draft,
published, deprecated, and retired model-version statuses. **Not yet
started** as a language feature — `docs/architecture.md` currently documents
accurately that no `status` field exists in the grammar/IR today (the
documentation-accuracy half of this slice's concern is already satisfied the
same way Slice D5's was; the language-feature decision itself remains open).
Depends on D0 (done). Existing versioned declarations would need an explicit
default status (most likely `published`) if implemented; semantics to define
include draft mutability, published immutability, deprecated resolution
warnings, retired range resolution, legal transitions, interaction with
required `changeKind`, and signature/registry records.

Also in this lane, **not** gated behind D0 because it is purely additive
grammar that never reinterprets existing text:

#### Slice H1 — projection Pick/Omit clauses

**Shipped, 2026-08-06.**

Lets a `projection` select or exclude a field subset from its source
(including qualified `alias.field` selection across `join`s, and annotation
filters like `@pii` reusing `auto projections ... exclude`'s existing
matcher) without hand-writing a `<-` line per field. Full design:
[Projection Pick/Omit Clauses](docs/superpowers/specs/archived/2026-08-03-projection-pick-omit-design.md).

**Outcome:** grammar adds an optional `selection_clause?` on `projection_decl`
(`pick(...)`/`omit(...)`, mutually exclusive, non-empty by grammar
construction). `SelectionClause` IR mirrors `AutoProjectionTarget`'s existing
`excluded_fields`/`excluded_annotations` split. Expansion
(`planner/planner.py::expand_projection_selections`) runs alongside
`expand_auto_projections`, reuses `dependency_graph.py`'s alias resolution and
the (now-public) auto-projection annotation matcher, and produces the same
explicit `<-` IR a hand-written projection would — so compatibility (Slice
C1), the dependency graph (Slice A2), lineage, and governance need no
special-casing. Unqualified selectors are valid only if unambiguous across
all declared sources; same-output-name collisions across two aliases are a
distinct error rather than silently dropping one. The formatter
(`compiler/render.py`) gained `_render_selection_clause` so `pick`/`omit`
clauses round-trip on reformat instead of silently collapsing to `{ }` — a
gap this slice found and fixed rather than leaving as a follow-up. Covered by
`cli/tests/test_projection_selection.py`, including canonical-signature and
compatibility equivalence with hand-written projections.

Also extensibility work (Track E) that is additive but not yet prioritized
against a concrete consumer:

#### Slice E1 — typed namespaced annotations

`@acme.retention("7y")`-style annotations, a grammar prerequisite for any
annotation-plugin system. The current grammar has a closed set of
single-token built-in annotations. First sub-slice: namespaced annotation
identifiers, typed argument syntax, lossless preservation of unknown
annotation text, rejection of unsupported annotations under strict policy,
deterministic canonical rendering. A plugin contract would need each
extension to declare its namespace/version, annotation schema, valid
targets, compatibility significance, propagation rules, validation hooks,
and emitter behavior.

#### Slice E2 — data-quality contract metadata

Non-null, uniqueness, accepted values, ranges, row-count thresholds,
referential integrity, and external test references, surfaced through ODCS,
dbt tests, OpenMetadata contract metadata, and the machine-readable Modelable
graph — validated by Modelable but executed by external tools, not turning
Modelable into a scheduler.

#### Slice E3 — freshness, SLA, and retention metadata

Model/projection ownership, inheritance, compatibility significance,
duration syntax, timezone handling, and target mappings for freshness/SLA/
retention metadata, preserved by supported contract/catalog emitters and
visible as review or compatibility findings.

Target work gated on the above language work (Track F, items 2-5). Priority 5
owns sequencing and product scope; these slices describe language/compiler
prerequisites:

#### Slice F1 — nominal semantic types beyond Rust

Directly aligns with [Priority 4 item 4](#priority-4--improve-authoring-adoption-and-cross-target-consistency)
and remains valid; not gated on D0. Priority order (follow concrete consumer
demand, roadmap ordering as the starting point): TypeScript, Go, Java, C#,
Python, JSON Schema, SQL. Each target must state whether it preserves or
intentionally erases nominal identity.

#### Slice F2 — OpenAPI emission

Phase A (schema-only `components.schemas` emission) is implemented; see
`docs/superpowers/specs/archived/2026-08-14-openapi-emission-design.md`.
Phase B (versioned paths and operations, including operation-aware
compatibility facts) is implemented in [PR #357](https://github.com/ktjn/modelable/pull/357)
and [PR #358](https://github.com/ktjn/modelable/pull/358); the original downstream
request is complete and closed in [issue #352](https://github.com/ktjn/modelable/issues/352).
See the archived Phase B design and implementation plan. Phase C (deterministic OpenAPI import hardening) is
implemented in the format adapter used by the local import flow: JSON/YAML,
stable traversal of all component schemas, explicit multi-schema selection,
`x-modelable` metadata, and versioned component references are supported.
Unsupported unions, composition, nullability, and value constraints also emit
explicit lossy-import warnings instead of being silently discarded; dropped
operation, request/response, and security metadata is reported the same way.
Phase D (fidelity follow-ups): the core D1-D4 schema slices have shipped
(constraints, named enums, and discriminated unions all reach OpenAPI output
through the same field-mapping path `json-schema` uses, so they already have
parity there). Compatibility reporting and explicit loss diagnostics are now
also shipped: `modelable validate-compat --target openapi` reports breaking
changes to operations, path parameters, request/response bindings, and
component schemas ([PR #409](https://github.com/ktjn/modelable/pull/409),
[PR #410](https://github.com/ktjn/modelable/pull/410)), and the emitter
validates the complete generated document against OpenAPI 3.1 — not just the
`components.schemas` fragment — surfacing invalid output through the existing
`EMIT004` warning path ([PR #411](https://github.com/ktjn/modelable/pull/411)).
No further Phase D work is scoped; a genuinely new fidelity gap would need its
own issue and, per this roadmap's own policy, an accepted design before
becoming committed work.

#### Slice F3 — AsyncAPI emission

After named enums (D3), unions (D4), reference-version semantics, and the
event-envelope contract.

#### Slice F4 — Avro emission

The deterministic local record emitter is shipped for models and event
projections, including defaults, nullability, arrays, maps, enums, logical
types, and explicit loss warnings. Remaining work is deterministic Avro
import hardening and target-specific reader/writer compatibility.

#### Slice F5 — GraphQL/Federation emission

After identity/reference semantics and projection contract compatibility are
sufficiently explicit for stable subgraph generation.

## Priority 7 — repository health and engineering quality

Gaps found by direct code and CI inspection rather than product feature
requests. Nothing here is committed until it has an issue and an accepted
design, per the same policy as the rest of this roadmap. Findings are ranked
by impact within each section; "Evidence" cites the exact file so a claim can
be verified without re-deriving it. Unlike the priorities above, these are
continuous ratchets — "shipped" means the mechanism is in place and enforced,
not that the work is finished.

### Correctness and reliability

#### 1. `mypy --strict` is enforced as a baseline ratchet

**Evidence:** `cli/pyproject.toml` sets `[tool.mypy] strict = true`, and the
Validate workflow runs
`.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run
mypy src/modelable --no-error-summary --show-error-codes` from the `cli/`
directory. `cli/mypy-baseline.txt` captures the current strict baseline so new
error lines fail CI while existing debt remains visible.

**Impact:** Type regressions can no longer land silently on changed CLI
surfaces. The gate also reports resolved baseline lines, so typing cleanup can
shrink the baseline incrementally without requiring the repository to become
fully strict-clean in one large change.

**Remaining work:** see [Slice G2](#slice-g2--strict-typing-baseline-reduction)
above for the module burn-down order.

#### 2. CI enforces a per-critical-path coverage ratchet, not a repository-wide threshold

**Evidence:** `cli/pyproject.toml` declares `pytest-cov` as a dev dependency
and configures `[tool.coverage.run] source = ["src/modelable"]`.
`validate.yml`'s `cli` job runs `uv run pytest --tb=short --cov=modelable
--cov-report=term-missing --cov-report=xml`, uploads `cli/coverage.xml` as
the `cli-coverage-xml` artifact, and then runs
`.github/scripts/check_coverage_ratchet.py` against
`cli/coverage-baseline.txt` — the same checked-in-baseline pattern the mypy
strict ratchet (finding 1, above) already uses. The baseline lists the 12
files covering [Slice G1](#slice-g1--critical-compatibility-coverage)'s
eight protection categories.

**Impact:** A PR that drops coverage on any of these specific files fails
CI — critical-path coverage is a ratcheted signal, tied to the paths that
actually determine compiler correctness rather than an arbitrary
repository-wide percentage. The rest of the codebase keeps the same
visibility-only artifact/terminal-summary behavior as before.

**Remaining work:** Raise individual baseline numbers as their tests improve
(never lower one to make a change pass); add more files to
`coverage-baseline.txt` if a future slice identifies another critical path.

### Dependency management

#### 3. Dependabot routine groups are explicit version-update groups

**Evidence:** `.github/dependabot.yml` keeps one routine group per ecosystem
for Python, VS Code, and GitHub Actions updates, and each group declares
`applies-to: version-updates` before `patterns: ["*"]`.

**Impact:** Routine dependency churn remains grouped for review efficiency,
while the file documents that those groups are for version updates rather
than vulnerability remediation. Security updates can be handled as their own
Dependabot security-update PRs instead of being mixed into unrelated weekly
version bumps.

**Remaining work:** If security-update volume grows, add an explicit
security-update policy with narrower package patterns or labels. The current
configuration is deliberately simple until there is real update volume to
tune against.

## Candidate pool

These ideas are intentionally unordered until a concrete consumer, issue, and
accepted design establish their value:

- Embedded Python authoring that statically extracts a small, deterministic
  subset into canonical `.mdl` without importing or executing user code.
- Distributed registry synchronization beyond the current file-first ledger
  and local registry cache.
- Additional artifact formats requested by a real consumer beyond the explicit
  interoperability sequence in Priority 5.
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
  model that does not exist yet (see above); design work here should follow,
  not precede, an explicit product decision to build that runtime.

Until each gets its own accepted design, `modelable capabilities` and the
`DEFERRED` diagnostic are the authoritative source on their status — not
docs prose, which is exactly the drift Slice B2 corrected.

See [architecture](docs/architecture.md) for the product boundary,
[integrations](docs/integrations.md) for external-tool research, and
[GitHub issues](https://github.com/ktjn/modelable/issues) for work that is ready
for discussion or implementation.
