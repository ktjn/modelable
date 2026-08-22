# Model Evolution Slices Roadmap

This roadmap merges the former nominal-enum and model-version-delta delivery
plans into one ordered programme. It keeps their accepted semantic decisions,
but replaces broad multi-surface phases with independently reviewable slices.

The two capabilities solve related but different authoring problems:

- **nominal enums** give reusable closed sets a stable identity and explicit
  subset lineage; and
- **version deltas** let authors describe a new model version without copying
  every unchanged field while preserving complete immutable contracts.

They meet at one compiler rule:

> Source syntax may be concise, but every semantic consumer receives a complete,
> exact, reproducible contract.

## Review conclusions

The original plans had sound end-state semantics, but most of their slices were
too large for one focused pull request. They also understated an important part
of the live baseline: Modelable already supports versioned `semantic`
declarations backed by `enum(...)`, and the canonical `ROADMAP.md` records that
foundation as shipped. Adding a second parallel `enum Name` declaration would
create two nominal vocabulary mechanisms before a concrete consumer proves the
need. This roadmap therefore extends the shipped semantic-enum contract rather
than replacing it.

In addition:

- exact semantic-enum references, projections, editor support, and refactoring
  were grouped together;
- emitter work covered every implemented target in one slice;
- delta grammar, four operations, history resolution, provenance, metadata
  inheritance, and reservation policy were grouped together; and
- the plans repeated registry, compatibility, projection, editor, documentation,
  and qualification work without defining a shared normalization boundary.

This roadmap separates those concerns. Each numbered slice below should normally
produce one pull request. A slice may be split again when implementation reveals
an independently useful boundary, but adjacent slices should not be combined
unless the resulting review remains comparably focused.

## Locked semantic decisions

### Enum identity

1. `enum(a, b)` remains an anonymous local field type.
2. A domain-owned `semantic Name @ version: enum(...)` declaration is the source
   form for a nominal, independently versioned enum contract. Do not add a
   parallel `enum Name` declaration in this programme.
3. Matching members, wire values, generated names, or order never imply type
   equivalence.
4. A semantic-enum reference resolves to an exact declaration version before
   compatibility, signatures, registry operations, projections, or emission.
5. An enum projection is a distinct nominal type with explicit source lineage.
6. `pick(...)` fixes the projected member set. `omit(...)` is allowed, but a
   rebase must report members that become implicitly included.
7. Projection-to-source conversion is total. Source-to-projection conversion is
   checked and partial. Unrelated enums receive no generated conversion.
8. Protobuf member numbers are persistent allocation metadata, not source-list
   positions. Removed names and numbers cannot be silently reused.

Preferred source shape:

```mdl
domain customer {
  semantic CustomerStatus @ 1 (additive): enum(active, blocked, deleted)

  enum projection PublicCustomerStatus @ 1
    from CustomerStatus @ 1
    pick(active, blocked)

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    status: CustomerStatus @ 1
  }
}
```

`enum projection` is provisional because no equivalent construct exists today.
E3 must choose its final spelling after a grammar/formatter spike. Any syntax
change must retain the shipped semantic-enum declaration, explicit declaration
identity, exact versions, and explicit projection lineage.

### Model version deltas

1. `evolves @ N` constructs a version from the exact previous version of the
   same domain, model name, and model kind. It is not inheritance or subtyping.
2. The initial operations are `add`, `remove`, `rename`, and `replace`.
3. Operations execute in author order against an immutable copy of the base.
4. The base must be the highest existing lower version. Numeric gaps are valid;
   branching is not.
5. `replace` supplies one complete field declaration. There is no general field
   patch language.
6. Full declarations remain valid permanently and may appear between evolved
   versions.
7. Compatibility is derived from expanded old/new contracts. The declared
   `(additive)` or `(breaking)` kind remains an assertion, not an override.
8. Signatures and registry objects contain complete normalized versions, never
   unresolved delta chains.
9. Importers continue to produce full declarations. They do not infer author
   intent such as renames.

Preferred source shape:

```mdl
entity Customer @ 2 (additive) evolves @ 1 {
  add @pii email?: string
  add loyaltyPoints?: int
}

entity Customer @ 3 (breaking) evolves @ 2 {
  remove loyaltyPoints
  rename legalName -> displayName
  replace status: CustomerStatus @ 2
}
```

### Shared normalization boundary

The current parser IR (`MdlFile`) is also consumed directly as semantic state by
single-file compilation, workspace loading, browser APIs, language services,
registry code, and emitters. Version deltas cannot be expanded in only one of
those entry points.

Introduce one explicit source-to-normalized boundary:

```text
source text
  -> source declarations and locations
  -> merge declarations needed for exact resolution
  -> normalize exact semantic-enum references, enum projections, and version deltas
  -> complete semantic MdlFile
  -> validation, compatibility, signatures, registry, projections, impact,
     language-service semantics, and emitters
```

The normalized representation must contain complete `ModelVersion` objects and
exact enum identities. Source provenance is carried alongside normalized nodes
for diagnostics and navigation, but source spelling and formatting never enter a
canonical signature.

## Delivery rules for every slice

- Keep existing full declarations and anonymous enums backward compatible.
- Add focused parser/semantic tests before changing broad golden fixtures.
- When output changes intentionally, regenerate with
  `uv run python scripts/write_golden_artifacts.py --output tests/golden/artifacts`
  and review every target diff; never hand-edit golden artifacts.
- Add a `CHANGELOG.md` entry under `Unreleased` for each user-facing slice.
- Update language, compiler, wire, CLI, or capability documentation in the slice
  that makes the behavior usable; do not defer all documentation to the end.
- Before each commit, run from `cli/`:

  ```bash
  uv run ruff format .
  uv run ruff check .
  uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
  uv run pytest --tb=short
  ```

- For generated targets, golden equality proves deterministic output, not that a
  downstream compiler accepts it. Run the opt-in Docker compiler smoke with
  `MODELABLE_DOCKER_TESTS=1` when a slice changes compilable target output.
- If a slice touches browser conversation wiring or Python conversation plan
  schemas, also run or explicitly hand off the manual real-model WebLLM
  conformance described in `docs/maintainers.md`.

## Dependency map

```text
F1 -> F2 -> F3 -> F4
                   +-> E1 -> E2 -> E3 -> E4 -> E5 -> E6
                                      |         |     +-> E7
                                      |         +-------> E8
                                      |         +-------> E10
                                      +-----------------> E11
                                                E6 -----> E9

                   +-> D1 -> D2 -> D3 -> D4 -> D5 -> D6 -> D7
                                      +-----------------------> D8

E7 + E8 + E9 + E10 + E11 + D7 + D8 -> Q1 -> A1 and A2
```

`E` and `D` slices may proceed in parallel after F4. Q1 is the convergence gate;
the adoption slices remain optional follow-ups.

## Foundation slices

### F1 — remove unsafe Rust shape-based enum conversions

**Outcome:** unrelated anonymous enums with equal members can no longer convert
implicitly.

**Implementation instructions:**

1. Remove `_append_cross_enum_from_impls()` and the
   `frozenset(raw_variants)` registry from
   `cli/src/modelable/emitters/rust.py`.
2. Preserve only conversions required by an explicit record-projection mapping.
   Derive those conversions from the concrete source mapping and target field,
   never from a global member-shape scan.
3. Keep the temporary projection conversion local and clearly marked for removal
   in E7, when semantic enums and their projections share explicit generated
   types.
4. Add one fixture with unrelated equal-shaped enums and one direct-projection
   fixture. Assert the forbidden conversion is absent and the projection still
   compiles.
5. Regenerate Rust golden output if it changes and run the Rust Docker smoke.

**Likely surfaces:** `emitters/rust.py`, `tests/test_emit_rust.py`, projection
fixtures, Rust golden artifacts.

**Exit criteria:** no global shape registry remains; equal-shaped concepts do
not mix; direct projected fields still generate valid Rust.

### F2 — validate anonymous enum members centrally

**Outcome:** malformed anonymous enums fail before target generation.

**Implementation instructions:**

1. Add recursive semantic validation for `EnumType` inside arrays, maps, objects,
   unions, models, and projections.
2. Reject an empty member set and duplicate canonical member names with a
   diagnostic that names the owning field and both conflicting members.
3. Keep this validation independent of target spelling. Canonical identity is
   the authored member, not the escaped Rust or Protobuf identifier.
4. Add parser and semantic tests for empty, duplicate, and valid nested enums.

**Likely surfaces:** `parser/ir.py`, `validation/semantic.py`,
`tests/test_grammar.py`, `tests/test_compatibility.py` or a focused enum
validation module.

**Exit criteria:** every accepted anonymous enum has a non-empty unique
canonical member set and no emitter is the first component to detect duplicates.

### F3 — validate target enum-name and wire-value collisions

**Outcome:** two canonical members cannot silently collapse to one generated
identifier or wire value.

**Implementation instructions:**

1. Add a shared enum naming-analysis helper near `emitters/naming.py`; it accepts
   canonical members plus the selected target's casing/escaping policy and
   returns collision details without emitting code.
2. Use it for Rust, Protobuf, Avro, and every implemented target that emits a
   closed enum identifier. Do not claim coverage for targets that only preserve
   string values.
3. Validate `@wire` case transforms and overrides for duplicate resulting values.
4. Cover case folding, punctuation/underscore normalization, leading digits,
   reserved words, explicit overrides, and duplicate wire values.
5. Make diagnostics identify the target, owner, and colliding source members.

**Likely surfaces:** `emitters/naming.py`, `emitters/diagnostics.py`, wire
validation, affected emitter tests.

**Exit criteria:** every enum-emitting target either proves unique generated
names or returns one precise pre-emission diagnostic.

### F4 — establish normalized-contract equivalence

**Outcome:** the repository has one executable definition of semantic equality
and one documented place where source declarations become normalized contracts.

**Implementation instructions:**

1. Add a compact full-version fixture containing additive and breaking field,
   key, annotation, constraint, default, enum, `ref<>`, access, wire, and
   Protobuf-reservation behavior.
2. Add reusable assertions for normalized IR equality, canonical signature
   equality, semantic diff equality, projection resolution, and representative
   output equality.
3. Inventory all `parse_*_to_ir()` callers. Define a single normalization API
   used by `compiler/compiler.py`, `compiler/workspace.py`, browser compilation,
   LSP semantic workspace construction, CLI commands, and tests.
4. Keep parsing-only APIs available for syntax tooling, but name source and
   normalized types/functions so callers cannot accidentally treat unresolved
   declarations as canonical contracts.
5. Record source locations/provenance outside signature-bearing Pydantic fields,
   or explicitly exclude them from canonical serialization.

**Likely surfaces:** `parser/parse.py`, `parser/ir.py`, `compiler/workspace.py`,
`compiler/compiler.py`, `compiler/render.py`, `registry/signature.py`, and new
normalization tests.

**Exit criteria:** all semantic entry points pass through the same boundary, and
tests fail if source-only state reaches signatures, registry code, projections,
impact analysis, or emitters.

## Semantic-enum identity slices

### E1 — add exact versioned semantic-enum references

**Depends on:** F4.

**Outcome:** a model can reference an existing domain-owned semantic enum at an
exact version; enum projections are not included yet.

**Implementation instructions:**

1. Keep the shipped `semantic Name @ version (change-kind): enum(...)`
   declaration grammar and `SemanticTypeDecl` source representation.
2. Extend field-type grammar with same-domain and qualified exact-version
   references. Use a distinct `EnumRefType` or another discriminated reference
   shape rather than adding an optional version to every `NamedType` and silently
   changing non-enum semantics.
3. Derive a normalized declaration/member view from enum-backed semantic
   declarations. It may use `EnumDecl`/`EnumMember` internally, but it must not
   create a second source declaration registry.
4. Parse and render exact references while keeping unversioned semantic types and
   anonymous `enum(...)` source-compatible.
5. Reuse existing duplicate semantic-version validation and add member-identity
   checks specific to enum-backed declarations.
6. Add grammar-doc and editor-grammar generation updates for syntax recognition
   only; semantic editor features arrive in E11.
7. Add round-trip tests for same-domain, cross-domain, identical-shaped distinct
   semantic enums, and mixed anonymous/versioned semantic enums.

**Likely surfaces:** grammar, parser IR/transformer, compiler renderer,
`scripts/render_language_grammar.py`, `scripts/render_editor_grammars.py`, grammar
sync tests.

**Exit criteria:** parse-render-parse preserves semantic declaration identity and
exact reference syntax, while equal-shaped declarations remain separate
normalized contract objects and no parallel enum declaration mechanism exists.

### E2 — resolve exact enum identities

**Depends on:** E1.

**Outcome:** every semantic-enum reference is exact before normalized compiler
services run.

**Implementation instructions:**

1. Extend `resolve_semantic_type_ref()` with an exact version parameter or add a
   type-safe exact semantic-enum resolver that shares its ambiguity rules.
2. Resolve same-domain and qualified references; reject unknown, ambiguous, and
   wrong-kind targets.
3. Accept concise bare references only as an authoring form. Emit an `ENUMREF`
   diagnostic and resolve them deterministically where the existing `ref<>`
   version-diagnostic policy permits; published normalized state must be exact.
4. Reject an exact enum reference that resolves to a non-enum semantic type.
5. Extend recursive type traversal through arrays, maps, objects, unions, models,
   and projections.
6. Add a later-version fixture proving that adding a declaration does not change
   the resolved version of an existing published consumer.

**Likely surfaces:** `registry/resolver.py`, `compiler/workspace.py`, semantic
validation, resolver and version-resolution tests.

**Exit criteria:** normalized fields carry exact qualified enum identity and
version; no downstream service chooses a latest enum implicitly.

### E3 — add enum projections and subset lineage

**Depends on:** E2.

**Outcome:** authors can derive nominal subsets from exact semantic-enum versions
through `pick` or `omit`.

**Implementation instructions:**

1. Run a small grammar/formatter spike for the projection spelling. Prefer the
   concise `enum projection` form shown above, but reject it if it creates an
   ambiguous second declaration namespace. Record the chosen syntax and why.
2. Add an `EnumProjectionDecl` with exact semantic-enum source reference and
   authored `Pick` or `Omit` selection. The result participates in the same
   nominal enum namespace as its source declarations.
3. Resolve the source first, then normalize both forms into the exact resulting
   ordered-independent source-member identities. Retain authored form only for
   rendering and diagnostics.
4. Reject missing members, repeated selections, empty results, wrong source kind,
   and attempts to introduce members not present in the source.
5. Preserve a distinct projection identity even when two projections have the
   same source and subset.
6. Test that `pick` does not grow when the source gets a new member and that an
   `omit` rebase identifies the newly included member for E5 to report.

**Likely surfaces:** grammar, parser IR/transformer, enum resolver/normalizer,
compiler renderer, focused projection tests.

**Exit criteria:** normalized projections contain exact source version, exact
member identities, and immutable nominal identity.

### E4 — include enums in signatures, snapshots, and dependency graphs

**Depends on:** E3.

**Outcome:** enum contracts and lineage are reproducible offline before broad
emitter work begins.

**Implementation instructions:**

1. Extend canonical rendering/signatures to enum-backed semantic declarations
   and enum-projection versions. Sort only semantically unordered content; do
   not erase authored order if it has declared wire meaning.
2. Persist complete enum members, exact projection subsets, source lineage, wire
   metadata, and allocation placeholders in registry snapshot objects.
3. Reject one logical enum version with different canonical content under the
   existing immutability rule.
4. Extend registry usage and the shared dependency graph with enum-reference and
   enum-projection-source edges.
5. Rebuild from a snapshot without editable source and assert identical enum and
   projection signatures.
6. Add enum-backed semantic declarations and enum projections to capability and
   RAG/context inventories only where those inventories enumerate contract kinds.

**Likely surfaces:** `compiler/render.py`, `registry/signature.py`,
`registry/snapshot.py`, `registry/usage.py`, `dependency_graph.py`, capability and
RAG tests.

**Exit criteria:** a historical offline snapshot fully determines enum identity,
members, and projection lineage.

### E5 — implement enum compatibility and causal impact

**Depends on:** E3 and E4.

**Outcome:** enum evolution is reported at the owning declaration and propagated
to affected consumers.

**Implementation instructions:**

1. Add declaration-level findings for member add/remove/rename, wire change,
   number change, reference/version change, projection-source change, projection
   member add/remove, and implicit `omit` growth.
2. Treat member addition as schema-additive when existing wire identity is stable,
   while adding a target consequence for exhaustive consumers such as Rust.
3. Treat removal, rename, wire-value change, allocated-number change, and nominal
   declaration replacement as breaking. Reordering is non-semantic after stable
   allocation exists.
4. Compare an enum version bump through the referenced declaration diff, not as
   an unrelated structural field replacement.
5. Preserve conservative `enum_changed` behavior for anonymous enums.
6. Extend `modelable diff`, target compatibility, and `modelable impact` with one
   causal path through enum projections, models, record projections, APIs,
   generated artifacts, and consumers.

**Likely surfaces:** `compat/diff.py`, `compat/checker.py`, `compat/targets.py`,
`commands/diff.py`, `commands/impact.py`, dependency and impact tests.

**Exit criteria:** equal-shaped nominal enums never collapse; additive growth and
breaking evolution are distinct; implicit `omit` growth is never silent.

### E6 — allocate stable Protobuf enum numbers

**Depends on:** E4 and E5.

**Outcome:** published enum numbers remain stable across additions, reordering,
removal, and subset projection changes.

**Implementation instructions:**

1. Reserve `0` for `<ENUM>_UNSPECIFIED` under the initial policy.
2. Allocate positive numbers deterministically and persist member name/identity to
   number mappings in normalized registry metadata.
3. Carry source allocation identity into projected enums where Protobuf permits;
   otherwise allocate projection-local numbers and persist them independently.
4. Preserve numbers across reordering and additions. Record removed names and
   numbers as reservations and reject reuse.
5. Include allocations and reservations in Protobuf descriptor/signature inputs
   wherever they affect wire compatibility.
6. Add v1/v2/v3 fixtures for append, reorder, removal, rename, reuse attempts, and
   projection changes.

**Likely surfaces:** `emitters/protobuf.py`, registry snapshot schema/object
rendering, wire compatibility, Protobuf tests and golden fixtures.

**Exit criteria:** no existing source or projected member is renumbered by an
unrelated edit, and removed identifiers cannot reappear silently.

### E7 — emit nominal enums and lineage conversions in Rust

**Depends on:** E5 and E6.

**Outcome:** Rust emits one reusable type per semantic-enum declaration/version
and uses lineage, not shape, for conversions.

**Implementation instructions:**

1. Emit named source and projected enums once in deterministic domain/package
   modules; models and record projections import those types.
2. Generate `From<Projected> for Source` when lineage proves totality.
3. Generate `TryFrom<Source> for Projected` for proper subsets and return a stable
   error representation for excluded values.
4. Generate projection-to-projection conversion only when the lineage graph proves
   totality, or a checked conversion when the target relation is partial.
5. Remove the temporary anonymous direct-projection conversion left by F1 when
   explicit semantic-enum types cover it; keep anonymous enums local.
6. Preserve serde casing/overrides and ClickHouse string handling.

**Likely surfaces:** `emitters/rust.py`, named-type/package helpers, Rust tests,
goldens, Docker smoke fixture.

**Exit criteria:** no unrelated `From` exists; semantic enums are reused; every
generated total/partial conversion matches proven lineage.

### E8 — emit semantic enums in typed SDK targets

**Depends on:** E5.

**Outcome:** TypeScript, Python, Java, C#, and Go preserve enum-backed semantic
declarations as reusable target types.

**Implementation instructions:**

1. Add one shared emitter-shape abstraction for nominal enum references instead
   of independently rediscovering ownership in each emitter.
2. TypeScript should use one reusable runtime/value declaration plus type; choose
   branding only in a separate explicit decision and do not claim nominal safety
   from an unbranded structural alias.
3. Python, Java, C#, and Go should emit/import the target's ordinary named enum
   form and preserve wire mappings.
4. Where a language supports checked conversion helpers, generate them for proper
   subsets; otherwise emit a validator/parser with explicit failure.
5. Add per-target focused tests and regenerate all affected goldens.

**Likely surfaces:** `emitters/shapes.py`, `emitters/named_types.py`, TypeScript,
Python, Java, C#, and Go emitters and tests.

**Exit criteria:** each target declares an enum-backed semantic type once per
contract version and consumer types reference it rather than duplicate local
literals.

### E9 — emit semantic enums in schema and API targets

**Depends on:** E6.

**Outcome:** Protobuf/gRPC, Avro, JSON Schema, and OpenAPI preserve reusable enum
identity as far as their formats allow.

**Implementation instructions:**

1. Protobuf/gRPC must emit and reference the stable declarations allocated in E6,
   including cross-domain package qualification.
2. Avro must derive one qualified named enum from Modelable identity and use Avro
   named-type references for repeats; enum projections get distinct names.
3. JSON Schema and OpenAPI must place named enums in reusable definitions or
   components and use `$ref`; anonymous enums stay inline.
4. Carry projection lineage in Modelable-owned manifests/extensions where the
   external schema language cannot express it.
5. Validate generated schemas with existing validators and run applicable Docker
   compiler smoke tests.

**Likely surfaces:** Protobuf, gRPC, Avro, JSON Schema, OpenAPI emitters; schema
mapping helpers; their tests and goldens.

**Exit criteria:** supported formats reuse one stable declaration, and structural
formats document rather than conceal their loss of nominal semantics.

### E10 — propagate enum identity through storage and metadata targets

**Depends on:** E4 and E5.

**Outcome:** every remaining implemented target either carries enum identity and
lineage or explicitly records target-level structural loss.

**Implementation instructions:**

1. Cover the live implemented-target inventory, currently `sql-postgres`,
   `sql-clickhouse`, `dbt-yaml`, `fhir-profile`, `openmetadata`, `openlineage`,
   `odcs`, `markdown`, `registry`, and `event-sink`.
2. Keep physical storage mappings target-driven, but do not use string/text
   storage equality as logical enum compatibility.
3. Add qualified enum/version and projection-source lineage to Modelable-owned
   metadata where useful. For external formats without such concepts, state the
   loss in emitted metadata or capability documentation.
4. Add a guard that the union of E7-E10 test matrices equals
   `list_implemented_codegen_targets()` so a new target cannot bypass enum
   qualification.
5. Regenerate and review the complete golden tree once all target changes land.

**Likely surfaces:** storage/metadata emitters, `emitters/targets.py`, golden and
capability tests.

**Exit criteria:** all implemented targets are accounted for, with no emitter
inferring canonical identity from field paths or member shape.

### E11 — add semantic-enum editor and language-service support

**Depends on:** E2 and E3; may proceed alongside E4-E10.

**Outcome:** enum-backed semantic declarations, exact references, projection
sources, and members have first-class editing behavior.

**Implementation instructions:**

1. Extend semantic-declaration tokens, document/workspace symbols, hover,
   completion, definition, references, highlight, and rename for exact enum
   references.
2. Resolve member definition/completion inside `pick` and `omit` against the exact
   source version.
3. Rename a member only within its nominal identity and dependent projections;
   never rename equal-spelled members in unrelated enums.
4. Mirror behavior through Python language services, LSP adapters, VS Code grammar,
   and Monaco/browser providers.
5. Add cross-surface conformance fixtures and keep generated editor grammars in
   sync.

**Likely surfaces:** `language/`, `lsp/`, VS Code syntax/config, Monaco providers,
language and browser conformance tests.

**Exit criteria:** editor operations preserve nominal boundaries and exact
versions; syntax and semantic behavior match across CLI LSP and browser.

## Model version delta slices

### D1 — deliver add-only exact-base evolution

**Depends on:** F4.

**Outcome:** authors can use `evolves @ N` with `add` operations as the first
usable vertical delta slice.

**Implementation instructions:**

1. Add source declarations for `ModelVersionDecl`, `ModelEvolution`, and
   `AddField`; do not add half-expanded optional fields to canonical
   `ModelVersion`.
2. Extend grammar with `evolves @ INT` and `add` using ordinary complete field
   syntax.
3. Resolve the base only within the same domain/model/kind. Require it to be the
   highest existing lower version; allow numeric gaps; reject first-version,
   missing-base, wrong-kind, forward, and branching histories.
4. Deep-copy the already normalized exact base, append added fields in operation
   order, and produce a complete `ModelVersion` before semantic validation.
5. Reject duplicate fields at the `add` source location.
6. Prove equivalent full and add-only source forms have identical normalized IR,
   signatures, semantic validation, and a small representative target output.

**Likely surfaces:** grammar, parser source IR/transformer, new compiler
normalizer, workspace/single-file/browser entry points, parser and normalization
tests.

**Exit criteria:** add-only evolution is usable end to end and no semantic caller
can observe an unresolved evolution object.

### D2 — add remove, rename, replace, and provenance

**Depends on:** D1.

**Outcome:** the complete initial field-operation vocabulary executes
deterministically with source-local diagnostics.

**Implementation instructions:**

1. Add source IR and grammar for `remove`, `rename old -> new`, and `replace`
   using a complete field declaration.
2. Apply operations sequentially. Rename and replace retain field position;
   remove deletes the complete field; add remains append-only.
3. Reject unknown sources, occupied rename targets, replacement-name mismatch,
   repeated removal, and every invalid sequence at the failing operation.
4. Record provenance for inherited fields and for the operation that last added,
   renamed, or replaced each field. Keep it out of signatures.
5. Preserve operation order in formatter round trips; do not reorder for style.
6. Add table-driven valid/invalid sequence tests, including rename-then-replace.

**Likely surfaces:** grammar, source IR, normalizer, source-map/provenance model,
renderer/formatter, focused operation tests.

**Exit criteria:** all four operations normalize deterministically and diagnostics
point to authored operations rather than synthetic expanded fields.

### D3 — settle and implement model-level metadata inheritance

**Depends on:** D2.

**Outcome:** evolved versions preserve access, annotation, wire, key, and
reservation semantics without accidental contract loss.

**Implementation instructions:**

1. Treat an omitted access block as inherited and a present access block as a
   complete replacement.
2. Treat omitted model annotations as inherited and present annotations for the
   same target as complete replacement metadata; verify existing `@wire`
   semantics against golden fixtures.
3. Keep index declarations outside `evolves`.
4. Before coding reservation behavior, use existing Protobuf compatibility tests
   to decide whether reservations are cumulative semantic state or explicitly
   version-local declarations. Record the decision in `docs/architecture.md` or
   the wire-format contract, then implement exactly that policy.
5. Run ordinary key, model-kind, annotation, constraint, default, and type
   validation only on the complete expanded version. De-duplicate consequences
   when one operation causes both model invalidity and compatibility findings.
6. Cover entity, aggregate, event, and value histories.

**Likely surfaces:** normalizer, semantic validation, wire helpers, Protobuf
reservation logic/tests, architecture or wire documentation.

**Exit criteria:** omitted metadata cannot silently change generated contracts,
and the reservation rule is explicit, tested, and reproducible.

### D4 — connect operation intent to compatibility

**Depends on:** D2 and D3.

**Outcome:** compatibility remains contract-derived while diagnostics explain the
author operation that caused each fact.

**Implementation instructions:**

1. Keep `compare_model_versions()` operating only on complete versions.
2. Feed explicit rename provenance into field matching so declared renames do not
   rely on name-similarity or deprecation inference.
3. Classify `replace` from the actual old/new field definitions; the operation
   name is not itself additive or breaking.
4. Check `(additive)`/`(breaking)` against the normalized result and report both
   the responsible operation and derived consequence when they conflict.
5. Preserve source, target, storage, identity, and governance axes.
6. Add paired full/delta tests requiring identical findings apart from richer
   provenance text.

**Likely surfaces:** `compat/diff.py`, `compat/checker.py`, semantic change-kind
validation, diagnostic DTOs and tests.

**Exit criteria:** author intent enriches but never overrides compatibility, and
equivalent source forms produce the same facts.

### D5 — prove signatures and registry objects are syntax-independent

**Depends on:** D3 and D4.

**Outcome:** registry consumers never execute authoring deltas.

**Implementation instructions:**

1. Compute signatures only from expanded complete versions.
2. Store complete normalized model objects in snapshots and omit unresolved base
   chains and operation syntax from canonical content.
3. Preserve original `.mdl` only in source packages that intentionally carry
   source, separate from canonical contract objects.
4. Rebuild and compile a historical snapshot without the base source file.
5. Assert equivalent full/delta versions have identical signatures, object
   hashes, immutability conflicts, and offline artifacts.
6. If provenance is exported for diagnostics, keep formatting and locations out
   of semantic hashes.

**Likely surfaces:** `registry/signature.py`, `registry/snapshot.py`, canonical
renderer, registry tests.

**Exit criteria:** a snapshot is self-contained and byte-for-byte reproducible
without replaying a delta chain.

### D6 — prove projection, dependency, and impact transparency

**Depends on:** D4 and D5.

**Outcome:** projections and consequences cannot tell whether their source was
authored fully or as a delta.

**Implementation instructions:**

1. Pair full/delta fixtures for direct fields, computed fields, `pick`, `omit`,
   joins, filters, grouping, and projection-of-projection chains.
2. Require equivalent resolved projection fields and property dependency graph
   edges.
3. Require equivalent projection compatibility and impact paths.
4. Keep canonical lineage anchored to normalized field/model identities; expose
   inherited/added/renamed origin only as optional diagnostic or hover metadata.
5. Add guards preventing planner, dependency, conversion, and impact modules from
   branching on delta source syntax.

**Likely surfaces:** projection planner/resolver, `dependency_graph.py`,
`compat/checker.py`, projection/dependency/impact tests.

**Exit criteria:** all projection behavior and causal impact are logically
identical for equivalent full and delta source.

### D7 — prove all generated targets are syntax-independent

**Depends on:** D5 and D6.

**Outcome:** every implemented emitter consumes only complete normalized models.

**Implementation instructions:**

1. Compile one small history in full and equivalent delta forms using
   `list_implemented_codegen_targets()`.
2. Compare every artifact byte-for-byte. Permit a difference only for a narrowly
   documented source-location/source-snippet field, never for contract output.
3. Include Protobuf numbering/reservations, API requiredness, SDK field shapes,
   SQL mappings, metadata lineage, registry manifests, and event-sink output.
4. Reuse generated trees across assertions so the matrix stays fast.
5. Run Docker compiler smoke for compilable targets using the same generated
   output, not a second Modelable compilation.

**Likely surfaces:** `tests/test_golden_artifacts.py`, a focused normalization
equivalence module, Docker smoke harness, shared fixtures.

**Exit criteria:** target inventory coverage is exact and no emitter contains an
`evolves` or operation-specific branch.

### D8 — add delta formatter and language-service support

**Depends on:** D2 and D3; final acceptance depends on D4.

**Outcome:** concise authoring has source-local navigation, completion, rename,
and diagnostics across LSP and browser.

**Implementation instructions:**

1. Preserve `evolves` and operation order in formatter round trips.
2. Add syntax tokens and operation-aware completion. At each operation, propose
   fields from the intermediate expansion state, not only the base or final state.
3. Add definition/hover on the exact base version and show base signature/field
   count.
4. Map semantic and compatibility findings to the responsible operation or
   inherited declaration through the shared provenance map.
5. Update references and symbol rename for field names in `remove`, `rename`, and
   `replace`; distinguish a rename operation from an editor symbol-rename action.
6. Mirror behavior through Python language services, LSP, VS Code grammar, and
   Monaco/browser tests.

**Likely surfaces:** compiler formatter/renderer, `language/`, `lsp/`, VS Code
grammar, Monaco provider, cross-surface tests.

**Exit criteria:** editor diagnostics never expose synthetic locations and all
surfaces preserve operation semantics consistently.

## Convergence and adoption slices

### Q1 — run combined feature qualification and complete documentation

**Depends on:** E10, E11, and D8.

**Outcome:** the two capabilities are proven together through every semantic and
generated surface.

**Implementation instructions:**

1. Add one compact history with a full v1, additive delta v2, breaking delta v3,
   full reset v5, and additive delta v8.
2. Include two equal-shaped unrelated semantic enums, a `pick` projection, an `omit`
   projection, one anonymous enum, enum additive/breaking versions, a cross-domain
   reference, target-name collision coverage, keys, constraints/defaults,
   governance/wire metadata, access policy, reservations, `ref<>`, value and
   semantic types, indexes, projections, API/event/storage surfaces.
3. Prove full/delta signature equivalence; nominal enum separation; total/partial
   conversion behavior; stable Protobuf allocations; exact snapshot rebuild;
   matching compatibility, dependency, impact, and all-target artifacts.
4. Update `docs/language-reference.md`, generated `docs/grammar.md`,
   `docs/compiler-reference.md`, `docs/wire-format-contract.md`,
   `docs/architecture.md`, relevant CLI reference, capabilities, getting-started
   examples, and representative samples.
5. Document structural loss per target and the distinction among anonymous enum,
   semantic enum, enum projection, non-enum semantic type, value model, full declaration,
   evolved declaration, normalized version, and record projection.

**Exit criteria:** all focused and full gates pass; docs and capability output
match implementation; the feature scenario is suitable for future regression
testing rather than a one-time script.

### A1 — add explicit enum discovery and extraction tooling

**Depends on:** Q1. Optional adoption work.

**Outcome:** developers can find duplicate anonymous shapes and deliberately
extract selected occurrences without heuristic identity merging.

**Implementation instructions:**

1. Add a lint finding that lists repeated anonymous shapes and locations but makes
   no equivalence claim.
2. Require the user to choose the canonical name, owning domain, selected
   occurrences, and whether intentional subsets become enum projections.
3. Preserve wire metadata and validate affected target outputs before applying.
4. Abort safely when comments or source edits cannot be mapped without loss.
5. Keep anonymous enums supported indefinitely.

**Exit criteria:** discovery is informative; extraction requires an explicit
semantic choice; no unrelated concepts are merged automatically.

### A2 — add expand and compact tooling for version deltas

**Depends on:** Q1. Optional adoption work.

**Outcome:** existing full histories can adopt concise authoring with a proven
equivalence gate.

**Implementation instructions:**

1. Add a compiler-owned complete-version-to-delta representation for consecutive
   versions.
2. Add an expand command/code action that renders a delta-authored version as a
   complete declaration for review.
3. Add compact tooling that proposes `add`, `remove`, `replace`, and only
   evidence-backed `rename`; ambiguous rename-like changes remain remove plus add.
4. Normalize both forms and require identical signatures for every affected
   version before applying edits.
5. Preserve comments when mapping is exact; otherwise stop and request review.
6. A repetition lint may suggest the refactor but must never require delta syntax.

**Exit criteria:** adoption changes authoring ergonomics only, with no canonical
contract or generated artifact changes.

## Programme completion gate

The core programme is complete at Q1 when:

- unrelated equal-shaped enums cannot mix;
- semantic enums and enum projections retain exact identity and lineage through
  compatibility, registry snapshots, impact analysis, editor tooling, and every
  implemented generator;
- projected-subset conversions are total in one direction and checked in the
  other;
- Protobuf enum allocations remain stable and removed identities cannot be reused;
- authors can evolve all model kinds through exact linear deltas without copying
  unchanged fields;
- full and delta-authored equivalents have identical normalized contracts,
  signatures, registry objects, compatibility facts, projection/dependency/impact
  results, and generated artifacts; and
- source provenance improves diagnostics without entering canonical identity.

## Non-goals

- Inferring enum equivalence or subset lineage from matching values.
- Replacing value models or semantic types with enums.
- Making physical storage representation define logical compatibility.
- Cross-model inheritance, mixins, traits, reusable field bundles, or subtyping.
- Generic arbitrary AST patches or partial field-mutation syntax.
- Inferring renames from spelling similarity.
- Floating/ranged evolution bases or branching model histories.
- Storing unresolved delta chains as registry contracts.
- Inferring deltas from imported external schema histories.
- Making the optional A1/A2 refactoring tools prerequisites for the core language
  capabilities.
