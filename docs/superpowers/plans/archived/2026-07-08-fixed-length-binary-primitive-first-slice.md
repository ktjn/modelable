# Fixed-Length Binary Primitive First Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `binary(N)` — a fixed-length variant of the existing variable-length `binary` primitive — with a length bound of `1..=4096`, and a defined mapping in every currently implemented emitter.

**Architecture:** Unlike gap 1 (fixed-width integers), which added `PrimitiveType.kind` variants, `binary(N)` is a **distinct IR node** — `FixedBinaryType(kind="fixed_binary", length: int)` — sibling to `DecimalType` in the `FieldType` union, exactly as
[docs/superpowers/specs/2026-07-07-modelable-feature-gaps-response-design.md](../specs/2026-07-07-modelable-feature-gaps-response-design.md)
section 9 specifies. This means every dispatch site that pattern-matches on `FieldType` subclasses (`isinstance(field_type, DecimalType)` and friends) needs a new branch, not a new dict key — a structurally different, slightly larger change than gap 1 even though the primitive-count is smaller.

**Two dispatch paths exist in this codebase and both need `FixedBinaryType` support:**
- `emitters/shapes.py`'s `TypeShape.from_field_type` — consumed by `rust.py`, `go.py`, `java.py`, `csharp.py`, `python.py`. `TypeShape.from_field_type` currently **raises `TypeError`** for any `FieldType` subclass it doesn't recognize, so adding `FixedBinaryType` to the IR without updating this function breaks all five of those emitters immediately and loudly (not silently) — this is the mandatory first step after the grammar/IR/transformer work.
- Direct `isinstance(field_type, ...)` dispatch on raw `FieldType` — used by `typescript.py`, `sql.py`, `json_schema.py`, `protobuf.py` (and also `dbt_yaml.py`, `markdown.py`, `odcs.py`, `openlineage.py`, `openmetadata.py`, `fhir.py`, none of which are in scope — see Scope below).

**Tech Stack:** Python 3.14, Lark (Earley) grammar, Pydantic IR, pytest, ruff.

---

## Scope And Version Boundary

This is Modelable 1.2 work, the second slice of that version line (gap 1, fixed-width integers, shipped first — see `ROADMAP.md`). `binary` is unchanged and not deprecated.

Out of scope for this first slice, matching the precedent already set by the fixed-width-integers slice (which also left these same files untouched):

- `dbt_yaml.py`, `markdown.py`, `odcs.py`, `openlineage.py`, `openmetadata.py`, `fhir.py` — none of these are listed in the response design doc's gap-6 mapping table (unlike gap 1, which explicitly listed FHIR). Their existing `isinstance(field_type, DecimalType)`-style dispatch chains will fall through to each function's generic default case for a `FixedBinaryType` field — the same tolerated behavior gap 1 left in place for these files' handling of the new integer kinds.
- MySQL, SQLite, and Avro mappings — same reason as gap 1: none are implemented emitter targets in `emitters/targets.py`'s `CODEGEN_TARGETS` as of this writing. Recorded in the response design doc as forward guidance only.
- Base64-length-aware JSON Schema `minLength`/`maxLength` — the design doc explicitly defers this ("a known follow-up nicety, not required for the first slice"); this slice adds only the `x-modelable-fixed-length` vendor extension.
- Compatibility/diff special-casing — `compat/diff.py`'s `_type_signature` calls `field.type.model_dump(...)` generically, which already works correctly for any new Pydantic `FieldType` subclass with no changes needed; a `binary` ↔ `binary(N)` change is already `type_changed` (breaking) via the existing generic signature comparison.

## File Structure

- Modify `cli/src/modelable/grammar/modelable.lark`: add `fixed_binary_type` as a new `type_expr` alternative.
- Modify `cli/src/modelable/parser/transformer.py`: add the `fixed_binary_type` transformer method.
- Modify `cli/src/modelable/parser/ir.py`: add `FixedBinaryType` to the `FieldType` union.
- Modify `cli/src/modelable/emitters/shapes.py`: add a `length` field to `TypeShape` and a `"fixed_binary"` branch to `TypeShape.from_field_type`.
- Modify `cli/src/modelable/validation/semantic.py`: add a `1..=4096` length-bound check.
- Modify emitters: `rust.py`, `go.py`, `java.py`, `csharp.py`, `python.py` (via `TypeShape`), `typescript.py`, `sql.py`, `json_schema.py`, `protobuf.py` (via direct `FixedBinaryType` isinstance checks).
- Modify `docs/language-reference.md`, `docs/compiler-reference.md`, `ROADMAP.md`, `CHANGELOG.md`.
- Create/modify test files: `cli/tests/test_grammar.py`, `cli/tests/test_semantic.py`, and a `test_emit_*` file per touched emitter.

## Task 1: Grammar, Transformer, IR, And Validation

**Files:**
- Modify: `cli/src/modelable/grammar/modelable.lark`
- Modify: `cli/src/modelable/parser/transformer.py`
- Modify: `cli/src/modelable/parser/ir.py`
- Modify: `cli/src/modelable/validation/semantic.py`
- Modify: `cli/tests/test_grammar.py`, `cli/tests/test_semantic.py`

- [ ] **Step 1: Write the failing parse and IR tests**

Append to `cli/tests/test_grammar.py`:

```python
def test_parse_fixed_length_binary():
    tree = parse_text("""
    domain types {
      owner: "test-team"
      entity Widths @ 1 (additive) {
        @key id: uuid
        keyHash: binary(32)
        avatar: binary
      }
    }
    """)
    assert tree.data == "start"


def test_fixed_length_binary_ir_shape():
    ir = parse_text_to_ir(SIMPLE_MODEL.replace(
        'total: decimal(12, 2)',
        'total: decimal(12, 2)\n    keyHash: binary(32)',
    ))
    fields = {f.name: f.type for f in ir.domains[0].models["Customer"][0].fields}
    assert fields["keyHash"].kind == "fixed_binary"
    assert fields["keyHash"].length == 32
```

- [ ] **Step 2: Verify the tests fail**

Run from `cli/`: `uv run pytest tests/test_grammar.py -k fixed_length_binary -q`. Expected: the plain-binary parse succeeds (falls back to `pt_binary`), but `binary(32)` fails to parse — the grammar has no production for `"binary" "(" INT ")"` yet.

- [ ] **Step 3: Extend the grammar**

In `modelable.lark`, add a new `type_expr` alternative (do not touch the existing `pt_binary` alt inside `primitive_type` — bare `binary` stays exactly as-is):

```
type_expr: primitive_type
         | decimal_type
         | fixed_binary_type
         | enum_type
         | array_type
         | map_type
         | ref_type
         | object_type
         | IDENT

fixed_binary_type: "binary" "(" INT ")"
```

- [ ] **Step 4: Add the transformer method**

In `transformer.py`, alongside `decimal_type`:

```python
    def fixed_binary_type(self, items: list[object]) -> FixedBinaryType:
        return FixedBinaryType(length=int(items[0]))
```

Add `FixedBinaryType` to the import from `modelable.parser.ir`.

- [ ] **Step 5: Add the IR node**

In `parser/ir.py`, add next to `DecimalType`:

```python
class FixedBinaryType(BaseModel):
    kind: Literal["fixed_binary"] = "fixed_binary"
    length: int
```

Add `FixedBinaryType` to the `FieldType` union (`Annotated[PrimitiveType | DecimalType | FixedBinaryType | ArrayType | ...]`).

- [ ] **Step 6: Verify parse/IR tests pass**

Run from `cli/`: `uv run pytest tests/test_grammar.py -k fixed_length_binary -q`. Expected: pass. Then run the full grammar suite (`uv run pytest tests/test_grammar.py -q`) to confirm no regression from the new `type_expr` alternative.

- [ ] **Step 7: Write the failing length-bound tests**

Append to `cli/tests/test_semantic.py`:

```python
def test_fixed_binary_length_out_of_range_is_error():
    mdl = parse_text_to_ir("""
    domain types {
      owner: "test-team"
      entity Widths @ 1 (additive) {
        @key id: uuid
        keyHash: binary(5000)
      }
    }
    """)

    errors = validate(mdl)

    assert any("keyHash" in e and "4096" in e for e in errors)


def test_fixed_binary_zero_length_is_error():
    mdl = parse_text_to_ir("""
    domain types {
      owner: "test-team"
      entity Widths @ 1 (additive) {
        @key id: uuid
        keyHash: binary(0)
      }
    }
    """)

    errors = validate(mdl)

    assert any("keyHash" in e for e in errors)


def test_fixed_binary_in_range_is_valid():
    mdl = parse_text_to_ir("""
    domain types {
      owner: "test-team"
      entity Widths @ 1 (additive) {
        @key id: uuid
        keyHash: binary(32)
      }
    }
    """)

    errors = validate(mdl)

    assert errors == []
```

- [ ] **Step 8: Verify the tests fail**

Run from `cli/`: `uv run pytest tests/test_semantic.py -k fixed_binary -q`. Expected: the out-of-range cases pass validation silently (no check exists yet).

- [ ] **Step 9: Add the length-bound check**

In `validation/semantic.py`, add a helper and call it from the same per-field loop in `_validate_models` that already calls `_validate_default_value_range` (added by the fixed-width-integers slice):

```python
def _validate_fixed_binary_length(
    fqn: str,
    field: FieldDef,
    diagnostics: list[Diagnostic],
    path: str | Path | None,
) -> None:
    if not isinstance(field.type, FixedBinaryType):
        return
    if not (1 <= field.type.length <= 4096):
        diagnostics.append(
            _diag(
                "SEM",
                f"{fqn}: field '{field.name}' binary({field.type.length}) length must be between 1 and 4096",
                path,
            )
        )
```

Add `FixedBinaryType` to the `modelable.parser.ir` import list. Add the call:
`_validate_fixed_binary_length(f"{fqn}@{version.version}", field, diagnostics, path)`
next to the existing `_validate_default_value_range(...)` call.

- [ ] **Step 10: Verify the tests pass**

Run from `cli/`: `uv run pytest tests/test_semantic.py -k fixed_binary -q`, then the full file: `uv run pytest tests/test_semantic.py -q`.

## Task 2: `TypeShape` And The Five `TypeShape`-Based Emitters

**Files:**
- Modify: `cli/src/modelable/emitters/shapes.py`
- Modify: `cli/src/modelable/emitters/rust.py`, `go.py`, `java.py`, `csharp.py`, `python.py`
- Modify: `cli/tests/test_emit_rust.py`, `test_emit_go.py`, `test_emit_java.py`, `test_emit_csharp.py`, `test_emit_python.py`

- [ ] **Step 1: Write one failing test per emitter**

For each file, add a test compiling an entity with a `binary(32)` field, following the exact structure of that file's existing `binary`-mapping assertions (each already has one from the base language coverage — locate it first). Assert:

- Rust: `pub keyHash: [u8; 32],` — a native fixed-size array.
- Go: `KeyHash [32]byte \`json:"keyHash"\`` — native fixed-size array, no warning.
- Java: `byte[] keyHash` — same as plain `binary`, plus a Javadoc-style comment noting the required length is not enforced by the type system (assert the comment text is present; this is a documented partial-enforcement case, matching the response design doc).
- C#: `public required byte[] KeyHash { get; init; }` — same as plain `binary`, with an XML `<summary>`-style doc comment noting the required length (same partial-enforcement tier as Java).
- Python: `keyHash: bytes` — bare `bytes`, no constraint mechanism, exactly matching this slice's precedent from the fixed-width-integers work (this emitter generates plain `@dataclass`, not Pydantic, so there is nothing to hang a length constraint off of).

- [ ] **Step 2: Verify all five new tests fail**

Run from `cli/`:
```bash
uv run pytest tests/test_emit_rust.py tests/test_emit_go.py tests/test_emit_java.py tests/test_emit_csharp.py tests/test_emit_python.py -k fixed_binary -q
```
Expected: every one fails with `TypeError: unsupported field type` raised from `TypeShape.from_field_type` — confirming the mandatory-first-step claim in this plan's Architecture section.

- [ ] **Step 3: Extend `TypeShape`**

In `shapes.py`:

```python
@dataclass(frozen=True)
class TypeShape:
    ...
    precision: int | None = None
    scale: int | None = None
    length: int | None = None  # for fixed_binary
```

In `from_field_type`, add before the final `raise TypeError`:

```python
        if isinstance(field_type, FixedBinaryType):
            return cls(kind="fixed_binary", optional=optional, length=field_type.length)
```

Add `FixedBinaryType` to the `modelable.parser.ir` import.

- [ ] **Step 4: Extend each emitter's shape-dispatch function**

Each of `rust.py`, `go.py`, `java.py`, `csharp.py`, `python.py` has a `_shape_base_to_<lang>`/`_shape_base_annotation`-style function with a chain of `if shape.kind == "..."` branches (`"primitive"`, `"decimal"`, `"array"`, ...). Add a `"fixed_binary"` branch to each, following that function's existing style exactly (check how `"decimal"` is handled in the same function immediately before writing the new branch, since each file's decimal branch is the closest structural sibling):

- Rust: `if shape.kind == "fixed_binary": return f"[u8; {shape.length}]"`.
- Go: `if shape.kind == "fixed_binary": return f"[{shape.length}]byte"`.
- Java: `if shape.kind == "fixed_binary": return "byte[]"` for the type, plus thread a short doc-comment note through this emitter's existing per-field comment mechanism if one exists (check `_build_record_definition`/`_emit_model` for an existing Javadoc-line mechanism before inventing a new one; if none exists, add the minimal one needed — a `/** binary(N): length is not enforced by the type system */` line immediately above the field).
- C#: `if shape.kind == "fixed_binary": return "byte[]"` for the type, with the equivalent XML-doc-comment treatment as Java, matching whatever comment mechanism (or lack of one) this emitter already has.
- Python: `if shape.kind == "fixed_binary": return "bytes"`.

- [ ] **Step 5: Verify all five tests pass**

Run from `cli/`:
```bash
uv run pytest tests/test_emit_rust.py tests/test_emit_go.py tests/test_emit_java.py tests/test_emit_csharp.py tests/test_emit_python.py -q
```

## Task 3: TypeScript, SQL, JSON Schema, Protobuf

**Files:**
- Modify: `cli/src/modelable/emitters/typescript.py`, `sql.py`, `json_schema.py`, `protobuf.py`
- Modify: `cli/tests/test_emit_typescript.py`, `test_emit_sql.py`, `test_emit_json_schema.py`, `test_emit_protobuf.py`

These four emitters dispatch on raw `FieldType` directly (`isinstance(field_type, DecimalType)` and similar), not through `TypeShape` — each needs its own `isinstance(field_type, FixedBinaryType)` branch, added next to that function's existing `DecimalType` branch (the closest structural sibling in each file).

- [ ] **Step 1: Write failing tests per target**

- TypeScript: `keyHash: Uint8Array;` with a `/** binary(32): fixed length not enforced by TypeScript's type system */`-style JSDoc line immediately above the field (check this emitter's existing per-field comment mechanism, if any, before adding a new one).
- SQL Postgres: `key_hash BYTEA NOT NULL` plus a `CHECK (octet_length(key_hash) = 32)` table constraint — extend the same `checks` list this emitter's `_emit_projection_ddl` already collects for the fixed-width-integers unsigned-range checks (added by the previous slice); this is now a second reason to emit a `CHECK` clause, not a new mechanism.
- SQL ClickHouse: `key_hash FixedString(32)` — exact native match, no check needed.
- JSON Schema: existing `binary` schema (`{"type": "string", "contentEncoding": "base64"}`) plus `"x-modelable-fixed-length": 32`.
- Protobuf: `bytes key_hash = N;` plus `"fixed_length": 32` in the schema manifest — reuse the exact `fixed_length` manifest field the fixed-width-integers slice already added to `_ProtoField`/`_manifest_field` for `u128`/`i128`; this is a second producer of that same field, not a new one.

- [ ] **Step 2: Verify all four sets of tests fail**

Run from `cli/`:
```bash
uv run pytest tests/test_emit_typescript.py tests/test_emit_sql.py tests/test_emit_json_schema.py tests/test_emit_protobuf.py -k fixed_binary -q
```

- [ ] **Step 3: Extend each emitter**

`typescript.py`'s `_type_to_ts`: add an `isinstance(field_type, FixedBinaryType)` branch returning `"Uint8Array"`, following the same structure as the adjacent `DecimalType` branch.

`sql.py`: in both `_pg_base_type` and `_ch_base_type`, add a `FixedBinaryType` branch (`BYTEA` / `FixedString(N)` respectively). In `_emit_projection_ddl`'s column loop, extend the existing postgres-only `checks.append(...)` logic (currently gated on `_pg_needs_unsigned_check`) with a second condition for `FixedBinaryType` fields, appending `CHECK (octet_length(col) = N)`.

`json_schema.py`'s `_primitive_to_json_schema`-adjacent dispatch: add a branch for `FixedBinaryType` that starts from the existing `binary` schema dict and adds `"x-modelable-fixed-length"`.

`protobuf.py`: in `_type_to_proto`, add an `isinstance(field_type, FixedBinaryType)` branch returning `("bytes", None, field_type.length)` — reusing the existing three-tuple shape `(type_name, enum, fixed_length)` this function already returns for `u128`/`i128` (added by the fixed-width-integers slice), so `_manifest_field` picks up `fixed_length` with no further changes.

- [ ] **Step 4: Verify all four sets of tests pass**

Run from `cli/`:
```bash
uv run pytest tests/test_emit_typescript.py tests/test_emit_sql.py tests/test_emit_json_schema.py tests/test_emit_protobuf.py -q
```

## Task 4: Documentation

**Files:**
- Modify: `docs/language-reference.md`, `docs/compiler-reference.md`, `ROADMAP.md`, `CHANGELOG.md`

- [ ] **Step 1: Update the language reference**

In `docs/language-reference.md` section 2.1's built-in types table, add a row for `binary(N)` immediately after `binary`, following the exact format already used for `decimal(p,s)`.

- [ ] **Step 2: Update the compiler reference**

In `docs/compiler-reference.md`'s JSON Schema type-mapping table (extended by the fixed-width-integers slice), add a `binary(N)` row.

- [ ] **Step 3: Update ROADMAP and CHANGELOG**

Mark gap 6 as shipped in `ROADMAP.md`'s feature-gaps response entry, matching the wording style used for gap 1. Add a `CHANGELOG.md` entry under `[Unreleased]`.

- [ ] **Step 4: Verify docs mention the new type**

Run from repo root: `rg -n "binary\(N\)|binary\(32\)|fixed_binary" docs/language-reference.md docs/compiler-reference.md CHANGELOG.md ROADMAP.md`. Expected: matches in all four files.

## Task 5: Final Verification

**Files:** All touched files

- [ ] **Step 1: Run all focused tests**

```bash
uv run pytest tests/test_grammar.py tests/test_semantic.py tests/test_emit_rust.py tests/test_emit_go.py tests/test_emit_java.py tests/test_emit_csharp.py tests/test_emit_python.py tests/test_emit_typescript.py tests/test_emit_sql.py tests/test_emit_json_schema.py tests/test_emit_protobuf.py --tb=short -q
```

- [ ] **Step 2: Run the full suite, ruff, and the mypy baseline ratchet**

```bash
uv run ruff format --check .
uv run ruff check .
uv run pytest --tb=short
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
```

Regenerate `mypy-baseline.txt` if the ratchet reports new errors caused by line shifts or new but stylistically-consistent debt, exactly as the fixed-width-integers slice needed to (see that slice's PR for the precedent — this is expected, not a sign of a real regression, whenever new fields are inserted into already-imperfect files).

- [ ] **Step 3: Inspect the final diff**

```bash
git diff --stat
```

Expected: diff touches only the grammar, transformer, IR, shapes, validator, the nine emitters listed above, their tests, the four documentation files, and (if needed) the mypy baseline.

## Self-Review

Spec coverage:

- Covered: `binary(N)` parses; `FixedBinaryType` IR node; length bound `1..=4096`; a defined mapping in Rust, Go, Java, C#, Python, TypeScript, SQL (Postgres, ClickHouse), JSON Schema, and Protobuf.
- Deferred by design, matching the response design doc and the fixed-width-integers slice's own precedent: dbt_yaml/markdown/odcs/openlineage/openmetadata/FHIR (not in the gap-6 mapping table), MySQL/SQLite/Avro (not implemented targets), base64-aware JSON Schema length bounds.

Placeholder scan: none — every task ends with a green-test checkpoint.

Type consistency: `FixedBinaryType` is a new `FieldType` union member, matching `DecimalType`'s existing shape exactly (a `kind` literal plus scalar fields, no nested nodes) — this is the smallest-blast-radius way to add a parameterized primitive-like type without touching `TypeShape`'s recursive structure beyond one new leaf branch.
