# Protobuf Schema Fidelity - Design

Date: 2026-07-17

## 1. Purpose

Priority 1 item 3 in [ROADMAP.md](../../../ROADMAP.md) closes two known gaps in
the Protobuf and Scalable gRPC contract path:

- `map<K,V>` fields currently emit opaque `bytes`, which erases the map's wire
  structure and hides whether the generated contract is actually consumable by a
  Protobuf client.
- Declared `index` metadata is parsed and used by Postgres DDL, but Protobuf
  schema manifests and gRPC service manifests do not yet expose the declared
  primary and secondary read metadata Scalable needs for schema registration.

This slice makes both surfaces deterministic and explicit while keeping
descriptor sets, field reservations, compatibility validation, and end-to-end
Scalable registration fixtures in later roadmap items.

## 2. Goals

This slice must:

- replace the Protobuf emitter's opaque map fallback with native Protobuf
  `map<K,V>` for supported map shapes;
- fail clearly for unsupported map shapes instead of silently emitting `bytes`;
- preserve existing primitive, enum, semantic wrapper, array, package, field
  numbering, and projection type-resolution behavior outside the map change;
- record field-level map metadata in `schema-manifest.json`;
- include declared primary and secondary index metadata in schema manifests for
  indexed model versions;
- carry the same declared read index metadata into generated gRPC
  `service-manifest.json` files;
- keep `protobuf` and `grpc` payload schema manifests identical; and
- update the wire-format, compiler, CLI, changelog, and roadmap docs.

## 3. Protobuf Map Encoding

### 3.1 Supported map shape

The Protobuf emitter uses native `map<K,V>` for `.mdl` fields whose key and value
types can be represented as a Protobuf map entry without additional generated
messages:

```text
attributes: map<string, int>
labels: map<string, Label>
schemaIds: map<string, SchemaId>
```

Supported map keys are the key scalar types accepted by Protocol Buffers:

| Modelable key type | Protobuf key type |
|---|---|
| `string` | `string` |
| `int`, `i64` | `int64` |
| `i8`, `i16`, `i32` | `int32` |
| `u8`, `u16`, `u32` | `uint32` |
| `u64` | `uint64` |
| `bool` | `bool` |

Supported map values are singular, non-repeated Protobuf value types already
supported by the emitter:

- primitive scalar types, including `timestamp` as
  `google.protobuf.Timestamp`;
- `decimal(P,S)` as `string`;
- `binary`, `binary(N)`, `u128`, and `i128` as `bytes`, with fixed-length
  metadata recorded in the manifest;
- inline `enum(...)` fields, using the existing generated enum naming rule; and
- supported semantic `NamedType` wrappers, including cross-domain semantic
  wrappers from the previous Protobuf semantic identity slice.

Optional map fields render as:

```proto
map<string, int64> attributes = 3;
```

They do not use `optional`. In proto3, map fields already have collection
presence semantics distinct from singular scalar presence. The schema manifest
records the source field's optionality separately so Modelable's canonical
contract remains visible even when the Protobuf surface cannot encode that
presence bit.

### 3.2 Unsupported map shape

The emitter fails with a clear `ValueError` for map keys or values that cannot
be represented in this first deterministic map slice. Unsupported shapes
include:

- `float`, `double`, `bytes`, `fixed_binary`, `decimal`, `timestamp`, `date`,
  `time`, `duration`, `uuid`, `u128`, and `i128` map keys;
- enum map keys;
- array, object, ref, and nested map keys or values;
- non-semantic `NamedType` map values; and
- ambiguous semantic map values.

Failing is intentional. The previous fallback produced compile-successful
artifacts that were not meaningful Protobuf contracts. After this slice, a map
field is either rendered with deterministic Protobuf structure or rejected with
the field path and unsupported type reason.

### 3.3 Field rendering and imports

Map value type conversion reuses the existing `_type_to_proto` rules, but it
must reject any value type that returns a repeated type or the ordinary
unsupported `bytes` fallback. This preserves the existing fallback for a
top-level non-semantic `NamedType` field while preventing a map from smuggling
an unsupported value through as opaque bytes.

If a map value references a semantic wrapper, the consumer `.proto` imports the
declaring domain's `semantic-types.proto` exactly as a singular semantic field
does.

If a map value is `timestamp`, the consumer imports
`google/protobuf/timestamp.proto`.

Inline enum values keep the current enum declaration behavior. A field:

```text
states: map<string, enum(active, blocked)>
```

renders as:

```proto
map<string, CustomerStates> states = 4;
```

with `enum CustomerStates` emitted as a sibling enum using the existing
declaration-order numbering rule.

### 3.4 Manifest metadata

Each map field in `schema-manifest.json` keeps its existing field entry and adds
a `map` object:

```json
{
  "name": "attributes",
  "proto_name": "attributes",
  "number": 3,
  "type": "map<string, int64>",
  "key": false,
  "map": {
    "key_type": "string",
    "value_type": "int64"
  }
}
```

When the map value carries extra metadata, the map object records it:

```json
{
  "map": {
    "key_type": "string",
    "value_type": ".modelable.platform.semantic.SchemaId",
    "value_semantic_type": "platform.SchemaId"
  }
}
```

For fixed-length byte-backed values, the map object records
`value_fixed_length`. For semantic values, the schema-level `semantic_types`
array includes the referenced semantic declaration once, sorted and deduplicated
with non-map semantic fields.

The manifest field's top-level `semantic_type` remains reserved for fields
whose field itself is a semantic wrapper. A map whose value is semantic uses
`map.value_semantic_type` so consumers do not confuse the map field with a
singular semantic wrapper field.

`schema_fingerprint` includes the `map` object because the map key/value shape
is part of the target-specific wire contract.

## 4. Declared Index Manifest Metadata

### 4.1 Source of truth

The source of read metadata is the parsed `IndexDecl` already produced by the
language:

```text
index Order @ 1 {
  primary orderId
  secondary byCustomer {
    key: [customerId]
    sort: [createdAt desc]
    unique: false
  }
}
```

The emitter does not infer secondary indexes from ordinary field names. If a
model version has no `index` declaration, manifests may still expose a
compatibility primary index derived from `@key` fields for the existing gRPC
behavior, but they do not invent secondary indexes.

Semantic validation remains responsible for ensuring the declaration targets an
existing entity or aggregate model version, the primary fields match the
model's key fields, secondary names are unique, and secondary key/sort fields
exist.

### 4.2 Schema manifest shape

For model schema manifests whose version has an `index` declaration, the schema
object adds `indexes`:

```json
{
  "indexes": {
    "primary": {
      "index_name": "primary",
      "index_version": 1,
      "key_fields": ["orderId"],
      "sort_fields": [],
      "unique": true
    },
    "secondary": [
      {
        "index_name": "byCustomer",
        "index_version": 1,
        "key_fields": ["customerId"],
        "sort_fields": [
          {"field": "createdAt", "direction": "desc"}
        ],
        "unique": false
      }
    ]
  }
}
```

`index_version` is the model version number targeted by the `index` declaration.
This keeps index metadata tied to the source model contract revision rather
than introducing an independent counter in this slice.

`sort_fields` is an array of objects in schema manifests so direction remains
lossless. This differs from the current gRPC `IndexMetadata` message, which has
only `repeated string sort_fields`; the service manifest must flatten each
entry as described below.

Projection schema manifests do not get their own `indexes` block in this slice.
Index declarations target model versions. Projection-to-index field remapping
for materialized SQL already belongs to the SQL emitter; Scalable read
registration consumes model read metadata.

### 4.3 Service manifest shape

`emit_grpc()` reads the schema manifest's `indexes` block and writes
`read_indexes` in `service-manifest.json`:

```json
[
  {
    "index_name": "primary",
    "index_version": 1,
    "key_fields": ["orderId"],
    "sort_fields": [],
    "unique": true
  },
  {
    "index_name": "byCustomer",
    "index_version": 1,
    "key_fields": ["customerId"],
    "sort_fields": ["createdAt desc"],
    "unique": false
  }
]
```

For gRPC service manifests, sort fields are flattened as field names with a
` desc` suffix only when the declared direction is `desc`; ascending sort fields
use the bare field name. This matches the existing generated `IndexMetadata`
message shape without changing the service `.proto` envelope in this slice.

When there is no `index` declaration, gRPC keeps the existing primary-index
fallback derived from manifest fields whose `key` is true:

```json
{
  "index_name": "primary",
  "index_version": 1,
  "key_fields": ["customerId"],
  "sort_fields": [],
  "unique": true
}
```

When there is an `index` declaration, it is authoritative for `read_indexes`.
The emitter must not append a second inferred primary index.

### 4.4 Fingerprints and compatibility

The schema manifest's `indexes` block is part of `schema_fingerprint`, because
Scalable read registration needs index changes to be visible as generated
contract changes. It is not part of `modelable_signature`; that value remains
the canonical normalized Modelable version signature produced by
`compute_version_signature()`.

This slice does not classify index changes as safe, rebuild-required, or
breaking. Existing compatibility visibility for `index_changed` remains the
extent of compatibility behavior until the later Protobuf/gRPC compatibility
validation roadmap item.

## 5. Emitter Structure

The Protobuf emitter should keep one conversion path for model and projection
fields, but the internal result object needs enough structure to render maps
and manifests without ad hoc string parsing.

The existing `_ProtoField` should gain structured metadata equivalent to:

```python
@dataclass(frozen=True)
class _ProtoMap:
    key_type: str
    value_type: str
    value_fixed_length: int | None = None
    value_semantic: _SemanticProtoType | None = None

@dataclass(frozen=True)
class _ProtoField:
    ...
    map: _ProtoMap | None = None
```

The exact internal names are implementation details, but the implementation
must avoid parsing `type_name` strings to rediscover map or semantic metadata.

Index metadata should be resolved once per emitted model schema from the
domain's `index_decls`, then normalized through a small helper used by both:

- `_manifest_json()` for schema manifests; and
- `grpc.py` service-manifest rendering through the already-generated schema
  manifest.

`emit_grpc()` should continue to call `emit_protobuf()` and retarget the
payload artifacts. It must not rebuild index metadata from raw workspace state
when the schema manifest already contains the normalized contract.

## 6. Error Behavior

Unsupported map errors must include:

- the containing schema ref or enough field context to find the source;
- the field name; and
- the unsupported key or value reason.

Examples:

```text
platform.Widget@1.attributes: protobuf map key type uuid is not supported
platform.Widget@1.payloads: protobuf map value type map<string,int> is not supported
platform.Widget@1.addresses: protobuf map value named type Address is not supported
```

Ambiguous semantic references inside map values use the same candidate-list
error style as singular semantic fields.

The emitter must not partially write artifacts after a map error when called
through the CLI. The existing compile command behavior of failing the target is
sufficient; this slice does not add recovery or per-field warning output.

## 7. Documentation Updates

Implementation must update:

- `docs/wire-format-contract.md` to replace the `map<K,V>` opaque bytes row
  with the native-map rule and the unsupported-map failure boundary;
- `docs/compiler-reference.md` for Protobuf schema manifests, gRPC service
  manifests, and index metadata;
- `docs/cli-reference.md` for target behavior if its Protobuf/gRPC sections
  still describe maps or indexes incompletely;
- `CHANGELOG.md`; and
- `ROADMAP.md` to mark Priority 1 item 3 shipped and leave items 4 and 5 as
  the next dependency-ordered slices.

The active design and implementation plan remain under
`docs/superpowers/specs/` and `docs/superpowers/plans/` until the
implementation merges, then both are archived immediately after merge.

## 8. Verification

Tests must cover:

- Protobuf native map rendering for primitive key/value pairs;
- semantic map values with imports and `semantic_types` manifest entries;
- timestamp and fixed-length byte-backed map values with import/fixed-length
  metadata;
- inline enum map values;
- unsupported key and value types failing clearly;
- no fallback to `bytes` for unsupported map shapes;
- map fields included in `schema_fingerprint`;
- unchanged non-map `NamedType` fallback behavior;
- schema manifest `indexes` for declared primary and secondary indexes;
- service manifest `read_indexes` sourced from declared index metadata;
- existing inferred primary gRPC fallback when no `index` declaration exists;
- deterministic output across repeated emission;
- wire golden fixture update for `map<string,int>`; and
- CLI compile behavior for both `protobuf` and `grpc`.

The final branch must run the four mandatory CLI gates from `cli/`:

```text
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

The docs build must also pass:

```text
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
```

## 9. Out of Scope

- Descriptor-set generation.
- Reserved deleted field numbers and names.
- Protobuf/gRPC compatibility validation and read-rebuild classification.
- End-to-end Scalable registration fixtures.
- General Protobuf support for non-semantic named model/value-object fields.
- Generated entry messages for arbitrary nested map/object values.
- Custom Protobuf options for index metadata.
- Changing the generated gRPC service envelope `.proto` shape.
- ClickHouse index DDL changes.

## 10. Acceptance Criteria

The slice is complete when a Scalable consumer can compile generated Protobuf
and gRPC artifacts containing supported map fields, read declared primary and
secondary index metadata from schema and service manifests, and rely on the
compiler to reject unsupported map shapes instead of receiving opaque `bytes`
fields that hide the contract loss.
