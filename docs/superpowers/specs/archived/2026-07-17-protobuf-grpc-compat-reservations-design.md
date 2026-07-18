# Protobuf and gRPC Compatibility Reservations Design

Date: 2026-07-17

## 1. Purpose

Modelable now emits Protobuf payload schemas, Scalable-oriented gRPC service
profiles, descriptor artifacts, schema identity, semantic identity, maps, and
read-index metadata. The remaining Priority 1 wire-contract gap is enforcement:
authors need a source-controlled way to reserve deleted Protobuf field numbers
and names, and CI needs a target-aware compatibility command that rejects unsafe
Protobuf/gRPC transport changes before they reach consumers.

This design defines the next cohesive slice: source-level reservations plus
`validate-compat --target protobuf|grpc`.

## 2. Context

The accepted archived
[Scalable Protobuf and gRPC Support Design](2026-07-04-scalable-protobuf-grpc-support-design.md)
requires stable field numbers, reserved deleted numbers and names, and
Protobuf/gRPC compatibility validation. Current behavior is intentionally
simpler:

- Protobuf field numbers are assigned from declaration order.
- Inline enum values are assigned from declaration order after a generated
  `_UNSPECIFIED = 0` value.
- Schema manifests record generated field names, Protobuf names, field numbers,
  target types, semantic refs, map metadata, fingerprints, and indexes.
- gRPC service manifests record service proto names and read-index metadata.
- Generic `modelable diff` classifies source-model field changes, but does not
  enforce target-specific wire compatibility.

Descriptor artifacts are useful as a compiled contract surface, but comparing
descriptor binaries would require external `protoc` availability and would make
compatibility validation depend on a toolchain. This first validator should be
deterministic and dependency-free by comparing generated manifests and service
metadata.

## 3. Goals

- Add explicit `.mdl` syntax for Protobuf field reservations on model and
  projection versions.
- Emit reservations into generated `.proto` messages.
- Record reservations in `schema-manifest.json`.
- Add `modelable validate-compat --from OLD --to NEW --target protobuf|grpc`.
- Detect field-number reuse, field-name reuse, unsafe target type changes,
  unsafe requiredness changes, inline enum value reuse, package/message/service
  identity changes, and gRPC read-index compatibility changes.
- Classify results using the roadmap statuses:
  `wire_compatible`, `read_compatible`, `requires_read_rebuild`,
  `requires_state_migration`, and `breaking`.
- Keep validation independent of `protoc`; descriptor generation remains
  compile-time behavior only when `--descriptor-set` is requested.

## 4. Non-Goals

- No global field-number pinning syntax in this slice. Existing declaration-order
  numbering remains the assignment mechanism; compatibility validation makes
  unsafe reordering and deletion visible.
- No rebuild or migration declaration syntax in this slice. The validator can
  classify index changes as `requires_read_rebuild`, but it will not accept a
  user-declared rebuild plan yet.
- No descriptor-binary diffing.
- No domain-specific Scalable service generation.
- No compatibility validation for every non-Protobuf target.

## 5. Reservation Syntax

Reservations are declared inside a model or projection body:

```mdl
entity Customer @ 2 (additive) {
  reserved protobuf {
    numbers: [3, 7]
    names: ["legacy_status"]
  }

  @key customerId: uuid
  displayName?: string
}
```

The first slice only accepts `reserved protobuf`. `grpc` uses the same payload
message reservations because the gRPC target reuses generated Protobuf payload
schemas.

Rules:

- `numbers` is a list of positive integers.
- `names` is a list of source field names or generated Protobuf field names.
- A reservation block may omit either `numbers` or `names`, but not both.
- Duplicate numbers or names inside a version are invalid.
- A declared field may not use a reserved source name, generated Protobuf name,
  or field number in the same version.
- Reservations belong to a specific version. A deleted field from version `N`
  must be reserved in version `N+1` or any later replacement version that is
  being validated against `N`.

The IR should represent this as a version-local structure, for example:

```python
class ProtobufReservations(BaseModel):
    numbers: list[int] = Field(default_factory=list)
    names: list[str] = Field(default_factory=list)
```

`ModelVersion` and `ProjectionVersion` should each gain
`protobuf_reservations: ProtobufReservations | None`.

## 6. Protobuf Emission

For each model or projection message, the Protobuf emitter should render
reservation declarations before fields:

```proto
message Customer {
  reserved 3, 7;
  reserved "legacy_status";

  string customer_id = 1;
  optional string display_name = 2;
}
```

The schema manifest should include:

```json
{
  "reservations": {
    "numbers": [3, 7],
    "names": ["legacy_status"]
  }
}
```

Reservation rendering must not change `schema_fingerprint` unless the emitted
wire contract changes. A reservation is a wire-contract guard, so adding or
removing reservations should affect the fingerprint.

## 7. Compatibility Command

Add a new top-level command:

```text
modelable validate-compat --from OLD --to NEW --target protobuf
modelable validate-compat --from OLD --to NEW --target grpc
```

`OLD` and `NEW` are files or directories loadable as Modelable workspaces.

The command should:

1. Load both workspaces.
2. Generate target artifacts in memory into temporary output roots.
3. Compare schema manifests by logical ref.
4. Print a deterministic report.
5. Exit `0` only for accepted target compatibility statuses.

For this first slice:

- `wire_compatible` exits `0`.
- `read_compatible` exits `0`.
- `requires_read_rebuild`, `requires_state_migration`, and `breaking` exit
  non-zero.

Future flags may allow known rebuild or migration statuses after the project
has explicit rebuild/migration declarations.

## 8. Protobuf Compatibility Rules

For each ref present in both old and new manifests:

- Package name, message name, and schema kind must remain unchanged.
- Existing field numbers must not be reused for a different field unless the
  old field explicitly declared a compatible rename through existing
  deprecation replacement metadata and the generated target type is unchanged.
- Existing source names and Protobuf names must not be reused for a different
  field.
- Removed fields must have both their old field number and old Protobuf name
  reserved in the new version.
- Target type changes are `breaking`, including scalar kind changes, semantic
  wrapper identity changes, map key/value type changes, fixed-length binary
  length changes, and array/repeated shape changes.
- Optional-to-required changes are `breaking`.
- Required-to-optional changes are `wire_compatible`.
- Added optional fields are `wire_compatible`.
- Added required fields are `breaking` for old readers/writers.
- Inline enum changes are compared by generated enum member number:
  - Adding a new enum value at the end is `wire_compatible`.
  - Reordering existing values is `breaking`.
  - Reusing a removed enum value number for a different value is `breaking`.
  - Removing an enum value without reservation remains `breaking`. This slice
    may report the failure without adding enum reservation syntax; enum
    reservations can be a follow-up if needed.

For refs present only in the new workspace, the status is `wire_compatible`.
For refs present only in the old workspace, the status is `breaking`.

## 9. gRPC Compatibility Rules

The gRPC validator reuses the Protobuf payload comparison and additionally
compares service manifests:

- Service proto filename must remain stable for an unchanged ref.
- Service package and generated service names must remain stable.
- Removing an entity read service surface is `breaking`.
- Adding read indexes is `read_compatible`.
- Removing a read index, changing its key fields, changing its sort fields, or
  changing uniqueness is `requires_read_rebuild`.
- Changing the primary index key fields is `requires_state_migration`.
- If any payload schema comparison is `breaking`, the gRPC result is `breaking`.
- If payloads are wire-compatible but read indexes require rebuild, the gRPC
  result is `requires_read_rebuild`.

## 10. Report Shape

Human-readable output should be stable and concise:

```text
target: protobuf
status: breaking

- billing.Customer@1 -> billing.Customer@2: removed field legacyStatus number 3 is not reserved
- billing.Customer@1 -> billing.Customer@2: field status reuses enum value 2 for a different member
```

JSON output is not required in the first slice, but internal report structures
should be typed so JSON output can be added later without rewriting the
validator.

Suggested internal model:

```python
class TargetCompatibilityFinding(BaseModel):
    ref: str
    status: str
    code: str
    message: str
    old_path: str | None = None
    new_path: str | None = None
```

## 11. Error Handling

- Invalid reservation syntax is a parse or validation error.
- Duplicate reservation entries are a validation error.
- A field colliding with a same-version reservation is a validation error.
- Unsupported targets for `validate-compat` fail with a Click error listing
  supported targets.
- Missing or unloadable `--from`/`--to` paths fail before any comparison.
- Emitter failures are surfaced as compatibility command failures with the
  original target error text.

## 12. Testing Strategy

Add focused tests for:

- Parsing reservation blocks in models and projections.
- Rejecting duplicate reservation numbers/names.
- Rejecting fields that collide with same-version reservations.
- Protobuf emitter rendering `reserved` declarations.
- Schema manifests including reservations.
- `validate-compat --target protobuf` passing safe additive optional fields.
- `validate-compat --target protobuf` failing removed fields without
  reservations.
- `validate-compat --target protobuf` passing removed fields with number/name
  reservations.
- `validate-compat --target protobuf` failing declaration-order field-number
  reuse/reordering.
- `validate-compat --target protobuf` failing inline enum reorder/reuse.
- `validate-compat --target grpc` surfacing payload failures.
- `validate-compat --target grpc` classifying read-index changes as
  `requires_read_rebuild`.

Run the existing Protobuf/gRPC emitter tests and the full mandatory CLI gate
before publishing.

## 13. Documentation Updates

Update:

- `docs/language-reference.md` with `reserved protobuf` syntax.
- `docs/cli-reference.md` with `validate-compat`.
- `docs/compiler-reference.md` with Protobuf/gRPC compatibility status.
- `docs/wire-format-contract.md` to replace the current "no compiler guard"
  caveat with the new guarded behavior and remaining limits.
- `CHANGELOG.md` and `ROADMAP.md`.

## 14. Open Follow-Ups

- Field-number pinning syntax if declaration-order numbering becomes too
  restrictive.
- Enum reservation syntax.
- Explicit read-rebuild and state-migration declarations.
- JSON output for compatibility reports.
- Descriptor-binary comparison as an optional stricter smoke when `protoc` is
  available.
