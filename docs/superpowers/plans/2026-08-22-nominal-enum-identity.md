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

The exact parser syntax may be adjusted if `NamedType @ version` creates grammar ambiguity, but the semantic requirements are fixed: named enum references must carry declaration identity and resolve reproducibly to a concrete version.

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

EnumType
  values[]
```

`EnumType` remains anonymous and structural. `EnumRefType` is nominal. Emitters and compatibility code must not silently resolve `EnumRefType` into an anonymous `EnumType` and lose the declaration identity.

`DomainDef` owns named enum declarations in the same way it owns models, projections, and semantic declarations. Registry normalization must include the qualified enum identity, exact version, canonical members, and allocation metadata needed for deterministic target generation.

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

## Slice 2 — add named enum declarations and resolution

- [ ] Extend the grammar with domain-level `enum` declarations and version/change-kind headers.
- [ ] Add `EnumDecl`, `EnumMember`, and `EnumRefType` to the parser IR.
- [ ] Add `DomainDef.enums` and deterministic declaration ordering.
- [ ] Add same-domain and qualified enum reference resolution.
- [ ] Reject ambiguous bare enum names across domains.
- [ ] Resolve every enum reference to an exact declaration version before normalized compiler services run.
- [ ] Add an `ENUMREF` diagnostic for floating/bare references where exact versioning is required, following the existing `ref<>` version-diagnostic pattern.
- [ ] Add formatter, language-service, Monaco/editor grammar, hover, completion, definition, and rename support.
- [ ] Keep `enum(...)` parsing unchanged.

Acceptance:

- named enum identity survives parse -> validate -> normalized IR -> render round trips;
- two named enums with identical members remain distinct;
- a consuming model version resolves the same enum version regardless of later declarations added to the workspace.

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
- [ ] Preserve existing conservative behavior for anonymous `enum(...)` changes until anonymous-member evolution has a stronger identity mechanism.

Extend `modelable diff`, target compatibility, and `modelable impact` so enum changes expose causal paths to affected models, projections, APIs, generated artifacts, and consumers.

Acceptance:

- enum declaration changes are reported once at the owning declaration and propagated as consequences;
- equal-shaped enum declarations never collapse into one compatibility identity;
- additive member growth and destructive changes are distinguishable.

## Slice 4 — stable member identity and Protobuf numbering

- [ ] Introduce deterministic persistent Protobuf number allocation for named enum members.
- [ ] Reserve `0` for `<ENUM>_UNSPECIFIED` unless the declaration explicitly defines a compatible future policy.
- [ ] Persist member allocations in normalized registry metadata so rebuilding from a snapshot produces byte-for-byte stable `.proto` output.
- [ ] Never derive a published member number from current list position.
- [ ] Preserve numbers across source reordering and member additions.
- [ ] Record removed numbers and generated names as reservations and reject reuse.
- [ ] Include enum member allocations in the Protobuf schema manifest/fingerprint inputs where they affect wire compatibility.
- [ ] Add v1/v2/v3 fixtures covering append, reorder, removal, attempted reuse, and rename.

Acceptance:

- adding a member cannot renumber existing members;
- reordering source does not change generated Protobuf numbers;
- removed numbers cannot be reused silently.

## Slice 5 — preserve nominal identity in emitters

Named enums must be emitted once per canonical declaration/version where the target supports named declarations. Anonymous enums retain their current local behavior.

### Rust

- [ ] Emit one Rust enum type per named Modelable enum declaration/version.
- [ ] Import/reuse that type from models and projections instead of regenerating nested copies.
- [ ] Remove the temporary lineage-specific anonymous-enum conversion once named enum projections share the same Rust type.
- [ ] Preserve serde rename/case/override behavior without changing Rust nominal identity.

### TypeScript

- [ ] Emit one reusable declaration per named enum.
- [ ] Prefer a `const` object plus value type, or another representation that preserves one canonical declaration and useful runtime values.
- [ ] Decide separately whether optional branding is justified; do not claim TypeScript structural aliases are nominally safe if branding is not used.
- [ ] Models and projections import the shared enum type rather than repeating string unions.

### Protobuf/gRPC

- [ ] Emit one stable enum declaration per named enum version with allocated numeric values.
- [ ] Reference the shared enum from all consuming messages.
- [ ] Preserve qualified package identity across domains.

### Avro

- [ ] Emit/reuse a stable Avro named enum using the canonical qualified identity instead of deriving names from field paths.
- [ ] Ensure repeated references use Avro named-type references rather than duplicate declarations.

### JSON Schema/OpenAPI/AsyncAPI

- [ ] Represent named enums through shared schema components/definitions and `$ref` where the format supports it.
- [ ] Preserve anonymous inline enums as inline schemas.

### SQL/storage targets

- [ ] Keep storage representation target-driven, but carry enum identity in schema metadata and diagnostics even when the physical column remains text/string.
- [ ] Ensure ClickHouse/Postgres mappings do not infer compatibility solely from physical storage type.

### Documentation/data-contract targets

- [ ] ODCS, Markdown, OpenMetadata, dbt, OpenLineage, and other metadata emitters must expose the qualified enum declaration and version where useful instead of only the member list.

Acceptance:

- a named enum is generated once and reused across model/projection boundaries for each target that supports named types;
- generators never create implicit conversions between unrelated named enums;
- canonical enum identity is visible in generated manifests/metadata.

## Slice 6 — registry, signatures, imports, and offline snapshots

- [ ] Include named enum declarations in canonical workspace normalization and content signatures.
- [ ] Include exact enum dependencies in registry usage graphs and snapshot objects.
- [ ] Make imported domain snapshots resolve enum declarations without requiring original editable source files.
- [ ] Reject same enum logical version with different canonical content under the existing immutable-version rule.
- [ ] Add enum dependency edges to impact/consequence traversal.
- [ ] Include named enum references in RAG/context indexes and compiler capability metadata where model/type declarations are enumerated.
- [ ] Preserve offline reproducibility: resolving and compiling a historical snapshot must reproduce the same enum identity, members, wire metadata, and Protobuf numbers.

Acceptance:

- enum declarations behave like other published contract entities in local snapshots;
- registry rebuilds never depend on emitter-specific inferred enum names;
- usage and impact reports can identify exactly which enum declaration caused a consequence.

## Slice 7 — migration and duplicate discovery

Do not automatically merge equal-shaped enums. Equal values are insufficient evidence that two domain concepts are the same.

- [ ] Add a lint/analysis finding for repeated anonymous enum shapes, including all locations but making no automatic semantic-equivalence claim.
- [ ] Suggest extraction only when the developer explicitly chooses a canonical enum name/domain.
- [ ] Add a safe refactoring command or LSP code action that:
  1. creates a named enum declaration;
  2. replaces selected occurrences with references to that declaration;
  3. preserves wire metadata;
  4. validates all affected target outputs before applying the change.
- [ ] Allow the user to select a subset of equal-shaped occurrences. Do not force unrelated concepts together.
- [ ] Keep old inline enums valid indefinitely unless a later major language revision deliberately removes them.

Acceptance:

- duplicated anonymous enums become discoverable;
- migration requires an explicit semantic choice;
- no heuristic deduplication changes type identity automatically.

## Feature qualification

Add one compact scenario that exercises enum identity through the complete product surface.

The fixture should include:

- `AccountStatus @ 1` and `PaymentStatus @ 1` with identical members;
- one entity using each enum;
- one projection directly mapping `AccountStatus`;
- an anonymous `enum(asc, desc)` field;
- an enum v2 with one additive member;
- an enum v3 with a breaking member removal;
- one cross-domain enum reference;
- one member spelling pair that would collide after a target normalization if collision checks were absent.

The fixture must prove:

- [ ] the two equal-shaped named enums remain distinct in canonical IR and generated code;
- [ ] no Rust `From<AccountStatus> for PaymentStatus` or equivalent conversion exists;
- [ ] the direct projection reuses or explicitly converts only the correct source enum;
- [ ] TypeScript, Rust, Protobuf, Avro, JSON Schema/OpenAPI, and all implemented metadata targets preserve the expected enum identity;
- [ ] Protobuf numbers remain stable across additive growth and reorder;
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
anonymous enum    local structural closed set
a named enum      domain-owned nominal contract entity
semantic type     nominal alias/value over another type
value model       reusable structured value object
```

## Implementation order

1. Slice 0: remove unsafe structural conversion.
2. Slice 1: harden anonymous enums.
3. Slice 2: named enum grammar, IR, and resolution.
4. Slice 3: declaration-level compatibility and consequences.
5. Slice 4: stable Protobuf member allocation.
6. Slice 5: emitter migration.
7. Slice 6: registry/signature/offline integration.
8. Slice 7: duplicate discovery and migration tooling.
9. Run the complete feature qualification and update docs/capabilities.

Slices 0 and 1 are safety fixes and should not wait for the language redesign. Slices 2-6 form the first-class enum feature and should be treated as one architectural capability even if delivered incrementally.

## Non-goals

- Automatically merging enums because their members match.
- Replacing `value` models with enums or vice versa.
- Reusing semantic-type flattening as the enum identity mechanism.
- Inferring domain semantics from field names.
- Making storage representation define logical enum compatibility.
- Designing a general arbitrary-language migration framework in this slice.

## Completion gate

The enum work is complete when Modelable owns enum identity end-to-end and target generators no longer have to infer it. Specifically:

- unrelated equal-shaped enums cannot mix;
- named enums are reusable domain entities with reproducible versions;
- anonymous enums remain safe local types;
- projections preserve source enum identity;
- compatibility reports member-level evolution;
- Protobuf numbers are stable;
- registry snapshots preserve enum contracts offline;
- all implemented generators either preserve nominal enum identity or explicitly document target-level structural loss without changing canonical Modelable identity.