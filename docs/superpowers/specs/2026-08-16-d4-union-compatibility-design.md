# D4 Discriminated Union Compatibility Design

**Status:** Implemented in the current D4 follow-up slice

## Context

PR #384 added the discriminated-union grammar, IR, schema emission, and
round-trip import. Model versions still compare a changed union as one opaque
`type_changed` finding, so consumers cannot tell whether a discriminator or a
specific variant changed.

## Decision

When both field types are discriminated unions:

- a discriminator rename is reported as `union_discriminator_changed`;
- a newly introduced variant is reported as `union_variant_added`;
- a removed variant is reported as `union_variant_removed`;
- a changed common variant type is reported as `union_variant_changed`.

Variant findings use `field.variant` in their human-readable subject by
encoding the stable path as `fieldName.variantTag`; existing compatibility DTOs
therefore remain wire-compatible. All union-specific changes are breaking for
the current conservative source-compatibility classifier: consumers may be
exhaustive, and a discriminator or variant-shape change cannot be proven safe
without direction-specific request/response semantics.

If a union changes to a non-union type, the existing `type_changed` finding is
retained. If two non-union types change, behavior is unchanged.

## Consequences

- `modelable diff` and browser compatibility results expose the actual union
  evolution rather than only an opaque shape change.
- Existing clients that only understand `type_changed` continue to receive
  compatible dataclass/DTO fields and can treat the new findings as breaking.
- Direction-aware compatibility policy can later refine variant additions once
  request/response semantics are available.
