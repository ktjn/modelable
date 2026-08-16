# D4 Discriminated Union Compatibility Plan

This slice follows the implemented schema foundation from PR #384.

## Steps

- [x] Compare two `UnionType` values by discriminator, variant tag, and variant
   type signature.
- [x] Emit stable union-specific `FieldChange` kinds while preserving existing
   DTO fields and browser serialization.
- [x] Classify all union-specific changes as breaking in the current conservative
   source-compatibility policy.
- [x] Add model-diff regression tests for discriminator,
   addition, removal, and common-variant shape changes.
- [x] Update the roadmap and language/compiler references, run doc/spec review,
   and execute all four CLI verification gates.

## Deferred follow-up

Target emitters that cannot preserve discriminated unions still need explicit
loss diagnostics or native representations. That is a separate D4 slice after
compatibility semantics land.
