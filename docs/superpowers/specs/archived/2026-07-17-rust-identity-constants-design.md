# Rust Identity Constants — Design

Date: 2026-07-17

## 1. Purpose

Modelable allocates stable small-integer IDs for registry-backed semantic
types and computes a canonical SHA-256 signature for every versioned model and
projection. The Rust emitter currently exposes an allocated registry ID only
as a doc comment and does not expose a version or canonical signature in
generated code.

This forces Rust consumers to maintain parallel constants. Scalable currently
hand-writes its runtime-kernel-configuration schema ID and version even though
the ID is already committed in `registry-ids.lock` and the version is already
declared in `.mdl`.

The first item in [ROADMAP.md](../../../../ROADMAP.md) Priority 1 is therefore a
focused Rust-emitter slice: make Modelable's existing identity data directly
consumable as associated constants without introducing a dependency on
Scalable types or a second identity scheme.

## 2. Goals

This slice must:

- expose an allocated registry ID on each generated registry-backed semantic
  newtype;
- expose the declared version and canonical Modelable content signature on
  each generated model and projection type;
- use associated constants so generated modules do not accumulate colliding
  global names;
- reuse `compute_version_signature()` as the sole source of canonical
  signatures;
- preserve deterministic Rust output and the existing behavior of direct
  emitter calls that do not supply registry allocations; and
- keep target-specific artifact hashes and wire fingerprints separate from
  canonical Modelable identity.

## 3. Generated Rust API

### 3.1 Registry-backed semantic types

When `emit_rust()` receives an allocated ID for a
`semantic ... { registry: true }` declaration, the generated newtype gains an
associated `u32` constant:

```rust
/// registry id: 1
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, serde::Serialize, serde::Deserialize)]
#[serde(transparent)]
pub struct RuntimeKernelConfigSchemaId(pub u32);

impl RuntimeKernelConfigSchemaId {
    pub const REGISTRY_ID: u32 = 1;
}
```

The existing doc comment remains for source readability and compatibility.
The constant is emitted only when an allocation is supplied. A direct
`emit_rust()` caller that omits `registry_ids` receives the current newtype
without `REGISTRY_ID`; the emitter must not invent `0` or another sentinel.

An ordinary semantic type without `registry: true` never gains
`REGISTRY_ID`.

### 3.2 Models and projections

Every generated versioned model and projection gains two associated constants:

```rust
impl RuntimeKernelConfigV1 {
    pub const SCHEMA_VERSION: u32 = 1;
    pub const SCHEMA_CONTENT_SIGNATURE: [u8; 32] = [
        0x00, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77,
        0x88, 0x99, 0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff,
        0x00, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77,
        0x88, 0x99, 0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff,
    ];
}
```

`SCHEMA_VERSION` is the integer declared after `@` in `.mdl`.

`SCHEMA_CONTENT_SIGNATURE` is the 32-byte value represented by the canonical
hex digest returned by `compute_version_signature(domain, name, version)`.
Hexadecimal byte literals make comparison with the canonical digest readable
while retaining a dependency-free `[u8; 32]` API.

Scalable can consume these primitives without generated Modelable code
depending on Scalable:

```rust
let schema_id = RuntimeKernelConfigSchemaId::REGISTRY_ID;
let schema_version = RuntimeKernelConfigV1::SCHEMA_VERSION;
let signature = Hash256(RuntimeKernelConfigV1::SCHEMA_CONTENT_SIGNATURE);
```

This slice does not add a model-level `SCHEMA_ID`. Registry allocation belongs
to the explicit registry-backed semantic declaration, not implicitly to every
model or projection.

## 4. Data Flow and Placement

The implementation remains local to the existing Rust emission path:

1. `modelable compile` reads and updates `registry-ids.lock`.
2. The compile command passes the resulting `registry_ids` map to
   `emit_rust()`, as it does today.
3. `_emit_semantic_type()` renders `REGISTRY_ID` when `allocated_id` is not
   `None`.
4. `_emit_model()` and `_emit_projection()` call
   `compute_version_signature()` with the same domain, declaration name, and
   parsed version they are already rendering.
5. A small Rust-emitter helper converts the 64-character digest into 32
   deterministic hexadecimal byte literals.

The associated `impl` block is rendered immediately after its owning
top-level struct and before conversion implementations or nested generated
definitions. Nested helper structs and enums are implementation details and do
not receive schema identity constants.

No precomputed cross-emitter identity map is introduced. A future cross-target
identity project may justify one, but it would widen compiler APIs without
benefit to this Rust-only slice.

## 5. Identity Boundaries

The three identity values serve different purposes:

| Value | Source | Meaning |
|---|---|---|
| `REGISTRY_ID` | `registry-ids.lock` | Stable small integer allocated to an explicit registry-backed semantic type |
| `SCHEMA_VERSION` | `.mdl` declaration | Declared version of one model or projection |
| `SCHEMA_CONTENT_SIGNATURE` | `compute_version_signature()` | Canonical SHA-256 identity of the normalized published contract |

The Rust artifact's `EmittedArtifact.content_hash` remains a hash of generated
Rust text. Protobuf `schema_fingerprint` remains target-specific wire metadata.
Neither may be substituted for `SCHEMA_CONTENT_SIGNATURE`.

## 6. Error and Compatibility Behavior

- `modelable compile` continues to enforce missing, orphaned, and conflicting
  registry allocations through the existing ledger workflow.
- Direct emitter calls without a registry map remain supported and omit
  `REGISTRY_ID`.
- Digest conversion treats a non-64-character or non-hexadecimal value as an
  internal invariant violation. The helper must fail clearly rather than emit
  malformed Rust.
- Adding associated constants is source-compatible for generated Rust
  consumers. Existing struct construction, serialization, conversions, and
  wire behavior remain unchanged.
- The signature constant intentionally changes when the canonical Modelable
  contract changes. It does not change because of Rust formatting or emitter
  implementation changes alone.

## 7. Verification

Behavior tests in `cli/tests/test_emit_rust.py` must cover:

- a registry-backed semantic type with an allocation emits the exact
  `REGISTRY_ID`;
- a registry-backed semantic type without a supplied allocation omits the
  constant;
- a non-registry semantic type omits the constant even if unrelated
  allocations exist;
- a model emits its declared `SCHEMA_VERSION`;
- a projection emits its declared `SCHEMA_VERSION`;
- model and projection signature bytes reconstruct the exact digest returned
  by `compute_version_signature()`;
- repeated emission is byte-for-byte deterministic; and
- generated Rust containing the constants compiles in the existing Rust
  generated-output smoke.

Documentation updates must cover the generated API in
`docs/compiler-reference.md`, record the user-visible addition in
`CHANGELOG.md`, and mark only Priority 1 item 1 as shipped in `ROADMAP.md` when
implementation is complete.

The repository's four mandatory CLI gates and the strict documentation build
must pass before publication.

## 8. Out of Scope

- Protobuf semantic-type resolution or registry IDs in schema manifests.
- Descriptor sets, deleted-field reservations, or compatibility validation.
- Emitting nominal semantic types in non-Rust targets.
- Adding registry-ID or signature lookup to `modelable inspect`.
- A generated `SchemaIdentity` struct or dependency on Scalable crates.
- Removing Scalable's temporary handwritten adapter; that follow-up occurs
  after Scalable consumes a released Modelable version containing these
  constants.
- Assigning registry IDs implicitly to models or projections that do not
  declare a registry-backed semantic ID.

## 9. Acceptance Criteria

The slice is complete when a Rust consumer can obtain the allocated schema ID,
declared model or projection version, and canonical contract signature entirely
from generated code, wrap those primitives in its own domain types, and remove
parallel handwritten values without changing generated wire behavior.
