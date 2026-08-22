# Model Version Delta Authoring Delivery Plan

This plan reduces repeated field declarations across versions of the same Modelable model without weakening the existing immutable-version contract model.

Today every `entity`, `aggregate`, `event`, and `value` version is authored as a complete independent field set. That makes normalized compatibility simple and historical versions self-contained, but it creates substantial source duplication for ordinary additive evolution. A version that adds one optional field must restate every unchanged field, annotation, constraint, type, default, and key declaration from the previous version.

The proposed solution is **delta authoring with full-version normalization**.

Authors may describe a new model version as an exact evolution of the previous version using a small explicit mutation vocabulary. Before ordinary semantic validation, compatibility, signatures, registry snapshots, projection resolution, or code generation, the compiler expands that delta into the same complete `ModelVersion` shape used today.

The guiding rules are:

> Source may be concise; canonical contracts remain complete.

> Evolution is version construction, not type inheritance.

## Current baseline

- Model kinds are `entity`, `aggregate`, `event`, and `value`.
- All four kinds use the same `ModelVersion` IR shape with a complete `fields: list[FieldDef]`.
- The language reference explicitly treats each model version as a full independent declaration.
- Compatibility compares complete old/new field maps to derive additions, removals, renames, presence/nullability changes, type changes, identity changes, governance changes, and target consequences.
- Canonical signatures, target generation, projections, dependency analysis, registry snapshots, and imported contracts assume resolved complete model versions.
- Projections already avoid much consumer-shape duplication through direct mappings and `pick(...)` / `omit(...)`; this plan addresses duplication **within the version history of one canonical model**.
- Shared structured domain concepts are already represented by `value` models and references; this plan does not introduce cross-model inheritance.

A representative current pattern is:

```mdl
entity Customer @ 1 (additive) {
  @key customerId: uuid
  legalName: string
  status: enum(active, blocked, deleted)
  createdAt: timestamp
}

entity Customer @ 2 (additive) {
  @key customerId: uuid
  legalName: string
  @pii email?: string
  loyaltyPoints?: int
  status: enum(active, blocked, deleted)
  createdAt: timestamp
}
```

Only two fields are new, but the second version repeats the entire previous shape.

## Accepted direction

1. Add an optional exact-base `evolves @ N` clause to model declarations.
2. An evolved version contains explicit delta operations rather than a complete copied field list.
3. The initial mutation vocabulary is deliberately small: `add`, `remove`, `rename`, and `replace`.
4. `evolves` means construction from an immutable previous version. It does **not** mean inheritance, subtyping, mixins, traits, or polymorphism.
5. The base must be an exact version of the same domain, model name, and model kind.
6. Initially require a linear model history: an evolved version must reference the immediately previous available version of that model, not an arbitrary ancestor.
7. Normalize deltas into full `ModelVersion` instances before existing compiler services run.
8. Canonical signatures and registry snapshots are calculated from the expanded full contract, never from delta syntax.
9. Existing full declarations remain permanently valid. Delta authoring is optional and may be introduced incrementally.
10. Imported external contracts may continue to render as full declarations; importers do not need to infer author intent or generate deltas.
11. Declared `(additive)` / `(breaking)` remains an author assertion and is checked against the actual normalized diff.
12. Do not introduce cross-entity field inheritance to solve similar-looking fields. Reuse domain concepts with `value`, `semantic`, named enums, references, and projections instead.

## Proposed language shape

### Additive evolution

```mdl
entity Customer @ 1 (additive) {
  @key customerId: uuid
  legalName: string
  status: CustomerStatus @ 1
  createdAt: timestamp
}

entity Customer @ 2 (additive) evolves @ 1 {
  add @pii email?: string
  add loyaltyPoints?: int
}
```

The compiler expands `Customer @ 2` to the complete field set:

```text
customerId
legalName
status
createdAt
email
loyaltyPoints
```

The exact retained field ordering policy is defined below.

### Breaking evolution

```mdl
entity Customer @ 3 (breaking) evolves @ 2 {
  remove loyaltyPoints
  rename legalName -> displayName
  replace status: CustomerStatus @ 2
}
```

### Full declarations still work

```mdl
entity Customer @ 4 (breaking) {
  @key customerId: uuid
  displayName: string
  status: CustomerStatus @ 3
  createdAt: timestamp
}
```

A later delta may evolve from that full version normally.

## Delta operation semantics

### `add`

`add` introduces one complete field declaration using ordinary field syntax:

```mdl
add @pii email?: string
add tags?: array<string> constraint { max_items: 20 }
```

Rules:

- the target field name must not exist in the base version;
- all ordinary field validation applies after expansion;
- newly added fields are appended after inherited fields in author operation order;
- adding a required field remains a breaking compatibility change under current rules;
- `@key` additions/removals are subject to existing model-kind identity validation and compatibility rules.

### `remove`

```mdl
remove loyaltyPoints
```

Rules:

- the field must exist in the base state at the point the operation is applied;
- removal deletes the complete field definition, including annotations, constraints, default, optionality, nullability, and type;
- removal is breaking under current source compatibility rules;
- removing the only key from an `entity`/`aggregate` fails normalized semantic validation in addition to being breaking.

### `rename`

```mdl
rename legalName -> displayName
```

Rules:

- the source field must exist;
- the destination field must not exist;
- rename preserves the complete source field shape and changes only its canonical field name;
- the field keeps its position in the normalized field sequence;
- the explicit rename operation is preserved as author intent/provenance so compatibility need not infer a relationship from delete+add;
- target-specific wire naming remains governed by existing `@wire` rules and may still require an explicit `replace` if the author intends to change those annotations too;
- rename is breaking unless existing/future explicit alias or migration semantics say otherwise.

### `replace`

`replace` substitutes the complete declaration of an existing field:

```mdl
replace status: CustomerStatus @ 2
replace @pii email: string
```

Rules:

- the field must already exist;
- the replacement field name must match the existing field name; use `rename` separately for a name change;
- replacement specifies the complete new field declaration, not a partial patch;
- annotations, type, optionality, nullability, constraints, and default all come from the replacement declaration;
- the field retains its existing position;
- compatibility is still calculated by comparing the expanded old/new `FieldDef`s, so `replace` itself is not automatically breaking or additive.

This intentionally avoids a large patch vocabulary such as `set optional`, `remove annotation`, `change constraint`, or `set default`. Those operations can be expressed unambiguously by one complete `replace`.

## Operation ordering

Operations are applied sequentially to an in-memory copy of the exact base version.

Example:

```mdl
entity Customer @ 3 (breaking) evolves @ 2 {
  rename legalName -> displayName
  replace displayName: string constraint { min_length: 1 }
}
```

This is valid because the second operation sees the result of the first.

Validation must reject contradictory or invalid sequences with diagnostics at the failing operation, for example:

```mdl
remove email
replace email: string
```

or:

```mdl
rename name -> displayName
rename name -> legalName
```

Do not silently reorder operations.

## Full-version normalization boundary

The feature succeeds only if delta syntax disappears before ordinary compiler logic.

Conceptually:

```text
source AST

Customer@1 full
Customer@2 evolves @1 { add email }
Customer@3 evolves @2 { rename legalName -> displayName }
        │
        ▼
model-version expansion
        │
        ├── Customer@1 complete ModelVersion
        ├── Customer@2 complete ModelVersion
        └── Customer@3 complete ModelVersion
        │
        ▼
existing semantic graph
        │
        ├── validation
        ├── compatibility
        ├── signatures
        ├── registry
        ├── projections/lineage
        ├── impact/consequences
        └── emitters
```

### Canonical contract rule

For the same logical resulting model version, these two source forms must produce identical canonical contract content and signatures:

```mdl
entity Customer @ 2 (additive) evolves @ 1 {
  add email?: string
}
```

and the equivalent complete declaration.

Source rendering/provenance may differ; canonical normalized contract identity must not.

### Suggested parser/source IR

Do not overload the current normalized `ModelVersion` with half-expanded state.

Use a source-level declaration distinction such as:

```text
ModelVersionDecl
  model_kind
  name
  version
  change_kind
  body

ModelEvolution
  base_version
  operations[]

EvolutionOperation
  AddField
  RemoveField
  RenameField
  ReplaceField
```

Then expansion produces the existing normalized `ModelVersion`.

If retaining one parser IR is materially simpler, an optional `evolution` field may temporarily coexist with `fields`, but normalized services must receive an explicit expanded workspace type or a guaranteed post-expansion invariant. Avoid requiring every emitter/validator to branch on `if version.evolution`.

## Base resolution and history rules

Initial rules should be intentionally strict.

- The base is written as exact `evolves @ INT` only.
- No ranges, minimum versions, hashes, `latest`, or floating resolution in evolution syntax.
- The base must exist in the same domain and have the same model name and kind.
- The base version must be lower than the new version.
- The base must be the highest existing lower version of that model. This creates one linear evolution chain even if numeric versions have gaps.
- A model's first version cannot use `evolves`.
- A version cannot evolve from a projection or another model.
- Duplicate logical versions remain invalid under existing rules.

Example valid history:

```text
Customer@1 full
Customer@3 evolves @1
Customer@7 evolves @3
```

Numeric contiguity is not required; history contiguity is.

Example invalid branching:

```text
Customer@1
├── Customer@2 evolves @1
└── Customer@3 evolves @1   <- reject; previous version is @2
```

Branching can be reconsidered later only with a concrete contract-management use case.

## Model-level metadata and non-field body items

The first slice should solve field duplication without inventing a generic model patch language.

### Access blocks

Treat an `access { ... }` block present in an evolved declaration as a complete replacement of the inherited model-level access block. If omitted, inherit the base access block unchanged.

This mirrors `replace` semantics: explicit and complete rather than patching individual grants in the first version.

### Protobuf reservations

Reservations are version-local today and carry target-evolution meaning. Do **not** blindly inherit reservation blocks through source expansion without verifying current target semantics.

Initial implementation should make the policy explicit:

- preserve current semantic behavior of reservations in normalized versions;
- require authors to declare any reservations that the new version itself must publish;
- add helper tooling/code actions later if copying forward reservations is routinely required;
- do not let delta authoring accidentally erase required wire compatibility state.

A design checkpoint in Slice 1 must settle whether existing reservations are logically cumulative and therefore should be inherited/unioned, or remain explicitly version-local. Use existing Protobuf compatibility fixtures as the authority.

### Model annotations / wire annotations

If a model-level annotation is not repeated in a delta version, inherit it from the base. If model-level annotations are present on the evolved declaration, define them as complete replacement metadata for that annotation target rather than field-level patches.

Before implementation, reconcile this with current model-level `@wire` semantics and golden fixtures so expansion cannot silently change generated wire contracts.

### Index declarations

Indexes are separate versioned declarations today. Keep them separate. This plan does not add index mutations inside `evolves`.

## Declared intent vs derived compatibility

Delta operations give Modelable explicit author intent, but compatibility remains based on the normalized contract.

For every evolved version, the compiler should be able to compare:

```text
author operation                 normalized compatibility fact
----------------------------------------------------------------
add email?                       added_field email
remove legacyCode                removed_field legacyCode
rename legalName -> displayName  renamed_field legalName -> displayName
replace status: Status@2         type/reference/member changes as applicable
```

The compiler must reject contradictions between the declared model `change_kind` and the normalized compatibility result exactly as it does for full declarations.

Examples:

```mdl
entity Customer @ 2 (additive) evolves @ 1 {
  remove legalName
}
```

must fail because the normalized diff is breaking.

The explicit operation should enrich diagnostics and consequence provenance, but it must not override compatibility facts.

## Interaction with projections

No projection semantics should change.

A projection sourcing:

```mdl
from customer.Customer @ 2 as c
```

sees the fully expanded `Customer @ 2` contract.

`pick`, `omit`, direct mappings, computed mappings, joins, property-dependency analysis, compatibility impact, and lineage must not need to know whether the source version was authored as a full declaration or a delta.

This is an important acceptance invariant: **delta source syntax must be observationally invisible to projection resolution after normalization.**

## Interaction with named enums, semantic types, values, and refs

`replace` and `add` use ordinary field declarations, so they naturally support:

- primitive and collection types;
- semantic types;
- named enums and enum projections once implemented;
- `value` models;
- `ref<>` references;
- objects and unions.

Do not add special delta operations for nested type contents. If a field's type changes, replace the field declaration or evolve the referenced first-class type separately.

This keeps ownership clear:

```text
same model over time                  -> evolves delta
same structured value reused          -> value model
same scalar meaning reused             -> semantic type
same closed set reused                 -> named enum
consumer-specific record shape         -> projection
consumer-specific enum subset          -> enum projection
unrelated similar-looking structures   -> remain separate
```

## Interaction with imports and external formats

Importers should continue generating complete versions initially.

Reasons:

- external schemas describe snapshots, not Modelable author intent;
- guessing whether a change was `rename` vs remove+add is unsafe;
- imported version history may be incomplete;
- full declarations remain the simplest lossless representation.

A later explicit refactoring command may convert a verified sequence of complete Modelable versions into delta authoring form while proving normalized equivalence.

## Formatting and language tooling

Delta syntax is an authoring feature and therefore needs first-class tooling.

- formatter preserves `evolves @ N` and operation order;
- syntax highlighting recognizes `evolves`, `add`, `remove`, `rename`, and `replace`;
- completion after `remove`/`rename` lists fields available at that operation point;
- completion after `replace` suggests current field names/types;
- hover on `evolves @ N` shows the resolved base signature and field count;
- hover on inherited fields may indicate origin version;
- definition on the base version navigates to its declaration;
- rename-symbol operations must distinguish DSL operation names from model field renames;
- diagnostics should point to the delta operation, not merely the post-expansion synthetic field.

The source mapper should preserve enough provenance from expanded fields to original declarations/operations for useful diagnostics and LSP navigation.

## CLI/refactoring opportunities

Not required for the first parser slice, but design the source provenance so these can be added cleanly:

```bash
modelable compact-versions customer.Customer
modelable expand-version customer.Customer@3
```

Potential behavior:

- `compact-versions` computes consecutive normalized diffs and proposes equivalent `evolves` operations for review;
- only emit `rename` when Modelable has explicit rename evidence, never heuristic name similarity;
- otherwise represent ambiguous rename-like changes as `remove` + `add`;
- `expand-version` renders the canonical full version for review/debugging;
- both commands must prove normalized signature equivalence before applying edits.

LSP code actions can expose the same transformations later.

## Slice 0 — lock the normalization invariants

Before grammar changes, add tests around the current complete-version pipeline that define what delta expansion must preserve.

- [ ] Add a fixture containing two complete versions with additive, breaking, governance, constraint, default, enum/ref, and wire changes.
- [ ] Record the normalized `ModelVersion` dumps and canonical signatures used by compatibility/registry services.
- [ ] Record representative projection resolution and target outputs for the latest version.
- [ ] Add a helper assertion that two workspaces with equivalent normalized versions produce identical canonical signatures and semantic diffs.
- [ ] Identify the exact compiler stage after parsing and before semantic validation where model-version expansion will become mandatory.
- [ ] Document which current services consume parser IR directly and must be moved behind the normalized-workspace boundary if any bypass exists.

Acceptance:

- the repository has an executable definition of "equivalent full contract";
- no implementation slice can accidentally make author syntax participate in canonical identity.

## Slice 1 — define source IR and field-delta expansion

- [ ] Extend grammar with `evolves @ INT` on model declarations.
- [ ] Add source IR for `add`, `remove`, `rename`, and `replace` operations.
- [ ] Implement deterministic exact-base resolution for the same domain/model/kind.
- [ ] Enforce the linear-history rule.
- [ ] Expand the base via a deep immutable copy before applying operations.
- [ ] Apply operations sequentially with precise source-location diagnostics.
- [ ] Preserve field ordering: inherited order remains stable, renamed/replaced fields stay in place, added fields append in operation order.
- [ ] Emit a complete normalized `ModelVersion` using the existing canonical field structures.
- [ ] Reject duplicate/unknown fields and invalid operation sequences before ordinary semantic validation.
- [ ] Preserve source provenance from every expanded field to either the inherited original field or the delta operation that last modified it.
- [ ] Resolve and test access-block, model-annotation, wire-annotation, and Protobuf-reservation inheritance/replacement policy before declaring the slice complete.

Acceptance:

- a delta-authored version and equivalent full version normalize to identical complete model contracts;
- existing full-only workspaces parse and normalize unchanged;
- downstream services cannot observe an unexpanded model version.

## Slice 2 — connect semantic validation and compatibility intent

- [ ] Run existing model-kind/key/field/type/annotation/constraint/default validation on the expanded full version.
- [ ] Keep `compare_model_versions()` operating on complete `ModelVersion`s rather than teaching it delta syntax.
- [ ] Feed explicit `rename` provenance into compatibility so a declared rename does not rely on deprecation-name inference alone.
- [ ] Verify normalized changes agree with declared `(additive)` / `(breaking)`.
- [ ] Add diagnostics that show both the author operation and the derived breaking consequence when they conflict.
- [ ] Ensure `replace` is classified from actual old/new field shape, not from the operation name.
- [ ] Preserve source-vs-target compatibility axes and storage/governance consequences.
- [ ] Ensure removing/replacing keys produces both identity and model-validity diagnostics as appropriate without duplicate confusing messages.

Acceptance:

- compatibility output is identical for equivalent full and delta-authored versions except for optional richer provenance text;
- author intent cannot override a compiler-derived compatibility fact.

## Slice 3 — make canonical signatures, registry, and snapshots syntax-independent

- [ ] Compute version signatures exclusively from expanded complete versions.
- [ ] Prove full and delta-authored equivalent versions produce identical signatures.
- [ ] Store complete normalized model objects in registry snapshots, not unresolved delta chains.
- [ ] Preserve source authoring form separately only where source packages intentionally retain `.mdl` text.
- [ ] Ensure historical registry snapshots compile without needing the base version's source file when the full normalized object is available.
- [ ] Reject same logical model version with different normalized content exactly as today.
- [ ] Add delta provenance to optional diagnostics/metadata without including non-semantic source formatting in canonical signatures.

Acceptance:

- offline reproducibility remains unchanged;
- a registry consumer never has to execute source delta operations to understand a published model version.

## Slice 4 — prove projections, dependency graph, and impact transparency

- [ ] Source projections from delta-authored models through the ordinary resolver.
- [ ] Exercise `pick`, `omit`, direct fields, computed fields, joins, filters, and grouping against expanded versions.
- [ ] Verify property dependency graph entries are byte-for-byte/logically identical between equivalent full and delta-authored sources.
- [ ] Verify projection compatibility and impact reports are identical.
- [ ] Exercise projection-of-projection chains where the root model uses delta authoring.
- [ ] Ensure hover/lineage can optionally report that a field was inherited/added/renamed in a particular version without changing canonical lineage identity.

Acceptance:

- no projection/planner/dependency module branches on delta syntax;
- all existing model-source behaviors operate on the expanded contract.

## Slice 5 — prove all emitters are syntax-independent

Use one fixture compiled in both forms: complete versions and equivalent `evolves` versions.

- [ ] Enumerate every implemented code-generation target.
- [ ] Generate all targets from both fixture forms.
- [ ] Compare canonical/generated artifacts and require equality except for artifacts that intentionally embed raw source snippets or source-location metadata.
- [ ] For any intentional difference, document why it is non-semantic and exclude it narrowly rather than weakening the equality test.
- [ ] Run existing language/compiler smoke tests against the delta-authored fixture.
- [ ] Cover Protobuf field numbering/reservations, OpenAPI/JSON Schema requiredness, Rust/TS/Python/etc. generated field shapes, SQL storage mappings, metadata/data-contract targets, and manifests.

Acceptance:

- emitters do not know or care whether a model version was authored as a delta;
- generated consumer contracts remain deterministic.

## Slice 6 — formatter, LSP, diagnostics, and editor support

- [ ] Round-trip full and evolved model declarations without expanding source text.
- [ ] Add syntax highlighting and completion for delta operations.
- [ ] Add base-version definition navigation and hover.
- [ ] Add operation-aware field completion based on the intermediate expansion state.
- [ ] Map semantic/compatibility errors back to the responsible operation or inherited field source.
- [ ] Make references/rename tooling aware of field names mentioned by `remove`, `rename`, and `replace`.
- [ ] Update browser/Playground parser and language-service conformance tests.
- [ ] Add source maps/provenance only once in the normalization layer; do not re-derive evolution lineage independently in each language service.

Acceptance:

- delta authoring is no worse than full declarations for editor feedback;
- diagnostics never expose synthetic expanded locations as if they were authored text.

## Slice 7 — migration/refactoring tooling

Deliver only after the language feature is stable.

- [ ] Add a compiler-owned diff-to-delta representation for consecutive versions.
- [ ] Add an `expand` rendering mode that shows a delta-authored version as a complete declaration.
- [ ] Add a safe compact/refactor action that converts selected consecutive full versions to deltas.
- [ ] Generate `rename` only from explicit existing rename/deprecation evidence; ambiguous cases remain remove+add.
- [ ] Before applying a compact refactor, normalize both forms and assert identical signatures for every affected version.
- [ ] Preserve comments/documentation where possible; if comments cannot be mapped safely, abort or require review rather than deleting them silently.
- [ ] Add a lint suggestion for highly repetitive consecutive full versions, but never force compact syntax.

Acceptance:

- existing workspaces can adopt the feature without manual large-scale rewriting;
- refactoring changes source ergonomics, not canonical contracts.

## Feature qualification scenario

Create one compact model history that exercises the whole feature:

```text
Customer@1 full
Customer@2 additive delta
Customer@3 breaking delta
Customer@5 full reset
Customer@8 additive delta from @5
```

Include:

- an entity key;
- optional and required additions;
- `@pii` / classification metadata;
- field constraints and defaults;
- semantic/named-enum/ref/value fields;
- one rename;
- one remove;
- one type/reference replacement;
- model-level wire metadata;
- access policy;
- Protobuf reservation behavior according to the Slice 1 decision;
- an index declaration outside the model;
- direct and computed projections;
- `pick` / `omit` projections;
- a generated API/event/storage surface.

The fixture must prove:

- [ ] each evolved source version expands to the expected complete `ModelVersion`;
- [ ] equivalent full-source fixture versions have identical canonical signatures;
- [ ] compatibility findings match between source forms;
- [ ] declared rename provenance is preserved;
- [ ] projections and dependency/impact graphs match;
- [ ] all implemented targets generate equivalent artifacts;
- [ ] registry snapshot/offline compile does not need unresolved authoring deltas;
- [ ] invalid additive declarations with breaking operations are rejected;
- [ ] invalid branching/missing-base/wrong-kind operation histories are rejected;
- [ ] formatter/LSP preserve the concise source form.

## Documentation updates

Update together with implementation:

- `docs/language-reference.md`
- generated `docs/grammar.md`
- `docs/compiler-reference.md`
- `docs/architecture.md`
- `docs/cli-reference.md` when expansion/refactoring commands land
- capabilities manifest/documentation
- getting-started examples
- representative samples

The language reference should clearly distinguish:

```text
full declaration   complete authored immutable version
evolved declaration concise authored delta over an exact previous version
normalized version complete immutable semantic contract used by the compiler
projection         consumer-specific derived shape with field lineage
value              reusable structured domain value
```

## Implementation order

1. Slice 0: freeze normalization equivalence invariants.
2. Slice 1: grammar/source IR and deterministic expansion.
3. Slice 2: semantic validation + compatibility provenance.
4. Slice 3: signatures/registry/offline snapshot guarantees.
5. Slice 4: projections/dependency/impact transparency.
6. Slice 5: all-target generation equivalence.
7. Slice 6: formatter/LSP/editor support.
8. Slice 7: optional migration/refactoring tooling.
9. Update language/docs/capabilities and run complete feature qualification.

Slices 0-6 are the actual language capability. Slice 7 is adoption tooling and may land later.

## Non-goals

- Cross-model inheritance such as `entity Customer extends Person`.
- Mixins, traits, multiple inheritance, or reusable field bundles.
- Making one entity subtype-compatible with another entity.
- Generic arbitrary AST patch syntax.
- Partial field mutation syntax such as `set optional` or `remove @pii` in the first version.
- Inferring renames from spelling similarity.
- Allowing version ranges or `latest` as an evolution base.
- Branching model histories in the first version.
- Storing unresolved delta chains as the canonical registry contract.
- Changing projection semantics or using deltas to replace projections.
- Automatically converting imported external schema histories into inferred deltas.

## Completion gate

The work is complete when a developer can evolve a model without restating unchanged fields while every compiler-owned semantic consumer still sees the same immutable complete versions it sees today.

Specifically:

- ordinary additive changes can be authored with small explicit deltas;
- full declarations remain valid and equivalent;
- bases are exact and histories deterministic;
- `add/remove/rename/replace` have precise validation and provenance;
- normalized versions are complete before semantic validation;
- canonical signatures are syntax-independent;
- registry snapshots remain self-contained and offline-reproducible;
- compatibility remains derived from complete old/new contracts;
- projections, dependency graphs, impact analysis, and emitters are unaware of delta syntax;
- language tooling provides useful source-local diagnostics;
- Modelable avoids introducing inheritance merely to reduce repetition.
