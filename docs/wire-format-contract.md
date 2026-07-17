# Wire-Format Contract: Rust and Protobuf Emitters

> **Authority:** This document pins the byte-level encoding guarantees the
> Rust (`emitters/rust.py`) and Protobuf (`emitters/protobuf.py`) emitters
> actually provide today, verified directly against their source. It does
> not describe aspirational behavior — every rule below is enforced by the
> golden-fixture regression suite at
> [`cli/tests/fixtures/wire_golden/`](https://github.com/ktjn/modelable/tree/main/cli/tests/fixtures/wire_golden)
> (test file: `cli/tests/test_wire_golden.py`).

## 1. Status and Scope

**What this document guarantees:** compiling the same `.mdl` source with
the same compiler version produces byte-identical Rust and Protobuf
output, every time. That determinism is not new — the emitters were
already pure functions of the parsed IR — but it wasn't previously pinned
by a regression test. This document and the accompanying golden fixture
close that gap.

**What this document does not guarantee:**

- **Wire compatibility across schema changes.** Reordering fields in a
  `.mdl` model, for example, silently renumbers every Protobuf field
  after the moved one — a wire-breaking change with no compiler guard
  today. Validating *compatibility* between two versions of a schema
  (`modelable validate-compat`) is tracked separately in
  [`2026-07-04-scalable-protobuf-grpc-support-design.md`](superpowers/specs/archived/2026-07-04-scalable-protobuf-grpc-support-design.md)
  and is not implemented. Section 4 below calls out each place this
  matters.
- **Descriptor sets, richer index metadata, or Scalable registration
  fixtures.** Also tracked under the design doc above, not this one.
- **Value-level canonicalization.** Decimal literals and timestamp
  strings pass through the compiler unmodified — there is no numeric
  reformatting or truncation applied to field *values* (as opposed to
  field *types*, which this document does cover).

## 2. Field Ordering And Numbering

Both emitters iterate `ModelVersion.fields` (or `ProjectionVersion.fields`)
in **declaration order** — the order fields appear in the `.mdl` source.
Neither emitter sorts, groups, or otherwise reorders fields.

- **Protobuf:** field numbers are assigned `1..N` by declaration order
  (`enumerate(version.fields, start=1)`). There is no support for
  explicit field-number pinning or reserved-number gaps yet — moving a
  field's declaration position changes its wire number.
- **Rust:** struct fields are emitted in declaration order too, but this
  has no wire-format consequence by itself: generated structs derive
  `serde::Serialize`/`Deserialize` for JSON, which is field-name-keyed,
  not positional. Declaration order only affects the generated *source
  text* (relevant to the golden-fixture byte comparison), not the runtime
  wire encoding.

## 3. Per-Type Encoding

| `.mdl` type | Rust | Protobuf |
|---|---|---|
| `string` | `String` | `string` |
| `int` | `i64` | `int64` |
| `float` | `f64` | `double` |
| `bool` | `bool` | `bool` |
| `uuid`, `uuid(7)` | `uuid::Uuid` (identical for both versions) | `string` (identical for both versions) |
| `timestamp` | `String` (verbatim, no truncation) | `google.protobuf.Timestamp` (nanosecond precision, no truncation) |
| `date` | `String` | `string` |
| `time` | `String` | `string` |
| `duration` | `String` | `string` |
| `binary` | `Vec<u8>` | `bytes` |
| `binary(N)` | `[u8; N]` | `bytes` (fixed length `N` recorded only in the companion `schema-manifest.json`, not in the `.proto` type itself) |
| `decimal(p,s)` | `String` | `string` (the value's precision/scale are not encoded in the wire type; both emitters treat it as an opaque decimal-shaped string) |
| `json` | `serde_json::Value` | `string` (protobuf has no dynamic-JSON well-known type in scope here) |
| `u8`, `u16`, `u32` | `u8`, `u16`, `u32` | `uint32` (all three widths widen to the same wire type — `u8`/`u16` are not distinguished on the wire) |
| `u64` | `u64` | `uint64` |
| `u128` | `u128` (native) | `bytes`, fixed length 16 (no native 128-bit protobuf type) |
| `i8`, `i16`, `i32` | `i8`, `i16`, `i32` | `int32` (same widening as the unsigned case) |
| `i64` | `i64` | `int64` |
| `i128` | `i128` (native) | `bytes`, fixed length 16 |
| `enum(...)` | `pub enum` with `#[serde(rename = "...")]` per variant | a sibling `enum` message with a synthetic `_UNSPECIFIED = 0` plus declaration-order sequential values (see section 4) |
| `array<T>` | `Vec<T>` | `repeated <T>` |
| `map<K,V>` | `HashMap<K,V>` | **`bytes`** — Protobuf has no map-type handling in `_type_to_proto` today; this is a real, unaddressed gap, not a deliberate encoding choice. Modeling a `map<K,V>` field and compiling to Protobuf produces an opaque `bytes` field with no wire-level structure. Included in the golden fixture below anyway — pinning current (imperfect) output still catches an *unintentional* regression to this fallback, even though the fallback itself is a known gap, not a guarantee. |
| Semantic type reference (`semantic Name: Underlying`) | the generated newtype (see `compiler-reference.md`) | **unsupported** — `protobuf.py` has no `NamedType` resolution at all; a field referencing a semantic type (or any named model) falls through to the same `bytes` catch-all as an unrecognized type. Not included in the golden fixture below — it's out of scope for a *primitive*-type-focused representative fixture, not because pinning it would be wrong. |

## 4. Enum Discriminant Stability

Protobuf enums get a synthetic zero value (protobuf3 requires every enum
to have a `0` member) named `<PREFIX>_UNSPECIFIED`, where `<PREFIX>` is
the enum's generated name upper-snake-cased. Every declared value then
gets a sequential number starting at `1`, in declaration order:

```proto
enum WidgetStatus {
  WIDGET_STATUS_UNSPECIFIED = 0;
  WIDGET_STATUS_ACTIVE = 1;
  WIDGET_STATUS_INACTIVE = 2;
  WIDGET_STATUS_DISCONTINUED = 3;
}
```

Reordering or removing an `enum(...)` value in `.mdl` changes which
number an existing value maps to, with no compiler guard today — the
same caveat as field numbering in section 2. Rust enums have no numeric
discriminant exposed to serde (variants serialize by their `#[serde(rename)]`
string), so this specific hazard is Protobuf-only.

## 5. Package And Message Naming

Protobuf packages are `modelable.<domain>.v<version>` (domain name
lowercased, non-alphanumeric characters collapsed to `_`). Message names
are the bare model/projection name, unchanged. Field names are
snake-cased from their `.mdl` camelCase source (`widgetId` → `widget_id`).

## 6. How This Is Enforced

[`cli/tests/fixtures/wire_golden/wire_golden.mdl`](https://github.com/ktjn/modelable/blob/main/cli/tests/fixtures/wire_golden/wire_golden.mdl)
is a single representative entity covering every row in section 3's table
except semantic-type references (out of scope for a primitive-focused
fixture; see the table above).
[`cli/tests/test_wire_golden.py`](https://github.com/ktjn/modelable/blob/main/cli/tests/test_wire_golden.py)
compiles it fresh on every test run and asserts the Rust struct file and
the Protobuf `.proto` file match the committed golden files in
`cli/tests/fixtures/wire_golden/golden/` **byte-for-byte**.

**If this test fails after an intentional emitter change:** regenerate
the golden files from the new emitter output, read the diff carefully
(confirm it matches what you intended to change and nothing else), update
this document if the change affects any rule above, and commit the
updated golden files alongside the emitter change in the same PR — never
as an unreviewed follow-up.

**If this test fails and you didn't intend to change emitter output:**
that's exactly what this suite exists to catch. Do not regenerate the
golden files to make it pass; find and fix the unintended drift instead.
