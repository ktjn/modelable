# Protobuf and gRPC Descriptor Artifacts - Design

Date: 2026-07-17

## 1. Purpose

Priority 1 item 4 in [ROADMAP.md](../../../ROADMAP.md) makes generated
Protobuf and Scalable gRPC contracts enforceable over time. This first slice
adds compiled descriptor artifacts as a deterministic output surface for
`compile --target protobuf` and `compile --target grpc`.

Descriptor sets are the next dependency-ordered step because compatibility
validation needs a concrete compiled wire artifact to compare. Field-number
reservations and Protobuf/gRPC compatibility classification remain follow-up
slices.

## 2. Goals

This slice must:

- emit Protobuf `FileDescriptorSet` artifacts for generated Protobuf payload
  schemas when descriptor generation is requested;
- emit descriptor artifacts for the Scalable gRPC profile when descriptor
  generation is requested;
- include descriptor artifact metadata in schema and service manifests;
- verify generated `.proto` files with a real `protoc` boundary rather than
  trusting text generation alone;
- preserve existing `compile --target protobuf` and `compile --target grpc`
  behavior when descriptor generation is not requested;
- fail with an actionable error when descriptor generation is requested but
  `protoc` is unavailable or generated `.proto` files are invalid; and
- update compiler, CLI, wire-format, changelog, and roadmap docs.

This slice must not:

- introduce field-number or field-name reservation syntax;
- add `validate-compat --target protobuf|grpc`;
- classify Protobuf or gRPC compatibility changes;
- change existing `.proto`, schema manifest, or service manifest shapes except
  for adding descriptor metadata when descriptors are emitted;
- add a Python runtime dependency on `protobuf`, `grpcio`, or `grpcio-tools`;
  or
- require Docker for normal descriptor generation.

## 3. User Interface

Descriptor generation is explicitly requested with a compile flag:

```text
modelable compile ./models --target protobuf --out ./dist/protobuf --descriptor-set
modelable compile ./models --target grpc --out ./dist/grpc --descriptor-set
```

The flag name is singular because each schema or service directory receives its
own descriptor artifact. A future aggregate descriptor bundle can add a separate
flag without changing this behavior.

The default remains unchanged:

```text
modelable compile ./models --target protobuf --out ./dist/protobuf
modelable compile ./models --target grpc --out ./dist/grpc
```

Existing users who do not ask for descriptors should not need `protoc` on
`PATH`.

When `--descriptor-set` is present, the compiler requires a `protoc` executable
on `PATH`. If it is missing, compilation fails with:

```text
descriptor generation requires protoc on PATH
```

If `protoc` rejects the generated files, compilation fails and includes the
target ref and `protoc` stderr so the broken generated surface is reviewable.

## 4. Output Layout

For `protobuf`, each model or projection version directory gains one
descriptor artifact:

```text
dist/protobuf/
  <domain>/semantic-types.proto
  <domain>/<Name>.v<version>/<Name>.v<version>.proto
  <domain>/<Name>.v<version>/<Name>.v<version>.descriptor.pb
  <domain>/<Name>.v<version>/schema-manifest.json
```

For `grpc`, each model or projection version directory gains one service
descriptor artifact:

```text
dist/grpc/
  <domain>/semantic-types.proto
  <domain>/<Name>.v<version>/<Name>.v<version>.proto
  <domain>/<Name>.v<version>/<Name>.v<version>.grpc.proto
  <domain>/<Name>.v<version>/<Name>.v<version>.grpc.descriptor.pb
  <domain>/<Name>.v<version>/schema-manifest.json
  <domain>/<Name>.v<version>/service-manifest.json
```

The `grpc` descriptor compiles the service profile and imports the generated
payload schema plus any semantic bundles needed by that payload. The payload
`.proto` remains present as an ordinary emitted artifact, but the descriptor
artifact represents the gRPC service contract.

Semantic bundles do not receive standalone descriptors in this slice. They are
included transitively via `--include_imports` in descriptors for schemas or
services that import them.

## 5. Descriptor Generation Boundary

Modelable should not hand-build binary `FileDescriptorSet` messages in Python
for this slice. It should invoke the `protoc` executable after writing the
generated `.proto` files to the output tree.

Rationale:

- `protoc` is the canonical compiler for descriptor-set semantics.
- The repository already uses `protoc` in the Docker smoke test to prove
  generated Protobuf text is valid.
- Avoiding a new Python Protobuf dependency keeps the CLI lightweight and
  avoids version coupling.

The implementation should use a small internal helper, for example:

```python
def compile_descriptor_set(
    *,
    proto_root: Path,
    proto_files: list[Path],
    out_path: Path,
    include_imports: bool = True,
) -> bytes:
    ...
```

The helper is responsible for:

- resolving `protoc` from `PATH`;
- passing `-I <proto_root>`;
- passing every input `.proto` path relative to `proto_root`;
- writing to a temporary descriptor path before reading the bytes back;
- returning the descriptor bytes so the ordinary artifact-writing path can
  still compute `content_hash`; and
- surfacing clear exceptions that name the target and underlying `protoc`
  failure.

Generated descriptor artifacts use `bytes` content in `EmittedArtifact`.
Existing artifact writing already handles bytes for binary outputs; if it does
not, this slice must add that support in the compile writer rather than encode
descriptors as base64 text.

## 6. Manifest Metadata

When `--descriptor-set` is not used, manifests remain unchanged.

When descriptors are emitted, `schema-manifest.json` adds:

```json
{
  "descriptor": {
    "path": "Order.v1.descriptor.pb",
    "content_hash": "<sha256>",
    "include_imports": true
  }
}
```

The descriptor path is relative to the manifest directory. The hash is the same
content hash format Modelable already uses for emitted artifacts.

When gRPC descriptors are emitted, `service-manifest.json` adds:

```json
{
  "descriptor": {
    "path": "Order.v1.grpc.descriptor.pb",
    "content_hash": "<sha256>",
    "include_imports": true
  }
}
```

The schema manifest produced as part of `compile --target grpc` may also include
payload descriptor metadata if the implementation chooses to compile payload
descriptors before service descriptors. The required artifact for this slice is
the service descriptor in the service manifest.

Descriptor metadata is target-specific. It must not change
`modelable_signature`, because canonical Modelable identity is independent of a
generated target artifact. Descriptor metadata may affect future
target-specific compatibility validation, but it should not change the existing
`schema_fingerprint` in this slice unless the generated `.proto` contract
changes.

## 7. Error Handling

Descriptor generation is a strict compile boundary when requested:

- missing `protoc` fails the command;
- invalid generated `.proto` fails the command;
- unreadable descriptor output fails the command; and
- descriptor helper failures must include the logical target ref where possible.

The command should not silently skip descriptors. Silent omission would make CI
green while leaving Scalable without the compiled artifacts this slice is meant
to produce.

## 8. Testing Strategy

Unit and CLI tests should cover:

- `compile --target protobuf --descriptor-set` writes
  `<Name>.v<version>.descriptor.pb`;
- `compile --target grpc --descriptor-set` writes
  `<Name>.v<version>.grpc.descriptor.pb`;
- schema and service manifests include descriptor path/hash metadata only when
  descriptors are requested;
- descriptor generation invokes the helper with deterministic proto root and
  relative proto file paths;
- missing `protoc` produces an actionable failure; and
- default `compile --target protobuf|grpc` still works without descriptor
  generation.

Tests should not require Docker for the normal unit suite. The descriptor helper
can be tested by stubbing the `protoc` executable with a tiny script that writes
deterministic bytes to the requested `--descriptor_set_out` path. Existing
Docker smoke tests may continue to use real `protoc` as an opt-in external
validator.

## 9. Documentation Updates

This slice should update:

- `docs/compiler-reference.md` to move descriptor-set generation from deferred
  to shipped for the opt-in descriptor flag;
- `docs/cli-reference.md` to document `--descriptor-set`;
- `docs/wire-format-contract.md` to state that descriptor artifacts are the
  compiled contract surface used by future compatibility validation;
- `CHANGELOG.md` with the new descriptor artifact capability; and
- `ROADMAP.md` to mark descriptor artifacts shipped while keeping field
  reservations and Protobuf/gRPC compatibility validation active under Priority
  1 item 4.

## 10. Follow-up Work

After this slice, the next enforceability slices are:

1. field-number and field-name reservation metadata;
2. `validate-compat --target protobuf|grpc` using generated manifest and
   descriptor surfaces;
3. compatibility classifications for `wire_compatible`,
   `read_compatible`, `requires_read_rebuild`, `requires_state_migration`, and
   `breaking`; and
4. Scalable-side registration fixtures that consume descriptors and manifests
   without duplicating Modelable-owned constants.
