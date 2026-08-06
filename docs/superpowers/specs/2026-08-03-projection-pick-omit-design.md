# Projection Pick/Omit Clauses — Design

**Date:** 2026-08-03

## Status

Implemented (2026-08-06). Outcome recorded in
[docs/correction-and-capability-plan.md](../../correction-and-capability-plan.md#slice-h1--projection-pickomit-clauses).

## Context

Every field in a hand-written `projection` needs an explicit `<-` (direct
mapping) or `=` (computed) line — this is deliberate: it is how Modelable
guarantees complete, traceable lineage
(`docs/language-reference.md:180`, "No field can exist in a projection
without a `<-` or `=`"). That guarantee is correct and should not change.

But it means even a pure "subset of an entity" projection requires listing
every kept field by hand:

```mdl
projection BillingCustomer @ 1
  from customer.Customer @ 2 as c
{
  customerId <- c.customerId
  legalName  <- c.legalName
  email      <- c.email
}
```

`auto projections` already solves a fixed version of this problem: it expands
an entity into four standard projections (`db`, `request`, `reply`, `event`),
with `exclude [fieldName, ...]` and `exclude [@pii]` / `exclude
[@classification("secret")]` as customization (`docs/language-reference.md:
290-370`). But auto projections are entity-wide, fixed to those four kinds,
and explicitly do not support joins, aggregations, or computed fields
(`docs/language-reference.md:402`).

There is no equivalent shorthand for an arbitrary hand-written `projection` —
including ones with joins or computed fields — that just wants "most fields
of X, verbatim." This design adds one, borrowing the shape of TypeScript's
`Pick<T, K>` / `Omit<T, K>` utility types: a compact field-selection clause
that the compiler expands into the same fully explicit form a human would
have typed.

## Goals

- Let a `projection` declaration select (`pick`) or exclude (`omit`) a subset
  of its source fields by name, without hand-writing a `<-` line per field.
- Support qualified `alias.field` selection so this also works on multi-source
  `join` projections, not just single-source ones.
- Support annotation-based filters (`@pii`, `@classification("secret")`) using
  the *exact* grammar `auto projections ... exclude` already has — no second
  filter syntax.
- Expand at compile time into the same IR shape hand-written projections
  produce, so compatibility (Track C1), the shared property-dependency graph
  (Slice A2), lineage, governance, canonical signatures, the formatter, and
  `modelable inspect` need zero special-casing.
- Let the body still add extra computed (`=`) fields alongside picked ones.

## Non-goals (deferred)

These are real TypeScript-inspired follow-ups, explicitly out of scope here:

- **Partial/Required-style bulk optionality flips** (TS `Partial<T>` /
  `Required<T>`). A later slice could add e.g. `pick(...) as optional` for
  PATCH-style update projections.
- **Inline rename while picking** (TS mapped-type `as` remapping), e.g.
  `pick(customerId as id)`. Renaming still requires a hand-written `newName
  <- c.oldName` line in the body.
- **Composing one projection from another** (TS intersection/union of mapped
  types) — building a new projection from the field union/intersection of two
  existing projections.
- **Structural auto-sync**: pick/omit lists are frozen at the fields named (or
  matched by annotation) at compile time. Adding a field to the source entity
  does **not** automatically flow into a projection that used `pick`/`omit` —
  this is boilerplate reduction, not implicit drift-following, matching the
  explicit-lineage principle this design preserves.

## Architecture

Add an optional clause to the `projection` grammar, positioned after the
source/join clauses and before the field body:

```mdl
projection BillingCustomer @ 1
  from customer.Customer @ 2 as c
  pick(customerId, legalName, email)
{
  isBillable = c.status == "active"
}
```

```mdl
projection OrderWithCustomer @ 1
  from orders.Order @ 3 as o
  join customer.Customer @ 2 as c on o.customerId == c.customerId
  omit(c.phoneNumber, @pii)
{
  isHighValue = o.totalAmount > 1000.00
}
```

Grammar:

```text
selection_clause := ('pick' | 'omit') '(' selector (',' selector)* ')'
selector          := qualified_field | field_name | annotation_filter
qualified_field   := alias '.' field_name
annotation_filter := '@' identifier ('(' string_literal ')')?
```

- `pick` and `omit` are mutually exclusive; at most one may appear.
- `pick(...)` may not be empty.
- Unqualified `field_name` resolves against the `from` source. On a `join`
  projection, unqualified names are only valid if unambiguous across all
  sources; otherwise the field must be qualified (`o.orderId`).
- `annotation_filter` reuses `auto projections`' existing exclude-by-annotation
  matcher rather than a new implementation.

**Expansion happens before semantic validation**, in the same compiler stage
that expands `auto projections` into explicit projections today. `pick`/`omit`
resolve against the already-resolved source/join field sets and produce
ordinary `target <- source.field` nodes — indistinguishable, downstream, from
a hand-written mapping. No new node kind is added to the projection IR.

Annotations on picked fields (e.g. `@pii`) are inherited from the source
field's declaration automatically — the same way `exclude [@pii]` already
knows which generated fields are PII without the user re-declaring the
annotation on the projection field.

## Components

### Parser / grammar

Add the `selection_clause` production to the projection rule. No changes to
the `from`/`join`/body grammar.

### Expansion (compiler-owned, shared with auto projections)

- Reuse (not duplicate) the field-set resolution and annotation-matching logic
  `auto projections ... exclude` already implements.
- New: qualified (`alias.field`) resolution across `join` sources — auto
  projections never had to do this since they are single-source only.
- Output: a list of `target <- source.field` IR nodes, appended to whatever
  the hand-written body already declares.

### Semantic validation

- Reject `pick` + `omit` together.
- Reject empty `pick()`.
- Reject unknown field name, unknown alias, or unrecognized/unmatched
  annotation filter, naming the offending token.
- Reject a body field declaration whose name collides with a pick/omit-
  produced field (same "reserved name" conflict `auto projections` already
  enforces for `CustomerDb` etc., applied per-field here).

### Downstream consumers (unchanged)

Compatibility (Track C1), the property-dependency graph (Slice A2), lineage
reports, governance validation, canonical signatures, the formatter, and
`modelable inspect` all consume the expanded IR exactly as they consume a
hand-written projection. No changes required in any of these subsystems.

## Error handling

| Case | Result |
|---|---|
| `pick(...)` and `omit(...)` both present | compile error |
| `pick()` with no selectors | compile error |
| selector names an unknown field or alias | compile error, names the token |
| selector is an unrecognized annotation | compile error, names the token |
| body redeclares a picked/omitted field name | compile error (reserved-name conflict) |
| `pick`/`omit` field removed from source in a newer version | compile error at re-resolution, same as a hand-written `<-` referencing a removed field |

## Testing

- Unqualified `pick`, single source.
- Unqualified `omit`, single source.
- Qualified `alias.field` `pick` across a `join`.
- Qualified `alias.field` `omit` across a `join`.
- Annotation-filter selection (`@pii`, `@classification("secret")`).
- Combined field-name + annotation-filter list.
- Error: `pick` and `omit` both specified.
- Error: empty `pick()`.
- Error: unknown field/alias/annotation in selector list.
- Error: body redeclares an already-picked field.
- Body adds an extra computed (`=`) field alongside picked fields.
- Pick/omit-expanded fields appear in the shared property-dependency graph
  (Slice A2) identically to hand-written mappings — proves no parallel
  lineage path exists.
- Pick/omit-expanded projections participate in projection-to-projection
  compatibility (Slice C1) identically to hand-written projections.
- Canonical signature / formatter round-trip: source text keeps the
  `pick`/`omit` shorthand; canonical signature is computed from the expanded
  field set and is stable across re-compiles.

## Acceptance criteria

- `pick(...)` / `omit(...)` expand to the same explicit IR shape
  `auto projections` already produces, before any compatibility, lineage, or
  governance analysis runs.
- No new parallel lineage or compatibility code path is introduced; the
  annotation-filter matcher is shared with `auto projections ... exclude`,
  not reimplemented.
- Qualified `alias.field` selection works across `join` sources.
- Existing hand-written projections and existing `auto projections` blocks
  are unaffected — this is purely additive grammar, so it needs no historical-
  interpretation policy (Slice D0) the way nullability (D1) or lifecycle
  status (D6) do.
- Every error case above produces a diagnostic naming the offending field,
  alias, or annotation.

## Dependencies

None strictly required — expansion happens before any dependency-graph
consumer runs. Landing after Slice A2 (shared property-dependency graph) is
preferred so the "identical to hand-written" testing claim above has the
target graph API to test against, but this slice does not block on A2 and
could land independently.
