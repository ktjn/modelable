# D1 Presence and Nullability Implementation Plan

This plan implements the design in
`docs/superpowers/specs/2026-08-16-presence-nullability-design.md`.

## Steps

1. Extend parser IR and grammar with `FieldDef.nullable`, parsing the
   post-type `?` while retaining the pre-colon legacy optional marker.
2. Update canonical rendering, language hover, graph export, registry
   persistence/migration, and DTOs to carry both field-state bits.
3. Split compatibility findings into `presence_changed` and
   `nullability_changed`, preserving both old and new payload fields during
   the compatibility DTO migration.
4. Update JSON Schema and OpenAPI mapping to emit `null` branches independently
   from `required`, and add loss diagnostics to targets without faithful support.
5. Add parser, round-trip, compatibility, emitter, registry, and language
   stability fixtures for all four states.
6. Run the full CLI checks, archive this plan and spec in the implementation
   PR, and update the D1 roadmap status only after all acceptance criteria pass.

## Verification order

Run focused parser/compatibility/emitter tests first, then the four commands in
`AGENTS.md` from `cli/`. The full pytest invocation must use
`bash scripts/run-tests.sh`.
