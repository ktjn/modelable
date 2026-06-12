# JSON Passthrough Type Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `json` primitive type to Modelable's IDL/IR (mapping to `serde_json::Value` / `unknown` / an empty JSON Schema), and complete the previously-unimplemented `@wire(clickhouse: "string")` / `map<K, json>` → `String` row conversion in the Rust emitter, so that Observable can model JSON-passthrough fields like `tracing.Span@1.attributes`.

**Architecture:** Six small, additive changes across the grammar/transformer/IR (new primitive kind), three emitters (JSON Schema, TypeScript, Rust primitive mappings), and the Rust emitter's projection/from-impl machinery (clickhouse-hint-aware shape annotation + generated `serde_json::to_string` conversion). Each change is independently testable; later tasks build on earlier ones but no task requires reverting prior work.

**Tech Stack:** Python 3.14, `lark` grammar, `pydantic` IR models, `pytest`, `uv`.

---

## Before You Start

All work happens in `C:\git\modelable\cli`. Run commands from that directory unless stated otherwise. Use `uv run` to invoke tools (matches existing project convention — see `cli/tests/` for examples of how tests are structured).

Reference spec: `docs/superpowers/specs/2026-06-11-json-passthrough-type-design.md` (approved). Reference prior spec for hint vocabulary: `docs/superpowers/specs/2026-06-08-target-serialization-hints-design.md`.

---

### Task 1: Add `json` to the grammar, transformer, and IR

**Files:**
- Modify: `cli/src/modelable/grammar/modelable.lark:86-95`
- Modify: `cli/src/modelable/parser/transformer.py:342-344` (near `pt_binary`)
- Modify: `cli/src/modelable/parser/ir.py:150-162` (`PrimitiveType.kind` Literal)
- Test: `cli/tests/test_transformer.py`

- [ ] **Step 1: Write the failing test**

Add to `cli/tests/test_transformer.py` (near the other `pt_*`/primitive-type coverage — there isn't a dedicated one today, so add this as a new top-level test function):

```python
def test_transform_json_primitive_type():
    mdl = parse_text_to_ir("""
    domain example {
      owner: "test-team"
      entity Widget @ 1 (additive) {
        @key id: uuid
        payload: json
        tags: array<json>
        attributes: map<string, json>
      }
    }
    """)

    fields = {f.name: f for f in mdl.domains[0].models["Widget"][0].fields}
    assert fields["payload"].type.kind == "json"
    assert fields["tags"].type.item.kind == "json"
    assert fields["attributes"].type.value.kind == "json"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_transformer.py::test_transform_json_primitive_type -v`
Expected: FAIL — grammar parse error (`json` is not a recognized `primitive_type`), since `pt_json` doesn't exist yet.

- [ ] **Step 3: Add `json` to the grammar**

In `cli/src/modelable/grammar/modelable.lark`, change lines 86-95 from:

```lark
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
```

to:

```lark
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
```

- [ ] **Step 4: Add `pt_json` to the transformer**

In `cli/src/modelable/parser/transformer.py`, add a new method immediately after `pt_binary` (around line 343-344):

```python
    def pt_binary(self, _items):
        return PrimitiveType(kind="binary")

    def pt_json(self, _items):
        return PrimitiveType(kind="json")
```

- [ ] **Step 5: Add `"json"` to the IR `PrimitiveType.kind` Literal**

In `cli/src/modelable/parser/ir.py`, change the `PrimitiveType` class (lines 150-162) from:

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
    ]
```

to:

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
    ]
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_transformer.py::test_transform_json_primitive_type -v`
Expected: PASS

- [ ] **Step 7: Run the full transformer/parser test suite**

Run: `uv run pytest tests/test_transformer.py -v`
Expected: All PASS (no regressions to existing primitive-type parsing).

- [ ] **Step 8: Commit**

```bash
cd C:\git\modelable
git add cli/src/modelable/grammar/modelable.lark cli/src/modelable/parser/transformer.py cli/src/modelable/parser/ir.py cli/tests/test_transformer.py
git commit -m "feat(ir): add json primitive type to grammar, transformer, and IR"
```

---

### Task 2: JSON Schema emitter — `json` → empty schema (`{}`)

**Files:**
- Modify: `cli/src/modelable/emitters/json_schema.py:410-424` (`_primitive_to_json_schema`)
- Test: `cli/tests/test_emit_json_schema.py`

- [ ] **Step 1: Write the failing test**

Add to `cli/tests/test_emit_json_schema.py`:

```python
def test_emit_json_primitive_type_is_empty_schema(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain example {
  owner: "test-team"
  entity Widget @ 1 (additive) {
    @key id: uuid
    payload: json
    attributes: map<string, json>
    tags: array<json>
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifacts = emit_json_schema(workspace, tmp_path / "out")
    schema = artifacts[0].content
    props = schema["properties"]

    assert props["payload"] == {}
    assert props["attributes"]["type"] == "object"
    assert props["attributes"]["additionalProperties"] == {}
    assert props["tags"]["type"] == "array"
    assert props["tags"]["items"] == {}

    Draft202012Validator.check_schema(schema)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_emit_json_schema.py::test_emit_json_primitive_type_is_empty_schema -v`
Expected: FAIL — `props["payload"]` is currently `{"type": "string"}` (the `_primitive_to_json_schema` fallback for an unrecognized kind), not `{}`.

- [ ] **Step 3: Add `"json"` to `_primitive_to_json_schema`**

In `cli/src/modelable/emitters/json_schema.py`, change the mapping in `_primitive_to_json_schema` (lines 410-423) from:

```python
def _primitive_to_json_schema(kind: str) -> dict:
    mapping: dict[str, dict] = {
        "string": {"type": "string"},
        "bool": {"type": "boolean"},
        "int": {"type": "integer", "format": "int64"},
        "float": {"type": "number"},
        "uuid": {"type": "string", "format": "uuid"},
        "timestamp": {"type": "string", "format": "date-time"},
        "date": {"type": "string", "format": "date"},
        "time": {"type": "string", "format": "time"},
        "duration": {"type": "string", "format": "duration"},
        "binary": {"type": "string", "contentEncoding": "base64"},
    }
    return mapping.get(kind, {"type": "string"})
```

to:

```python
def _primitive_to_json_schema(kind: str) -> dict:
    mapping: dict[str, dict] = {
        "string": {"type": "string"},
        "bool": {"type": "boolean"},
        "int": {"type": "integer", "format": "int64"},
        "float": {"type": "number"},
        "uuid": {"type": "string", "format": "uuid"},
        "timestamp": {"type": "string", "format": "date-time"},
        "date": {"type": "string", "format": "date"},
        "time": {"type": "string", "format": "time"},
        "duration": {"type": "string", "format": "duration"},
        "binary": {"type": "string", "contentEncoding": "base64"},
        "json": {},
    }
    return mapping.get(kind, {"type": "string"})
```

`{}` is the JSON Schema "any value" schema — combined with `MapType` → `{"type": "object", "additionalProperties": <value schema>}` and `ArrayType` → `{"type": "array", "items": <element schema>}` (both already implemented and unaffected by this change), `map<string, json>` → `{"type": "object", "additionalProperties": {}}` and `array<json>` → `{"type": "array", "items": {}}` fall out automatically.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_emit_json_schema.py::test_emit_json_primitive_type_is_empty_schema -v`
Expected: PASS

- [ ] **Step 5: Run the full JSON Schema emitter test suite**

Run: `uv run pytest tests/test_emit_json_schema.py -v`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
cd C:\git\modelable
git add cli/src/modelable/emitters/json_schema.py cli/tests/test_emit_json_schema.py
git commit -m "feat(json-schema): map json primitive type to empty schema"
```

---

### Task 3: TypeScript emitter — `json` → `unknown`

**Files:**
- Modify: `cli/src/modelable/emitters/typescript.py:226-237` (`_type_to_ts` primitive mapping)
- Test: `cli/tests/test_emit_typescript.py`

- [ ] **Step 1: Write the failing test**

Add to `cli/tests/test_emit_typescript.py`:

```python
def test_emit_typescript_json_primitive_maps_to_unknown(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain example {
  owner: "test-team"
  entity Widget @ 1 (additive) {
    @key id: uuid
    payload: json
    attributes: map<string, json>
    tags: array<json>
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    model_art = next(a for a in artifacts if a.ref == "example.Widget@1")

    assert "payload: unknown;" in model_art.content
    assert "attributes: Record<string, unknown>;" in model_art.content
    assert "tags: unknown[];" in model_art.content
```

- [ ] **Step 2: Run test to verify it fails or passes for the wrong reason**

Run: `uv run pytest tests/test_emit_typescript.py::test_emit_typescript_json_primitive_maps_to_unknown -v`

Note: this may already PASS today, because `_type_to_ts`'s primitive mapping dict currently does `mapping.get(field_type.kind, "unknown")` — an unrecognized `"json"` kind already falls through to `"unknown"`. That's an accidental pass, not a guaranteed one (the fallback could change for unrelated reasons). Proceed to Step 3 regardless, to make the mapping explicit and locked-in.

- [ ] **Step 3: Add an explicit `"json"` entry to the primitive mapping**

In `cli/src/modelable/emitters/typescript.py`, change the mapping dict inside `_type_to_ts` (lines 226-237) from:

```python
        mapping = {
            "string": "string",
            "int": "number",
            "float": "number",
            "bool": "boolean",
            "date": "string",
            "time": "string",
            "timestamp": "string",
            "uuid": "string",
            "duration": "string",
            "binary": "string",
        }
        return mapping.get(field_type.kind, "unknown")
```

to:

```python
        mapping = {
            "string": "string",
            "int": "number",
            "float": "number",
            "bool": "boolean",
            "date": "string",
            "time": "string",
            "timestamp": "string",
            "uuid": "string",
            "duration": "string",
            "binary": "string",
            "json": "unknown",
        }
        return mapping.get(field_type.kind, "unknown")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_emit_typescript.py::test_emit_typescript_json_primitive_maps_to_unknown -v`
Expected: PASS

- [ ] **Step 5: Run the full TypeScript emitter test suite**

Run: `uv run pytest tests/test_emit_typescript.py -v`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
cd C:\git\modelable
git add cli/src/modelable/emitters/typescript.py cli/tests/test_emit_typescript.py
git commit -m "feat(typescript): map json primitive type to unknown explicitly"
```

---

### Task 4: Rust emitter — `json` → `serde_json::Value`, with `// requires: serde_json` header

**Files:**
- Modify: `cli/src/modelable/emitters/rust.py` — `_primitive_to_rust` (lines 473-486), `_header_lines` (lines 278-293), new helper `_any_needs_serde_json`, callers in `_emit_model` and `_emit_projection`
- Test: `cli/tests/test_emit_rust.py`

- [ ] **Step 1: Write the failing test**

Add to `cli/tests/test_emit_rust.py`:

```python
def test_emit_rust_json_primitive_maps_to_serde_json_value(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain example {
  owner: "test-team"
  entity Widget @ 1 (additive) {
    @key id: uuid
    payload: json
    attributes: map<string, json>
    tags: array<json>
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_rust(workspace, tmp_path / "out")
    model = next(a for a in artifacts if a.ref == "example.Widget@1")

    assert "pub payload: serde_json::Value," in model.content
    assert "pub attributes: HashMap<String, serde_json::Value>," in model.content
    assert "pub tags: Vec<serde_json::Value>," in model.content
    assert "// requires: serde_json (https://docs.rs/serde_json)" in model.content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_emit_rust.py::test_emit_rust_json_primitive_maps_to_serde_json_value -v`
Expected: FAIL — `_primitive_to_rust("json")` currently falls back to `"String"` (the dict's default), and no `// requires: serde_json` header is emitted.

- [ ] **Step 3: Add `"json"` to `_primitive_to_rust`**

In `cli/src/modelable/emitters/rust.py`, change `_primitive_to_rust` (lines 473-486) from:

```python
def _primitive_to_rust(kind: str) -> str:
    mapping = {
        "string": "String",
        "bool": "bool",
        "int": "i64",
        "float": "f64",
        "uuid": "uuid::Uuid",
        "timestamp": "String",
        "date": "String",
        "time": "String",
        "duration": "String",
        "binary": "Vec<u8>",
    }
    return mapping.get(kind, "String")
```

to:

```python
def _primitive_to_rust(kind: str) -> str:
    mapping = {
        "string": "String",
        "bool": "bool",
        "int": "i64",
        "float": "f64",
        "uuid": "uuid::Uuid",
        "timestamp": "String",
        "date": "String",
        "time": "String",
        "duration": "String",
        "binary": "Vec<u8>",
        "json": "serde_json::Value",
    }
    return mapping.get(kind, "String")
```

`HashMap<String, V>` / `Vec<T>` wrapping for `map`/`array` shapes (in `_shape_base_annotation`, unchanged by this task) already recurses through this function, so `map<string, json>` → `HashMap<String, serde_json::Value>` and `array<json>` → `Vec<serde_json::Value>` follow automatically.

- [ ] **Step 4: Add `serde_json` parameter to `_header_lines`**

In `cli/src/modelable/emitters/rust.py`, change `_header_lines` (lines 278-293) from:

```python
def _header_lines(*, serde_with: bool = False, sqlx: bool = False, clickhouse: bool = False, uuid: bool = False) -> list[str]:
    lines = [
        "// @generated by Modelable",
        "use std::collections::HashMap;",
        "",
    ]
    if clickhouse:
        lines.insert(1, "// requires: clickhouse (https://docs.rs/clickhouse)")
    if sqlx:
        lines.insert(1, "// requires: sqlx (https://docs.rs/sqlx)")
    if serde_with:
        lines.insert(1, "// requires: serde_with (https://docs.rs/serde_with)")
    if uuid:
        lines.insert(1, "// requires: uuid (https://docs.rs/uuid)")
    return lines
```

to:

```python
def _header_lines(*, serde_with: bool = False, sqlx: bool = False, clickhouse: bool = False, uuid: bool = False, serde_json: bool = False) -> list[str]:
    lines = [
        "// @generated by Modelable",
        "use std::collections::HashMap;",
        "",
    ]
    if clickhouse:
        lines.insert(1, "// requires: clickhouse (https://docs.rs/clickhouse)")
    if sqlx:
        lines.insert(1, "// requires: sqlx (https://docs.rs/sqlx)")
    if serde_with:
        lines.insert(1, "// requires: serde_with (https://docs.rs/serde_with)")
    if uuid:
        lines.insert(1, "// requires: uuid (https://docs.rs/uuid)")
    if serde_json:
        lines.insert(1, "// requires: serde_json (https://docs.rs/serde_json)")
    return lines
```

- [ ] **Step 5: Add `_any_needs_serde_json` helper**

In `cli/src/modelable/emitters/rust.py`, add this immediately after `_any_needs_uuid` (lines 487-489):

```python
def _any_needs_uuid(field_specs: list[_FieldSpec]) -> bool:
    return any("uuid::Uuid" in spec.annotation for spec in field_specs)


def _any_needs_serde_json(field_specs: list[_FieldSpec]) -> bool:
    return any("serde_json::Value" in spec.annotation for spec in field_specs)
```

- [ ] **Step 6: Wire `_any_needs_serde_json` into `_emit_model`**

In `cli/src/modelable/emitters/rust.py`, change `_emit_model` (around lines 90-93) from:

```python
    needs_serde_with = _any_needs_serde_with(field_specs)
    needs_uuid = _any_needs_uuid(field_specs)
    lines = _header_lines(serde_with=needs_serde_with, uuid=needs_uuid)
```

to:

```python
    needs_serde_with = _any_needs_serde_with(field_specs)
    needs_uuid = _any_needs_uuid(field_specs)
    needs_serde_json = _any_needs_serde_json(field_specs)
    lines = _header_lines(serde_with=needs_serde_with, uuid=needs_uuid, serde_json=needs_serde_json)
```

- [ ] **Step 7: Wire `_any_needs_serde_json` into `_emit_projection`**

In `cli/src/modelable/emitters/rust.py`, change `_emit_projection` (around lines 141-148) from:

```python
    needs_serde_with = _any_needs_serde_with(field_specs)
    needs_uuid = _any_needs_uuid(field_specs)
    storage_gated = sqlx_fromrow or clickhouse_row
    extra_derives: list[str] = []
    if sqlx_fromrow:
        extra_derives.append("sqlx::FromRow")
    if clickhouse_row:
        extra_derives.append("clickhouse::Row")
    lines = _header_lines(serde_with=needs_serde_with, sqlx=sqlx_fromrow, clickhouse=clickhouse_row, uuid=needs_uuid)
```

to:

```python
    needs_serde_with = _any_needs_serde_with(field_specs)
    needs_uuid = _any_needs_uuid(field_specs)
    needs_serde_json = _any_needs_serde_json(field_specs)
    storage_gated = sqlx_fromrow or clickhouse_row
    extra_derives: list[str] = []
    if sqlx_fromrow:
        extra_derives.append("sqlx::FromRow")
    if clickhouse_row:
        extra_derives.append("clickhouse::Row")
    lines = _header_lines(serde_with=needs_serde_with, sqlx=sqlx_fromrow, clickhouse=clickhouse_row, uuid=needs_uuid, serde_json=needs_serde_json)
```

(Note: Task 6 below will extend this `needs_serde_json` computation further, for the case where a projection's *own* fields don't contain `serde_json::Value` but its generated `From` impl still calls `serde_json::to_string`. That extension is deferred to Task 6 because it depends on the helper introduced there.)

- [ ] **Step 8: Run test to verify it passes**

Run: `uv run pytest tests/test_emit_rust.py::test_emit_rust_json_primitive_maps_to_serde_json_value -v`
Expected: PASS

- [ ] **Step 9: Run the full Rust emitter test suite**

Run: `uv run pytest tests/test_emit_rust.py -v`
Expected: All PASS.

- [ ] **Step 10: Commit**

```bash
cd C:\git\modelable
git add cli/src/modelable/emitters/rust.py cli/tests/test_emit_rust.py
git commit -m "feat(rust): map json primitive type to serde_json::Value"
```

---

### Task 5: Rust emitter — `@wire(clickhouse: "string")` on `map<K, json>` (and bare `json`) projection fields → `String`

**Files:**
- Modify: `cli/src/modelable/emitters/rust.py` — `_emit_projection` (thread `clickhouse_hint`), `_shape_annotation`/`_shape_base_annotation` (lines 399-472)
- Test: `cli/tests/test_emit_rust.py`

This implements the `clickhouse: "string"` / `map<K, json>` row of the closed vocabulary table in `2026-06-08-target-serialization-hints-design.md` (§2, line 78) for the *shape* side. Task 6 implements the *conversion* side.

- [ ] **Step 1: Write the failing test**

Add to `cli/tests/test_emit_rust.py`:

```python
def test_emit_rust_clickhouse_string_hint_on_map_json_field_becomes_string(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain telemetry {
  owner: "test-team"
  entity Span @ 1 (additive) {
    @key spanId: uuid
    attributes: map<string, json>
  }

  projection SpanRow @ 1
    from telemetry.Span @ 1 as s
  {
    spanId <- s.spanId
    @wire(clickhouse: "string")
    attributes <- s.attributes
  }
}
""",
        encoding="utf-8",
    )
    (tmp_path / "bindings.mdl").write_text(
        """
binding ch-conn {
  adapter: clickhouse
}

binding span-binding {
  model: telemetry.Span @ 1
  adapter: ch-conn
  table: "spans"
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_rust(workspace, tmp_path / "out")

    proj = next(a for a in artifacts if a.ref == "telemetry.SpanRow@1")
    assert "pub attributes: String," in proj.content

    # The entity itself keeps the canonical map<K, json> shape regardless of the
    # projection-level hint.
    model = next(a for a in artifacts if a.ref == "telemetry.Span@1")
    assert "pub attributes: HashMap<String, serde_json::Value>," in model.content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_emit_rust.py::test_emit_rust_clickhouse_string_hint_on_map_json_field_becomes_string -v`
Expected: FAIL — `proj.content` currently has `pub attributes: HashMap<String, serde_json::Value>,` (the `clickhouse: "string"` hint is parsed but not consulted by `_shape_annotation`).

- [ ] **Step 3: Thread `clickhouse_hint` through `_shape_annotation` / `_shape_base_annotation`**

In `cli/src/modelable/emitters/rust.py`, change the signatures and bodies of `_shape_annotation` and `_shape_base_annotation` (lines 399-472) from:

```python
def _shape_annotation(
    shape: TypeShape,
    *,
    owner_type: str,
    path: list[str],
    definitions: dict[str, list[str]],
    rust_hint=None,
) -> str:
    base = _shape_base_annotation(
        shape,
        owner_type=owner_type,
        path=path,
        definitions=definitions,
        rust_hint=rust_hint,
    )
    if shape.optional or shape.nullable:
        return f"Option<{base}>"
    return base


def _shape_base_annotation(
    shape: TypeShape,
    *,
    owner_type: str,
    path: list[str],
    definitions: dict[str, list[str]],
    rust_hint=None,
) -> str:
    if shape.kind == "primitive":
        if rust_hint is not None and getattr(rust_hint, "type", None) and (shape.ref or "string") == "int":
            return rust_hint.type
        return _primitive_to_rust(shape.ref or "string")
    if shape.kind == "decimal":
        return "String"
    if shape.kind == "array":
        element = shape.element or TypeShape(kind="primitive", ref="object")
        element_type = _shape_annotation(
            element,
            owner_type=owner_type,
            path=path + ["Item"],
            definitions=definitions,
        )
        return f"Vec<{element_type}>"
    if shape.kind == "map":
        value = shape.value or TypeShape(kind="primitive", ref="object")
        value_type = _shape_annotation(
            value,
            owner_type=owner_type,
            path=path + ["Value"],
            definitions=definitions,
        )
        return f"HashMap<String, {value_type}>"
```

to:

```python
def _shape_annotation(
    shape: TypeShape,
    *,
    owner_type: str,
    path: list[str],
    definitions: dict[str, list[str]],
    rust_hint=None,
    clickhouse_hint=None,
) -> str:
    base = _shape_base_annotation(
        shape,
        owner_type=owner_type,
        path=path,
        definitions=definitions,
        rust_hint=rust_hint,
        clickhouse_hint=clickhouse_hint,
    )
    if shape.optional or shape.nullable:
        return f"Option<{base}>"
    return base


def _shape_base_annotation(
    shape: TypeShape,
    *,
    owner_type: str,
    path: list[str],
    definitions: dict[str, list[str]],
    rust_hint=None,
    clickhouse_hint=None,
) -> str:
    clickhouse_string = clickhouse_hint is not None and getattr(clickhouse_hint, "encoding", None) == "string"
    if shape.kind == "primitive":
        if rust_hint is not None and getattr(rust_hint, "type", None) and (shape.ref or "string") == "int":
            return rust_hint.type
        if shape.ref == "json" and clickhouse_string:
            return "String"
        return _primitive_to_rust(shape.ref or "string")
    if shape.kind == "decimal":
        return "String"
    if shape.kind == "array":
        element = shape.element or TypeShape(kind="primitive", ref="object")
        element_type = _shape_annotation(
            element,
            owner_type=owner_type,
            path=path + ["Item"],
            definitions=definitions,
        )
        return f"Vec<{element_type}>"
    if shape.kind == "map":
        value = shape.value or TypeShape(kind="primitive", ref="object")
        if value.kind == "primitive" and value.ref == "json" and clickhouse_string:
            return "String"
        value_type = _shape_annotation(
            value,
            owner_type=owner_type,
            path=path + ["Value"],
            definitions=definitions,
        )
        return f"HashMap<String, {value_type}>"
```

- [ ] **Step 4: Pass `clickhouse_hint` from `_emit_projection`**

In `cli/src/modelable/emitters/rust.py`, change the `_shape_annotation` call inside `_emit_projection` (around lines 132-138) from:

```python
        annotation = _shape_annotation(
            field_shape,
            owner_type=type_name,
            path=[field.name],
            definitions=nested_definitions,
            rust_hint=wire.get("rust"),
        )
```

to:

```python
        annotation = _shape_annotation(
            field_shape,
            owner_type=type_name,
            path=[field.name],
            definitions=nested_definitions,
            rust_hint=wire.get("rust"),
            clickhouse_hint=wire.get("clickhouse"),
        )
```

The other three call sites of `_shape_annotation` (`_field_specs_from_model_fields`, `_field_specs_from_object_fields`, and the recursive `array`/`map` element calls inside `_shape_base_annotation` itself) are intentionally left without `clickhouse_hint` — it defaults to `None`, so entity/object field emission is unaffected (entities always emit the canonical `HashMap<String, serde_json::Value>` shape, per Resolved Design Decision in the spec).

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_emit_rust.py::test_emit_rust_clickhouse_string_hint_on_map_json_field_becomes_string -v`
Expected: PASS

- [ ] **Step 6: Run the full Rust emitter test suite**

Run: `uv run pytest tests/test_emit_rust.py -v`
Expected: All PASS — in particular, re-check `test_emit_rust_clickhouse_row_on_clickhouse_bound_projection` and other `clickhouse: "uuid"`-hint tests still pass unchanged (the new `clickhouse_string` check is `False` for `encoding == "uuid"`, so existing UUID handling in `_serde_attrs_for_field` is untouched).

- [ ] **Step 7: Commit**

```bash
cd C:\git\modelable
git add cli/src/modelable/emitters/rust.py cli/tests/test_emit_rust.py
git commit -m "feat(rust): clickhouse string hint maps map<K,json> projection fields to String"
```

---

### Task 6: Rust emitter — generate `serde_json::to_string` conversion in `_emit_from_impl`

**Files:**
- Modify: `cli/src/modelable/emitters/rust.py` — new helper `_projection_field_is_json_passthrough_to_string`, `_emit_from_impl` (lines 166-225), `_emit_projection`'s `needs_serde_json` computation (extends Task 4 Step 7)
- Test: `cli/tests/test_emit_rust.py`

This implements the conversion half of the `clickhouse: "string"` / `map<K, json>` row: "generated `From` impls call `serde_json::to_string`/`from_str`" (per `2026-06-08-target-serialization-hints-design.md` §2, line 78). Only the `to_string` direction is generated (`_emit_from_impl` only emits `From<Entity> for Projection`); the reverse (`from_str`, row → entity) is deferred per Resolved Design Decision #2 in `2026-06-11-json-passthrough-type-design.md`.

- [ ] **Step 1: Write the failing test**

Add to `cli/tests/test_emit_rust.py`:

```python
def test_emit_rust_from_impl_generates_serde_json_to_string_for_clickhouse_string_map(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain telemetry {
  owner: "test-team"
  entity Span @ 1 (additive) {
    @key spanId: uuid
    attributes: map<string, json>
  }

  projection SpanRow @ 1
    from telemetry.Span @ 1 as s
  {
    spanId <- s.spanId
    @wire(clickhouse: "string")
    attributes <- s.attributes
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_rust(workspace, tmp_path / "out")

    proj = next(a for a in artifacts if a.ref == "telemetry.SpanRow@1")
    assert "attributes: serde_json::to_string(&src.attributes).unwrap_or_default()," in proj.content
    assert "spanId" not in proj.content or "span_id: src.span_id.into()," in proj.content
    assert "// requires: serde_json (https://docs.rs/serde_json)" in proj.content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_emit_rust.py::test_emit_rust_from_impl_generates_serde_json_to_string_for_clickhouse_string_map -v`
Expected: FAIL — `_emit_from_impl` currently emits `attributes: src.attributes.into(),` (which wouldn't even compile, since `HashMap<String, serde_json::Value>` has no `Into<String>` impl) and the projection struct (whose only field types are `uuid::Uuid` and `String` after Task 5) doesn't trigger `needs_serde_json`, so the header comment is missing too.

- [ ] **Step 3: Add `_projection_field_is_json_passthrough_to_string` helper**

In `cli/src/modelable/emitters/rust.py`, add this new function immediately before `_emit_from_impl` (i.e. just before line 166):

```python
def _projection_field_is_json_passthrough_to_string(proj_field, version: ProjectionVersion, mdl: MdlFile) -> bool:
    """True if this projection field maps a map<K, json> (or bare json) source
    field to a @wire(clickhouse: "string") String target — i.e. needs a
    generated serde_json::to_string conversion in the From impl, and a
    serde_json::Value-shaped header requirement even though the projection's
    own field type is plain String.
    """
    if not isinstance(proj_field.mapping, DirectMapping):
        return False
    field_shape = _resolve_projection_field_shape(proj_field, version, mdl)
    if field_shape is None:
        return False
    is_json_value = (
        field_shape.kind == "primitive" and field_shape.ref == "json"
    ) or (
        field_shape.kind == "map"
        and field_shape.value is not None
        and field_shape.value.kind == "primitive"
        and field_shape.value.ref == "json"
    )
    if not is_json_value:
        return False
    wire = _resolve_merged_projection_wire(proj_field, version, mdl)
    ch_hint = wire.get("clickhouse")
    return ch_hint is not None and getattr(ch_hint, "encoding", None) == "string"
```

- [ ] **Step 4: Use the helper in `_emit_from_impl`**

In `cli/src/modelable/emitters/rust.py`, change the field loop inside `_emit_from_impl` (lines ~213-223) from:

```python
    for proj_field in version.fields:
        rust_name = _field_name(proj_field.name)
        if isinstance(proj_field.mapping, DirectMapping):
            src_rust_name = _field_name(proj_field.mapping.source_field)
            field_shape = _resolve_projection_field_shape(proj_field, version, mdl)
            if field_shape is not None and _shape_involves_object(field_shape):
                lines.append(f"            {rust_name}: Default::default(), // nested struct — provide manual impl")
            else:
                lines.append(f"            {rust_name}: src.{src_rust_name}.into(),")
        else:
            lines.append(f"            {rust_name}: Default::default(), // computed — provide manual impl")
```

to:

```python
    for proj_field in version.fields:
        rust_name = _field_name(proj_field.name)
        if isinstance(proj_field.mapping, DirectMapping):
            src_rust_name = _field_name(proj_field.mapping.source_field)
            field_shape = _resolve_projection_field_shape(proj_field, version, mdl)
            if _projection_field_is_json_passthrough_to_string(proj_field, version, mdl):
                lines.append(f"            {rust_name}: serde_json::to_string(&src.{src_rust_name}).unwrap_or_default(),")
            elif field_shape is not None and _shape_involves_object(field_shape):
                lines.append(f"            {rust_name}: Default::default(), // nested struct — provide manual impl")
            else:
                lines.append(f"            {rust_name}: src.{src_rust_name}.into(),")
        else:
            lines.append(f"            {rust_name}: Default::default(), // computed — provide manual impl")
```

- [ ] **Step 5: Extend `needs_serde_json` in `_emit_projection` to cover the conversion case**

In `cli/src/modelable/emitters/rust.py`, change the line added in Task 4 Step 7 inside `_emit_projection`:

```python
    needs_serde_json = _any_needs_serde_json(field_specs)
```

to:

```python
    needs_serde_json = _any_needs_serde_json(field_specs) or any(
        _projection_field_is_json_passthrough_to_string(f, version, mdl) for f in version.fields
    )
```

This covers the case in the test above: the `SpanRow` struct's own fields are `uuid::Uuid` and `String` (no `serde_json::Value` anywhere in `field_specs`), but its generated `From` impl calls `serde_json::to_string`, so the `// requires: serde_json` header comment is still needed.

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_emit_rust.py::test_emit_rust_from_impl_generates_serde_json_to_string_for_clickhouse_string_map -v`
Expected: PASS

- [ ] **Step 7: Run the full Rust emitter test suite**

Run: `uv run pytest tests/test_emit_rust.py -v`
Expected: All PASS — pay particular attention to `test_emit_rust_from_impl_basic`, `test_emit_rust_from_impl_storage_gated`, `test_emit_rust_from_impl_skipped_with_joins`, and `test_emit_rust_from_impl_computed_field_defaults`, none of which involve `json`/`map<K,json>` fields and so should be completely unaffected (the new helper returns `False` for all their fields, falling through to the existing `.into()`/`Default::default()` branches unchanged).

- [ ] **Step 8: Commit**

```bash
cd C:\git\modelable
git add cli/src/modelable/emitters/rust.py cli/tests/test_emit_rust.py
git commit -m "feat(rust): generate serde_json::to_string conversion for clickhouse-string map<K,json> projection fields"
```

---

### Task 7: End-to-end test mirroring Observable's `tracing.mdl` usage, and full test suite run

**Files:**
- Test: `cli/tests/test_emit_rust.py` (new end-to-end test)
- No source changes — this task is verification only.

- [ ] **Step 1: Write an end-to-end test combining Tasks 1-6**

Add to `cli/tests/test_emit_rust.py`. This mirrors the actual shape of `tracing.Span@1` / `SpanRow@1` in Observable's `models/tracing.mdl` (a `map<string, json>` entity field, projected to a `@wire(clickhouse: "string")` `String` row field), confirming the full pipeline — grammar → IR → Rust shape → Rust conversion — works together for a realistic model:

```python
def test_emit_rust_json_passthrough_end_to_end(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain tracing {
  owner: "platform-team"
  entity Span @ 1 (additive) {
    @key spanId: string
    traceId: string
    attributes: map<string, json>
    resourceAttributes: map<string, json>
  }

  projection SpanRow @ 1
    from tracing.Span @ 1 as s
  {
    spanId <- s.spanId
    traceId <- s.traceId
    @wire(clickhouse: "string")
    attributes <- s.attributes
    @wire(clickhouse: "string")
    resourceAttributes <- s.resourceAttributes
  }
}
""",
        encoding="utf-8",
    )
    (tmp_path / "bindings.mdl").write_text(
        """
binding ch-conn {
  adapter: clickhouse
}

binding span-binding {
  model: tracing.Span @ 1
  adapter: ch-conn
  table: "spans"
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_rust(workspace, tmp_path / "out")

    model = next(a for a in artifacts if a.ref == "tracing.Span@1")
    assert "pub attributes: HashMap<String, serde_json::Value>," in model.content
    assert "pub resource_attributes: HashMap<String, serde_json::Value>," in model.content
    assert "// requires: serde_json (https://docs.rs/serde_json)" in model.content

    proj = next(a for a in artifacts if a.ref == "tracing.SpanRow@1")
    assert "pub attributes: String," in proj.content
    assert "pub resource_attributes: String," in proj.content
    assert "attributes: serde_json::to_string(&src.attributes).unwrap_or_default()," in proj.content
    assert "resource_attributes: serde_json::to_string(&src.resource_attributes).unwrap_or_default()," in proj.content
    assert "clickhouse::Row" in proj.content
    assert "// requires: serde_json (https://docs.rs/serde_json)" in proj.content
```

- [ ] **Step 2: Run the new test**

Run: `uv run pytest tests/test_emit_rust.py::test_emit_rust_json_passthrough_end_to_end -v`
Expected: PASS (all building blocks were implemented in Tasks 1-6).

- [ ] **Step 3: Run the entire Python test suite**

Run: `uv run pytest -q`
Expected: All PASS, no regressions anywhere (LSP, other emitters, SQL DDL, compatibility/lineage checks, etc. — `json` is additive and none of those should reference the new kind, but this confirms nothing exhaustively switches on `PrimitiveType.kind` without a default).

If any non-Rust/non-required emitter (Go, Java, C#, Python, SQL DDL, LSP semantic tokens) fails because it does direct dict indexing (`dict[kind]`, raising `KeyError`) instead of `.get(kind, default)` for an unrecognized primitive kind: fix that one call site to use `.get(kind, <existing-default-for-that-emitter>)`, matching the pattern already used in `cli/src/modelable/emitters/sql.py` (`_PG_PRIMITIVE.get(field_type.kind, "TEXT")` / `_CH_PRIMITIVE.get(field_type.kind, "String")`). This is a pre-existing latent bug for *any* unrecognized primitive, not `json`-specific — fix only the call sites that actually fail, do not preemptively rewrite emitters that already pass.

- [ ] **Step 4: Run lint/type-check (matches existing CI)**

Run: `uv run ruff check src tests`
Run: `uv run mypy src` (or whatever the project's configured type-checker invocation is — check `cli/pyproject.toml` `[tool]` sections or `.github/workflows/` if `mypy` isn't installed)
Expected: No new errors introduced by Tasks 1-6's changes.

- [ ] **Step 5: Validate against `docs/idl-design-spec.md` consistency**

Read `docs/idl-design-spec.md` §2.1 (built-in types table) and add `json` to that table, documenting it alongside the other primitives (e.g. "`json` — arbitrary JSON value, opaque to Modelable; maps to `serde_json::Value` (Rust), `unknown` (TypeScript), `{}` (JSON Schema)"). This is documentation only — keeps the spec doc in sync with the implemented type system, per `AGENTS.md`'s "ADR and Spec Synchronization" expectations.

- [ ] **Step 6: Commit**

```bash
cd C:\git\modelable
git add cli/tests/test_emit_rust.py docs/idl-design-spec.md
git commit -m "test(rust): add end-to-end json passthrough test; document json type in IDL spec"
```

---

### Task 8: Version bump and release tag

**Files:**
- Modify: `cli/pyproject.toml` (version)
- Modify: `cli/tests/test_release_metadata.py` (version assertion)
- Modify: `cli/uv.lock` (regenerated)

This follows the same pattern as the `0.2.0` → `0.2.1` bump (`068d276`). `json` is a purely additive type addition (new primitive kind, new mappings, new generated-code branch gated on a hint that previously produced incorrect/uncompilable output) — no existing `.mdl` files or generated artifacts change behavior unless they opt in by using `json` or `@wire(clickhouse: "string")` on a `map<K, json>` field. Per semver, this is a **minor** version bump: `0.2.1` → `0.3.0`.

- [ ] **Step 1: Check current version references**

Run: `grep -rn "0.2.1" cli/pyproject.toml cli/tests/test_release_metadata.py cli/uv.lock`
Expected: shows the exact lines to update (mirrors the 3 files changed in `068d276`).

- [ ] **Step 2: Bump version in `cli/pyproject.toml`**

Change the `version = "0.2.1"` line (around line 7) to `version = "0.3.0"`.

- [ ] **Step 3: Update `cli/tests/test_release_metadata.py`**

Update the version assertion(s) in this file from `0.2.1` to `0.3.0` (matches whatever the test currently asserts the package version equals).

- [ ] **Step 4: Regenerate the lockfile**

Run: `uv lock` (from `cli/`)
Expected: `cli/uv.lock` updates the `modelable` package version entry to `0.3.0`.

- [ ] **Step 5: Run the release metadata test**

Run: `uv run pytest cli/tests/test_release_metadata.py -v`
Expected: PASS

- [ ] **Step 6: Run the full test suite once more**

Run: `uv run pytest -q`
Expected: All PASS.

- [ ] **Step 7: Commit the version bump**

```bash
cd C:\git\modelable
git add cli/pyproject.toml cli/tests/test_release_metadata.py cli/uv.lock
git commit -m "chore: bump version to 0.3.0 for release"
```

- [ ] **Step 8: Tag and push (requires explicit user confirmation)**

This step pushes a `v*` tag, which triggers `.github/workflows/release.yml` and publishes a GitHub release — a visible, hard-to-reverse action affecting the repo's public release history. **Stop here and confirm with the user before running:**

```bash
git tag v0.3.0
git push origin main
git push origin v0.3.0
```

After the tag is pushed, confirm the release workflow succeeds (`gh run list --workflow=release.yml -L 1` / `gh run watch`), matching the verification done for `v0.2.1`.

- [ ] **Step 9: Update Observable's pinned dependency (separate repo, separate step)**

This is **out of scope for this plan** — it belongs to Observable's migration plan (`docs/superpowers/plans/2026-06-08-modelable-type-mapping-migration-plan.md`, picking back up at steps 2.4/2.5). Once `v0.3.0` is released, that work can resume: bump Observable's pinned modelable version, change `models/tracing.mdl`'s `attributes`/`resourceAttributes` fields to `map<string, json>` with `@wire(clickhouse: "string")` on the `SpanRow`/`SpanEventRow` projections, and regenerate.

---

## Self-Review Notes

- **Spec coverage:** Part 1 (json type: grammar/transformer/IR/JSON-Schema/TypeScript/Rust) → Tasks 1-4. Part 2 (clickhouse:"string" map<K,json>→String shape + conversion) → Tasks 5-6. Non-required-emitter fallback check → Task 7 Step 3. IDL spec doc sync → Task 7 Step 5. Release → Task 8.
- **Type/name consistency:** `_any_needs_serde_json`, `_projection_field_is_json_passthrough_to_string`, and the `serde_json: bool = False` parameter on `_header_lines` are each defined once (Tasks 4/5/6) and reused consistently in later tasks without renaming.
- **Reverse conversion (`from_str`)** is explicitly out of scope per Resolved Design Decision #2 in the spec — not included as a task, and Task 6 documents why.
- **Non-required emitters** (Go/Java/C#/Python/SQL/LSP) get a verification-only check (Task 7 Step 3) rather than dedicated tasks, per the spec's "no crash, sane fallback" scoping.
