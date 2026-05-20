# Emitter Specification

> **Status:** Approved for Phase 1 targets; later target mappings are deferred by phase.
>
> **Scope:** Output target generation from the normalized Modelable model graph.

## 1. Purpose

Emitters transform validated Modelable definitions into external artifacts. They do not define contract semantics. The normalized model graph remains the source for lineage, compatibility, governance, and generated output.

Emitters must be deterministic: the same normalized graph and emitter options produce byte-for-byte equivalent artifacts, apart from documented formatting differences.

## 2. Phase Scope

| Target | Phase | Status |
|---|---:|---|
| JSON Schema 2020-12 | 1 | Required |
| TypeScript via `json-schema-to-typescript` | 1 | Required |
| Markdown documentation | 1 | Required |
| OpenMetadata export | 3 | Deferred |
| ODCS export | 4 | Deferred |
| Avro | 5 | Deferred |
| Protobuf | 5 | Deferred |
| SQL DDL | 5 | Deferred |
| OpenAPI | 5 | Deferred |
| AsyncAPI | 5 | Deferred |

Phase 1 must not require runtime adapters.

## 3. Emitter Interface

Each emitter receives:

- Normalized model graph.
- Selected model/projection references, or all definitions.
- Output directory.
- Emitter options.
- Registry metadata needed for lineage and governance annotations.

Conceptual interface:

```text
emit(graph, selection, options) -> emitted_artifacts
```

Each emitted artifact records:

- Target format.
- Logical reference (`domain.Name@version`).
- Artifact ID (`domain.Name.v<version>`).
- Relative output path.
- Content hash.
- Warnings.

## 4. Artifact Identity

Artifact IDs use:

```text
<domain>.<name>.v<version>
```

Examples:

```text
customer.Customer.v2
billing.BillingCustomer.v1
commerce.OrderPlaced.v3
```

Model references in CLI arguments remain `domain.Name@version`; artifact IDs and filenames use `.v<version>`.

## 5. Required Metadata

Every generated artifact must carry:

- Domain.
- Name.
- Kind.
- Version.
- Change kind.
- Source `.mdl` reference when available.
- Field-level classifications.
- Field-level lineage for projections.
- POR reference metadata when available.

For formats that do not support vendor extensions, emitters must generate a companion metadata document or document the loss explicitly.

## 6. JSON Schema Emitter

JSON Schema is the first canonical output format.

Requirements:

- Emit draft 2020-12 schemas.
- Use `type: object` for models and projections.
- Map required fields from non-optional `.mdl` fields.
- Preserve nullable fields according to JSON Schema 2020-12 conventions.
- Emit `x-modelable`, `x-modelable-field`, `x-modelable-classification`, `x-modelable-lineage`, `x-modelable-ref`, and `x-modelable-por` where applicable.
- Use `$defs` for local value objects when needed.
- Validate every generated schema with `jsonschema`.

Type mapping:

| Modelable | JSON Schema |
|---|---|
| `string` | `{ "type": "string" }` |
| `bool` | `{ "type": "boolean" }` |
| `int` | `{ "type": "integer", "format": "int64" }` |
| `float` | `{ "type": "number" }` |
| `decimal(p,s)` | `{ "type": "string", "pattern": "^-?\\d+(\\.\\d+)?$" }` |
| `uuid` | `{ "type": "string", "format": "uuid" }` |
| `timestamp` | `{ "type": "string", "format": "date-time" }` |
| `date` | `{ "type": "string", "format": "date" }` |
| `time` | `{ "type": "string", "format": "time" }` |
| `duration` | `{ "type": "string", "format": "duration" }` |
| `binary` | `{ "type": "string", "contentEncoding": "base64" }` |
| `enum(a,b)` | `{ "type": "string", "enum": ["a", "b"] }` |
| `array<T>` | `{ "type": "array", "items": <T schema> }` |
| `map<K,V>` | `{ "type": "object", "additionalProperties": <V schema> }` |
| Named value object | `$ref` into `$defs` |
| `ref<Domain.Model>` | String or object reference plus `x-modelable-ref` |

## 7. TypeScript Emitter

The TypeScript emitter delegates type generation to `json-schema-to-typescript`.

Requirements:

- Generate JSON Schema first.
- Generate one `.ts` file per schema.
- Preserve `x-modelable-*` metadata as JSDoc where supported.
- Use stable interface names derived from `<Domain><Name>V<version>`.
- Do not hand-roll a separate TypeScript type mapper in Phase 1.

## 8. Markdown Documentation Emitter

Markdown docs are for human review in source control.

Each document should include:

- Domain, owner, model/projection name, version, kind, and change kind.
- Field table with type, optionality, annotations, classification, and owner.
- Projection source table.
- Lineage table for projected fields.
- Compatibility notes when generated from a diff.
- Generated artifact references.

Markdown must avoid embedding secrets from bindings.

## 9. Deferred Target Notes

Deferred emitters must preserve Modelable semantics when implemented:

- Avro: preserve logical types and field defaults; avoid incompatible schema evolution.
- Protobuf: preserve deterministic field numbering through explicit metadata or generated registry state.
- SQL DDL: treat SQL as a binding/materialization artifact, not canonical model truth.
- OpenAPI: generate schemas from projections, not necessarily canonical entities.
- AsyncAPI: generate event channels from event projections and change event envelopes.
- ODCS: export data contracts while keeping `.mdl` as source of truth.
- OpenMetadata: export ownership, lineage, and classification metadata.
- Generated-language targets beyond TypeScript: C#, Java, Python, Rust, and Go. These targets are implemented in the local codegen boundary; additional future targets stay deferred.

## 10. Diagnostics

Emitter diagnostics are warnings unless the artifact cannot be generated correctly.

| Code | Meaning |
|---|---|
| `EMIT001` | Unsupported target |
| `EMIT002` | Type cannot be represented without loss |
| `EMIT003` | Missing metadata required by target |
| `EMIT004` | Generated artifact failed validation |
| `EMIT005` | Deferred target requested in current phase |

## 11. Open Decisions

- Whether emitters become third-party plugins through Python entry points.
- How target-specific annotations are represented without polluting canonical models.
- Whether large domains require streaming artifact generation APIs.

## 12. Acceptance Criteria

- Phase 1 emits JSON Schema, TypeScript, and Markdown for models and projections.
- JSON Schema output validates against draft 2020-12.
- Generated artifacts include version metadata and `x-modelable-*` extensions where supported.
- Projection artifacts include field-level lineage.
- Deferred targets fail with clear diagnostics rather than partial output.

## 13. Dependencies

- `idl-design-spec.md` — target catalog and type system
- `adapter-architecture-spec.md` — artifact output adapter boundary
- `cli-spec.md` — `compile`, `docs`, and `codegen` commands
- `ownership-permissions-spec.md` — POR and classification metadata
