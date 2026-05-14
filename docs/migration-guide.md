# Migration Guide

> **Status:** Placeholder.
>
> **Scope:** Guidance for migrating existing schema definitions into Modellable.

## Purpose

Help teams adopt Modellable by migrating from existing schema and contract formats.

## Source Formats

| Source | Approach | Tooling |
|---|---|---|
| OpenAPI 3.x | Import paths and schemas as Modellable models; extract entities and projections | `modellable generate --from <openapi.yaml>` |
| JSON Schema | Import as value objects or event models; annotate classifications | `modellable generate --from <schema.json>` |
| Protobuf | Import messages as entities/events; preserve field numbers as annotations | `modellable generate --from <proto>` |
| SQL DDL | Reverse-engineer tables into entities; infer keys and types | `modellable generate --from <ddl.sql>` |
| Avro | Import schemas as event models; preserve logical types | `modellable generate --from <avro.json>` |
| Existing YAML/DSL | Manual or semi-automated rewrite using `modellable generate` | LLM-assisted (`modellable describe` + `modellable generate`) |

## Migration Principles

1. **Start with canonical entities** — Identify the core business entities in the existing schema and model them first.
2. **Add projections incrementally** — Do not try to map every existing view/table to a projection on day one.
3. **Preserve version history** — Map existing schema versions to Modellable versions; mark breaking changes explicitly.
4. **Validate early and often** — Use `modellable validate` after each incremental migration step.

## Dependencies

- `cli-spec.md` — `generate` and `validate` commands
- `llm-integration-spec.md` — AI-assisted migration workflows
