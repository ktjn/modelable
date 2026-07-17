# Protobuf Semantic Identity — Design

Date: 2026-07-17

## 1. Purpose

Modelable's Protobuf emitter currently maps every `NamedType` to opaque
`bytes`. That includes fields referencing a declared semantic type, even when
the semantic declaration has a precise scalar representation such as `u32`,
`uuid`, or `binary(32)`.

The fallback loses both the usable wire representation and the semantic type's
nominal identity. The companion `schema-manifest.json` also has no record of
which semantic declaration a field references or which stable registry ID was
allocated to a `registry: true` declaration.

Priority 1 item 2 in [ROADMAP.md](../../../../ROADMAP.md) therefore adds semantic
identity to the Protobuf and Scalable gRPC targets. This follows the shipped
Rust identity constants slice while preserving the distinction between
canonical Modelable identity and target-specific Protobuf wire identity.

## 2. Goals

This slice must:

- represent each declared semantic type as a nominal Protobuf wrapper message;
- give each wrapper a stable fully qualified name owned by its declaring
  domain, independent of the consuming model or projection version;
- flatten chained semantic aliases to their terminal supported Protobuf scalar;
- use wrappers from model fields, projection fields, and arrays of semantic
  types;
- expose semantic refs and allocated registry IDs in each consuming schema
  manifest;
- expose the canonical Modelable version signature beside the existing
  target-specific Protobuf fingerprint;
- preserve existing field numbering, package names, primitive mappings, enum
  rendering, and unsupported non-semantic `NamedType` behavior;
- keep direct emitter calls without registry allocations supported; and
- keep Protobuf payload artifacts identical between the `protobuf` and `grpc`
  targets.

## 3. Shared Semantic Wrapper Artifacts

### 3.1 One bundle per declaring domain

For every domain containing semantic declarations, `emit_protobuf()` emits one
shared artifact:

```text
<out>/<domain>/semantic-types.proto
```

For example:

```proto
syntax = "proto3";

package modelable.platform.semantic;

message SchemaId {
  uint32 value = 1;
}
```

The artifact has:

- target `protobuf`;
- ref and artifact ID `<domain>.semantic-types`;
- the path shown above; and
- the same generated-header and dependency-import conventions as other
  Protobuf artifacts.

`emit_grpc()` retargets this payload artifact to `grpc` exactly as it retargets
model and projection Protobuf artifacts.

The bundle is emitted even when a semantic declaration is not currently
referenced. This keeps the declaring domain's generated type surface
deterministic and makes the nominal type available for future consumers
without changing an unrelated model artifact.

### 3.2 Stable packages and names

The package is:

```text
modelable.<normalized-domain>.semantic
```

It does not contain a model version because semantic declarations are
unversioned. Message names are the declared semantic names.

Consumers refer to wrappers with a leading-dot fully qualified name:

```proto
.modelable.platform.semantic.SchemaId
```

The leading dot prevents resolution relative to the consumer's versioned
package.

Wrappers are sorted by declaration name. Dependency imports and consumer
imports are deduplicated and sorted. This makes output independent of
workspace file order and Python hash iteration.

### 3.3 Terminal-scalar flattening

Each wrapper contains one `value = 1` field. A direct scalar semantic maps
through the existing Protobuf rules:

| Modelable terminal type | Wrapper field type |
|---|---|
| `u8`, `u16`, `u32` | `uint32` |
| `u64` | `uint64` |
| `i8`, `i16`, `i32` | `int32` |
| `int`, `i64` | `int64` |
| `u128`, `i128` | `bytes` |
| `string`, `uuid`, `date`, `time`, `duration` | `string` |
| `float` | `double` |
| `bool` | `bool` |
| `timestamp` | `google.protobuf.Timestamp` |
| `binary`, `binary(N)` | `bytes` |
| `decimal(P,S)` | `string` |

Fixed-length metadata remains a manifest concern; proto3 cannot express a
fixed byte length on the wrapper field.

A chain such as:

```text
semantic EntityId : uuid
semantic OrderId : EntityId
```

emits both wrappers directly over `string`. `OrderId` does not contain an
`EntityId` message. The distinct wrapper message names preserve nominal
identity without adding one length-delimited wire layer per alias in the
chain.

Timestamp-backed bundles import `google/protobuf/timestamp.proto`.

## 4. Consumer Type Resolution

`emit_protobuf()` builds a semantic index once from the full emitted
workspace. Model and projection field conversion consults that index before
using the existing unsupported-type fallback.

When a `NamedType` resolves to a semantic declaration:

1. resolve its declaring domain and terminal scalar;
2. render the field as the fully qualified wrapper message;
3. add the declaring domain's semantic bundle import; and
4. carry the semantic ref into manifest field metadata.

An `array<SemanticType>` becomes `repeated <fully-qualified-wrapper>` and
retains the semantic ref.

Projection fields reuse the source model field type they already resolve, so a
directly mapped semantic field follows the same path as a model field.
Computed projection fields keep their current `string` fallback.

The current grammar has only unqualified bare `NamedType` references. If more
than one domain declares the same semantic name, a field reference cannot
select one unambiguously. Protobuf emission must fail clearly for that
ambiguous reference rather than silently choose a declaration. Dotted semantic
type-reference syntax remains a separate language-design follow-up.

A `NamedType` that does not resolve to a semantic declaration keeps the
existing `bytes` fallback. This slice does not add general named
model/value-object support.

Maps, objects, and other structural contexts that currently degrade to
`bytes` remain unchanged. In particular, the emitter must not claim semantic
identity for a semantic type hidden inside an unsupported map representation.
Map fidelity is Priority 1 item 3.

## 5. Schema Manifest Contract

Each model or projection `schema-manifest.json` retains its current shape and
adds canonical identity plus normalized semantic definitions:

```json
{
  "target": "protobuf",
  "schemas": [
    {
      "ref": "runtime.RuntimeKernelConfig@1",
      "kind": "entity",
      "schema_id": "modelable://runtime/RuntimeKernelConfig/v1/protobuf",
      "modelable_signature": "<64-character canonical hex digest>",
      "schema_fingerprint": "<64-character protobuf layout digest>",
      "semantic_types": [
        {
          "ref": "platform.SchemaId",
          "proto_type": ".modelable.platform.semantic.SchemaId",
          "underlying_type": "uint32",
          "registry_id": 1
        }
      ],
      "fields": [
        {
          "name": "schemaId",
          "proto_name": "schema_id",
          "number": 1,
          "type": ".modelable.platform.semantic.SchemaId",
          "key": false,
          "semantic_type": "platform.SchemaId"
        }
      ]
    }
  ]
}
```

`modelable_signature` is the exact digest returned by
`compute_version_signature(domain, name, version)`. It identifies the
canonical normalized Modelable contract.

`schema_fingerprint` remains the digest of the rendered Protobuf field-layout
metadata. Its normalized input includes the consuming fields plus the
referenced semantic definitions' `ref`, `proto_type`, `underlying_type`, and
`fixed_length`. It excludes `registry_id`, which is allocation metadata rather
than wire shape. This ensures a wrapper's terminal representation affects the
fingerprint even though the consuming field continues to name the same wrapper
message. The fingerprint identifies target-specific wire shape. The two
identity values are intentionally separate and may change under different
conditions.

`semantic_types` is sorted by qualified `ref` and contains each semantic type
referenced by the schema once. Each entry contains:

- `ref`: `<declaring-domain>.<semantic-name>`;
- `proto_type`: its fully qualified wrapper message;
- `underlying_type`: the terminal Protobuf scalar used inside the wrapper;
- `fixed_length`: only when the terminal type has a known fixed byte length;
  and
- `registry_id`: only when the declaration is explicitly `registry: true`
  and the caller supplied its allocation.

A direct emitter call without `registry_ids` omits `registry_id`; it never
emits `0`, `null`, or another sentinel. A non-registry semantic declaration
never receives a registry ID even if an unrelated map entry is supplied.

Each manifest field using a supported semantic wrapper gains
`semantic_type: <qualified-ref>`. Arrays use the same qualified ref. Fields
without supported semantic identity retain their current manifest shape.

The wrapper bundle itself does not introduce a second manifest format.
Registry metadata is exposed in the model/projection schema manifests that
Scalable registers and consumes.

## 6. Compiler and gRPC Data Flow

The compile command already allocates and persists `registry_ids` before
dispatching to a target. This slice changes the call path to:

```text
compile
  -> emit_protobuf(workspace, out, registry_ids=registry_ids)
  -> emit_grpc(workspace, out, registry_ids=registry_ids)
       -> emit_protobuf(workspace, out, registry_ids=registry_ids)
```

Both emitter APIs default `registry_ids` to `None` for compatibility with
direct callers.

The Protobuf emitter passes the parsed `ModelVersion` or `ProjectionVersion`
to manifest rendering so it can compute the canonical signature. It does not
derive canonical identity from generated `.proto` text or from
`schema_fingerprint`.

`emit_grpc()` continues to generate services from per-schema manifests. It
retargets the semantic bundles and enriched schema manifests unchanged, so
the `protobuf` and `grpc` targets expose identical payload contracts.

## 7. Error and Compatibility Behavior

- Existing validation remains authoritative for dangling, cyclic, and
  over-depth semantic chains.
- Ambiguous unqualified semantic references fail with a clear emitter error
  naming the candidate qualified declarations.
- Registry IDs must remain positive `u32` values. Invalid supplied values fail
  before malformed manifest metadata is emitted.
- Unsupported semantic terminal types are not expected after validation; if
  encountered through a direct low-level call, emission fails clearly rather
  than falling back to `bytes`.
- Wrapper messages are an intentional wire change from the previous
  semantic-`NamedType` fallback. A semantic field becomes a
  length-delimited message containing the mapped scalar at field number `1`.
- Existing primitive fields, enums, field numbers, model/projection packages,
  and ordinary unsupported `NamedType` fields remain unchanged.
- The existing primitive-focused wire golden fixture contains no semantic
  reference and must remain byte-for-byte unchanged.
- Adding or removing an allocated registry ID changes manifest text but does
  not change `.proto` wire shape or `schema_fingerprint`.
- Changing a semantic declaration's terminal representation changes the
  wrapper bundle and the consuming schema's field type metadata. Canonical
  Modelable signatures continue to follow normalized source contracts.

## 8. Verification

Behavior tests in `cli/tests/test_emit_protobuf.py` must cover:

- deterministic shared semantic bundles and stable packages;
- direct scalar wrappers for numeric, UUID, timestamp, decimal, and fixed
  binary terminals;
- chained aliases flattened to terminal scalars;
- same-domain and cross-domain model fields;
- directly mapped projection fields;
- arrays of semantic types;
- sorted, deduplicated imports and semantic manifest entries;
- canonical `modelable_signature` equality with
  `compute_version_signature()`;
- separation from `schema_fingerprint`;
- registry-backed semantics with supplied allocations;
- omission without allocations and for non-registry semantics;
- invalid registry ID rejection;
- ambiguous semantic reference rejection;
- unchanged ordinary `NamedType` and map fallbacks; and
- repeated emission byte-for-byte determinism.

CLI tests must prove that persisted ledger allocations reach both
`--target protobuf` and `--target grpc`.

gRPC tests must prove that semantic bundles and enriched schema manifests are
retargeted unchanged and service generation still consumes the field list.

The existing Docker codegen smoke must compile generated Protobuf containing a
semantic wrapper, including a cross-domain import.

Repository verification includes the four mandatory CLI gates and strict
MkDocs:

```text
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
```

## 9. Documentation and Roadmap

Implementation updates:

- `docs/compiler-reference.md`;
- `docs/cli-reference.md`;
- `docs/wire-format-contract.md`;
- `CHANGELOG.md`; and
- Priority 1 item 2 in `ROADMAP.md`.

Only item 2 is marked shipped. Protobuf map/index fidelity, descriptor sets,
reserved fields, compatibility validation, and Scalable consumer fixtures
remain later dependency-ordered slices.

This design and its
[implementation plan](../../plans/archived/2026-07-17-protobuf-semantic-identity.md) stay
in the active `docs/superpowers/specs/` and `docs/superpowers/plans/`
directories until the implementation merges. They are archived immediately
after merge.

## 10. Out of Scope

- General Protobuf support for named model/value-object references.
- Dotted or otherwise qualified semantic type syntax in `.mdl`.
- Map encoding, nested object encoding, or primary/secondary index metadata.
- Custom Protobuf options for registry IDs or canonical signatures.
- Descriptor-set generation.
- Deleted-field reservations and compatibility validation.
- Changes to the generated Scalable service envelope schema.
- A standalone semantic-types manifest format.
- Non-Protobuf nominal semantic-type support.
- Scalable consumer/adaptor removal; that follows a released Modelable
  version containing this feature.

## 11. Acceptance Criteria

The slice is complete when a Protobuf or gRPC consumer can compile a model or
projection that references a semantic type, observe a stable fully qualified
wrapper message owned by the declaring domain, and read the semantic ref,
allocated registry ID, canonical Modelable signature, and target-specific
wire fingerprint from the generated schema manifest without parallel
handwritten identity metadata.
