# Modelable Compiler and Artifact Reference

> **Scope:** Compiler outputs, emitters, compatibility metadata, lineage, and
> generated-artifact guarantees.

> **Status:** Approved for Phase 1 targets, selected local integration
> emitters, and Apicurio JSON Schema artifact publish/pull. Catalog and runtime
> integrations remain deferred by phase.
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
| C#, Java, Python, Rust, and Go | 1 | Implemented |
| SQL DDL | 5 | Implemented local artifact |
| dbt `schema.yml` | 4 | Implemented local artifact |
| FHIR R4 profile | 4b | Implemented local artifact for Patient, Observation, and Encounter profile bases |
| Apicurio Registry | 2 | Implemented JSON Schema artifact publish/pull |
| OpenMetadata export | 3 | Implemented local artifact; live catalog sync deferred |
| OpenLineage sync | 3 | Implemented for Marquez-compatible `/api/v1/lineage` endpoints |
| OpenLineage export | 3 | Implemented local artifact; runtime collection deferred |
| ODCS export | 4 | Implemented local artifact |
| Protobuf | 5 | Implemented local artifact with opt-in descriptor artifacts and native supported maps; compatibility validation deferred |
| Scalable gRPC profile | 5 | Implemented local artifact with opt-in service descriptors and declared read-index metadata; compatibility validation deferred |
| Avro | 5 | Deferred |
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
| `u8`..`u128`, `i8`..`i128` | `{ "type": "integer", "minimum": ..., "maximum": ... }` bounds per width |
| `float` | `{ "type": "number" }` |
| `decimal(p,s)` | `{ "type": "string", "pattern": "^-?\\d+(\\.\\d+)?$" }` |
| `uuid` | `{ "type": "string", "format": "uuid" }` |
| `uuid(7)` | `{ "type": "string", "format": "uuid", "x-modelable-uuid-version": 7 }` |
| `timestamp` | `{ "type": "string", "format": "date-time" }` |
| `date` | `{ "type": "string", "format": "date" }` |
| `time` | `{ "type": "string", "format": "time" }` |
| `duration` | `{ "type": "string", "format": "duration" }` |
| `binary` | `{ "type": "string", "contentEncoding": "base64" }` |
| `binary(N)` | `{ "type": "string", "contentEncoding": "base64", "x-modelable-fixed-length": N }` |
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

## 9. Apicurio Registry Publishing

`modelable publish apicurio` publishes generated JSON Schema 2020-12 artifacts
to Apicurio Registry 3.x Core Registry API v3. Artifact IDs are deterministic:
`domain.Name.vVersion`. Apicurio is derived artifact storage and versioning; it
does not replace `.mdl` source files, the local normalized graph, registry.db,
lineage, compatibility, or governance validation.

`modelable pull apicurio` retrieves a JSON Schema artifact by Modelable
reference (`domain.Name@version`) from the Apicurio version content endpoint
and writes it under the requested output directory as
`domain/Name.vVersion.json`.

## 10. Deferred Target Notes

Deferred and integration emitters must preserve Modelable semantics when
implemented:

- Avro: preserve logical types and field defaults; avoid incompatible schema evolution.
- Scalable gRPC profile: `compile --target grpc` emits the Protobuf payload
  schemas, generic Scalable command/read service definitions, schema manifests,
  and service manifests for models and projections. The target exposes
  `CommandService`, `EntityReadService`, envelope contracts, schema identity,
  and `read_indexes` from declared primary/secondary indexes, with an inferred
  primary fallback from existing `@key` fields when no index declaration
  exists. When `--descriptor-set` is used, each service emits a compiled
  `<Name>.v<version>.grpc.descriptor.pb` descriptor artifact and records it in
  `service-manifest.json`. Scalable registration fixtures and protobuf/gRPC
  compatibility validation remain deferred follow-up work before gRPC is
  considered stable for long-lived external transport contracts.
- Protobuf: `compile --target protobuf` emits deterministic `.proto` files and
  schema manifests for models and projections. Supported `map<K,V>` fields
  render as native Protobuf maps, unsupported map shapes fail clearly, and
  model schema manifests include declared primary/secondary `indexes`
  metadata. Field manifest entries for maps record `map.key_type`,
  `map.value_type`, and optional `map.value_fixed_length` or
  `map.value_semantic_type`. When `--descriptor-set` is used, each schema emits
  a compiled `<Name>.v<version>.descriptor.pb` descriptor artifact and records
  it in `schema-manifest.json`. The remaining wire-contract boundary is
  deleted-field reservations and protobuf compatibility validation before
  protobuf is considered stable for long-lived external wire contracts.
- SQL DDL: treat SQL as a binding/materialization artifact, not canonical
  model truth. `index` declarations (see [Language Reference
  §3.9](language-reference.md#39-index-declarations)) generate
  `CREATE INDEX IF NOT EXISTS`/`CREATE UNIQUE INDEX IF NOT EXISTS`
  statements after the table's `CREATE TABLE`, Postgres only — the
  `secondary` block's `key` fields form the leading index columns, its
  `sort` fields are appended with `DESC` where declared (`asc` needs no
  suffix). Every field name is resolved from the indexed *model* through
  to the emitting projection's own column name via its `DirectMapping`s;
  a referenced field the projection doesn't include is skipped (with a
  `type_loss` warning) rather than emitted as a broken column reference.
  ClickHouse index DDL is deferred — ClickHouse's data-skipping-index
  model doesn't map mechanically onto the same statement shape.
- dbt YAML: describe schemas and model/source metadata without making dbt the source of truth.
- FHIR R4 profiles: emit R4 `StructureDefinition` constraint profiles for
  projection artifacts. The current hardening boundary supports projections
  whose source model name is `Patient`, `Observation`, or `Encounter`; other
  source models fall back to the R4 `Basic` resource with an emitter warning.
  Profile output includes root and field `ElementDefinition` entries, direct
  Modelable lineage mappings, required/optional and repeating cardinality,
  primitive type mappings, enum bindings to deterministic Modelable ValueSet
  URLs, FHIR `Reference` target profiles, and Modelable classification/PII
  extensions. The FHIR export gate includes an opt-in smoke against the
  HL7-maintained Java FHIR Validator (`validator_cli.jar`) for representative
  R4 profiles. Fields that are not legal base-resource children are mapped to
  FHIR extension slices on the resource's `extension` element, paired with
  companion `Extension`-type StructureDefinitions that fix the extension URL
  and value type. Unsupported nested/complex FHIR representation remains a
  warning/follow-up boundary rather than a silent lossy mapping.
- OpenAPI: generate schemas from projections, not necessarily canonical entities.
- AsyncAPI: generate event channels from event projections and change event envelopes.
- ODCS: export data contracts while keeping `.mdl` as source of truth.
- OpenMetadata: export ownership, lineage, and classification metadata. Live
  catalog publishing remains outside the local emitter boundary.
- OpenLineage: emit design-time run events with schema and column-lineage
  facets from the local graph. Runtime event collection remains outside the
  local emitter boundary.
- Generated-language targets beyond TypeScript: C#, Java, Python, Rust, and Go. These targets are implemented in the local codegen boundary; additional future targets stay deferred.
- Semantic types (`semantic Name: Underlying`, see [Language Reference §3.8](language-reference.md#38-semantic-types)): the Rust emitter generates a `#[serde(transparent)]` tuple-struct newtype per declaration (`pub struct Name(pub Underlying);`) with `From`/`From`(reverse) conversions and `Deref` to the underlying type. Derives (`Debug`, `Clone`, plus `Copy`/`Eq`/`Hash` where the underlying Rust type supports them) are chosen per underlying kind — e.g. integers and `uuid::Uuid` derive `Copy + Eq + Hash`, `String` and `f64`-backed types omit `Copy`, and `f64` additionally omits `Eq`/`Hash`. Fields that reference a semantic type use the newtype directly, with a `use` import generated the same way cross-domain model references are resolved. When a declaration is `registry: true` and has an entry in `registry-ids.lock`, the generated struct retains its `/// registry id: N` doc comment and exposes the allocation as an associated `u32` constant such as `RuntimeKernelConfigSchemaId::REGISTRY_ID`. A direct emitter call without supplied allocations omits the constant.

  The Protobuf and gRPC targets preserve semantic types nominally as shared
  declaring-domain wrapper messages in `<domain>/semantic-types.proto`.
  Chained aliases flatten to their terminal scalar inside each wrapper.
  Consuming schema manifests record `semantic_type`, optional allocated
  `registry_id`, and the canonical `modelable_signature` separately from
  `schema_fingerprint`. Other non-Rust targets continue to resolve semantic
  references structurally.

Every generated Rust model and projection exposes its declared version as an
associated `u32` constant such as
`RuntimeKernelConfigV1::SCHEMA_VERSION`. It also exposes the canonical
Modelable signature as
`RuntimeKernelConfigV1::SCHEMA_CONTENT_SIGNATURE`, a dependency-free
`[u8; 32]` produced from `compute_version_signature()`. This canonical
contract identity is distinct from the generated Rust artifact's text hash
and from target-specific wire fingerprints such as Protobuf
`schema_fingerprint`.

## 11. Diagnostics

Emitter diagnostics are warnings unless the artifact cannot be generated correctly.

| Code | Meaning |
|---|---|
| `EMIT001` | Unsupported target |
| `EMIT002` | Type cannot be represented without loss |
| `EMIT003` | Missing metadata required by target |
| `EMIT004` | Generated artifact failed validation |
| `EMIT005` | Deferred target requested in current phase |

## 12. Open Decisions

- Whether emitters become third-party plugins through Python entry points.
- How target-specific annotations are represented without polluting canonical models.
- Whether large domains require streaming artifact generation APIs.

## 13. Acceptance Criteria

- Phase 1 emits JSON Schema, TypeScript, and Markdown for models and projections.
- Implemented local emitters are deterministic and appear in `modelable codegen formats`.
- JSON Schema output validates against draft 2020-12.
- Generated artifacts include version metadata and `x-modelable-*` extensions where supported.
- Projection artifacts include field-level lineage.
- Deferred targets fail with clear diagnostics rather than partial output.

## 14. Dependencies

- [Language reference](language-reference.md) for the type system, governance
  annotations, and target declarations.
- [Tooling reference](cli-reference.md) for `compile`, `docs`, `codegen`, and
  graph-export commands.
- [Architecture](architecture.md) for adapter boundaries and product semantics.

## 15. Registry and Distributed Lineage

`.mdl` files are the source of truth. `registry.db`, plan documents, generated
artifacts, mirrors, and exported graphs are reproducible derived state.

The local compiler records model and projection identities, compatibility
reports, ownership, classifications, content signatures, and property-level
lineage. Distributed workspaces may declare git-backed peers. Foreign source is
resolved from local mirrors, while downstream consumer registrations are stored
as explicit source-controlled records. Rebuilding the registry from source must
produce the same graph.

Cross-registry references include logical identity, concrete version, source
registry, and content signature. A signature mismatch is an integrity error,
not a warning. Fetch and write-back failures must be explicit and must not leave
partially updated registry state.

The `graph export` command emits deterministic canonical JSON suitable for
catalogs and lineage tools. External systems may visualize or enrich that graph, but they do
not replace Modelable's source definitions or compiler validation.
