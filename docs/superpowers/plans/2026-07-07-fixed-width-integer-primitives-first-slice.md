# Fixed-Width Integer Primitives First Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add ten new `.mdl` primitive types — `u8, u16, u32, u64, u128, i8, i16, i32, i64, i128` — as siblings to the existing `int`, with range-checked default values and a defined mapping in every currently implemented emitter.

**Architecture:** Extend the existing primitive-type machinery (grammar → transformer → `PrimitiveType` IR → `shapes.py` → per-emitter mapping dict) the same way `int`, `float`, and `uuid` are already handled — no new IR node kind, no new `type_expr` alternative. This is gap 1 of
[docs/superpowers/specs/2026-07-07-modelable-feature-gaps-response-design.md](../specs/2026-07-07-modelable-feature-gaps-response-design.md)
section 4; see that document for the full per-target mapping rationale this plan implements.

**Tech Stack:** Python 3.14, Lark (Earley) grammar, Pydantic IR, pytest, ruff.

---

## Scope And Version Boundary

This is Modelable 1.2 work per `ROADMAP.md`'s feature-gaps response entry.
`int` is unchanged and not deprecated — this slice is purely additive to
the grammar and every downstream consumer.

Out of scope for this first slice:

- The `semantic` type-alias mechanism (gap 3) — depends on this slice
  shipping first, tracked separately.
- `binary(N)` (gap 6) — same mechanical shape, separate plan once this
  slice's pattern is proven.
- Compatibility/diff special-casing beyond what already exists for
  `int` — e.g. is `u32 -> u64` additive or breaking is answered by the
  existing `type_changed` classification in `compat/diff.py` (any
  primitive-kind change is `type_changed`, always breaking); no new
  compatibility rule is needed.
- LLM importers (`llm/importers.py`) inferring fixed-width kinds from
  source schemas (dbt/FHIR/ODCS) automatically — those keep emitting
  `int` until a follow-up teaches the importers to read explicit
  width/signedness hints from the source format.

## File Structure

- Modify `cli/src/modelable/grammar/modelable.lark`: add ten primitive
  type alternatives.
- Modify `cli/src/modelable/parser/transformer.py`: add ten transformer
  methods producing `PrimitiveType(kind=...)`.
- Modify `cli/src/modelable/parser/ir.py`: extend `PrimitiveType.kind`'s
  `Literal[...]`.
- Modify `cli/src/modelable/emitters/shapes.py`: extend `_PRIMITIVE_NAMES`.
- Modify `cli/src/modelable/validation/semantic.py`: generalize the
  existing `int`-only default-value range check to all integer-kind
  primitives, with per-width bounds.
- Modify emitters: `rust.py`, `go.py`, `java.py`, `csharp.py`,
  `python.py`, `typescript.py`, `sql.py`, `json_schema.py`,
  `protobuf.py`, `fhir.py`. `emitters/targets.py`'s `CODEGEN_TARGETS`
  currently implements only `sql-postgres` and `sql-clickhouse` for SQL
  (no `sql-mysql`/`sql-sqlite`), and has no `avro` target at all —
  `language-reference.md`'s target catalog table documents Avro and
  other targets that are not yet implemented emitters. This slice only
  touches implemented targets; MySQL/SQLite/Avro mappings recorded in
  the response design doc are forward guidance for whenever those
  targets are implemented, not work items here.
- Modify `docs/language-reference.md`, `docs/compiler-reference.md`,
  `ROADMAP.md`, `CHANGELOG.md`.
- Create/modify test files: `cli/tests/test_grammar.py`,
  `cli/tests/test_semantic.py`, and a `test_emit_*` file per touched
  emitter.

## Task 1: Grammar, Transformer, And IR

**Files:**
- Modify: `cli/src/modelable/grammar/modelable.lark`
- Modify: `cli/src/modelable/parser/transformer.py`
- Modify: `cli/src/modelable/parser/ir.py`
- Modify: `cli/src/modelable/emitters/shapes.py`
- Modify: `cli/tests/test_grammar.py`

- [ ] **Step 1: Write the failing parse test**

Append to `cli/tests/test_grammar.py`:

```python
def test_parse_all_fixed_width_integer_types():
    tree = parse_text("""
    domain types {
      owner: "test-team"
      entity FixedWidth @ 1 (additive) {
        a: u8
        b: u16
        c: u32
        d: u64
        e: u128
        f: i8
        g: i16
        h: i32
        i: i64
        j: i128
      }
    }
    """)
    assert tree.data == "start"


def test_fixed_width_integer_ir_kinds():
    ir = parse_text_to_ir(SIMPLE_MODEL.replace(
        'total: decimal(12, 2)',
        'total: decimal(12, 2)\n    moduleId: u32\n    delta: i64',
    ))
    fields = {f.name: f.type for f in ir.domains[0].models["Customer"][0].fields}
    assert fields["moduleId"].kind == "u32"
    assert fields["delta"].kind == "i64"
```

- [ ] **Step 2: Verify the tests fail**

Run from `cli/`:

```bash
uv run pytest tests/test_grammar.py -k fixed_width -q
```

Expected: parse failure — the grammar doesn't recognize `u8`..`i128`.

- [ ] **Step 3: Extend the grammar**

In `modelable.lark`, add to `primitive_type`:

```
primitive_type: "string"    -> pt_string
              | "int"       -> pt_int
              | "float"     -> pt_float
              | "bool"      -> pt_bool
              | "date"      -> pt_date
              | "time"      -> pt_time
              | "timestamp" -> pt_timestamp
              | "uuid"      -> pt_uuid
              | "duration"  -> pt_duration
              | "binary"    -> pt_binary
              | "json"      -> pt_json
              | "u8"        -> pt_u8
              | "u16"       -> pt_u16
              | "u32"       -> pt_u32
              | "u64"       -> pt_u64
              | "u128"      -> pt_u128
              | "i8"        -> pt_i8
              | "i16"       -> pt_i16
              | "i32"       -> pt_i32
              | "i64"       -> pt_i64
              | "i128"      -> pt_i128
```

Keyword ordering matters for Earley lexing ambiguity with `IDENT`: since
these are exact string literals (terminals), Lark's contextual lexer
already prefers them over `IDENT` the same way it does for `int`/`uuid`
today — no additional precedence declaration needed, but verify this in
Step 6.

- [ ] **Step 4: Add transformer methods**

In `transformer.py`, alongside the existing `pt_*` methods:

```python
    def pt_u8(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="u8")

    def pt_u16(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="u16")

    def pt_u32(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="u32")

    def pt_u64(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="u64")

    def pt_u128(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="u128")

    def pt_i8(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="i8")

    def pt_i16(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="i16")

    def pt_i32(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="i32")

    def pt_i64(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="i64")

    def pt_i128(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="i128")
```

- [ ] **Step 5: Extend the IR and shapes catalog**

In `parser/ir.py`, extend `PrimitiveType.kind`:

```python
class PrimitiveType(BaseModel):
    kind: Literal[
        "string",
        "int",
        "float",
        "bool",
        "date",
        "time",
        "timestamp",
        "uuid",
        "duration",
        "binary",
        "json",
        "u8", "u16", "u32", "u64", "u128",
        "i8", "i16", "i32", "i64", "i128",
    ]
```

In `emitters/shapes.py`, extend `_PRIMITIVE_NAMES` with the same ten
strings.

- [ ] **Step 6: Verify the tests pass**

Run from `cli/`:

```bash
uv run pytest tests/test_grammar.py -k fixed_width -q
```

Expected: pass. If the contextual lexer treats a new keyword ambiguously
against `IDENT` (e.g. a field literally named `u8`), confirm existing
tests for keyword-as-identifier collisions (search `test_grammar.py` for
how `int`/`uuid` are already guarded) still pass — run the full grammar
suite:

```bash
uv run pytest tests/test_grammar.py -q
```

## Task 2: Default-Value Range Validation

**Files:**
- Modify: `cli/src/modelable/validation/semantic.py`
- Modify: `cli/tests/test_semantic.py`

- [ ] **Step 1: Write the failing range-check tests**

Add to `cli/tests/test_semantic.py`:

```python
def test_fixed_width_default_out_of_range_is_error():
    errors = validate_text("""
    domain types {
      owner: "test-team"
      entity Widths @ 1 (additive) {
        score: u8 = 300
      }
    }
    """)
    assert any("u8" in e and "range" in e.lower() for e in errors)


def test_fixed_width_default_in_range_is_valid():
    errors = validate_text("""
    domain types {
      owner: "test-team"
      entity Widths @ 1 (additive) {
        score: u8 = 200
        delta: i8 = -100
      }
    }
    """)
    assert errors == []


def test_fixed_width_negative_default_on_unsigned_is_error():
    errors = validate_text("""
    domain types {
      owner: "test-team"
      entity Widths @ 1 (additive) {
        score: u32 = -1
      }
    }
    """)
    assert any("u32" in e for e in errors)
```

Use whatever helper (`validate_text`, or the workspace-load-and-collect
pattern already used elsewhere in `test_semantic.py`) matches the
existing test style in that file — inspect the file's current imports
before writing these.

- [ ] **Step 2: Verify the tests fail**

Run from `cli/`:

```bash
uv run pytest tests/test_semantic.py -k fixed_width -q
```

Expected: failures — no range check exists yet, so out-of-range defaults
currently pass validation silently.

- [ ] **Step 3: Add the range table and generalize the existing check**

In `validation/semantic.py`, add:

```python
_INTEGER_BOUNDS: dict[str, tuple[int, int]] = {
    "u8": (0, 2**8 - 1),
    "u16": (0, 2**16 - 1),
    "u32": (0, 2**32 - 1),
    "u64": (0, 2**64 - 1),
    "u128": (0, 2**128 - 1),
    "i8": (-(2**7), 2**7 - 1),
    "i16": (-(2**15), 2**15 - 1),
    "i32": (-(2**31), 2**31 - 1),
    "i64": (-(2**63), 2**63 - 1),
    "i128": (-(2**127), 2**127 - 1),
}
```

Find the existing default-value check that special-cases
`isinstance(field_type, PrimitiveType) and field_type.kind == "int"`
(around lines 501 and 536 per the current file). Generalize both sites:
replace the `== "int"` check with `field_type.kind in {"int", *_INTEGER_BOUNDS}`,
and where the default literal is parsed as an integer, look up
`_INTEGER_BOUNDS.get(field_type.kind)` and emit a validation error if the
parsed value falls outside `(low, high)`. Follow the existing error
message format in that file (check how other range/type errors are
worded there and match it, including which field/model reference is
included).

- [ ] **Step 4: Verify the tests pass**

Run from `cli/`:

```bash
uv run pytest tests/test_semantic.py -k fixed_width -q
```

Expected: pass.

## Task 3: Rust, Go, Java, C#, Python, TypeScript Emitters

**Files:**
- Modify: `cli/src/modelable/emitters/rust.py`
- Modify: `cli/src/modelable/emitters/go.py`
- Modify: `cli/src/modelable/emitters/java.py`
- Modify: `cli/src/modelable/emitters/csharp.py`
- Modify: `cli/src/modelable/emitters/python.py`
- Modify: `cli/src/modelable/emitters/typescript.py`
- Modify: `cli/tests/test_emit_rust.py`, `test_emit_go.py`,
  `test_emit_java.py`, `test_emit_csharp.py`, `test_emit_python.py`,
  `test_emit_typescript.py`

- [ ] **Step 1: Write one failing test per emitter**

For each emitter's test file, add a test that compiles an entity with
one field per new kind and asserts the emitted type text matches the
mapping table in
[docs/superpowers/specs/2026-07-07-modelable-feature-gaps-response-design.md](../specs/2026-07-07-modelable-feature-gaps-response-design.md)
section 4. Follow the exact structure of that file's existing
`int`/`uuid`/`binary` mapping test (each of these files already has one —
locate it before writing the new test so field ordering, helper
functions, and assertion style match). At minimum assert:

- Rust: `u8, u16, u32, u64, u128, i8, i16, i32, i64, i128` map to
  themselves exactly.
- Go: `u8..u64`/`i8..i64` map to `uint8/16/32/64`/`int8/16/32/64`; `u128`
  and `i128` map to `[16]byte` and the artifact carries a `type_loss`
  warning (assert on `artifact.warnings`, matching how existing
  `type_loss` cases are asserted elsewhere in `test_emit_go.py`).
- Java: unsigned widths map to the next-widest signed primitive
  (`byte/short/int/long`) with a `type_loss` warning; `u128`/`i128` map
  to `BigInteger` with no warning (widening to `BigInteger` is lossless).
- C#: `byte/ushort/uint/ulong`/`sbyte/short/int/long`, and
  `System.UInt128`/`System.Int128` for the 128-bit pair, with **no**
  warnings anywhere in this emitter (C# has exact native types for all
  ten).
- Python: emitted field type is `int` in all ten cases, with a
  `Field(ge=.., le=..)` constraint whose bounds match `_INTEGER_BOUNDS`
  from Task 2.
- TypeScript: `u8..u32`/`i8..i32` map to `number`; `u64, u128, i64, i128`
  map to `bigint`.

- [ ] **Step 2: Verify all six new tests fail**

Run from `cli/`:

```bash
uv run pytest tests/test_emit_rust.py tests/test_emit_go.py tests/test_emit_java.py tests/test_emit_csharp.py tests/test_emit_python.py tests/test_emit_typescript.py -k fixed_width -q
```

Expected: failures — every emitter's primitive-kind mapping dict falls
through to that emitter's default case for unrecognized kinds (verify
what that fallback currently renders before assuming it's `"String"`/an
error; each emitter's `_primitive_to_*` function has its own default).

- [ ] **Step 3: Extend each mapping dict**

`rust.py`'s `_primitive_to_rust` (around line 810):

```python
    mapping = {
        ...
        "u8": "u8", "u16": "u16", "u32": "u32", "u64": "u64", "u128": "u128",
        "i8": "i8", "i16": "i16", "i32": "i32", "i64": "i64", "i128": "i128",
    }
```

`go.py`'s equivalent dict (around line 299): map `u8..u64`/`i8..i64` to
Go's native names; for `u128`/`i128`, return `[16]byte` and push a
`type_loss("u128")`/`type_loss("i128")` warning onto the artifact the
same way this file already does for its other unsupported-shape cases —
find that existing warning-attachment call site before adding a new one,
to match the pattern exactly (warnings are collected per-field during
shape resolution, not appended after the fact, in most of these
emitters).

`java.py` (around line 205): unsigned widths map to next-widest signed
plus a `type_loss` call; `u128`/`i128` map to `"BigInteger"` and require
adding the corresponding import statement to the emitted file's header —
find where `java.py` already conditionally adds imports (it does this
for `UUID` and other non-`java.lang` types) and extend that same
import-collection logic for `BigInteger`.

`csharp.py` (around line 190): all ten map directly, no warnings,
`System.UInt128`/`System.Int128` for the 128-bit pair (no `using`
statement needed — both are in the `System` namespace already imported
by default in this emitter's generated files; verify this assumption
against the emitter's current header-generation code in Step 4).

`python.py` (around line 250): all ten map to `"int"` for the bare type
name, plus extend whatever mechanism this emitter uses for
`Annotated[..., Field(...)]` constraints (check how `decimal(p,s)` or
`binary` length constraints, if any, are already threaded through this
emitter before adding a new constraint kind) to add `ge`/`le` bounds
sourced from Task 2's `_INTEGER_BOUNDS`.

`typescript.py` (around line 330): `u8..u32`, `i8..i32` map to
`"number"`; `u64, u128, i64, i128` map to `"bigint"`.

- [ ] **Step 4: Verify all six tests pass**

Run from `cli/`:

```bash
uv run pytest tests/test_emit_rust.py tests/test_emit_go.py tests/test_emit_java.py tests/test_emit_csharp.py tests/test_emit_python.py tests/test_emit_typescript.py -k fixed_width -q
```

Expected: pass.

## Task 4: SQL, JSON Schema, Protobuf, Avro, FHIR Emitters

**Files:**
- Modify: `cli/src/modelable/emitters/sql.py`
- Modify: `cli/src/modelable/emitters/json_schema.py`
- Modify: `cli/src/modelable/emitters/protobuf.py`
- Modify: `cli/src/modelable/emitters/fhir.py`
- Modify: `cli/tests/test_emit_sql.py`, `test_emit_json_schema.py`,
  `test_emit_protobuf.py`, `test_emit_fhir.py`

No Avro emitter exists in `emitters/targets.py`'s current
`CODEGEN_TARGETS` (only `sql-postgres` and `sql-clickhouse` for SQL, no
`sql-mysql`/`sql-sqlite`, no `avro`) — skip Avro/MySQL/SQLite in this
task; the response design doc's mappings for those are recorded for
whenever those targets are implemented, not for this slice.

- [ ] **Step 1: Write failing tests per target**

Follow the same per-target assertion approach as Task 3 Step 1, using
the mapping table in section 4 of the response design doc:

- SQL Postgres: `u8/u16/u32` → `SMALLINT`/`INTEGER` + a `CHECK (col >= 0)`
  clause in the emitted `CREATE TABLE`; `u64` → `NUMERIC(20,0)` + the same
  check; `u128` → `NUMERIC(39,0)` + check; `i8..i64` → `SMALLINT/INTEGER/BIGINT`;
  `i128` → `NUMERIC(39,0)`, no check.
- SQL ClickHouse: exact `UInt8/16/32/64/128`/`Int8/16/32/64/128` — no
  loss, no check clauses needed (ClickHouse enforces range natively).
- JSON Schema: `{"type":"integer","minimum":..,"maximum":..}` per kind,
  sourced from the same `_INTEGER_BOUNDS` table (import it from
  `validation/semantic.py` or duplicate a frozen copy in
  `emitters/shapes.py` if importing from `validation` would create an
  undesirable layering dependency — check whether emitters already
  import from `validation` anywhere before deciding).
- Protobuf: `u8/u16/u32` → `uint32`; `u64` → `uint64`; `i8/i16/i32` →
  `int32`; `i64` → `int64`; `u128`/`i128` → `bytes` with
  `"fixed_length": 16` style metadata added to the schema manifest (mirror
  the manifest metadata pattern the protobuf emitter already uses for its
  other special-cased types).
- FHIR: `u8..i32`-range kinds → `integer`; `u64, u128, i64, i128` →
  `string` + `type_loss` warning (FHIR R4 `integer` is 32-bit signed
  only).

- [ ] **Step 2: Verify the new tests fail**

Run from `cli/`:

```bash
uv run pytest tests/test_emit_sql.py tests/test_emit_json_schema.py tests/test_emit_protobuf.py tests/test_emit_fhir.py -k fixed_width -q
```

- [ ] **Step 3: Extend each emitter's mapping**

Mirror Task 3 Step 3's approach: locate each emitter's existing
`"int"`/`"uuid"`/`"binary"` mapping dict or branch (grep the file for
`"int"` to find it quickly, as in the earlier grep against `rust.py`
line 813 and `json_schema.py` line 413), and extend it per the table
above. For the Postgres `CHECK` clause and ClickHouse's native mapping,
follow `sql.py`'s existing pattern for emitting column-level constraints
(search for how `@pii`/`decimal` constraints, if any, already attach
extra DDL fragments to a column definition before adding a new one).

- [ ] **Step 4: Verify the tests pass**

Run from `cli/`:

```bash
uv run pytest tests/test_emit_sql.py tests/test_emit_json_schema.py tests/test_emit_protobuf.py tests/test_emit_fhir.py -q
```

Expected: pass.

## Task 5: Conformance Fixture And Documentation

**Files:**
- Modify: `samples/conformance/` (add fixed-width fields to the existing
  conformance model, or add a new dedicated fixture model — match
  whichever pattern the existing conformance fixture already uses for
  introducing a new type)
- Modify: `docs/language-reference.md` (section 2.1 built-in types table)
- Modify: `docs/compiler-reference.md` (wherever the type system is
  described for the compiler audience)
- Modify: `ROADMAP.md` (mark this slice complete once shipped — the
  entry was added by this plan's own predecessor edit; update its
  wording from "planned" to "shipped" language matching how the 1.0
  entry above it is worded)
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add the ten new types to the conformance fixture**

Add fields of each new kind to the conformance model(s) under
`samples/conformance/`, following that directory's existing structure
(check its README or the existing model files for how new types are
expected to be added — the roadmap for 1.0 states this fixture mirrors
former private release checks, so treat additions here as
release-blocking coverage, not optional).

- [ ] **Step 2: Update the language reference**

In `docs/language-reference.md` section 2.1's built-in types table, add
one row per new type, following the exact table format already used for
`int`/`uuid`/`binary`. Cross-reference the new
`docs/superpowers/specs/2026-07-07-modelable-feature-gaps-response-design.md`
document is not required in the public docs (that doc lives under
`superpowers/`, which `mkdocs.yml` explicitly excludes from the site
build — do not link to it from published docs).

- [ ] **Step 3: Update the compiler reference and changelog**

Document the new primitives in `docs/compiler-reference.md` wherever the
existing type system is described for compiler-internal audience. Add a
`CHANGELOG.md` entry under an "Unreleased" or next-version heading
(match whatever heading convention the top of that file currently uses).

- [ ] **Step 4: Verify docs mention the new types**

Run from repo root:

```bash
rg -n "u8|u128|i128" docs/language-reference.md docs/compiler-reference.md CHANGELOG.md
```

Expected: matches in all three files.

## Task 6: Final Verification

**Files:**
- All touched files

- [ ] **Step 1: Run all focused tests**

Run from `cli/`:

```bash
uv run pytest tests/test_grammar.py tests/test_semantic.py tests/test_emit_rust.py tests/test_emit_go.py tests/test_emit_java.py tests/test_emit_csharp.py tests/test_emit_python.py tests/test_emit_typescript.py tests/test_emit_sql.py tests/test_emit_json_schema.py tests/test_emit_protobuf.py tests/test_emit_fhir.py --tb=short -q
```

Expected: pass.

- [ ] **Step 2: Run the conformance fixture and the required pre-commit gate**

Run from `cli/`:

```bash
uv run ruff format .
uv run ruff check .
uv run pytest --tb=short
```

Expected: all pass cleanly, including the conformance fixture compile
that Task 5 extended.

- [ ] **Step 3: Inspect the final diff**

Run from repo root:

```bash
git diff --stat
```

Expected: diff touches only the grammar, transformer, IR, shapes,
validator, the emitters listed above, their tests, the conformance
fixture, and the four documentation files. No unrelated files changed.

## Self-Review

Spec coverage:

- Covered: all ten new primitive kinds parse; default-value range
  validation for all ten; a defined mapping (exact, lossy-with-warning,
  or metadata-only) in Rust, Go, Java, C#, Python, TypeScript, SQL
  (Postgres, ClickHouse), JSON Schema, Protobuf, and FHIR; conformance
  fixture and doc coverage.
- Deferred by design (see the response design doc, section 12, and this
  plan's Scope section): `semantic` type-alias mechanism, `binary(N)`,
  compatibility-rule changes beyond the existing `type_changed`
  classification, LLM-importer auto-inference of fixed widths from
  source schemas, and Avro/MySQL/SQLite mappings — none of those three
  targets are implemented emitters as of this slice (`emitters/targets.py`
  has no `avro`, `sql-mysql`, or `sql-sqlite` entry), so there is nothing
  to modify for them yet; their mappings are recorded in the response
  design doc for whenever those targets are built.

Placeholder scan:

- No placeholder tasks are left. Every task ends with a green-test
  checkpoint.

Type consistency:

- No new IR node kind is introduced — this slice reuses the existing
  `PrimitiveType.kind` string-literal pattern exactly as `int`, `float`,
  and `uuid` already work, which is why it doesn't touch
  `type_shape_catalog()`'s structural shapes beyond `_PRIMITIVE_NAMES`.
