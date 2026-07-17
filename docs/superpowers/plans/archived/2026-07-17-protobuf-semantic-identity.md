# Protobuf Semantic Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate stable declaring-domain Protobuf wrapper messages for semantic types and expose semantic refs, registry IDs, canonical Modelable signatures, and target-specific wire fingerprints through Protobuf and gRPC schema manifests.

**Architecture:** `emit_protobuf()` builds one workspace semantic index, emits one deterministic `semantic-types.proto` bundle per declaring domain, and resolves supported semantic `NamedType` fields to fully qualified wrapper messages. Per-schema manifests normalize referenced semantic definitions and compute canonical Modelable identity separately from a Protobuf fingerprint that includes semantic wire shape. `emit_grpc()` reuses the enriched Protobuf artifacts, and the compile command passes its existing registry allocation map to both targets.

**Tech Stack:** Python 3.14+, Pydantic parser IR, Protocol Buffers proto3, Click, pytest, Ruff, mypy baseline ratchet, MkDocs, Docker with `python:3.14.4-slim` plus Debian's `protobuf-compiler`.

## Global Constraints

- Implement the accepted
  [design contract](../../specs/archived/2026-07-17-protobuf-semantic-identity-design.md).
- Emit one `<out>/<domain>/semantic-types.proto` bundle for every domain containing semantic declarations.
- Use package `modelable.<normalized-domain>.semantic`; consumers use leading-dot fully qualified wrapper names.
- Emit one wrapper message per semantic declaration, sorted by name, with a single `value = 1` field.
- Flatten semantic alias chains to their terminal supported scalar. Never nest one semantic wrapper inside another.
- Preserve existing Protobuf primitive mappings, model/projection packages, field numbering, enum output, and non-semantic `NamedType`/map fallbacks.
- `modelable_signature` comes only from `compute_version_signature()`.
- `schema_fingerprint` includes consuming field metadata plus referenced semantic wire definitions, but excludes registry allocation IDs.
- Emit `registry_id` only for an explicit `registry: true` declaration with a supplied allocation. Never invent a sentinel.
- Registry IDs must be integer values in `1..=4294967295`; reject booleans and out-of-range values.
- Keep direct `emit_protobuf()` and `emit_grpc()` callers compatible by defaulting `registry_ids` to `None`.
- Keep this spec and plan active until implementation merges; archive both immediately after merge.
- From `cli/`, run all four required repository gates before every commit:

  ```powershell
  uv run ruff format .
  uv run ruff check .
  uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
  uv run pytest --tb=short
  ```

- If inserted lines move existing mypy errors, verify unchanged count/messages and regenerate `cli/mypy-baseline.txt` mechanically as required by `AGENTS.md`; fix real new errors.

---

## Task 1: Build the semantic index and declaring-domain bundles

**Files:**

- Modify: `cli/src/modelable/emitters/protobuf.py`
- Modify: `cli/tests/test_emit_protobuf.py`

**Interfaces:**

- Produces `_SemanticProtoType(ref, declaring_domain, proto_type, underlying_type, fixed_length, registry_id)`.
- Produces `_SemanticIndex(by_name, by_domain)` with `resolve(name)` and deterministic domain definitions.
- Produces `_build_semantic_index(mdl, registry_ids)` and `_emit_semantic_bundles(index, out_dir)`.
- Later tasks consume the same `_SemanticProtoType` objects in fields and manifests; do not create a second resolution representation.

- [ ] **Step 1: Add failing bundle and flattening tests**

Append to `cli/tests/test_emit_protobuf.py`:

```python
def test_emit_protobuf_semantic_bundles_are_stable_and_flatten_chains(tmp_path):
    (tmp_path / "semantic.mdl").write_text(
        """
domain platform {
  owner: "platform-team"

  semantic EntityId : uuid
  semantic OrderId : EntityId
  semantic SchemaId : u32 { registry: true }
  semantic RecordedAt : timestamp
  semantic ContentHash : binary(32)
  semantic Amount : decimal(12, 2)
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    artifacts = emit_protobuf(
        workspace,
        tmp_path / "out",
        registry_ids={"platform.SchemaId": 7},
    )

    bundle = next(art for art in artifacts if art.path.name == "semantic-types.proto")
    assert bundle.target == "protobuf"
    assert bundle.ref == "platform.semantic-types"
    assert bundle.artifact_id == "platform.semantic-types"
    assert bundle.path == tmp_path / "out" / "platform" / "semantic-types.proto"
    assert (
        bundle.content
        == """syntax = "proto3";

package modelable.platform.semantic;

import "google/protobuf/timestamp.proto";

message Amount {
  string value = 1;
}

message ContentHash {
  bytes value = 1;
}

message EntityId {
  string value = 1;
}

message OrderId {
  string value = 1;
}

message RecordedAt {
  google.protobuf.Timestamp value = 1;
}

message SchemaId {
  uint32 value = 1;
}
"""
    )


def test_emit_protobuf_semantic_bundles_are_domain_scoped_and_deterministic(tmp_path):
    (tmp_path / "semantic.mdl").write_text(
        """
domain zeta {
  owner: "zeta-team"
  semantic ZetaId : u64
}

domain alpha {
  owner: "alpha-team"
  semantic AlphaId : i32
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    first = emit_protobuf(workspace, tmp_path / "first")
    second = emit_protobuf(workspace, tmp_path / "second")
    first_bundles = [(art.ref, art.content) for art in first if art.path.name == "semantic-types.proto"]
    second_bundles = [(art.ref, art.content) for art in second if art.path.name == "semantic-types.proto"]

    assert first_bundles == second_bundles
    assert [ref for ref, _ in first_bundles] == ["alpha.semantic-types", "zeta.semantic-types"]
```

- [ ] **Step 2: Run the tests and verify RED**

From `cli/`:

```powershell
uv run pytest tests/test_emit_protobuf.py -k "semantic_bundles" --tb=short
```

Expected: failure because `emit_protobuf()` has no `registry_ids` keyword and emits no bundle.

- [ ] **Step 3: Add the semantic index data structures**

In `cli/src/modelable/emitters/protobuf.py`, import `DecimalType`,
`NamedType`, and `SemanticTypeDecl` if not already present, then add:

```python
@dataclass(frozen=True)
class _SemanticProtoType:
    ref: str
    declaring_domain: str
    proto_type: str
    underlying_type: str
    fixed_length: int | None
    registry_id: int | None


@dataclass(frozen=True)
class _SemanticIndex:
    by_name: dict[str, tuple[_SemanticProtoType, ...]]
    by_domain: dict[str, tuple[_SemanticProtoType, ...]]

    def resolve(self, name: str) -> _SemanticProtoType | None:
        candidates = self.by_name.get(name, ())
        if not candidates:
            return None
        if len(candidates) > 1:
            refs = ", ".join(candidate.ref for candidate in candidates)
            raise ValueError(f"ambiguous semantic type '{name}'; candidates: {refs}")
        return candidates[0]
```

- [ ] **Step 4: Implement terminal flattening and registry validation**

Add these helpers in `protobuf.py`:

```python
def _validate_registry_id(ref: str, value: int) -> int:
    maximum = 2**32 - 1
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"registry id for {ref} must be between 1 and {maximum}")
    return value


def _semantic_declarations(
    mdl: MdlFile,
) -> dict[str, tuple[tuple[str, SemanticTypeDecl], ...]]:
    grouped: dict[str, list[tuple[str, SemanticTypeDecl]]] = {}
    for domain in mdl.domains:
        for decl in domain.semantic_types:
            grouped.setdefault(decl.name, []).append((domain.name, decl))
    return {
        name: tuple(sorted(candidates, key=lambda candidate: candidate[0]))
        for name, candidates in grouped.items()
    }


def _unique_semantic_decl(
    name: str,
    declarations: dict[str, tuple[tuple[str, SemanticTypeDecl], ...]],
) -> tuple[str, SemanticTypeDecl]:
    candidates = declarations.get(name, ())
    if not candidates:
        raise ValueError(f"semantic type '{name}' is not declared")
    if len(candidates) > 1:
        refs = ", ".join(f"{domain}.{decl.name}" for domain, decl in candidates)
        raise ValueError(f"ambiguous semantic type '{name}'; candidates: {refs}")
    return candidates[0]


def _semantic_terminal_type(
    decl: SemanticTypeDecl,
    declarations: dict[str, tuple[tuple[str, SemanticTypeDecl], ...]],
) -> FieldType:
    current = decl.underlying
    visited = {decl.name}
    while isinstance(current, NamedType):
        if current.name in visited:
            raise ValueError(f"semantic type cycle encountered at '{current.name}'")
        visited.add(current.name)
        _, next_decl = _unique_semantic_decl(current.name, declarations)
        current = next_decl.underlying
    return current


def _semantic_terminal_proto(field_type: FieldType) -> tuple[str, int | None]:
    if isinstance(field_type, PrimitiveType):
        return _primitive_to_proto(field_type.kind)
    if isinstance(field_type, DecimalType):
        return "string", None
    if isinstance(field_type, FixedBinaryType):
        return "bytes", field_type.length
    raise ValueError(f"unsupported semantic terminal type: {type(field_type).__name__}")
```

Validation normally prevents cycles and unsupported terminals; these errors
defend direct low-level calls.

- [ ] **Step 5: Build the index and render bundles**

Add:

```python
def _semantic_package(domain: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z_]+", "_", domain).strip("_").lower()
    return f"modelable.{normalized}.semantic"


def _build_semantic_index(
    mdl: MdlFile,
    registry_ids: dict[str, int] | None,
) -> _SemanticIndex:
    declarations = _semantic_declarations(mdl)
    by_name: dict[str, list[_SemanticProtoType]] = {}
    by_domain: dict[str, list[_SemanticProtoType]] = {}
    for domain in sorted(mdl.domains, key=lambda item: item.name):
        for decl in sorted(domain.semantic_types, key=lambda item: item.name):
            ref = f"{domain.name}.{decl.name}"
            terminal, fixed_length = _semantic_terminal_proto(
                _semantic_terminal_type(decl, declarations)
            )
            allocated = (registry_ids or {}).get(ref) if decl.registry else None
            if allocated is not None:
                allocated = _validate_registry_id(ref, allocated)
            semantic = _SemanticProtoType(
                ref=ref,
                declaring_domain=domain.name,
                proto_type=f".{_semantic_package(domain.name)}.{decl.name}",
                underlying_type=terminal,
                fixed_length=fixed_length,
                registry_id=allocated,
            )
            by_name.setdefault(decl.name, []).append(semantic)
            by_domain.setdefault(domain.name, []).append(semantic)
    return _SemanticIndex(
        by_name={name: tuple(values) for name, values in by_name.items()},
        by_domain={domain: tuple(values) for domain, values in by_domain.items()},
    )


def _render_semantic_bundle(domain: str, definitions: tuple[_SemanticProtoType, ...]) -> str:
    lines = ['syntax = "proto3";', "", f"package {_semantic_package(domain)};", ""]
    if any(definition.underlying_type == "google.protobuf.Timestamp" for definition in definitions):
        lines.extend(['import "google/protobuf/timestamp.proto";', ""])
    for index, definition in enumerate(definitions):
        if index:
            lines.append("")
        message_name = definition.proto_type.rsplit(".", 1)[1]
        lines.extend(
            [
                f"message {message_name} {{",
                f"  {definition.underlying_type} value = 1;",
                "}",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def _emit_semantic_bundles(index: _SemanticIndex, out_dir: Path) -> list[EmittedArtifact]:
    artifacts: list[EmittedArtifact] = []
    for domain, definitions in sorted(index.by_domain.items()):
        content = _render_semantic_bundle(domain, definitions)
        ref = f"{domain}.semantic-types"
        artifacts.append(
            EmittedArtifact(
                target="protobuf",
                ref=ref,
                artifact_id=ref,
                path=out_dir / domain / "semantic-types.proto",
                content=content,
                content_hash=compute_content_hash(content),
            )
        )
    return artifacts
```

- [ ] **Step 6: Wire bundle emission into `emit_protobuf()`**

Change the public signature and initialization:

```python
def emit_protobuf(
    workspace: Workspace,
    out_dir: Path,
    *,
    registry_ids: dict[str, int] | None = None,
) -> list[EmittedArtifact]:
    """Emit Protocol Buffers schema artifacts for semantic types, models, and projections."""
    semantic_index = _build_semantic_index(workspace.mdl, registry_ids)
    artifacts = _emit_semantic_bundles(semantic_index, out_dir)
```

Keep existing model/projection loops after this initialization. Task 2 will
thread `semantic_index` into field conversion.

- [ ] **Step 7: Re-run focused tests**

```powershell
uv run pytest tests/test_emit_protobuf.py -k "semantic_bundles" --tb=short
```

Expected: both tests pass.

- [ ] **Step 8: Run mandatory gates**

From `cli/`:

```powershell
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

Expected: all pass. Refresh only mechanically shifted baseline entries.

- [ ] **Step 9: Commit Task 1**

```powershell
git add cli/src/modelable/emitters/protobuf.py cli/tests/test_emit_protobuf.py cli/mypy-baseline.txt
git commit -m "feat: emit Protobuf semantic type bundles"
```

Stage `mypy-baseline.txt` only when required by verified line shifts.

---

## Task 2: Resolve semantic wrappers in model and projection fields

**Files:**

- Modify: `cli/src/modelable/emitters/protobuf.py`
- Modify: `cli/tests/test_emit_protobuf.py`

**Interfaces:**

- Consumes `_SemanticIndex.resolve(name)` and `_SemanticProtoType` from Task 1.
- Extends `_ProtoField` with `semantic: _SemanticProtoType | None`.
- `_type_to_proto()` continues to be the only recursive type mapper; it now receives `semantic_index`.
- `_render_proto()` derives imports from fields. Task 3 consumes `field.semantic`.

- [ ] **Step 1: Add failing same-domain, cross-domain, projection, and array tests**

Append:

```python
def test_emit_protobuf_models_import_nominal_semantic_wrappers(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain platform {
  owner: "platform-team"
  semantic SchemaId : u32 { registry: true }
}

domain runtime {
  owner: "runtime-team"
  semantic CommandId : uuid

  entity RuntimeConfig @ 1 (additive) {
    @key commandId: CommandId
    schemaId: SchemaId
    relatedSchemaIds: array<SchemaId>
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    artifacts = emit_protobuf(workspace, tmp_path / "out")
    proto = next(art for art in artifacts if art.ref == "runtime.RuntimeConfig@1" and art.path.suffix == ".proto")

    assert 'import "platform/semantic-types.proto";' in proto.content
    assert 'import "runtime/semantic-types.proto";' in proto.content
    assert proto.content.index('import "platform/semantic-types.proto";') < proto.content.index(
        'import "runtime/semantic-types.proto";'
    )
    assert ".modelable.runtime.semantic.CommandId command_id = 1;" in proto.content
    assert ".modelable.platform.semantic.SchemaId schema_id = 2;" in proto.content
    assert "repeated .modelable.platform.semantic.SchemaId related_schema_ids = 3;" in proto.content


def test_emit_protobuf_projection_preserves_source_semantic_type(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain platform {
  owner: "platform-team"
  semantic SchemaId : u32 { registry: true }

  entity Schema @ 1 (additive) {
    @key schemaId: SchemaId
  }

  projection SchemaView @ 1
    from platform.Schema @ 1 as s
  {
    schemaId <- s.schemaId
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    artifacts = emit_protobuf(workspace, tmp_path / "out")
    proto = next(art for art in artifacts if art.ref == "platform.SchemaView@1" and art.path.suffix == ".proto")

    assert 'import "platform/semantic-types.proto";' in proto.content
    assert ".modelable.platform.semantic.SchemaId schema_id = 1;" in proto.content


def test_emit_protobuf_keeps_nonsemantic_named_type_and_map_fallbacks(tmp_path):
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
    attributes: map<string, string>
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    artifacts = emit_protobuf(workspace, tmp_path / "out")
    proto = next(art for art in artifacts if art.ref == "example.Customer@1" and art.path.suffix == ".proto")

    assert "bytes address = 2;" in proto.content
    assert "bytes attributes = 3;" in proto.content
    assert "semantic-types.proto" not in proto.content
```

- [ ] **Step 2: Verify RED**

```powershell
uv run pytest tests/test_emit_protobuf.py -k "nominal_semantic_wrappers or projection_preserves_source_semantic or nonsemantic_named_type" --tb=short
```

Expected: semantic fields remain `bytes` and imports are absent.

- [ ] **Step 3: Extend `_ProtoField` and mapping signatures**

Add to `_ProtoField`:

```python
semantic: _SemanticProtoType | None = None
```

Change `_type_to_proto()` to return semantic metadata:

```python
def _type_to_proto(
    field_type: FieldType,
    *,
    message_name: str,
    field_name: str,
    semantic_index: _SemanticIndex,
) -> tuple[str, _ProtoEnum | None, int | None, _SemanticProtoType | None]:
    if isinstance(field_type, PrimitiveType):
        type_name, fixed_length = _primitive_to_proto(field_type.kind)
        return type_name, None, fixed_length, None
    if isinstance(field_type, DecimalType):
        return "string", None, None, None
    if isinstance(field_type, FixedBinaryType):
        return "bytes", None, field_type.length, None
    if isinstance(field_type, NamedType):
        semantic = semantic_index.resolve(field_type.name)
        if semantic is not None:
            return semantic.proto_type, None, None, semantic
        return "bytes", None, None, None
    if isinstance(field_type, ArrayType):
        inner, _, _, semantic = _type_to_proto(
            field_type.item,
            message_name=message_name,
            field_name=field_name,
            semantic_index=semantic_index,
        )
        return f"repeated {inner.removeprefix('optional ')}", None, None, semantic
    if isinstance(field_type, EnumType):
        enum = _ProtoEnum(name=f"{message_name}{_pascal_case(field_name)}", values=tuple(field_type.values))
        return enum.name, enum, None, None
    return "bytes", None, None, None
```

Update `_field_to_proto()` and `_projection_field_to_proto()` to accept
`semantic_index`, unpack four values, and assign `semantic=semantic`.

- [ ] **Step 4: Thread the index through model and projection emission**

Update signatures:

```python
def _emit_model_version(
    domain: DomainDef,
    model_name: str,
    version: ModelVersion,
    out_dir: Path,
    semantic_index: _SemanticIndex,
) -> tuple[EmittedArtifact, EmittedArtifact]:
```

```python
def _emit_projection_version(
    domain: DomainDef,
    projection_name: str,
    version: ProjectionVersion,
    out_dir: Path,
    mdl: MdlFile,
    semantic_index: _SemanticIndex,
) -> tuple[EmittedArtifact, EmittedArtifact]:
```

Pass `semantic_index` from `emit_protobuf()` and into each field conversion.

- [ ] **Step 5: Render sorted semantic imports**

In `_render_proto()`, replace the timestamp-only import logic with:

```python
imports: set[str] = set()
if any("google.protobuf.Timestamp" in field.type_name for field in fields):
    imports.add("google/protobuf/timestamp.proto")
imports.update(
    f"{field.semantic.declaring_domain}/semantic-types.proto"
    for field in fields
    if field.semantic is not None
)
for import_path in sorted(imports):
    lines.append(f'import "{import_path}";')
if imports:
    lines.append("")
```

- [ ] **Step 6: Re-run focused tests**

```powershell
uv run pytest tests/test_emit_protobuf.py -k "nominal_semantic_wrappers or projection_preserves_source_semantic or nonsemantic_named_type" --tb=short
```

Expected: all three pass.

- [ ] **Step 7: Add and verify ambiguity behavior**

Add:

```python
def test_emit_protobuf_rejects_ambiguous_unqualified_semantic_reference(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain alpha {
  owner: "alpha-team"
  semantic SharedId : u32
}

domain beta {
  owner: "beta-team"
  semantic SharedId : u64
}

domain consumer {
  owner: "consumer-team"
  entity UsesShared @ 1 (additive) {
    @key id: SharedId
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    with pytest.raises(ValueError, match="ambiguous semantic type 'SharedId'.*alpha.SharedId.*beta.SharedId"):
        emit_protobuf(workspace, tmp_path / "out")
```

Add `import pytest` to the test module. Run:

```powershell
uv run pytest tests/test_emit_protobuf.py::test_emit_protobuf_rejects_ambiguous_unqualified_semantic_reference --tb=short
```

Expected: pass using `_SemanticIndex.resolve()`.

- [ ] **Step 8: Run mandatory gates**

```powershell
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

- [ ] **Step 9: Commit Task 2**

```powershell
git add cli/src/modelable/emitters/protobuf.py cli/tests/test_emit_protobuf.py cli/mypy-baseline.txt
git commit -m "feat: resolve Protobuf semantic wrappers"
```

---

## Task 3: Enrich schema manifests with canonical and semantic identity

**Files:**

- Modify: `cli/src/modelable/emitters/protobuf.py`
- Modify: `cli/tests/test_emit_protobuf.py`

**Interfaces:**

- Consumes `_ProtoField.semantic` and `_SemanticProtoType`.
- Produces `_manifest_semantic()`, `_referenced_semantics()`, and
  `_schema_fingerprint(fields, semantics)`.
- `modelable_signature` uses the actual `ModelVersion | ProjectionVersion`;
  no generated-text hash may enter that field.

- [ ] **Step 1: Add failing model and projection manifest tests**

Add imports:

```python
from modelable.registry.signature import compute_version_signature
```

Append:

```python
def test_emit_protobuf_manifest_separates_canonical_and_semantic_identity(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain platform {
  owner: "platform-team"
  semantic SchemaId : u32 { registry: true }
  semantic Label : string

  entity Schema @ 3 (additive) {
    @key schemaId: SchemaId
    parentSchemaId?: SchemaId
    label: Label
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    version = workspace.mdl.domains[0].models["Schema"][0]

    artifacts = emit_protobuf(
        workspace,
        tmp_path / "out",
        registry_ids={"platform.SchemaId": 11, "platform.Label": 99},
    )
    manifest = next(art for art in artifacts if art.ref == "platform.Schema@3" and art.path.name == "schema-manifest.json")
    schema = json.loads(manifest.content)["schemas"][0]

    assert schema["modelable_signature"] == compute_version_signature("platform", "Schema", version)
    assert schema["schema_fingerprint"] != schema["modelable_signature"]
    assert schema["semantic_types"] == [
        {
            "ref": "platform.Label",
            "proto_type": ".modelable.platform.semantic.Label",
            "underlying_type": "string",
        },
        {
            "ref": "platform.SchemaId",
            "proto_type": ".modelable.platform.semantic.SchemaId",
            "underlying_type": "uint32",
            "registry_id": 11,
        },
    ]
    fields = {field["name"]: field for field in schema["fields"]}
    assert fields["schemaId"]["semantic_type"] == "platform.SchemaId"
    assert fields["parentSchemaId"]["semantic_type"] == "platform.SchemaId"
    assert fields["label"]["semantic_type"] == "platform.Label"


def test_emit_protobuf_projection_manifest_has_canonical_signature(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain platform {
  owner: "platform-team"
  semantic SchemaId : u32 { registry: true }

  entity Schema @ 1 (additive) {
    @key schemaId: SchemaId
  }

  projection SchemaView @ 2
    from platform.Schema @ 1 as s
  {
    schemaId <- s.schemaId
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    version = workspace.mdl.domains[0].projections["SchemaView"][0]
    artifacts = emit_protobuf(workspace, tmp_path / "out")
    manifest = next(art for art in artifacts if art.ref == "platform.SchemaView@2" and art.path.name == "schema-manifest.json")
    schema = json.loads(manifest.content)["schemas"][0]

    assert schema["modelable_signature"] == compute_version_signature("platform", "SchemaView", version)
    assert schema["semantic_types"][0]["ref"] == "platform.SchemaId"
    assert "registry_id" not in schema["semantic_types"][0]
```

- [ ] **Step 2: Verify RED**

```powershell
uv run pytest tests/test_emit_protobuf.py -k "manifest_separates_canonical or projection_manifest_has_canonical" --tb=short
```

Expected: missing `modelable_signature`, `semantic_types`, and field
`semantic_type`.

- [ ] **Step 3: Add normalized semantic manifest helpers**

Import `compute_version_signature` in `protobuf.py`, then add:

```python
def _manifest_semantic(semantic: _SemanticProtoType, *, include_registry_id: bool) -> dict[str, object]:
    entry: dict[str, object] = {
        "ref": semantic.ref,
        "proto_type": semantic.proto_type,
        "underlying_type": semantic.underlying_type,
    }
    if semantic.fixed_length is not None:
        entry["fixed_length"] = semantic.fixed_length
    if include_registry_id and semantic.registry_id is not None:
        entry["registry_id"] = semantic.registry_id
    return entry


def _referenced_semantics(fields: list[_ProtoField]) -> list[_SemanticProtoType]:
    by_ref = {
        field.semantic.ref: field.semantic
        for field in fields
        if field.semantic is not None
    }
    return [by_ref[ref] for ref in sorted(by_ref)]
```

Extend `_manifest_field()`:

```python
if field.semantic is not None:
    entry["semantic_type"] = field.semantic.ref
```

- [ ] **Step 4: Separate canonical signature and wire fingerprint inputs**

Change:

```python
def _schema_fingerprint(
    fields: list[_ProtoField],
    semantics: list[_SemanticProtoType],
) -> str:
    normalized = {
        "fields": [_manifest_field(field) for field in fields],
        "semantic_types": [
            _manifest_semantic(semantic, include_registry_id=False)
            for semantic in semantics
        ],
    }
    return compute_content_hash(json.dumps(normalized, indent=2, ensure_ascii=False))
```

Registry IDs are deliberately absent from this normalized input.

- [ ] **Step 5: Pass version definitions into manifest rendering**

Change `_manifest_json()`:

```python
def _manifest_json(
    *,
    domain: str,
    name: str,
    kind: str,
    version: ModelVersion | ProjectionVersion,
    ref: str,
    fields: list[_ProtoField],
) -> str:
    semantics = _referenced_semantics(fields)
    schema = {
        "target": "protobuf",
        "schemas": [
            {
                "ref": ref,
                "kind": kind,
                "schema_id": f"modelable://{domain}/{name}/v{version.version}/protobuf",
                "modelable_signature": compute_version_signature(domain, name, version),
                "schema_fingerprint": _schema_fingerprint(fields, semantics),
                "semantic_types": [
                    _manifest_semantic(semantic, include_registry_id=True)
                    for semantic in semantics
                ],
                "fields": [_manifest_field(field) for field in fields],
            }
        ],
    }
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
```

Update both callers to pass `version=version`, not `version=version.version`.

- [ ] **Step 6: Re-run focused tests**

```powershell
uv run pytest tests/test_emit_protobuf.py -k "manifest_separates_canonical or projection_manifest_has_canonical" --tb=short
```

Expected: both pass.

- [ ] **Step 7: Prove allocation changes do not change wire fingerprint**

Append:

```python
def test_emit_protobuf_registry_allocation_does_not_change_wire_fingerprint(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain platform {
  owner: "platform-team"
  semantic SchemaId : u32 { registry: true }
  entity Schema @ 1 (additive) {
    @key schemaId: SchemaId
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    without_id = emit_protobuf(workspace, tmp_path / "without")
    with_id = emit_protobuf(
        workspace,
        tmp_path / "with",
        registry_ids={"platform.SchemaId": 23},
    )

    def schema(artifacts):
        manifest = next(art for art in artifacts if art.path.name == "schema-manifest.json")
        return json.loads(manifest.content)["schemas"][0]

    assert schema(without_id)["schema_fingerprint"] == schema(with_id)["schema_fingerprint"]
    assert "registry_id" not in schema(without_id)["semantic_types"][0]
    assert schema(with_id)["semantic_types"][0]["registry_id"] == 23
```

Run:

```powershell
uv run pytest tests/test_emit_protobuf.py::test_emit_protobuf_registry_allocation_does_not_change_wire_fingerprint --tb=short
```

Expected: pass.

- [ ] **Step 8: Add invalid registry boundary tests**

Append:

```python
@pytest.mark.parametrize("registry_id", [True, 0, -1, 2**32])
def test_emit_protobuf_rejects_invalid_registry_id(tmp_path, registry_id):
    (tmp_path / "model.mdl").write_text(
        """
domain platform {
  owner: "platform-team"
  semantic SchemaId : u32 { registry: true }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    with pytest.raises(ValueError, match="registry id for platform.SchemaId must be between 1 and 4294967295"):
        emit_protobuf(
            workspace,
            tmp_path / "out",
            registry_ids={"platform.SchemaId": registry_id},
        )
```

Run the parametrized test; expect four passes.

- [ ] **Step 9: Run mandatory gates**

```powershell
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

- [ ] **Step 10: Commit Task 3**

```powershell
git add cli/src/modelable/emitters/protobuf.py cli/tests/test_emit_protobuf.py cli/mypy-baseline.txt
git commit -m "feat: expose Protobuf semantic identity manifests"
```

---

## Task 4: Propagate allocations through CLI and gRPC, then compile generated Protobuf

**Files:**

- Modify: `cli/src/modelable/commands/compile.py`
- Modify: `cli/src/modelable/emitters/grpc.py`
- Modify: `cli/tests/test_emit_protobuf.py`
- Modify: `cli/tests/test_emit_grpc.py`
- Modify: `cli/tests/test_codegen_docker_smoke.py`

**Interfaces:**

- Changes `emit_grpc(workspace, out_dir, *, registry_ids=None)`.
- CLI passes the same allocated map to `emit_protobuf()` and `emit_grpc()`.
- gRPC continues to retarget every Protobuf artifact; service generation still iterates only `schema-manifest.json`.

- [ ] **Step 1: Add failing CLI allocation propagation tests**

Append to `cli/tests/test_emit_protobuf.py`:

```python
def test_compile_protobuf_passes_registry_allocations_to_manifest(tmp_path):
    mdl = tmp_path / "platform.mdl"
    mdl.write_text(
        """
domain platform {
  owner: "platform-team"
  semantic SchemaId : u32 { registry: true }
  entity Schema @ 1 (additive) {
    @key schemaId: SchemaId
  }
}
""",
        encoding="utf-8",
    )
    out = tmp_path / "dist"
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["compile", str(mdl), "--target", "protobuf", "--out", str(out)])

    assert result.exit_code == 0, result.output
    schema = json.loads(
        (out / "platform" / "Schema.v1" / "schema-manifest.json").read_text(encoding="utf-8")
    )["schemas"][0]
    assert schema["semantic_types"][0]["registry_id"] == 1
```

Append the equivalent gRPC CLI test to `cli/tests/test_emit_grpc.py`:

```python
def test_compile_grpc_passes_registry_allocations_to_payload_manifest(tmp_path):
    mdl = tmp_path / "platform.mdl"
    mdl.write_text(
        """
domain platform {
  owner: "platform-team"
  semantic SchemaId : u32 { registry: true }
  entity Schema @ 1 (additive) {
    @key schemaId: SchemaId
  }
}
""",
        encoding="utf-8",
    )
    out = tmp_path / "dist"
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["compile", str(mdl), "--target", "grpc", "--out", str(out)])

    assert result.exit_code == 0, result.output
    schema = json.loads(
        (out / "platform" / "Schema.v1" / "schema-manifest.json").read_text(encoding="utf-8")
    )["schemas"][0]
    assert schema["semantic_types"][0]["registry_id"] == 1
    assert (out / "platform" / "semantic-types.proto").exists()
```

- [ ] **Step 2: Verify RED**

```powershell
uv run pytest tests/test_emit_protobuf.py::test_compile_protobuf_passes_registry_allocations_to_manifest tests/test_emit_grpc.py::test_compile_grpc_passes_registry_allocations_to_payload_manifest --tb=short
```

Expected: missing `registry_id`; gRPC may also reject the new keyword until implemented.

- [ ] **Step 3: Thread allocations through compile and gRPC**

In `compile.py`:

```python
elif target == "protobuf":
    artifacts = emit_protobuf(emit_workspace, output, registry_ids=registry_ids)
```

```python
elif target == "grpc":
    artifacts = emit_grpc(emit_workspace, output, registry_ids=registry_ids)
```

In `grpc.py`:

```python
def emit_grpc(
    workspace: Workspace,
    out_dir: Path,
    *,
    registry_ids: dict[str, int] | None = None,
) -> list[EmittedArtifact]:
    """Emit the Scalable gRPC profile beside generated protobuf payload schemas."""
    artifacts: list[EmittedArtifact] = []
    protobuf_artifacts = emit_protobuf(workspace, out_dir, registry_ids=registry_ids)
```

- [ ] **Step 4: Verify CLI tests GREEN**

Run the two focused tests from Step 2. Expected: both pass.

- [ ] **Step 5: Add direct gRPC payload identity coverage**

Append to `cli/tests/test_emit_grpc.py`:

```python
def test_emit_grpc_retargets_semantic_payload_artifacts_unchanged(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain platform {
  owner: "platform-team"
  semantic SchemaId : u32 { registry: true }
  entity Schema @ 1 (additive) {
    @key schemaId: SchemaId
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_grpc(
        workspace,
        tmp_path / "out",
        registry_ids={"platform.SchemaId": 5},
    )

    bundle = next(art for art in artifacts if art.path.name == "semantic-types.proto")
    assert bundle.target == "grpc"
    assert "message SchemaId" in bundle.content
    schema_manifest = next(art for art in artifacts if art.path.name == "schema-manifest.json")
    schema = json.loads(schema_manifest.content)["schemas"][0]
    assert schema["semantic_types"][0]["registry_id"] == 5
    assert schema["fields"][0]["semantic_type"] == "platform.SchemaId"
```

Run it and expect PASS.

- [ ] **Step 6: Add a Protobuf-specific Docker fixture**

In `cli/tests/test_codegen_docker_smoke.py`, add:

```python
PROTOBUF_SAMPLE_MDL = """
domain platform {
  owner: "platform-team"
  semantic SchemaId : u32 { registry: true }
}

domain customer {
  owner: "customer-platform"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    schemaId: SchemaId
  }
}
"""
```

Add Protobuf to `TARGETS` using an already-pinned image:

```python
("protobuf", "python:3.14.4-slim", "protoc"),
```

Change `_compile_target()`:

```python
sample = PROTOBUF_SAMPLE_MDL if target == "protobuf" else SAMPLE_MDL
mdl.write_text(textwrap.dedent(sample).strip() + "\n", encoding="utf-8")
```

Add a branch before the final unhandled-target assertion:

```python
if target == "protobuf":
    result = _run_docker(
        tmp_path,
        image,
        "apt-get update >/dev/null"
        " && apt-get install -y --no-install-recommends protobuf-compiler >/dev/null"
        " && find generated/protobuf -name '*.proto' -print0"
        " | xargs -0 protoc -I generated/protobuf"
        " --descriptor_set_out=/tmp/modelable.pb --include_imports",
    )
    _assert_docker_success(result, target)
    return
```

This compiles both `platform/semantic-types.proto` and the importing customer
schema from the generated output root.

- [ ] **Step 7: Run the focused Docker smoke**

From `cli/`, with Docker available:

```powershell
$env:MODELABLE_DOCKER_SMOKE = "1"
uv run pytest tests/test_codegen_docker_smoke.py -k "protobuf" --tb=short
Remove-Item Env:MODELABLE_DOCKER_SMOKE
```

Expected: one Protobuf case passes. If Docker is unavailable, record it as
unverified rather than passed.

- [ ] **Step 8: Run mandatory gates**

```powershell
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

- [ ] **Step 9: Commit Task 4**

```powershell
git add cli/src/modelable/commands/compile.py cli/src/modelable/emitters/grpc.py cli/tests/test_emit_protobuf.py cli/tests/test_emit_grpc.py cli/tests/test_codegen_docker_smoke.py cli/mypy-baseline.txt
git commit -m "feat: propagate Protobuf semantic allocations"
```

---

## Task 5: Document the public contract and close roadmap item 2

**Files:**

- Modify: `docs/compiler-reference.md`
- Modify: `docs/cli-reference.md`
- Modify: `docs/wire-format-contract.md`
- Modify: `CHANGELOG.md`
- Modify: `ROADMAP.md`

**Interfaces:**

- Documentation must use the exact artifact path, package, manifest keys, and
  identity boundaries implemented in Tasks 1–4.
- This task marks only Priority 1 item 2 shipped.

- [ ] **Step 1: Update compiler and CLI references**

In `docs/compiler-reference.md`, replace the statement that all non-Rust
emitters structurally resolve semantic types with the implemented distinction:

```markdown
The Protobuf and gRPC targets preserve semantic types nominally as shared
declaring-domain wrapper messages in `<domain>/semantic-types.proto`. Chained
aliases flatten to their terminal scalar inside each wrapper. Consuming schema
manifests record `semantic_type`, optional allocated `registry_id`, and the
canonical `modelable_signature` separately from `schema_fingerprint`.
Other non-Rust targets continue to resolve semantic references structurally.
```

In `docs/cli-reference.md`, extend both Protobuf and gRPC target sections with:

```markdown
- one unversioned `<domain>/semantic-types.proto` bundle per declaring domain;
- fully qualified wrapper imports for semantic model/projection fields;
- `modelable_signature` and deduplicated `semantic_types` manifest metadata;
- allocated `registry_id` values when compilation uses `registry-ids.lock`.
```

- [ ] **Step 2: Update the wire contract**

In `docs/wire-format-contract.md`, replace the unsupported semantic row with:

```markdown
| Semantic type reference (`semantic Name: Underlying`) | the generated newtype (see `compiler-reference.md`) | a fully qualified declaring-domain wrapper message with one `value = 1` field mapped from the terminal scalar; alias chains flatten rather than nest. The schema manifest records the qualified semantic ref and optional registry allocation. Unsupported maps containing semantic values remain opaque `bytes`. |
```

Add a short compatibility note that adopting the wrapper is an intentional
wire change from the previous `bytes` fallback.

- [ ] **Step 3: Add changelog and roadmap status**

Under `CHANGELOG.md` `[Unreleased] / Added`, add:

```markdown
- Protobuf and gRPC generation now preserve semantic types as stable
  declaring-domain wrapper messages and expose semantic refs, registry IDs,
  canonical Modelable signatures, and target-specific wire fingerprints in
  schema manifests.
```

Change roadmap item 2 to:

```markdown
2. **Shipped: carry semantic identity into Protobuf.**
```

Rewrite its body in past tense and change the “next dependency-ordered slice”
sentence to item 3. Leave items 3–5 unfinished.

- [ ] **Step 4: Run doc/spec review**

Use the `doc-review` skill. Required result:

```text
Doc/spec review: all phases passed
```

The PR body must explain that no ADR update is needed because the work
implements the accepted active target-specific design.

- [ ] **Step 5: Run strict docs and scope checks**

From the repository root:

```powershell
git diff --check
rg -n "semantic-types.proto|modelable_signature|schema_fingerprint|registry_id|Shipped: carry semantic identity into Protobuf" docs ROADMAP.md CHANGELOG.md
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
```

Expected: no whitespace errors, all public surfaces documented, only roadmap
item 2 newly shipped, strict docs pass.

- [ ] **Step 6: Run mandatory gates**

From `cli/`:

```powershell
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

- [ ] **Step 7: Commit Task 5**

```powershell
git add docs/compiler-reference.md docs/cli-reference.md docs/wire-format-contract.md CHANGELOG.md ROADMAP.md
git commit -m "docs: document Protobuf semantic identity"
```

---

## Task 6: Final branch verification and post-merge lifecycle

**Files:**

- Verify all implementation files and documents.
- Do not archive the active spec or plan before the implementation merges.

- [ ] **Step 1: Inspect complete branch scope**

From the repository root:

```powershell
git status --short
git diff --check main...HEAD
git diff --stat main...HEAD
git log --oneline main..HEAD
```

Expected: clean worktree; only the accepted semantic Protobuf/gRPC slice,
design/plan, tests, manifests, and public docs.

- [ ] **Step 2: Run final documentation and repository gates**

```powershell
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
```

From `cli/`:

```powershell
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

- [ ] **Step 3: Run final Protobuf Docker smoke**

```powershell
$env:MODELABLE_DOCKER_SMOKE = "1"
uv run pytest tests/test_codegen_docker_smoke.py -k "protobuf" --tb=short
Remove-Item Env:MODELABLE_DOCKER_SMOKE
```

Expected: generated semantic bundles and importing schemas compile.

- [ ] **Step 4: Request independent code review**

Review `main..HEAD` against:

```text
docs/superpowers/specs/2026-07-17-protobuf-semantic-identity-design.md
docs/superpowers/plans/2026-07-17-protobuf-semantic-identity.md
```

Resolve every Critical and Important finding and rerun affected tests plus the
full gate.

- [ ] **Step 5: Prepare the PR contract**

Use `.github/pull_request_template.md`. The PR body must include:

- stable declaring-domain semantic wrapper bundles;
- terminal-scalar chain flattening;
- model/projection/array wrapper imports;
- semantic refs and conditional registry IDs;
- canonical signature versus Protobuf fingerprint separation;
- CLI and gRPC propagation;
- Docker `protoc` compilation;
- exact final gate results;
- `Doc/spec review: all phases passed`; and
- no `Closes #N` line unless a live issue was explicitly added to scope.

- [ ] **Step 6: Archive only after merge**

After the implementation PR merges to `main`, move:

```text
docs/superpowers/specs/2026-07-17-protobuf-semantic-identity-design.md
docs/superpowers/plans/2026-07-17-protobuf-semantic-identity.md
```

to:

```text
docs/superpowers/specs/archived/2026-07-17-protobuf-semantic-identity-design.md
docs/superpowers/plans/archived/2026-07-17-protobuf-semantic-identity.md
```

Update the roadmap link and the design's relative roadmap back-link in the
same merge PR if possible, or in a prompt follow-up archive PR immediately
after merge.
