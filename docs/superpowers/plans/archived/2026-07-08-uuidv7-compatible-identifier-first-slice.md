# UUIDv7-Compatible Identifier First Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `uuid` a parameterized primitive with an optional version argument — `uuid(7)` for UUIDv7 (timestamp-ordered), plain `uuid` unchanged (defaults to v4) — and surface the version in JSON Schema and Markdown output. This is gap 2 of Scalable's feature-gaps request, originally sequenced as Modelable 1.1 "cheapest gap, ships first" but not actually implemented in any prior slice; it lands now as an independent, self-contained slice.

**Architecture:** Unlike gap 6 (`binary(N)`, a separate top-level `type_expr` alternative producing a distinct `FixedBinaryType` IR node), `uuid(7)` stays inside the existing `primitive_type` rule and `PrimitiveType` IR class — the representation doesn't change (both v4 and v7 are 128-bit values with the same string form), only an added `version` field and generation/sort semantics differ. See
[docs/superpowers/specs/2026-07-07-modelable-feature-gaps-response-design.md](../specs/2026-07-07-modelable-feature-gaps-response-design.md)
section 5 for the full design, including a correction found while planning this slice: gap 6 did **not** end up reusing a "parameterized primitive" pattern gap 2 was meant to establish first (gap 6 shipped in 1.2 as its own `type_expr` alternative, independent of this gap), and two of the three target-mapping improvements described (SQL `DEFAULT uuidv7()`, prose-rendered hover/Markdown) don't have an existing mechanism to hook into and are deferred.

**Tech Stack:** Python 3.14, Lark (Earley) grammar, Pydantic IR, pytest, ruff.

---

## Scope And Version Boundary

This is Modelable 1.1-scope work (gap 2 in the original numbering), landing
independently rather than blocking on or being blocked by any other gap —
all of gaps 1, 3, 4, and 6 are already shipped, and this gap has no
dependency on any of them per the design doc's own dependency table.

Out of scope for this first slice (see the design doc's correction note
in section 5 for why):

- **SQL Postgres `DEFAULT uuidv7()` generation.** `sql.py` has no
  `@server`-driven `DEFAULT`-clause generation for any type today —
  adding one is a new emitter capability, not an extension of an
  existing per-type mapping. Deferred.
- **Prose rendering ("UUIDv7 (timestamp-ordered)") in Markdown or LSP
  hover.** Both existing renderers use type-signature-shaped output
  (`decimal(10,2)`, bare `field.type.kind`) uniformly across every
  parameterized type, never English prose for any of them. This slice
  renders `uuid(7)` as `uuid(7)` in Markdown (consistent with
  `decimal`/`binary` precedent) and leaves hover unchanged (consistent
  with `decimal`/`fixed_binary` precedent, none of which show their
  parameters in hover either).
- Any change to the 5 `TypeShape`-based emitters (Rust, Go, Java, C#,
  Python) — the design doc explicitly says no emitter's *type* mapping
  changes, and `TypeShape.from_field_type` only ever reads
  `field_type.kind` for `PrimitiveType`, never a version, so this is
  correct as-is with zero changes needed.
- Any change to the 10 direct-`FieldType`-dispatch emitters that map
  `"uuid"` to a fixed string/type (TypeScript, SQL, Protobuf, FHIR,
  dbt_yaml, ODCS, and the rest) — same reasoning, `.kind` stays `"uuid"`
  regardless of version.

## File Structure

- Modify `cli/src/modelable/grammar/modelable.lark`: `primitive_type`'s
  `"uuid" -> pt_uuid` alternative gains an optional `"(" INT ")"` suffix.
- Modify `cli/src/modelable/parser/transformer.py`: `pt_uuid` parses and
  validates the optional version argument.
- Modify `cli/src/modelable/parser/ir.py`: `PrimitiveType` gains
  `version: Literal[4, 7] = 4`.
- Modify `cli/src/modelable/emitters/json_schema.py`: `uuid(7)` fields get
  an `x-modelable-uuid-version: 7` extension key.
- Modify `cli/src/modelable/emitters/markdown.py`: `_type_str` renders
  `uuid(7)` for version 7, bare `uuid` for version 4 (unchanged).
- Modify `docs/language-reference.md`, `docs/compiler-reference.md`,
  `ROADMAP.md`, `CHANGELOG.md`.
- Modify test files: `cli/tests/test_grammar.py`,
  `cli/tests/test_emit_json_schema.py`, `cli/tests/test_emit_markdown.py`.

## Task 1: Grammar, Transformer, And IR

**Files:**
- Modify: `cli/src/modelable/grammar/modelable.lark`
- Modify: `cli/src/modelable/parser/transformer.py`
- Modify: `cli/src/modelable/parser/ir.py`
- Modify: `cli/tests/test_grammar.py`

- [ ] **Step 1: Write the failing parse and IR tests**

Append to `cli/tests/test_grammar.py`:

```python
def test_parse_uuid_v7():
    tree = parse_text("""
    domain platform {
      owner: "platform-team"
      entity Command @ 1 (additive) {
        @key commandId: uuid(7)
      }
    }
    """)
    assert tree.data == "start"


def test_uuid_v7_ir_shape():
    ir = parse_text_to_ir("""
    domain platform {
      owner: "platform-team"
      entity Command @ 1 (additive) {
        @key commandId: uuid(7)
                legacyId: uuid
      }
    }
    """)
    fields = {f.name: f.type for f in ir.domains[0].models["Command"][0].fields}
    assert fields["commandId"].kind == "uuid"
    assert fields["commandId"].version == 7
    assert fields["legacyId"].kind == "uuid"
    assert fields["legacyId"].version == 4


def test_uuid_invalid_version_is_parse_error():
    from modelable.parser.ir import ParseError

    try:
        parse_text_to_ir("""
        domain platform {
          owner: "platform-team"
          entity Command @ 1 (additive) {
            @key commandId: uuid(5)
          }
        }
        """)
        raise AssertionError("expected ParseError")
    except ParseError as exc:
        assert "uuid" in str(exc).lower()
        assert "5" in str(exc)
```

- [ ] **Step 2: Verify the tests fail**

Run from `cli/`: `uv run pytest tests/test_grammar.py -k uuid_v7 -q`.
Expected: `test_parse_uuid_v7` fails — `uuid(7)` isn't valid syntax yet
(`primitive_type` only accepts bare `"uuid"`); the other two fail because
`PrimitiveType` has no `version` attribute.

- [ ] **Step 3: Extend the grammar**

In `modelable.lark`, change:

```
              | "uuid"      -> pt_uuid
```

to:

```
              | "uuid" ("(" INT ")")?  -> pt_uuid
```

- [ ] **Step 4: Update the transformer**

In `transformer.py`, replace:

```python
    def pt_uuid(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="uuid")
```

with:

```python
    def pt_uuid(self, items: list[object]) -> PrimitiveType:
        if not items:
            return PrimitiveType(kind="uuid")
        version = int(items[0])
        if version not in (4, 7):
            raise ValueError(f"uuid version must be 4 or 7, got {version}")
        return PrimitiveType(kind="uuid", version=version)
```

`parse_text_to_ir` already wraps transformer `ValueError`s into
`ParseError` (see `cli/src/modelable/parser/parse.py`) — no new error
handling needed here, this is the same path every other parse-time
validation in this file already uses.

- [ ] **Step 5: Add the IR field**

In `parser/ir.py`, add to `PrimitiveType`:

```python
class PrimitiveType(BaseModel):
    kind: Literal[...]  # unchanged
    version: Literal[4, 7] = 4
```

- [ ] **Step 6: Verify the tests pass**

Run from `cli/`: `uv run pytest tests/test_grammar.py -k uuid_v7 -q`,
then the full file: `uv run pytest tests/test_grammar.py -q`.

- [ ] **Step 7: Run the full test suite once to check for incidental breaks**

`PrimitiveType` gaining a new field with a default shouldn't affect
equality/serialization anywhere, but this is the highest-blast-radius
change in the slice (touches the most common `FieldType` variant used
throughout the whole codebase) — run
`uv run pytest --tb=short -q` from `cli/` now, before continuing to Task
2, to catch any incidental breakage early rather than at the end.

## Task 2: JSON Schema Extension

**Files:**
- Modify: `cli/src/modelable/emitters/json_schema.py`
- Modify: `cli/tests/test_emit_json_schema.py`

- [ ] **Step 1: Write the failing test**

Append to `cli/tests/test_emit_json_schema.py`:

```python
def test_emit_json_schema_uuid_v7_adds_version_extension(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain platform {
  owner: "test-team"
  entity Command @ 1 (additive) {
    @key commandId: uuid(7)
            legacyId: uuid
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_json_schema(workspace, tmp_path / "out")
    art = next(a for a in artifacts if a.ref == "platform.Command@1")
    props = art.content["properties"]
    assert props["commandId"]["x-modelable-uuid-version"] == 7
    assert "x-modelable-uuid-version" not in props["legacyId"]
```

Check the existing imports/fixtures at the top of the file (`load_workspace`,
`emit_json_schema`) before adding — reuse them, don't reimport.

- [ ] **Step 2: Verify the test fails**

Run from `cli/`: `uv run pytest tests/test_emit_json_schema.py -k uuid_v7 -q`.
Expected: `KeyError` — no `x-modelable-uuid-version` key exists yet.

- [ ] **Step 3: Add the extension**

In `json_schema.py`'s `_type_to_json_schema`, find the `PrimitiveType`
branch (`return _primitive_to_json_schema(field_type.kind)`) and change it
to merge in the extension for `uuid(7)` only, following the same
dict-merge shape `FixedBinaryType`'s branch already uses for
`x-modelable-fixed-length`:

```python
    if isinstance(field_type, PrimitiveType):
        schema = _primitive_to_json_schema(field_type.kind)
        if field_type.kind == "uuid" and field_type.version == 7:
            schema = {**schema, "x-modelable-uuid-version": 7}
        return schema
```

Leave `_primitive_to_json_schema` itself unchanged — it stays a pure
`kind -> dict` mapping; the version-specific extension is layered on at
the call site, matching how `FixedBinaryType`/`DecimalType` extensions are
already layered on in `_type_to_json_schema` rather than inside a shared
primitive-mapping helper.

- [ ] **Step 4: Verify the test passes**

Run from `cli/`: `uv run pytest tests/test_emit_json_schema.py -k uuid_v7 -q`,
then the full file: `uv run pytest tests/test_emit_json_schema.py -q`.

## Task 3: Markdown Rendering

**Files:**
- Modify: `cli/src/modelable/emitters/markdown.py`
- Modify: `cli/tests/test_emit_markdown.py`

- [ ] **Step 1: Write the failing test**

Append to `cli/tests/test_emit_markdown.py`:

```python
def test_emit_markdown_renders_uuid_version(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain platform {
  owner: "test-team"
  entity Command @ 1 (additive) {
    @key commandId: uuid(7)
            legacyId: uuid
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_markdown(workspace, tmp_path / "out")
    art = next(a for a in artifacts if a.ref == "platform.Command@1")
    assert "uuid(7)" in art.content
    assert "legacyId" in art.content
```

Check the existing imports/fixtures at the top of the file before adding.

- [ ] **Step 2: Verify the test fails**

Run from `cli/`: `uv run pytest tests/test_emit_markdown.py -k uuid_version -q`.
Expected: fails — `_type_str` currently renders bare `field_type.kind`
("uuid") for every version.

- [ ] **Step 3: Update `_type_str`**

In `markdown.py`, change the `PrimitiveType` branch:

```python
    if isinstance(field_type, PrimitiveType):
        if field_type.kind == "uuid" and field_type.version == 7:
            return "uuid(7)"
        return field_type.kind
```

- [ ] **Step 4: Verify the test passes**

Run from `cli/`: `uv run pytest tests/test_emit_markdown.py -k uuid_version -q`,
then the full file: `uv run pytest tests/test_emit_markdown.py -q`.

## Task 4: Documentation

**Files:**
- Modify: `docs/language-reference.md`, `docs/compiler-reference.md`,
  `ROADMAP.md`, `CHANGELOG.md`

- [ ] **Step 1: Update the built-in types table**

`docs/language-reference.md`'s §2.1 built-in types table currently has
`| `uuid` | UUID v4 |`. Update to document the optional version argument
(`uuid(7)` for UUIDv7/timestamp-ordered, `uuid` unchanged/defaults to v4),
matching the row style used for `binary`/`binary(N)`.

- [ ] **Step 2: Update the compiler reference**

`docs/compiler-reference.md` §6 (JSON Schema Emitter) has a `uuid` row in
its type-mapping table. Add a note (or a second row) for `uuid(7)`'s
`x-modelable-uuid-version` extension key, matching how `binary(N)`'s
`x-modelable-fixed-length` key is documented there.

- [ ] **Step 3: Update ROADMAP and CHANGELOG**

Mark this slice shipped in `ROADMAP.md`'s feature-gaps response entry —
note it lands independently (no dependency on/from the other four shipped
slices) and explicitly list the two deferred target-mapping improvements
(SQL `DEFAULT uuidv7()`, prose hover/Markdown rendering) as intentional,
not silent omissions. Add a `CHANGELOG.md` `[Unreleased]` entry with the
same scope note.

- [ ] **Step 4: Verify docs mention the new capability**

Run from repo root:
`rg -n "uuid\(7\)|x-modelable-uuid-version" docs/language-reference.md docs/compiler-reference.md CHANGELOG.md ROADMAP.md`.

## Task 5: Final Verification

- [ ] **Step 1: Run all focused tests**

```bash
uv run pytest tests/test_grammar.py tests/test_emit_json_schema.py tests/test_emit_markdown.py --tb=short -q
```

- [ ] **Step 2: Run the full suite, ruff, and the mypy baseline ratchet**

```bash
uv run ruff format --check .
uv run ruff check .
uv run pytest --tb=short
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
```

Regenerate `mypy-baseline.txt` from a fresh `uv run mypy ...` run taken
**after** `ruff format`'s final pass, per the now-established lesson from
every prior slice.

- [ ] **Step 3: Inspect the final diff**

```bash
git diff --stat
```

Expected: diff touches the grammar, transformer, IR, JSON Schema emitter,
Markdown emitter, their tests, the four documentation files, the design
doc's correction note, and the mypy baseline.

## Self-Review

Spec coverage:

- Covered: `uuid(7)` parses; invalid version arguments are parse-time
  errors; `PrimitiveType.version` IR field; JSON Schema
  `x-modelable-uuid-version` extension; Markdown `uuid(7)` rendering.
- Deferred by design (see Scope section above and the design doc's
  correction note): SQL Postgres `DEFAULT uuidv7()` generation (no
  existing `@server`-driven default mechanism to extend), prose rendering
  in Markdown/LSP hover (inconsistent with how every other parameterized
  type is already rendered in both places).

Placeholder scan: none — every task ends with a green-test checkpoint.

Type consistency: `PrimitiveType.version` is a new field with a safe
default (`4`), so every existing `PrimitiveType(kind="uuid")` construction
site across the codebase (grepped: emitters, LSP, validation) continues to
mean exactly what it meant before — no call site needs updating, since
none of them read or need to change based on `.version`.
