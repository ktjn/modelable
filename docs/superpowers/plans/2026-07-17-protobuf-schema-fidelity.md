# Protobuf Schema Fidelity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Protobuf's opaque map fallback with deterministic native map emission and expose declared index metadata in Protobuf schema manifests and gRPC service manifests.

**Architecture:** Extend `protobuf.py`'s field conversion result with structured map and index metadata instead of parsing rendered type strings. `emit_protobuf()` remains the payload source for both `protobuf` and `grpc`; `grpc.py` reads normalized index metadata from the generated schema manifest and only keeps its current inferred-primary fallback when no declared index metadata exists. Unsupported map shapes fail during emission with clear field-context errors.

**Tech Stack:** Python 3.14, Pydantic parser IR, Protocol Buffers proto3, Click, pytest, Ruff, mypy baseline ratchet, MkDocs.

## Global Constraints

- Implement the accepted design in `docs/superpowers/specs/2026-07-17-protobuf-schema-fidelity-design.md`.
- Use native Protobuf `map<K,V>` only for supported key/value shapes.
- Fail clearly for unsupported map shapes instead of emitting opaque `bytes`.
- Preserve existing primitive, enum, semantic wrapper, array, package, field numbering, and projection type-resolution behavior outside the map change.
- Add field-level map metadata to `schema-manifest.json`.
- Add declared model-version `index` metadata to model schema manifests.
- Keep projection schema manifests without their own `indexes` block in this slice.
- Carry declared read index metadata into gRPC `service-manifest.json`.
- Keep `protobuf` and `grpc` payload schema manifests identical.
- Do not change the generated gRPC service envelope `.proto` shape.
- Do not implement descriptor sets, field reservations, Protobuf/gRPC compatibility validation, or Scalable registration fixtures in this slice.
- Keep the design and this plan active until implementation merges; archive both immediately after merge.
- From `cli/`, run all four required repository gates before every commit:

  ```powershell
  uv run ruff format .
  uv run ruff check .
  uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
  uv run pytest --tb=short
  ```

- If inserted lines move existing mypy errors, verify unchanged count/messages and regenerate `cli/mypy-baseline.txt` mechanically as required by `AGENTS.md`; fix real new errors.

---

## File Structure

- Modify `cli/src/modelable/emitters/protobuf.py`: add structured map metadata, native map conversion, unsupported-map errors, schema manifest map metadata, schema manifest index metadata, and fingerprint normalization updates.
- Modify `cli/src/modelable/emitters/grpc.py`: source `read_indexes` from schema manifest `indexes`; retain existing key-field fallback only when no declared indexes exist.
- Modify `cli/tests/test_emit_protobuf.py`: add map rendering, manifest, semantic map value, unsupported map, index metadata, fingerprint, determinism, and CLI tests.
- Modify `cli/tests/test_emit_grpc.py`: add service manifest tests for declared index metadata and fallback behavior.
- Modify `cli/tests/test_wire_golden.py`, `cli/tests/fixtures/wire_golden/golden/protobuf/platform_widget_v1.proto`: update the golden fixture for `map<string,int>`.
- Modify docs: `docs/wire-format-contract.md`, `docs/compiler-reference.md`, `docs/cli-reference.md`, `CHANGELOG.md`, `ROADMAP.md`.

## Task 1: Native Protobuf Map Rendering and Manifest Metadata

**Files:**
- Modify: `cli/src/modelable/emitters/protobuf.py`
- Modify: `cli/tests/test_emit_protobuf.py`

**Interfaces:**
- Consumes: `MapType`, `_SemanticIndex.resolve(name)`, `_type_to_proto(...)`, `_manifest_field(...)`, `_referenced_semantics(...)`, `_schema_fingerprint(...)`.
- Produces: `_ProtoMap(key_type, value_type, value_fixed_length=None, value_semantic=None)`, `_ProtoField.map`, native `map<K,V>` field rendering, and manifest field `map` objects.

- [ ] **Step 1: Add failing primitive map rendering and manifest test**

Append this test to `cli/tests/test_emit_protobuf.py`:

```python
def test_emit_protobuf_maps_use_native_map_type_and_manifest_metadata(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain platform {
  owner: "platform-team"

  entity Widget @ 1 (additive) {
    @key widgetId: uuid
    attributes: map<string, int>
    counts?: map<u32, u64>
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    artifacts = emit_protobuf(workspace, tmp_path / "out")

    proto = next(art for art in artifacts if art.ref == "platform.Widget@1" and art.path.suffix == ".proto")
    assert "map<string, int64> attributes = 2;" in proto.content
    assert "map<uint32, uint64> counts = 3;" in proto.content
    assert "optional map" not in proto.content
    assert "bytes attributes" not in proto.content
    assert "bytes counts" not in proto.content

    manifest = next(
        art for art in artifacts if art.ref == "platform.Widget@1" and art.path.name == "schema-manifest.json"
    )
    fields = {field["name"]: field for field in json.loads(manifest.content)["schemas"][0]["fields"]}
    assert fields["attributes"]["type"] == "map<string, int64>"
    assert fields["attributes"]["map"] == {"key_type": "string", "value_type": "int64"}
    assert fields["counts"]["type"] == "map<uint32, uint64>"
    assert fields["counts"]["map"] == {"key_type": "uint32", "value_type": "uint64"}
```

- [ ] **Step 2: Run the new test and verify it fails**

Run from `cli/`:

```powershell
uv run pytest tests/test_emit_protobuf.py::test_emit_protobuf_maps_use_native_map_type_and_manifest_metadata -q
```

Expected: failure because `MapType` still falls through to `bytes`.

- [ ] **Step 3: Add structured map metadata dataclass**

In `cli/src/modelable/emitters/protobuf.py`, import `MapType` from `modelable.parser.ir`.

Add this dataclass after `_ProtoEnum`:

```python
@dataclass(frozen=True)
class _ProtoMap:
    key_type: str
    value_type: str
    value_fixed_length: int | None = None
    value_semantic: _SemanticProtoType | None = None
```

Add `map: _ProtoMap | None = None` to `_ProtoField`.

Update `_ProtoField` construction in `_field_to_proto()` and `_projection_field_to_proto()` to receive a fifth return value from `_type_to_proto(...)`:

```python
type_name, enum, fixed_length, semantic, map_info = _type_to_proto(
    field.type,
    message_name=message_name,
    field_name=field.name,
    semantic_index=semantic_index,
)
```

Pass `map=map_info` into `_ProtoField(...)`. Apply the same pattern in `_projection_field_to_proto()`.

- [ ] **Step 4: Add key conversion helper**

Add this helper near `_primitive_to_proto()`:

```python
def _map_key_to_proto(field_type: FieldType, *, context: str) -> str:
    if not isinstance(field_type, PrimitiveType):
        raise ValueError(f"{context}: protobuf map key type {field_type.kind} is not supported")
    if field_type.kind in ("string", "bool"):
        return field_type.kind
    if field_type.kind in ("int", "i64"):
        return "int64"
    if field_type.kind in ("i8", "i16", "i32"):
        return "int32"
    if field_type.kind in ("u8", "u16", "u32"):
        return "uint32"
    if field_type.kind == "u64":
        return "uint64"
    raise ValueError(f"{context}: protobuf map key type {field_type.kind} is not supported")
```

If mypy reports that `field_type.kind` is unavailable for non-primitive types, replace the first error message with:

```python
raise ValueError(f"{context}: protobuf map key type {field_type.__class__.__name__} is not supported")
```

- [ ] **Step 5: Add map value conversion helper**

Add this helper near `_type_to_proto()`:

```python
def _map_value_to_proto(
    field_type: FieldType,
    *,
    message_name: str,
    field_name: str,
    semantic_index: _SemanticIndex,
    context: str,
) -> tuple[str, _ProtoEnum | None, int | None, _SemanticProtoType | None]:
    value_type, enum, fixed_length, semantic, nested_map = _type_to_proto(
        field_type,
        message_name=message_name,
        field_name=field_name,
        semantic_index=semantic_index,
        context=context,
    )
    if nested_map is not None or value_type.startswith("repeated "):
        raise ValueError(f"{context}: protobuf map value type {value_type} is not supported")
    if isinstance(field_type, NamedType) and semantic is None:
        raise ValueError(f"{context}: protobuf map value named type {field_type.name} is not supported")
    if value_type == "bytes" and not isinstance(field_type, (PrimitiveType, FixedBinaryType)):
        raise ValueError(f"{context}: protobuf map value type {field_type.__class__.__name__} is not supported")
    return value_type, enum, fixed_length, semantic
```

This helper intentionally allows byte-backed primitive/fixed-width values such as `binary`, `binary(N)`, `u128`, and `i128`; it rejects the ordinary unsupported-structural fallback to `bytes`.

- [ ] **Step 6: Extend `_type_to_proto()` for `MapType`**

Change `_type_to_proto()` to accept a `context: str | None = None` keyword and to return five values:

```python
) -> tuple[str, _ProtoEnum | None, int | None, _SemanticProtoType | None, _ProtoMap | None]:
```

Update every existing return in `_type_to_proto()` by appending `None` for the map slot.

Add this branch before `ArrayType`:

```python
    if isinstance(field_type, MapType):
        map_context = context or f"{message_name}.{field_name}"
        key_type = _map_key_to_proto(field_type.key, context=map_context)
        value_type, enum, fixed_length, semantic = _map_value_to_proto(
            field_type.value,
            message_name=message_name,
            field_name=field_name,
            semantic_index=semantic_index,
            context=map_context,
        )
        return (
            f"map<{key_type}, {value_type}>",
            enum,
            None,
            None,
            _ProtoMap(
                key_type=key_type,
                value_type=value_type,
                value_fixed_length=fixed_length,
                value_semantic=semantic,
            ),
        )
```

In the `ArrayType` branch, unpack the fifth return value and reject nested maps:

```python
inner, _, _, semantic, nested_map = _type_to_proto(...)
if nested_map is not None:
    raise ValueError(f"{context or f'{message_name}.{field_name}'}: protobuf array item map type is not supported")
```

- [ ] **Step 7: Render manifest map metadata**

Update `_manifest_field(field)`:

```python
    if field.map is not None:
        map_entry: dict[str, object] = {
            "key_type": field.map.key_type,
            "value_type": field.map.value_type,
        }
        if field.map.value_fixed_length is not None:
            map_entry["value_fixed_length"] = field.map.value_fixed_length
        if field.map.value_semantic is not None:
            map_entry["value_semantic_type"] = field.map.value_semantic.ref
        entry["map"] = map_entry
```

Keep top-level `semantic_type` only for `field.semantic`.

- [ ] **Step 8: Include map semantic values in referenced semantics**

Replace `_referenced_semantics(fields)` with logic that sees both direct fields and map values:

```python
def _referenced_semantics(fields: list[_ProtoField]) -> list[_SemanticProtoType]:
    by_ref: dict[str, _SemanticProtoType] = {}
    for field in fields:
        if field.semantic is not None:
            by_ref[field.semantic.ref] = field.semantic
        if field.map is not None and field.map.value_semantic is not None:
            by_ref[field.map.value_semantic.ref] = field.map.value_semantic
    return [by_ref[ref] for ref in sorted(by_ref)]
```

- [ ] **Step 9: Run focused test**

Run from `cli/`:

```powershell
uv run pytest tests/test_emit_protobuf.py::test_emit_protobuf_maps_use_native_map_type_and_manifest_metadata -q
```

Expected: pass.

- [ ] **Step 10: Commit Task 1**

Run from repo root:

```powershell
git add cli/src/modelable/emitters/protobuf.py cli/tests/test_emit_protobuf.py
git commit -m "feat: emit protobuf maps natively"
```

## Task 2: Semantic, Fixed-Length, Enum, and Unsupported Map Coverage

**Files:**
- Modify: `cli/src/modelable/emitters/protobuf.py`
- Modify: `cli/tests/test_emit_protobuf.py`

**Interfaces:**
- Consumes: Task 1 `_ProtoMap`, `_map_value_to_proto(...)`, `_referenced_semantics(...)`.
- Produces: verified map behavior for semantic values, timestamp values, fixed-length byte-backed values, inline enum values, unsupported values, fingerprint changes, and deterministic emission.

- [ ] **Step 1: Add semantic and timestamp map value test**

Append:

```python
def test_emit_protobuf_map_values_can_reference_semantic_wrappers_and_timestamps(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain platform {
  owner: "platform-team"
  semantic SchemaId : u32 { registry: true }
}

domain runtime {
  owner: "runtime-team"

  entity RuntimeIndex @ 1 (additive) {
    @key runtimeId: uuid
    schemas: map<string, SchemaId>
    seenAt: map<string, timestamp>
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    artifacts = emit_protobuf(workspace, tmp_path / "out", registry_ids={"platform.SchemaId": 17})

    proto = next(art for art in artifacts if art.ref == "runtime.RuntimeIndex@1" and art.path.suffix == ".proto")
    assert 'import "google/protobuf/timestamp.proto";' in proto.content
    assert 'import "platform/semantic-types.proto";' in proto.content
    assert "map<string, .modelable.platform.semantic.SchemaId> schemas = 2;" in proto.content
    assert "map<string, google.protobuf.Timestamp> seen_at = 3;" in proto.content

    manifest = next(
        art for art in artifacts if art.ref == "runtime.RuntimeIndex@1" and art.path.name == "schema-manifest.json"
    )
    schema = json.loads(manifest.content)["schemas"][0]
    assert schema["semantic_types"] == [
        {
            "ref": "platform.SchemaId",
            "proto_type": ".modelable.platform.semantic.SchemaId",
            "underlying_type": "uint32",
            "registry_id": 17,
        }
    ]
    fields = {field["name"]: field for field in schema["fields"]}
    assert fields["schemas"]["map"] == {
        "key_type": "string",
        "value_type": ".modelable.platform.semantic.SchemaId",
        "value_semantic_type": "platform.SchemaId",
    }
    assert "semantic_type" not in fields["schemas"]
```

- [ ] **Step 2: Add fixed-length and enum map value test**

Append:

```python
def test_emit_protobuf_map_values_preserve_fixed_length_and_inline_enum_metadata(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain platform {
  owner: "platform-team"

  entity Widget @ 1 (additive) {
    @key widgetId: uuid
    checksums: map<string, binary(32)>
    states: map<string, enum(active, blocked)>
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    artifacts = emit_protobuf(workspace, tmp_path / "out")

    proto = next(art for art in artifacts if art.ref == "platform.Widget@1" and art.path.suffix == ".proto")
    assert "map<string, bytes> checksums = 2;" in proto.content
    assert "map<string, WidgetStates> states = 3;" in proto.content
    assert "enum WidgetStates" in proto.content

    manifest = next(
        art for art in artifacts if art.ref == "platform.Widget@1" and art.path.name == "schema-manifest.json"
    )
    fields = {field["name"]: field for field in json.loads(manifest.content)["schemas"][0]["fields"]}
    assert fields["checksums"]["map"] == {
        "key_type": "string",
        "value_type": "bytes",
        "value_fixed_length": 32,
    }
    assert fields["states"]["map"] == {"key_type": "string", "value_type": "WidgetStates"}
```

- [ ] **Step 3: Add unsupported key/value tests**

Append:

```python
def test_emit_protobuf_rejects_unsupported_map_key_type(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain platform {
  owner: "platform-team"
  entity Widget @ 1 (additive) {
    @key widgetId: uuid
    byUuid: map<uuid, string>
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    with pytest.raises(ValueError, match=r"Widget.byUuid.*protobuf map key type uuid is not supported"):
        emit_protobuf(workspace, tmp_path / "out")


def test_emit_protobuf_rejects_unsupported_map_value_named_type(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain platform {
  owner: "platform-team"

  value Address @ 1 (additive) {
    line1: string
  }

  entity Widget @ 1 (additive) {
    @key widgetId: uuid
    addresses: map<string, Address>
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    with pytest.raises(ValueError, match=r"Widget.addresses.*protobuf map value named type Address is not supported"):
        emit_protobuf(workspace, tmp_path / "out")


def test_emit_protobuf_rejects_nested_map_value(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain platform {
  owner: "platform-team"
  entity Widget @ 1 (additive) {
    @key widgetId: uuid
    nested: map<string, map<string, int>>
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    with pytest.raises(ValueError, match=r"Widget.nested.*protobuf map value type map<string, int64> is not supported"):
        emit_protobuf(workspace, tmp_path / "out")
```

- [ ] **Step 4: Add fingerprint and determinism test**

Append:

```python
def test_emit_protobuf_map_shape_affects_schema_fingerprint_and_is_deterministic(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain platform {
  owner: "platform-team"
  entity Widget @ 1 (additive) {
    @key widgetId: uuid
    attributes: map<string, int>
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    first = emit_protobuf(workspace, tmp_path / "first")
    second = emit_protobuf(workspace, tmp_path / "second")

    def schema(artifacts):
        manifest = next(
            art for art in artifacts if art.ref == "platform.Widget@1" and art.path.name == "schema-manifest.json"
        )
        return json.loads(manifest.content)["schemas"][0]

    first_schema = schema(first)
    second_schema = schema(second)
    assert first_schema == second_schema
    assert first_schema["fields"][1]["map"] == {"key_type": "string", "value_type": "int64"}
    assert first_schema["schema_fingerprint"]
```

- [ ] **Step 5: Run focused tests and repair exact error strings if needed**

Run from `cli/`:

```powershell
uv run pytest tests/test_emit_protobuf.py -k "map_values or unsupported_map or map_shape" -q
```

Expected: tests pass. If a failure is only a regex mismatch, adjust the regex to the implemented clear error string while keeping field context and unsupported reason asserted.

- [ ] **Step 6: Confirm non-map named type fallback still works**

Run from `cli/`:

```powershell
uv run pytest tests/test_emit_protobuf.py::test_emit_protobuf_keeps_nonsemantic_named_type_and_map_fallbacks -q
```

Expected: this test now fails because the map part must no longer fall back to bytes. Replace it with this narrower assertion:

```python
def test_emit_protobuf_keeps_nonsemantic_named_type_fallback(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain example {
  owner: "example-team"

  value Address @ 1 (additive) {
    line1: string
  }

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    address: Address
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    artifacts = emit_protobuf(workspace, tmp_path / "out")
    proto = next(art for art in artifacts if art.ref == "example.Customer@1" and art.path.suffix == ".proto")

    assert "bytes address = 2;" in proto.content
    assert "semantic-types.proto" not in proto.content
```

Run the replacement test and expect pass.

- [ ] **Step 7: Commit Task 2**

Run from repo root:

```powershell
git add cli/src/modelable/emitters/protobuf.py cli/tests/test_emit_protobuf.py
git commit -m "test: cover protobuf map fidelity boundaries"
```

## Task 3: Declared Index Metadata in Schema Manifests

**Files:**
- Modify: `cli/src/modelable/emitters/protobuf.py`
- Modify: `cli/tests/test_emit_protobuf.py`

**Interfaces:**
- Consumes: `DomainDef.index_decls`, `IndexDecl`, `SecondaryIndexDecl`, `SortField`, `_manifest_json(...)`, `_schema_fingerprint(...)`.
- Produces: model schema manifest `indexes` blocks, fingerprint inclusion, and no projection `indexes` blocks.

- [ ] **Step 1: Add failing schema manifest index metadata test**

Append to `cli/tests/test_emit_protobuf.py`:

```python
def test_emit_protobuf_schema_manifest_includes_declared_indexes(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain platform {
  owner: "platform-team"

  entity Order @ 1 (additive) {
    @key orderId: uuid
    customerId: uuid
    createdAt: timestamp
  }

  index Order @ 1 {
    primary orderId
    secondary byCustomer {
      key: [customerId]
      sort: [createdAt desc]
      unique: false
    }
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    artifacts = emit_protobuf(workspace, tmp_path / "out")

    manifest = next(
        art for art in artifacts if art.ref == "platform.Order@1" and art.path.name == "schema-manifest.json"
    )
    schema = json.loads(manifest.content)["schemas"][0]
    assert schema["indexes"] == {
        "primary": {
            "index_name": "primary",
            "index_version": 1,
            "key_fields": ["orderId"],
            "sort_fields": [],
            "unique": True,
        },
        "secondary": [
            {
                "index_name": "byCustomer",
                "index_version": 1,
                "key_fields": ["customerId"],
                "sort_fields": [{"field": "createdAt", "direction": "desc"}],
                "unique": False,
            }
        ],
    }
```

- [ ] **Step 2: Add projection exclusion and fingerprint tests**

Append:

```python
def test_emit_protobuf_projection_manifest_does_not_duplicate_model_indexes(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain platform {
  owner: "platform-team"

  entity Order @ 1 (additive) {
    @key orderId: uuid
    customerId: uuid
  }

  index Order @ 1 {
    primary orderId
    secondary byCustomer {
      key: [customerId]
    }
  }

  projection OrderView @ 1
    from platform.Order @ 1 as o
  {
    orderId <- o.orderId
    customerId <- o.customerId
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_protobuf(workspace, tmp_path / "out")

    projection_manifest = next(
        art for art in artifacts if art.ref == "platform.OrderView@1" and art.path.name == "schema-manifest.json"
    )
    projection_schema = json.loads(projection_manifest.content)["schemas"][0]
    assert "indexes" not in projection_schema


def test_emit_protobuf_declared_indexes_change_schema_fingerprint(tmp_path):
    without_index = tmp_path / "without"
    with_index = tmp_path / "with"
    without_index.mkdir()
    with_index.mkdir()
    without_source = """
domain platform {
  owner: "platform-team"

  entity Order @ 1 (additive) {
    @key orderId: uuid
    customerId: uuid
  }
}
"""
    with_source = """
domain platform {
  owner: "platform-team"

  entity Order @ 1 (additive) {
    @key orderId: uuid
    customerId: uuid
  }

  index Order @ 1 {
    primary orderId
    secondary byCustomer {
      key: [customerId]
    }
  }
}
""",
    (without_index / "model.mdl").write_text(without_source, encoding="utf-8")
    (with_index / "model.mdl").write_text(with_source, encoding="utf-8")
    without_schema = json.loads(
        next(
            art
            for art in emit_protobuf(load_workspace(without_index), tmp_path / "out-without")
            if art.ref == "platform.Order@1" and art.path.name == "schema-manifest.json"
        ).content
    )["schemas"][0]
    with_schema = json.loads(
        next(
            art
            for art in emit_protobuf(load_workspace(with_index), tmp_path / "out-with")
            if art.ref == "platform.Order@1" and art.path.name == "schema-manifest.json"
        ).content
    )["schemas"][0]

    assert "indexes" not in without_schema
    assert "indexes" in with_schema
    assert without_schema["schema_fingerprint"] != with_schema["schema_fingerprint"]
```

- [ ] **Step 3: Run tests and verify they fail**

Run from `cli/`:

```powershell
uv run pytest tests/test_emit_protobuf.py -k "declared_indexes or model_indexes" -q
```

Expected: failures because schema manifests do not yet include `indexes`.

- [ ] **Step 4: Add index normalization helpers**

In `protobuf.py`, import `IndexDecl`.

Add helpers near manifest rendering:

```python
def _index_decl_for(domain: DomainDef, name: str, version: int) -> IndexDecl | None:
    return next(
        (decl for decl in domain.index_decls if decl.model == name and decl.version == version),
        None,
    )


def _manifest_indexes(index_decl: IndexDecl | None) -> dict[str, object] | None:
    if index_decl is None:
        return None
    return {
        "primary": {
            "index_name": "primary",
            "index_version": index_decl.version,
            "key_fields": list(index_decl.primary),
            "sort_fields": [],
            "unique": True,
        },
        "secondary": [
            {
                "index_name": secondary.name,
                "index_version": index_decl.version,
                "key_fields": list(secondary.key),
                "sort_fields": [
                    {"field": sort_field.field, "direction": sort_field.direction}
                    for sort_field in secondary.sort
                ],
                "unique": secondary.unique,
            }
            for secondary in index_decl.secondary
        ],
    }
```

- [ ] **Step 5: Pass index metadata into model manifests**

In `_emit_model_version(...)`, compute:

```python
indexes = _manifest_indexes(_index_decl_for(domain, model_name, model_version.version))
```

Pass `indexes=indexes` to `_manifest_json(...)`.

Change `_manifest_json(...)` signature:

```python
    indexes: dict[str, object] | None = None,
```

Before returning `json.dumps(...)`, add:

```python
    if indexes is not None:
        schema["schemas"][0]["indexes"] = indexes
```

Do not pass indexes from `_emit_projection_version(...)`.

- [ ] **Step 6: Include indexes in schema fingerprints**

Change `_schema_fingerprint(...)` signature to accept `indexes: dict[str, object] | None = None`.

Add indexes to normalized input only when present:

```python
    if indexes is not None:
        normalized["indexes"] = indexes
```

Call `_schema_fingerprint(fields, semantics, indexes)` from `_manifest_json(...)`.

- [ ] **Step 7: Run focused tests**

Run from `cli/`:

```powershell
uv run pytest tests/test_emit_protobuf.py -k "declared_indexes or model_indexes" -q
```

Expected: pass.

- [ ] **Step 8: Commit Task 3**

Run from repo root:

```powershell
git add cli/src/modelable/emitters/protobuf.py cli/tests/test_emit_protobuf.py
git commit -m "feat: expose declared indexes in protobuf manifests"
```

## Task 4: gRPC Service Manifest Read Indexes

**Files:**
- Modify: `cli/src/modelable/emitters/grpc.py`
- Modify: `cli/tests/test_emit_grpc.py`

**Interfaces:**
- Consumes: Protobuf schema manifest `indexes` block from Task 3, existing `_service_manifest_json(ref, service_proto, fields)`.
- Produces: service manifest `read_indexes` sourced from declared index metadata; existing inferred primary fallback when no declaration exists.

- [ ] **Step 1: Add failing declared index service manifest test**

Append to `cli/tests/test_emit_grpc.py`:

```python
def test_emit_grpc_service_manifest_uses_declared_index_metadata(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain platform {
  owner: "platform-team"

  entity Order @ 1 (additive) {
    @key orderId: uuid
    customerId: uuid
    createdAt: timestamp
  }

  index Order @ 1 {
    primary orderId
    secondary byCustomer {
      key: [customerId]
      sort: [createdAt desc]
      unique: false
    }
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    artifacts = emit_grpc(workspace, tmp_path / "out")

    service_manifest = next(
        art for art in artifacts if art.ref == "platform.Order@1" and art.path.name == "service-manifest.json"
    )
    manifest_doc = json.loads(service_manifest.content)
    assert manifest_doc["read_indexes"] == [
        {
            "index_name": "primary",
            "index_version": 1,
            "key_fields": ["orderId"],
            "sort_fields": [],
            "unique": True,
        },
        {
            "index_name": "byCustomer",
            "index_version": 1,
            "key_fields": ["customerId"],
            "sort_fields": ["createdAt desc"],
            "unique": False,
        },
    ]
```

- [ ] **Step 2: Preserve fallback test**

The existing `test_emit_grpc_service_profile_and_manifests` already asserts inferred primary fallback for a model without an `index` declaration. Keep that assertion unchanged.

- [ ] **Step 3: Run gRPC tests and verify failure**

Run from `cli/`:

```powershell
uv run pytest tests/test_emit_grpc.py -k "declared_index or service_profile" -q
```

Expected: the new declared-index test fails because `grpc.py` currently reconstructs only inferred primary key indexes from fields.

- [ ] **Step 4: Add schema-index extraction helpers**

In `cli/src/modelable/emitters/grpc.py`, add:

```python
def _read_indexes(indexes: object, fields: object) -> list[dict[str, object]]:
    declared = _declared_read_indexes(indexes)
    if declared:
        return declared
    key_fields = _key_fields(fields)
    if not key_fields:
        return []
    return [
        {
            "index_name": "primary",
            "index_version": 1,
            "key_fields": key_fields,
            "sort_fields": [],
            "unique": True,
        }
    ]


def _declared_read_indexes(indexes: object) -> list[dict[str, object]]:
    if not isinstance(indexes, dict):
        return []
    primary = indexes.get("primary")
    secondary = indexes.get("secondary")
    result: list[dict[str, object]] = []
    if isinstance(primary, dict):
        result.append(_service_index(primary))
    if isinstance(secondary, list):
        for item in secondary:
            if isinstance(item, dict):
                result.append(_service_index(item))
    return result


def _service_index(index: dict[str, object]) -> dict[str, object]:
    return {
        "index_name": str(index.get("index_name", "")),
        "index_version": int(index.get("index_version", 1)),
        "key_fields": [str(field) for field in index.get("key_fields", []) if isinstance(field, str)],
        "sort_fields": _service_sort_fields(index.get("sort_fields", [])),
        "unique": bool(index.get("unique", False)),
    }


def _service_sort_fields(sort_fields: object) -> list[str]:
    if not isinstance(sort_fields, list):
        return []
    rendered: list[str] = []
    for sort_field in sort_fields:
        if isinstance(sort_field, str):
            rendered.append(sort_field)
        elif isinstance(sort_field, dict):
            field = sort_field.get("field")
            direction = sort_field.get("direction")
            if isinstance(field, str):
                rendered.append(f"{field} desc" if direction == "desc" else field)
    return rendered
```

- [ ] **Step 5: Use schema manifest indexes in service manifest rendering**

Change `_service_manifest_json(...)` signature:

```python
def _service_manifest_json(*, ref: str, service_proto: str, fields: object, indexes: object = None) -> str:
```

Set:

```python
        "read_indexes": _read_indexes(indexes, fields),
```

Remove the old local `key_fields = _key_fields(fields)` branch from `_service_manifest_json(...)`.

In `emit_grpc(...)`, pass:

```python
            indexes=schema.get("indexes"),
```

- [ ] **Step 6: Run focused gRPC tests**

Run from `cli/`:

```powershell
uv run pytest tests/test_emit_grpc.py -k "declared_index or service_profile" -q
```

Expected: pass.

- [ ] **Step 7: Commit Task 4**

Run from repo root:

```powershell
git add cli/src/modelable/emitters/grpc.py cli/tests/test_emit_grpc.py
git commit -m "feat: expose declared indexes in grpc manifests"
```

## Task 5: CLI, Golden Fixture, Docs, and Final Gates

**Files:**
- Modify: `cli/tests/test_emit_protobuf.py`
- Modify: `cli/tests/test_emit_grpc.py`
- Modify: `cli/tests/fixtures/wire_golden/golden/protobuf/platform_widget_v1.proto`
- Modify: `docs/wire-format-contract.md`
- Modify: `docs/compiler-reference.md`
- Modify: `docs/cli-reference.md`
- Modify: `CHANGELOG.md`
- Modify: `ROADMAP.md`

**Interfaces:**
- Consumes: Tasks 1-4 behavior.
- Produces: CLI-level regression coverage, updated wire golden fixture, public docs, roadmap status, and final verification evidence.

- [ ] **Step 1: Add CLI compile coverage for map and index metadata**

Append to `cli/tests/test_emit_protobuf.py`:

```python
def test_compile_protobuf_writes_native_map_and_index_manifest(tmp_path):
    mdl = tmp_path / "platform.mdl"
    mdl.write_text(
        """
domain platform {
  owner: "platform-team"

  entity Order @ 1 (additive) {
    @key orderId: uuid
    attributes: map<string, int>
    customerId: uuid
  }

  index Order @ 1 {
    primary orderId
    secondary byCustomer {
      key: [customerId]
    }
  }
}
""",
        encoding="utf-8",
    )
    out = tmp_path / "dist"
    result = CliRunner().invoke(cli, ["compile", str(mdl), "--target", "protobuf", "--out", str(out)])

    assert result.exit_code == 0, result.output
    proto = (out / "platform" / "Order.v1" / "Order.v1.proto").read_text(encoding="utf-8")
    assert "map<string, int64> attributes = 2;" in proto
    schema = json.loads((out / "platform" / "Order.v1" / "schema-manifest.json").read_text(encoding="utf-8"))[
        "schemas"
    ][0]
    assert schema["fields"][1]["map"] == {"key_type": "string", "value_type": "int64"}
    assert schema["indexes"]["secondary"][0]["index_name"] == "byCustomer"
```

Append to `cli/tests/test_emit_grpc.py`:

```python
def test_compile_grpc_writes_declared_read_indexes(tmp_path):
    mdl = tmp_path / "platform.mdl"
    mdl.write_text(
        """
domain platform {
  owner: "platform-team"

  entity Order @ 1 (additive) {
    @key orderId: uuid
    customerId: uuid
  }

  index Order @ 1 {
    primary orderId
    secondary byCustomer {
      key: [customerId]
    }
  }
}
""",
        encoding="utf-8",
    )
    out = tmp_path / "dist"
    result = CliRunner().invoke(cli, ["compile", str(mdl), "--target", "grpc", "--out", str(out)])

    assert result.exit_code == 0, result.output
    manifest = json.loads((out / "platform" / "Order.v1" / "service-manifest.json").read_text(encoding="utf-8"))
    assert [index["index_name"] for index in manifest["read_indexes"]] == ["primary", "byCustomer"]
```

- [ ] **Step 2: Run CLI tests**

Run from `cli/`:

```powershell
uv run pytest tests/test_emit_protobuf.py::test_compile_protobuf_writes_native_map_and_index_manifest tests/test_emit_grpc.py::test_compile_grpc_writes_declared_read_indexes -q
```

Expected: pass.

- [ ] **Step 3: Update wire golden fixture**

Run from `cli/`:

```powershell
uv run pytest tests/test_wire_golden.py::test_protobuf_widget_output_matches_golden_file -q
```

Expected: fail because `attributes` now renders as `map<string, int64>`.

Update `cli/tests/fixtures/wire_golden/golden/protobuf/platform_widget_v1.proto` so the `attributes` field line reads:

```proto
  map<string, int64> attributes = 26;
```

Run from `cli/`:

```powershell
uv run pytest tests/test_wire_golden.py -q
```

Expected: pass.

- [ ] **Step 4: Update documentation**

Update `docs/wire-format-contract.md`:

- Replace the `map<K,V>` row that says Protobuf emits `bytes` with native `map<K,V>` for supported Protobuf key/value shapes.
- State that unsupported map shapes fail emission clearly instead of degrading to bytes.
- Update any prose that says semantic values inside maps remain opaque.

Update `docs/compiler-reference.md`:

- In the Protobuf/gRPC deferred target notes, say map fidelity and richer index metadata are now shipped.
- Document schema manifest `map` field metadata.
- Document schema manifest `indexes` and gRPC `read_indexes`.
- Leave descriptor sets, field reservations, compatibility validation, and Scalable registration fixtures deferred.

Update `docs/cli-reference.md`:

- In Protobuf/gRPC target descriptions, add one sentence that supported maps render as native Protobuf maps and unsupported map shapes fail the target.
- Add one sentence that declared index metadata appears in schema/service manifests.

Update `CHANGELOG.md`:

```markdown
- Added native Protobuf map emission for supported `map<K,V>` fields and clear failures for unsupported map shapes.
- Added declared primary/secondary index metadata to Protobuf schema manifests and gRPC service manifests.
```

Update `ROADMAP.md` Priority 1:

- Mark item 3 shipped.
- Make item 4 the next dependency-ordered slice.
- Keep item 5 after compatibility validation.

- [ ] **Step 5: Verify docs mention the shipped behavior**

Run from repo root:

```powershell
rg -n "map<K,V>|native Protobuf map|read_indexes|schema-manifest|service-manifest|Close Protobuf schema-fidelity gaps|Make the wire contract enforceable" ROADMAP.md CHANGELOG.md docs\wire-format-contract.md docs\compiler-reference.md docs\cli-reference.md
```

Expected: matches in all five files, with roadmap item 3 marked shipped and item 4 still active.

- [ ] **Step 6: Run focused behavior tests**

Run from `cli/`:

```powershell
uv run pytest tests/test_emit_protobuf.py tests/test_emit_grpc.py tests/test_wire_golden.py --tb=short -q
```

Expected: pass.

- [ ] **Step 7: Run docs build**

Run from repo root:

```powershell
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
```

Expected: exit 0. Existing informational messages about unnaved `wire-format-contract.md` and excluded archived spec links are acceptable if unchanged.

- [ ] **Step 8: Run mandatory repository gates**

Run from `cli/` in this exact order:

```powershell
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

Expected: all pass. If the mypy ratchet reports only shifted existing lines with unchanged messages/count, regenerate `cli/mypy-baseline.txt` according to `AGENTS.md`; otherwise fix the new type error.

- [ ] **Step 9: Inspect final diff**

Run from repo root:

```powershell
git diff --stat
git diff --check
```

Expected: diff touches only the files listed in this plan, and whitespace check passes.

- [ ] **Step 10: Commit Task 5**

Run from repo root:

```powershell
git add cli/src/modelable/emitters/protobuf.py cli/src/modelable/emitters/grpc.py cli/tests/test_emit_protobuf.py cli/tests/test_emit_grpc.py cli/tests/test_wire_golden.py cli/tests/fixtures/wire_golden/golden/protobuf/platform_widget_v1.proto docs/wire-format-contract.md docs/compiler-reference.md docs/cli-reference.md CHANGELOG.md ROADMAP.md
git commit -m "docs: document Protobuf schema fidelity"
```

## Final Publish Checklist

After all tasks are committed:

- [ ] Run `git status --short --branch` from repo root; expected branch is `design/protobuf-schema-fidelity` with no unstaged changes.
- [ ] Run `git log --oneline main..HEAD`; expected commits are the design commit plus the task commits.
- [ ] Push and open a draft PR:

```powershell
git push -u origin design/protobuf-schema-fidelity
gh pr create --draft --base main --head design/protobuf-schema-fidelity --title "feat: close Protobuf schema fidelity gaps" --body-file <body-file>
```

The PR body must mention:

- native map emission and unsupported-map failures;
- schema/service manifest index metadata;
- updated wire golden fixture and docs;
- all verification commands and results;
- `Doc/spec review: all phases passed`;
- no issue closure line unless an issue is created before implementation.

## Self-Review

Spec coverage:

- Map support: Tasks 1, 2, and 5 cover native maps, semantic/timestamp/fixed/enum values, unsupported shape failures, manifest map metadata, fingerprints, CLI behavior, docs, and golden output.
- Index metadata: Tasks 3, 4, and 5 cover schema manifest `indexes`, gRPC `read_indexes`, inferred primary fallback, fingerprints, CLI behavior, docs, and roadmap status.
- Preserved behavior: Tasks 1, 2, and 4 explicitly preserve non-map named-type fallback, existing gRPC primary fallback, existing package/field-number behavior, and unchanged service `.proto` shape.
- Deferred work: Task 5 keeps descriptor sets, reservations, compatibility validation, Scalable registration fixtures, arbitrary nested map/object encoding, custom Protobuf options, and ClickHouse DDL out of scope in docs and roadmap.

Placeholder scan:

- The plan intentionally avoids placeholder instructions and includes exact files, functions, commands, expected outcomes, and code snippets for every behavior-changing task.

Type consistency:

- `_ProtoMap` is introduced before `_ProtoField.map` consumes it.
- `_type_to_proto()` consistently returns `(type_name, enum, fixed_length, semantic, map_info)`.
- `_manifest_field()`, `_referenced_semantics()`, and `_schema_fingerprint()` consume structured metadata rather than rendered string parsing.
- `grpc.py` consumes schema manifest `indexes` through `_read_indexes(indexes, fields)` and retains `_key_fields(fields)` only as fallback input.
