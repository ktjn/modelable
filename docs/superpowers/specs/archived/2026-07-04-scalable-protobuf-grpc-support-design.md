# Scalable Protobuf and gRPC Support Design

Date: 2026-07-04

## 1. Purpose

Scalable, a sibling project at `../scalable`, needs Modelable to generate the
binary protocol artifacts for its external interface. Scalable will use
Modelable as the source of truth for command payloads, result payloads, read
replicas, secondary indexes, schema identity, and generic protocol envelopes.

This document defines the Modelable capability set needed by Scalable. It is an
accepted design target, not an implementation plan.

## 2. Context

Modelable already compiles `.mdl` sources to multiple artifact formats. The
Scalable external-interface design adds a concrete consumer for a standard
binary protocol target:

- Protobuf is the first binary payload encoding.
- gRPC over HTTP/2 is the first transport profile.
- Protobuf and gRPC remain generated targets, not sources of truth.
- Scalable's engine API remains generic and app-bound.
- Domain-specific SDKs may wrap generic calls, but Modelable should not make
  domain-specific engine RPC methods the primary runtime surface.

Scalable's corresponding design is in
`../scalable/docs/superpowers/specs/2026-07-04-modelable-scalable-protocol-support-design.md`.

## 3. Design Principles

- `.mdl` remains the reviewed contract source.
- Protobuf and gRPC are generated projections.
- Generated outputs are deterministic.
- Field numbers, schema ids, and fingerprints are stable and reviewable.
- Compatibility validation rejects unsafe wire changes.
- Read access patterns are explicit Modelable metadata, not inferred from field
  names.
- Generated Scalable protocol artifacts preserve app-bound generic command and
  read semantics.

## 4. Required Capabilities

Modelable should add:

- a Protobuf emitter;
- a Scalable gRPC profile emitter;
- deterministic schema identity and fingerprint metadata;
- descriptor-set export;
- generated schema and service manifests;
- primary-key, secondary-index, and sort-key metadata;
- generated Scalable envelope and read contracts;
- Protobuf/gRPC compatibility validation.

These capabilities should reuse the existing compiler, resolver, compatibility,
lineage, and generated-artifact patterns rather than creating a parallel schema
system.

## 5. Protobuf Target

The CLI should support:

```text
modelable compile ./models --target protobuf --out ./dist/protobuf
```

The target emits `.proto` files, descriptor sets, and a schema manifest. It must
define deterministic mappings for:

- package names;
- message names;
- field names;
- field numbers;
- enum names and values;
- optional and repeated fields;
- bytes;
- timestamps;
- ids;
- decimals or other precise numeric values;
- nested references;
- versioned model and projection names.

Field numbers are part of the generated contract. Once assigned, they must
remain stable. Deleted fields reserve their previous field numbers and names.
Renames may preserve a field number only when the model records an explicit
compatible rename.

## 6. Scalable gRPC Profile

The CLI should support:

```text
modelable compile ./models --target grpc --out ./dist/grpc
```

The `grpc` target emits the Scalable service profile over generated Protobuf
messages. The engine-facing service shape is generic:

```text
service CommandService {
  rpc SubmitCommand(CommandEnvelope) returns (CommandResultEnvelope);
  rpc CommandStream(stream CommandEnvelope)
      returns (stream CommandResultEnvelope);
}

service EntityReadService {
  rpc GetEntity(GetEntityRequest) returns (ReadResultEnvelope);
  rpc ListEntities(ListEntitiesRequest) returns (ListResultEnvelope);
  rpc ListByIndex(ListByIndexRequest) returns (ListResultEnvelope);
}
```

Modelable may later generate domain-specific client SDK wrappers, but those
wrappers are not the Scalable engine API.

## 7. Schema Identity

Generated artifacts should include:

```text
SchemaIdentity
  model_id
  model_name
  model_version
  schema_id
  schema_fingerprint
  source_ref
  generated_at
  target
```

`schema_fingerprint` is deterministic for the normalized Modelable contract and
target projection. It changes when the binary wire contract changes. Scalable
uses the schema id and fingerprint during app schema registration and payload
validation.

## 8. Protocol Envelope Contracts

Modelable should be able to define and generate the Scalable protocol
contracts:

```text
CommandEnvelope
CommandResultEnvelope
ReadConsistency
ReadResultEnvelope
ListResultEnvelope
GetEntityRequest
ListEntitiesRequest
ListByIndexRequest
IndexMetadata
SchemaIdentity
```

The generated contracts must preserve:

- protocol version;
- envelope version;
- application command model version;
- command type;
- command id;
- idempotency key;
- causation id;
- correlation id;
- deadline;
- target hint;
- payload codec;
- payload schema id;
- binary payload bytes;
- result status;
- retry hint;
- committed log position;
- applied log position;
- source commit position;
- freshness status.

## 9. Index and Read Metadata

Modelable needs first-class metadata for Scalable's default read replicas and
secondary indexes:

```text
primary_key
secondary_index
sort_key
unique
index_name
index_version
```

The exact `.mdl` syntax is an implementation-plan decision, but the semantics
are required:

- each durable entity can declare a primary key;
- secondary indexes are declared explicitly;
- index key fields and sort fields are known at compile time;
- index names are stable and versioned;
- uniqueness is explicit;
- adding or changing an index is visible as a schema and rebuild event;
- generated read APIs expose only declared indexes.

## 10. Compatibility Validation

Modelable should validate Protobuf and gRPC compatibility:

```text
modelable validate-compat --from old.mdl --to new.mdl --target protobuf
modelable validate-compat --from old.mdl --to new.mdl --target grpc
```

The validator must reject:

- field number reuse;
- deleted field name reuse without reservation;
- deleted field number reuse without reservation;
- enum value number reuse;
- incompatible scalar type changes;
- incompatible requiredness changes;
- changed primary-key semantics;
- removed secondary indexes without a migration path;
- changed index key or sort fields without a rebuild declaration;
- changed envelope metadata semantics;
- changed package, message, or service names that break clients.

Accepted changes should be classified as:

```text
wire_compatible
read_compatible
requires_read_rebuild
requires_state_migration
breaking
```

## 11. Generated Artifact Layout

The output should be deterministic and easy for Scalable to consume:

```text
dist/protobuf/
  <domain>/<model-version>/*.proto
  <domain>/<model-version>/descriptor.pb
  <domain>/<model-version>/schema-manifest.json

dist/grpc/
  <domain>/<model-version>/*.proto
  <domain>/<model-version>/descriptor.pb
  <domain>/<model-version>/schema-manifest.json
  <domain>/<model-version>/service-manifest.json
```

Manifest files summarize schema ids, fingerprints, command types, result types,
entity types, read indexes, and service bindings. They are generated artifacts
and must be reproducible from the same `.mdl` source.

## 12. Verification Requirements

Future implementation work should include:

- fixture `.mdl` files that compile to Protobuf;
- fixture `.mdl` files that compile to the Scalable gRPC profile;
- golden `.proto`, descriptor, and manifest tests;
- compatibility tests for safe additive changes;
- negative compatibility tests for field number reuse, enum value reuse, unsafe
  type changes, and unsafe requiredness changes;
- tests for primary-key and secondary-index metadata emission;
- tests for generated read contracts and envelope contracts;
- a Scalable fixture that can register generated descriptors and manifests.

Because Protobuf/gRPC are generated artifact formats, implementation changes
must also include deterministic emitter tests and any relevant generated-output
smokes required by `docs/maintainers.md`.

## 13. Non-Goals

- No JSON-first Scalable ingress target.
- No hand-written `.proto` files as the source of truth for Scalable-owned
  contracts.
- No domain-specific Scalable engine services as the primary profile.
- No automatic secondary indexes inferred from ordinary field names.
- No requirement to implement every future binary codec before the first
  Protobuf/gRPC implementation.

## 14. Open Questions

- Exact `.mdl` syntax for primary keys, secondary indexes, sort keys, and index
  rebuild declarations.
- Whether `protobuf` and `grpc` are separate targets or one target with
  profiles.
- Where stable Protobuf field numbers are stored and reviewed.
- Whether generated SDK wrappers belong in Modelable, Scalable, or a later
  application-tooling package.
- Whether compatibility validation extends an existing command or introduces a
  new CLI command.
