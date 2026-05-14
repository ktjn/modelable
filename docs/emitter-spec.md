# Emitter Specification

> **Status:** Placeholder — deferred from `idl-parser-implementation-plan.md`.
>
> **Scope:** Output target generation (JSON Schema, TypeScript, Avro, Protobuf, SQL DDL, AsyncAPI, Markdown docs).

## Purpose

Define the interface and behavior of each compiler emitter that transforms the normalized Modellable model graph into external artifact formats.

## Emitters

| Target | Phase | Canonical Spec |
|---|---|---|
| JSON Schema | 1 | `idl-design-spec.md` §4.3 |
| TypeScript | 1 | `idl-design-spec.md` §4.3 |
| Markdown docs | 1 | `idl-design-spec.md` §4.3 |
| Avro | 2 | `external-tools-data-modelling.md` §4 |
| Protobuf | 2 | `external-tools-data-modelling.md` §4 |
| SQL DDL (Postgres / MySQL / SQLite) | 2 | `idl-design-spec.md` §4.3 |
| AsyncAPI | 2 | `idl-design-spec.md` §4.3 |
| OpenAPI | 2 | `external-tools-data-modelling.md` §4 |

## Open Questions

- Should emitters be plugins with a well-defined Python entry-point interface?
- How are target-specific annotations (e.g., SQL index hints, Avro logical types) passed through?
- Should the emitter spec define a streaming API for large domains?

## Dependencies

- `idl-design-spec.md` — target catalog
- `adapter-architecture-spec.md` — artifact output adapters
- `cli-spec.md` — `compile` command interface
