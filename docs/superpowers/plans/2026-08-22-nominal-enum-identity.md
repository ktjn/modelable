# Nominal Enum Identity and Safety Delivery Plan

This plan addresses the current enum safety and duplication problems in Modelable. The existing language treats `enum(...)` as an anonymous structural field type. That is convenient locally, but it means enum identity is reconstructed independently by emitters and can be inferred from member shape rather than domain meaning.

The immediate correctness issue is the Rust emitter's cross-enum conversion registry: enums with identical raw member sets are grouped through `frozenset(raw_variants)` and receive generated `From<SourceEnum> for TargetEnum` implementations. Two unrelated enum concepts with the same members can therefore become implicitly convertible. This plan removes that behavior first, then introduces first-class nominal enum declarations without removing inline enums.

The guiding rule is:

> Same members do not imply the same type.

## Current baseline

- `enum(a, b, c)` is represented as `EnumType(values: list[str])` with no canonical name, namespace, declaration identity, or member identity.
- Inline enum members are not centrally validated for uniqueness.
- Compatibility currently treats any inline enum shape change as `enum_changed` and therefore breaking.
- TypeScript emits inline string unions.
- Rust emits per-owner nested enum types and currently reconnects equal member sets structurally.
- Protobuf emits per-field enum declarations and allocates numeric values from declaration order.
- Avro derives enum names from the containing field path.
- JSON/OpenAPI/schema-oriented targets represent enum values structurally rather than through one shared canonical declaration.
- Semantic types are nominal scalar aliases, but several emitters flatten them to their underlying representation. They are not a sufficient replacement for a dedicated enum concept.
- `value` models remain separate reusable structured value objects and should not be overloaded to represent enums.
- Existing projections are record/field-oriented; they do not currently project enum members or preserve enum subset lineage.

## Accepted direction

1. Keep `enum(...)` as an anonymous local enum for small one-off field types.
2. Add a first-class domain-owned `enum` declaration with nominal identity.
3. Add a distinct canonical enum reference in the IR. Do not identify a named enum by copying its member list into a field.
4. Do not infer enum equivalence from matching member names, order, values, generated target names, or wire representation.
5. Version named enums independently and make published references reproducible. A named enum reference must resolve to an exact enum version in normalized compiler state.
6. Allow a concise same-domain source form while retaining an explicit versioned form for published contracts. Bare/floating references may be accepted during authoring but must produce a diagnostic and resolve to an exact version before compatibility, registry, signature, or emission stages.
7. Keep semantic types and value models orthogonal to enums. A semantic type may eventually wrap or reference an enum if a concrete use case appears, but enum identity must not depend on semantic-type flattening.
8. Preserve canonical enum identity across model fields, projections, registry snapshots, compatibility analysis, impact analysis, and all emitters.
9. Protobuf member numbers become stable allocation metadata. Reordering source members must never renumber an already published member.
10. Existing inline enums remain source-compatible with the language. Migration to named enums is incremental.
11. Support explicit enum projections that derive a nominal enum from another named enum while preserving source lineage. Subset membership must be declared, never inferred from matching values.
12. Prefer `pick(...)` for published enum projections because it explicitly fixes the resulting contract. Allow `omit(...)` as convenience syntax, but treat it as more evolution-sensitive when the source version changes.
13. A derived enum projection is a distinct type from its source. Conversion from projection to source is total; conversion from source to projection is partial and must be checked.

## Proposed language shape

Preferred declaration form:

```mdl
domain customer {
  enum CustomerStatus @ 1 (additive) {
    active
    blocked
    deleted
  }

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    status: CustomerStatus @ 1
  }
}
```

Cross-domain reference:

```mdl
status: customer.CustomerStatus @ 1
```

Inline enums remain valid:

```mdl
sortDirection: enum(asc, desc)
```

Enum subsets are explicit projections with their own identity:

```mdl
enum OrderStatus @ 1 {
  draft
  submitted
  approved
  rejected
  cancelled
  deleted
}

enum projection PublicOrderStatus @ 1
  from OrderStatus @ 1
  pick(submitted, approved, rejected, cancelled)
```

Equivalent convenience form using exclusion:

```mdl
enum projection PublicOrderStatus @ 1
  from OrderStatus @ 1
  omit(draft, deleted)
```

For published contracts, `pick(...)` is preferred. It describes the complete resulting contract explicitly. `omit(...)` means "all source members except these" and therefore requires more care when rebasing the projection onto a newer source enum version.

The exact parser syntax may be adjusted if `NamedType @ version` or `enum projection` creates grammar ambiguity, but the semantic requirements are fixed: named enum references and enum projection sources must carry declaration identity and resolve reproducibly to concrete versions.

## Enum projection semantics

An enum projection is a derived nominal contract entity, not an alias and not a copied anonymous enum.

```text
OrderStatus != PublicOrderStatus
```

The compiler must retain lineage:

```text
OrderStatus @ 1
   └── PublicOrderStatus @ 1
```

This lineage is the only basis for generated conversions. Matching member sets alone are never sufficient.

### Membership

- `pick(a, b, c)` declares the complete member set of the projection.
- `omit(a, b)` derives the projection from all members of the exact referenced source version except the omitted members.
- Every selected/omitted member must exist in the exact source enum version.
- A projection must contain at least one member.
- Projection members retain canonical source-member identity and wire metadata unless an explicit future transformation feature defines otherwise.
- Member order should not define semantic identity.
- A projection cannot introduce a member that does not exist in its source enum. New values require a new enum declaration or a later explicit enum-transformation feature.

### Conversion rules

Because the projected member set is a subset of the source member set:

```text
PublicOrderStatus -> OrderStatus
```

is total. Modelable may generate an unconditional conversion such as Rust `From<PublicOrderStatus> for OrderStatus`.

The reverse direction:

```text
OrderStatus -> PublicOrderStatus
```

is partial. Values such as `draft` or `deleted` may not be representable. Modelable must generate a checked conversion such as Rust `TryFrom`, a TypeScript validator/type guard, or the target's equivalent. It must never generate an unconditional `From` merely because the members overlap.

Projection-to-projection conversion is generated only when lineage proves the conversion total or when the target API expresses a checked partial conversion. Structural member equality alone never creates a conversion edge.

### Evolution behavior

Enum projections participate in compatibility through both their own version and their source lineage.

- Adding a member to a source enum does not mutate a projection pinned to the previous source version.
- Rebasing a `pick(...)` projection to a newer source version preserves the same projected contract unless the pick list changes or selected source-member semantics change.
- Rebasing an `omit(...)` projection to a newer source version can implicitly include newly added source members. Compatibility analysis must surface these additions explicitly.
- Removing or renaming a source member used by a projection is a breaking consequence for that projection.
- Changing the projection subset is analyzed as member-level enum evolution on the projection itself.
- Two projections from the same source with identical subsets remain distinct nominal types unless one explicitly references or derives from the other.

## Canonical IR

Introduce declaration-level enum identity instead of extending `EnumType` with optional names.

Suggested shape:

```text
EnumDecl
  name
  version
  change_kind
  members[]
  annotations[]

EnumMember
  name
  wire metadata
  protobuf_number?

EnumRefType
  target
  version

EnumProjectionDecl
  name
  version
  source: EnumRef
  selection: Pick | Omit
  members[]        # normalized exact resolved subset

EnumType
  values[]
```

`EnumType` remains anonymous and structural. `EnumRefType` is nominal. Emitters and compatibility code must not silently resolve `EnumRefType` into an anonymous `EnumType` and lose the declaration identity.

`EnumProjectionDecl` is also nominal. Its normalized representation contains the exact resolved source enum version and exact resulting member identities so snapshots remain deterministic even when authoring syntax uses `omit(...)`.

`DomainDef` owns named enum declarations and enum projections in the same way it owns models, projections, and semantic declarations. Registry normalization must include the qualified enum identity, exact version, canonical members, projection lineage, and allocation metadata needed for deterministic target generation.

## Slice 0 — remove the current unsafe structural conversion

This slice is independent of the new language feature and should land first.

- [ ] Delete the Rust `_append_cross_enum_from_impls()` behavior that groups enum types by `frozenset(raw_variants)`.
- [ ] Generate enum conversions only from explicit projection lineage. A direct mapping from `source.status` to a projection field may generate a conversion between those two concrete generated enum types if required by the current anonymous-enum representation.
- [ ] Never generate a conversion merely because two enums have the same members.
- [ ] Add a regression fixture with two unrelated enums sharing the same member set and prove no cross-conversion is emitted.
- [ ] Add a projection fixture proving a direct mapping still generates or reuses the required safe conversion.
- [ ] Keep conversion generation deterministic and local to the source/target relationship so this temporary mechanism can be deleted once named enums are shared directly.

Acceptance:

- unrelated equal-shaped enums cannot be converted implicitly;
- current direct enum projections still compile;
- no global shape-based enum registry remains.

## Slice 1 — harden anonymous enums

- [ ] Add central validation that `EnumType.values` is non-empty and contains no duplicate canonical members.
- [ ] Reject duplicate enum members before emitters run.
- [ ] Add a shared target-name collision validation helper so distinct canonical members that normalize to the same Rust, Protobuf, Avro, or other target identifier fail with a precise diagnostic.
- [ ] Validate `@wire(...case...)` and override mappings for duplicate resulting wire values.
- [ ] Add fixtures for case-folding, punctuation/underscore normalization, numeric-leading members, explicit wire overrides, and duplicate wire values.
- [ ] Keep target-specific escaping separate from canonical member identity.

Acceptance:

- every accepted anonymous enum has unique canonical members;
- every generated enum has unique target identifiers and wire values for the selected target;
- target collision errors point to the enum field and conflicting members.

## Slice 2 — add named enum declarations, projections, and resolution

- [ ] Extend the grammar with domain-level `enum` declarations and version/change-kind headers.
- [ ] Add explicit enum projection syntax, preferably `enum projection Name @ version from Enum @ version pick(...)` / `omit(...)`.
- [ ] Add `EnumDecl`, `EnumMember`, `EnumRefType`, and `EnumProjectionDecl` to the parser IR.
- [ ] Add `DomainDef.enums` / enum projections and deterministic declaration ordering.
- [ ] Add same-domain and qualified enum reference resolution.
- [ ] Resolve enum projection sources to exact enum declaration versions.
- [ ] Normalize `pick` and `omit` into an exact ordered-independent member-identity subset while retaining the author's selection form for diagnostics/rendering where useful.
- [ ] Validate that all selected/omitted members exist, that projections are non-empty, and that projections cannot introduce new members.
- [ ] Reject ambiguous bare enum names across domains.
- [ ] Resolve every enum reference to an exact declaration version before normalized compiler services run.
- [ ] Add an `ENUMREF` diagnostic for floating/bare references where exact versioning is required, following the existing `ref<>` version-diagnostic pattern.
- [ ] Add formatter, language-service, Monaco/editor grammar, hover, completion, definition, and rename support for enum declarations, enum members, enum projection sources, and pick/omit members.
- [ ] Keep `enum(...)` parsing unchanged.

Acceptance:

- named enum identity survives parse -> validate -> normalized IR -> render round trips;
- two named enums with identical members remain distinct;
- enum projections preserve exact source lineage and remain distinct nominal types;
- `pick`/`omit` resolve deterministically to the expected subset;
- a consuming model or projection version resolves the same enum version regardless of later declarations added to the workspace.

## Slice 3 — enum compatibility and evolution

Add declaration-level compatibility rather than reducing every change to a consuming field's structural `enum_changed`.

Required findings:

```text
enum_member_added
enum_member_removed
enum_member_renamed
enum_member_wire_value_changed
enum_member_number_changed
enum_reference_changed
enum_version_changed
enum_projection_source_changed
enum_projection_member_added
enum_projection_member_removed
enum_projection_implicit_member_added
```

Rules:

- [ ] Adding a member is additive at the canonical/wire schema level when existing member identities and wire encodings are preserved.
- [ ] Adding a member also emits a consumer consequence for exhaustive-match targets such as Rust and generated closed enums.
- [ ] Removing a member is breaking.
- [ ] Renaming a member is breaking unless an explicit future migration/alias mechanism defines otherwise.
- [ ] Changing a canonical or target wire value is breaking for that target.
- [ ] Changing an already allocated Protobuf member number is forbidden.
- [ ] Reordering source members is non-semantic once stable member allocation exists.
- [ ] Changing a field from one named enum declaration to another is a nominal type change even when their member sets are identical.
- [ ] Bumping a field's enum version is classified from the referenced enum diff instead of as an unconditional unrelated type replacement.
- [ ] Adding/removing a picked projection member is classified as member evolution of the projected enum.
- [ ] Rebasing a `pick` projection reports changes only when selected members or their wire/member identity changed.
- [ ] Rebasing an `omit` projection must explicitly report members implicitly added because they are new in the source and not in the omit list.
- [ ] A source member removal/rename used by an enum projection creates a causal breaking consequence at the projection.
- [ ] Changing an enum projection's source declaration is a nominal source change even if the resulting member set is identical.
- [ ] Preserve existing conservative behavior for anonymous `enum(...)` changes until anonymous-member evolution has a stronger identity mechanism.

Extend `modelable diff`, target compatibility, and `modelable impact` so enum changes expose causal paths to affected enum projections, models, record projections, APIs, generated artifacts, and consumers.

Acceptance:

- enum declaration changes are reported once at the owning declaration and propagated as consequences;
- enum projection consequences retain source lineage;
- equal-shaped enum declarations and projections never collapse into one compatibility identity;
- additive member growth and destructive changes are distinguishable;
- implicit growth from `omit` is never silent.

## Slice 4 — stable member identity and Protobuf numbering

- [ ] Introduce deterministic persistent Protobuf number allocation for named enum members.
- [ ] Reserve `0` for `<ENUM>_UNSPECIFIED` unless the declaration explicitly defines a compatible future policy.
- [ ] Persist member allocations in normalized registry metadata so rebuilding from a snapshot produces byte-for-byte stable `.proto` output.
- [ ] Never derive a published member number from current list position.
- [ ] Preserve numbers across source reordering and member additions.
- [ ] Record removed numbers and generated names as reservations and reject reuse.
- [ ] Define projected enum numbering deterministically. Prefer carrying source-member allocation identity where target constraints allow it; otherwise allocate stable projection-local numbers and persist them independently.
- [ ] Never renumber an existing projected member because the source gained an excluded member.
- [ ] Include enum member allocations in the Protobuf schema manifest/fingerprint inputs where they affect wire compatibility.
- [ ] Add v1/v2/v3 fixtures covering append, reorder, removal, attempted reuse, rename, and subset projection evolution.

Acceptance:

- adding a member cannot renumber existing members;
- reordering source does not change generated Protobuf numbers;
- changing an unrelated/excluded source member does not renumber projected enum members;
- removed numbers cannot be reused silently.

## Slice 5 — preserve nominal identity and lineage in emitters

Named enums and enum projections must be emitted once per canonical declaration/version where the target supports named declarations. Anonymous enums retain their current local behavior.

### Rust

- [ ] Emit one Rust enum type per named Modelable enum declaration/version and enum projection/version.
- [ ] Import/reuse that type from models and record projections instead of regenerating nested copies.
- [ ] Generate `From<ProjectedEnum> for SourceEnum` when lineage proves the conversion total.
- [ ] Generate `TryFrom<SourceEnum> for ProjectedEnum` for proper subsets; never generate unconditional reverse conversion.
- [ ] Generate projection-to-projection conversions only from proven subset/lineage relationships.
- [ ] Remove the temporary lineage-specific anonymous-enum conversion once named enum projections share explicit types.
- [ ] Preserve serde rename/case/override behavior without changing Rust nominal identity.

### TypeScript

- [ ] Emit one reusable declaration per named enum and enum projection.
- [ ] Prefer a `const` object plus value type, or another representation that preserves one canonical declaration and useful runtime values.
- [ ] Generate safe source/projection guards or parsers for partial conversions rather than unsafe casts.
- [ ] Decide separately whether optional branding is justified; do not claim TypeScript structural aliases are nominally safe if branding is not used.
- [ ] Models and projections import the shared enum type rather than repeating string unions.

### Protobuf/gRPC

- [ ] Emit one stable enum declaration per named enum/projection version with allocated numeric values.
- [ ] Reference the shared enum from all consuming messages.
- [ ] Preserve qualified package identity across domains.
- [ ] Ensure projected enum numbering remains stable independently of excluded source members.

### Avro

- [ ] Emit/reuse a stable Avro named enum using the canonical qualified identity instead of deriving names from field paths.
- [ ] Emit enum projections as their own named Avro enum types while retaining source lineage in Modelable metadata.
- [ ] Ensure repeated references use Avro named-type references rather than duplicate declarations.

### JSON Schema/OpenAPI/AsyncAPI

- [ ] Represent named enums and enum projections through shared schema components/definitions and `$ref` where the format supports it.
- [ ] Preserve anonymous inline enums as inline schemas.
- [ ] Include source lineage in Modelable-owned manifest/extension metadata where target schemas cannot express it natively.

### SQL/storage targets

- [ ] Keep storage representation target-driven, but carry enum identity in schema metadata and diagnostics even when the physical column remains text/string.
- [ ] Ensure ClickHouse/Postgres mappings do not infer compatibility solely from physical storage type.
- [ ] Treat source and projected enums as distinct logical types even when they use the same physical representation.

### Documentation/data-contract targets

- [ ] ODCS, Markdown, OpenMetadata, dbt, OpenLineage, and other metadata emitters must expose the qualified enum declaration/version and enum projection source lineage where useful instead of only the member list.

Acceptance:

- a named enum or enum projection is generated once and reused across model/projection boundaries for each target that supports named types;
- generators never create implicit conversions between unrelated named enums;
- subset conversions follow total/partial conversion rules;
- canonical enum identity and projection lineage are visible in generated manifests/metadata.

## Slice 6 — registry, signatures, imports, and offline snapshots

- [ ] Include named enum declarations and enum projection declarations in canonical workspace normalization and content signatures.
- [ ] Include exact enum dependencies and projection-source edges in registry usage graphs and snapshot objects.
- [ ] Store the normalized exact member subset for enum projections so `omit(...)` does not depend on whatever source version happens to be latest during rebuild.
- [ ] Make imported domain snapshots resolve enum declarations and enum projections without requiring original editable source files.
- [ ] Reject same enum or enum-projection logical version with different canonical content under the existing immutable-version rule.
- [ ] Add enum and enum-projection dependency edges to impact/consequence traversal.
- [ ] Include named enum references and enum projections in RAG/context indexes and compiler capability metadata where model/type declarations are enumerated.
- [ ] Preserve offline reproducibility: resolving and compiling a historical snapshot must reproduce the same enum identity, members, projection lineage, wire metadata, and Protobuf numbers.

Acceptance:

- enum declarations and enum projections behave like other published contract entities in local snapshots;
- registry rebuilds never depend on emitter-specific inferred enum names or current source-enum state;
- usage and impact reports can identify exactly which enum declaration or enum projection caused a consequence.

## Slice 7 — migration and duplicate discovery

Do not automatically merge equal-shaped enums. Equal values are insufficient evidence that two domain concepts are the same.

- [ ] Add a lint/analysis finding for repeated anonymous enum shapes, including all locations but making no automatic semantic-equivalence claim.
- [ ] Suggest extraction only when the developer explicitly chooses a canonical enum name/domain.
- [ ] When several duplicated enums are intentional subsets of a wider concept, allow the refactoring flow to create a canonical enum plus explicit enum projections rather than several independent named enums.
- [ ] Add a safe refactoring command or LSP code action that:
  1. creates a named enum declaration;
  2. optionally creates selected enum projections for intentional subsets;
  3. replaces selected occurrences with references to the declaration/projection;
  4. preserves wire metadata;
  5. validates all affected target outputs before applying the change.
- [ ] Allow the user to select a subset of equal-shaped occurrences. Do not force unrelated concepts together.
- [ ] Keep old inline enums valid indefinitely unless a later major language revision deliberately removes them.

Acceptance:

- duplicated anonymous enums become discoverable;
- migration requires an explicit semantic choice;
- intentional subsets can be represented by lineage rather than duplication;
- no heuristic deduplication changes type identity automatically.

## Feature qualification

Add one compact scenario that exercises enum identity and subset lineage through the complete product surface.

The fixture should include:

- `AccountStatus @ 1` and `PaymentStatus @ 1` with identical members;
- one entity using each enum;
- one record projection directly mapping `AccountStatus`;
- `PublicAccountStatus @ 1` as an enum projection using `pick(...)`;
- a second enum projection using `omit(...)` to exercise source-version rebasing behavior;
- an anonymous `enum(asc, desc)` field;
- an enum v2 with one additive member;
- an enum v3 with a breaking member removal;
- one cross-domain enum reference;
- one member spelling pair that would collide after a target normalization if collision checks were absent.

The fixture must prove:

- [ ] the two equal-shaped named enums remain distinct in canonical IR and generated code;
- [ ] no Rust `From<AccountStatus> for PaymentStatus` or equivalent conversion exists;
- [ ] the direct record projection reuses or explicitly converts only the correct source enum;
- [ ] `PublicAccountStatus -> AccountStatus` is generated as a total safe conversion;
- [ ] `AccountStatus -> PublicAccountStatus` is generated only as a checked/partial conversion;
- [ ] enum projection lineage and exact subset survive registry snapshot -> offline compile;
- [ ] a `pick` projection does not silently grow when its source gains an unselected member;
- [ ] an `omit` projection rebase reports implicitly included new source members;
- [ ] TypeScript, Rust, Protobuf, Avro, JSON Schema/OpenAPI, and all implemented metadata targets preserve the expected enum identity;
- [ ] Protobuf numbers remain stable across additive growth, reorder, and projected subset changes;
- [ ] additive member growth produces an exhaustive-consumer consequence without being confused with enum replacement;
- [ ] removal is reported as breaking before candidate registry replacement;
- [ ] registry snapshot -> offline compile reproduces identical enum artifacts and signatures.

Reuse the existing codegen target enumeration and smoke-test infrastructure rather than building an enum-specific duplicate matrix.

## Documentation updates

Update together with the relevant slices:

- `docs/language-reference.md`
- `docs/grammar.md`
- `docs/compiler-reference.md`
- `docs/wire-format-contract.md`
- `docs/architecture.md`
- `docs/cli-reference.md`
- capability documentation/manifests
- representative samples

Document the distinction explicitly:

```text
anonymous enum     local structural closed set
named enum         domain-owned nominal contract entity
enum projection    nominal derived subset with explicit source lineage
semantic type      nominal alias/value over another type
value model        reusable structured value object
```

Document conversion behavior explicitly:

```text
projected subset -> source enum     total
source enum -> projected subset     partial / checked
unrelated equal-shaped enums        no conversion inferred
```

## Implementation order

1. Slice 0: remove unsafe structural conversion.
2. Slice 1: harden anonymous enums.
3. Slice 2: named enum and enum-projection grammar, IR, resolution, and subset validation.
4. Slice 3: declaration/projection-level compatibility and consequences.
5. Slice 4: stable Protobuf member allocation for source and projected enums.
6. Slice 5: emitter migration and lineage-driven conversions.
7. Slice 6: registry/signature/offline integration including projection edges.
8. Slice 7: duplicate discovery and migration tooling.
9. Run the complete feature qualification and update docs/capabilities.

Slices 0 and 1 are safety fixes and should not wait for the language redesign. Slices 2-6 form the first-class enum capability, including subset projections, and should be treated as one architectural capability even if delivered incrementally.

## Non-goals

- Automatically merging enums because their members match.
- Automatically treating one enum as a projection of another because its values happen to be a subset.
- Replacing `value` models with enums or vice versa.
- Reusing semantic-type flattening as the enum identity mechanism.
- Inferring domain semantics from field names.
- Allowing enum projections to invent arbitrary new values in the first implementation.
- Making storage representation define logical enum compatibility.
- Designing a general arbitrary-language migration framework in this slice.

## Completion gate

The enum work is complete when Modelable owns enum identity and enum lineage end-to-end and target generators no longer have to infer either. Specifically:

- unrelated equal-shaped enums cannot mix;
- named enums are reusable domain entities with reproducible versions;
- anonymous enums remain safe local types;
- enum projections can explicitly select subsets while preserving source lineage;
- total and partial conversions are generated according to proven lineage rather than shape;
- record projections preserve source enum identity;
- compatibility reports member-level and projection-level evolution;
- `pick` projections do not silently grow and `omit` growth is surfaced explicitly;
- Protobuf numbers are stable for both source and projected enums;
- registry snapshots preserve enum contracts and projection lineage offline;
- all implemented generators either preserve nominal enum identity or explicitly document target-level structural loss without changing canonical Modelable identity.