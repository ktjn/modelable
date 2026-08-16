# D1 Presence and Nullability Design

**Status:** Implemented — PR #364

## Context

Modelable currently stores only one field bit, `optional`. That bit controls
whether a field may be absent, but it cannot express whether a present value
may be `null`. OpenAPI export therefore cannot distinguish the four useful
contract states:

| Presence | Value | Meaning |
| --- | --- | --- |
| required | non-null | the field must be present and non-null |
| optional | non-null | the field may be absent, but must be non-null when present |
| required | nullable | the field must be present, and may be null |
| optional | nullable | the field may be absent or null |

The existing `field?` syntax is already published Modelable text and must not
change meaning.

## Decision

Keep `?` after a field name as the legacy presence marker:

```mdl
legacyOptional?: string
requiredNonNull: string
requiredNullable: string?
optionalNullable?: string?
```

The marker before the colon controls presence. The marker after the type
controls nullability. This is additive syntax: old files parse exactly as
before, and nullable values are opt-in.

The normalized IR adds `FieldDef.nullable: bool = False`. `optional` and
`nullable` are independent booleans. The same pair is used for fields nested
inside object types. D1 does not make array elements, map keys, or map values
nullable; those are type-level extensions that require an explicit follow-up
design rather than inheriting field syntax accidentally.

### Compatibility

Compatibility reports use separate findings:

- `presence_changed`: optional/required changed;
- `nullability_changed`: nullable/non-null changed.

The existing optionality compatibility rule remains the presence rule: adding
a required field or changing optional to required is breaking. Changing
non-null to nullable is source-compatible; changing nullable to non-null is
breaking. A field can produce both findings when both bits change in one
version. Finding payloads carry `from_optional`/`to_optional` and
`from_nullable`/`to_nullable` so clients do not need to infer either axis from
the other.

### Emitters

Every emitter must declare its D1 behavior. JSON Schema and OpenAPI represent
nullable values with a `null` type branch while using `required` only for
presence. Language emitters use their native nullable representation where
available. Targets without a faithful distinction must emit a loss diagnostic;
they must not silently turn required-nullable into optional-non-null.

### Round-trip and governance

The formatter emits both markers when present, preserving the canonical form
`name?: type?`. Graph export, registry records, compatibility DTOs, and
language hover output expose both bits. Existing registry rows default
`nullable` to false when read from older databases.

## Consequences

- Existing `.mdl` files retain their meaning byte-for-byte at the semantic
  level.
- OpenAPI export can preserve required-vs-nullable contracts instead of
  collapsing them into optionality.
- Compatibility consumers must handle two independent findings and two
  booleans; the legacy optional fields remain during the migration window.
- D2 constraints can attach to a field without overloading presence or
  nullability, and D4 variants can use the same explicit field-state model.

## Acceptance criteria

1. Existing language-stability fixtures remain unchanged.
2. All four field states parse, format, serialize, and round-trip.
3. Compatibility distinguishes presence and nullability, including a change
   where both bits move.
4. JSON Schema and OpenAPI preserve both axes.
5. Every implemented target has a test for its exact or loss-diagnostic
   behavior.
