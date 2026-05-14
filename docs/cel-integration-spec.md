# CEL Integration Specification

> **Status:** Placeholder.
>
> **Scope:** How the Common Expression Language (CEL) is embedded in `.mdl` projections, parsed, validated, and used for lineage extraction.

## Purpose

CEL is the chosen expression language for computed projection fields (`target = expression`). This document defines:

1. The subset of CEL supported in `.mdl`.
2. How field references are extracted from CEL expressions for lineage tracking.
3. Validation rules (type checking, null safety).
4. Integration with the semantic validator.

## Supported Subset

- Literals: strings, integers, floats, booleans, null.
- Operators: arithmetic, comparison, logical, ternary.
- Functions: string methods, timestamp/duration helpers, type casts.
- Field references: `alias.fieldName` (qualified) and bare field names (in scope).

## Lineage Extraction

The compiler must statically extract all `alias.fieldName` references from a CEL expression and record them as lineage sources for the computed field.

## Open Questions

- Should custom CEL macros be supported (e.g., `has(alias.field)`)?
- How are CEL validation errors surfaced in the CLI (`validate` command)?
- Performance implications of CEL parsing on large projection files.

## Dependencies

- `idl-design-spec.md` §2 — type system
- `idl-design-spec.md` §3 — projection operators
- `idl-parser-implementation-plan.md` — semantic validation task
