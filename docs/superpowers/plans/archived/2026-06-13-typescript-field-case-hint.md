# TypeScript Field-Name Case Hint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add a new `@wire(json.fieldCase: "<case>")` hint, attachable to a model or projection declaration, that tells the TypeScript emitter to rename all of that declaration's interface fields to the given case convention (e.g. `snake_case`) — without affecting Rust, JSON Schema, SQL, or lineage output.

**Architecture:** Extend the existing `@wire(...)` annotation grammar rule (`wire_annotation` / `ann_wire`) to also be accepted as a prefix on `model_decl` and `projection_decl`, threading the parsed `AnnWire` into new `annotations` fields on `ModelVersion`/`ProjectionVersion` (mirroring the existing `FieldDef.annotations` + `wire_targets()` pattern). Add a new `field_case` slot to `WireTargetHint`, validate it (model/projection-level only, closed vocabulary matching `_apply_case`'s implemented cases), and consume it in the TypeScript emitter's `_emit_model`/`_emit_projection` to rename emitted interface properties via the existing `_apply_case` helper.

**Tech Stack:** Python 3.14, Lark (Earley parser), Pydantic v2, pytest, uv.

---

## Reference: design spec

`docs/superpowers/specs/2026-06-13-typescript-field-case-hint-design.md` (approved). This plan implements that spec exactly.

---

### Task 1: Grammar, IR, transformer, and wire.py — parse `@wire(json.fieldCase: ...)` on model/projection declarations

**Files:**
- Modify: `cli/src/modelable/grammar/modelable.lark:35` (`model_decl`) and `:108` (`projection_decl`)
- Modify: `cli/src/modelable/parser/ir.py:88-111` (`WireTargetHint`, `AnnWire._validate_targets`), `:269-276` (`ModelVersion`), `:366-375` (`ProjectionVersion`)
- Modify: `cli/src/modelable/parser/transformer.py:232-269` (`ann_wire`), `:146-163` (`model_decl`), `:375-403` (`projection_decl`)
- Modify: `cli/src/modelable/parser/wire.py` (`wire_targets_from_annotations`, `render_wire_annotation`)
- Test: `cli/tests/test_grammar.py`

- [x] **Step 1: Write the failing tests**

Add to `cli/tests/test_grammar.py`. First, update the import at the top of the file:

```python
from modelable.parser.parse import ParseError, parse_file, parse_text, parse_text_to_ir
```

Then append these two tests at the end of the file:

```python
def test_model_level_wire_field_case_annotation():
    mdl = parse_text_to_ir("""
    domain tracing {
      owner: "test-team"

      @wire(json.fieldCase: "snake_case")
      entity Span @ 1 (additive) {
        @key spanId: string
        startTimeUnixNano: int
      }
    }
    """)

    model = mdl.domains[0].models["Span"][0]
    wire_targets = model.wire_targets()
    assert wire_targets["json"].field_case == "snake_case"


def test_projection_level_wire_field_case_annotation():
    mdl = parse_text_to_ir("""
    domain tracing {
      owner: "test-team"

      entity Span @ 1 (additive) {
        @key spanId: string
        startTimeUnixNano: int
      }

      @wire(json.fieldCase: "snake_case")
      projection SpanRow @ 1
        from tracing.Span @ 1 as s
      {
        spanId <- s.spanId
        startTimeUnixNano <- s.startTimeUnixNano
      }
    }
    """)

    projection = mdl.domains[0].projections["SpanRow"][0]
    wire_targets = projection.wire_targets()
    assert wire_targets["json"].field_case == "snake_case"
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd /c/git/modelable && uv run pytest cli/tests/test_grammar.py -v -k field_case`

Expected: FAIL — either a parse error (grammar doesn't accept a leading `@wire(...)` before `entity`/`projection`) or an `AttributeError`/`KeyError` (`ModelVersion`/`ProjectionVersion` have no `wire_targets`, or `WireTargetHint` has no `field_case`).

- [x] **Step 3: Grammar — accept a leading `@wire(...)` on model and projection declarations**

In `cli/src/modelable/grammar/modelable.lark`, change line 35:

```
model_decl: model_kind IDENT model_header? "{" model_body_item* "}"
```

to:

```
model_decl: wire_annotation* model_kind IDENT model_header? "{" model_body_item* "}"
```

And change line 108:

```
projection_decl: "projection" IDENT "@" INT projection_source_block? source_clause? "{" projection_body_item* "}"
```

to:

```
projection_decl: wire_annotation* "projection" IDENT "@" INT projection_source_block? source_clause? "{" projection_body_item* "}"
```

- [x] **Step 4: IR — add `field_case` to `WireTargetHint`, update `AnnWire` validation, add `annotations`/`wire_targets()` to `ModelVersion` and `ProjectionVersion`**

In `cli/src/modelable/parser/ir.py`, change the `WireTargetHint` class (lines 88-92):

```python
class WireTargetHint(BaseModel):
    encoding: str | None = None
    type: str | None = None
    case: str | None = None
    overrides: dict[str, str] = Field(default_factory=dict)
    field_case: str | None = None
```

Update `AnnWire._validate_targets` (lines 99-111) to treat `field_case` as a valid sole option:

```python
class AnnWire(BaseModel):
    kind: Literal["wire"] = "wire"
    targets: dict[str, WireTargetHint] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_targets(self):
        if not self.targets:
            raise ValueError("wire annotations must declare at least one target")
        for target, hint in self.targets.items():
            if (
                hint.encoding is None
                and hint.type is None
                and hint.case is None
                and not hint.overrides
                and hint.field_case is None
            ):
                raise ValueError(f"wire target '{target}' must define at least one option")
        return self
```

Update `ModelVersion` (lines 269-276) to add `annotations` and a `wire_targets()` method (mirroring `FieldDef`, lines 216-244):

```python
class ModelVersion(BaseModel):
    model_kind: ModelKind
    version: int
    change_kind: ChangeKind
    fields: list[FieldDef]
    access: AccessBlock | None = None
    has_version_header: bool = True
    has_change_kind: bool = True
    annotations: list[Annotation] = Field(default_factory=list)

    def wire_targets(self) -> dict[str, WireTargetHint]:
        from modelable.parser.wire import wire_targets_from_annotations

        return wire_targets_from_annotations(self.annotations)
```

Update `ProjectionVersion` (lines 366-375) the same way:

```python
class ProjectionVersion(BaseModel):
    version: int
    source: SourceRef
    joins: list[JoinRef] = Field(default_factory=list)
    where: str | None = None
    group_by: list[str] = Field(default_factory=list)
    fields: list[ProjectionField]
    auto_generated: bool = False
    access: AccessBlock | None = None
    annotations: list[Annotation] = Field(default_factory=list)

    def wire_targets(self) -> dict[str, WireTargetHint]:
        from modelable.parser.wire import wire_targets_from_annotations

        return wire_targets_from_annotations(self.annotations)
```

- [x] **Step 5: Transformer — handle the `fieldCase` modifier and thread leading `@wire(...)` annotations into `ModelVersion`/`ProjectionVersion`**

In `cli/src/modelable/parser/transformer.py`, update `ann_wire` (lines 232-269) to add a `fieldCase` branch. Insert it after the existing `overrides` branch (before the final `else: raise ValueError(...)`):

```python
            elif modifier == "overrides":
                overlap = sorted(set(hint.overrides) & set(value))
                for key in overlap:
                    if hint.overrides[key] != value[key]:
                        raise ValueError(
                            f"conflicting wire override for target '{target}' member '{key}': "
                            f"{hint.overrides[key]!r} vs {value[key]!r}"
                        )
                hint.overrides.update(value)
            elif modifier == "fieldCase":
                if hint.field_case is not None and hint.field_case != value:
                    raise ValueError(
                        f"conflicting wire field cases for target '{target}': "
                        f"{hint.field_case!r} vs {value!r}"
                    )
                hint.field_case = value
            else:
                raise ValueError(f"unsupported wire modifier: {modifier}")
```

Update `model_decl` (lines 146-163) to filter out leading `AnnWire` items and pass them through as `annotations`:

```python
    def model_decl(self, items):
        annotations = [item for item in items if isinstance(item, AnnWire)]
        items = [item for item in items if not isinstance(item, AnnWire)]
        name = str(items[1])
        header = items[2] if len(items) > 2 and isinstance(items[2], tuple) and items[2][0] == "model_header" else None
        body_start = 3 if header is not None else 2
        version = header[1] if header is not None else 0
        change_kind = header[2] if header is not None else ChangeKind.additive
        has_change_kind = header[3] if header is not None else False
        access = next((item for item in items[body_start:] if isinstance(item, AccessBlock)), None)
        model_version = ModelVersion(
            model_kind=items[0],
            version=int(version),
            change_kind=change_kind,
            fields=[item for item in items[body_start:] if isinstance(item, FieldDef)],
            access=access,
            has_version_header=header is not None,
            has_change_kind=has_change_kind,
            annotations=annotations,
        )
        return ("model", (name, model_version))
```

Update `projection_decl` (lines 375-403) the same way:

```python
    def projection_decl(self, items):
        annotations = [item for item in items if isinstance(item, AnnWire)]
        items = [item for item in items if not isinstance(item, AnnWire)]
        source_index = next(
            (
                i
                for i, item in enumerate(items[2:], start=2)
                if isinstance(item, tuple) and len(item) == 4 and isinstance(item[0], SourceRef)
            ),
            None,
        )
        if source_index is None:
            source = SourceRef(model="", version=VersionExact(version=0), alias="", where=None)
            joins: list[JoinRef] = []
            where = None
            group_by: list[str] = []
            body_start = 2
        else:
            source, joins, where, group_by = items[source_index]
            body_start = source_index + 1
        access = next((item for item in items[body_start:] if isinstance(item, AccessBlock)), None)
        projection_version = ProjectionVersion(
            version=int(items[1]),
            source=source,
            joins=joins,
            where=where,
            group_by=group_by,
            fields=[item for item in items[body_start:] if isinstance(item, ProjectionField)],
            access=access,
            annotations=annotations,
        )
        return ("projection", (str(items[0]), projection_version))
```

- [x] **Step 6: wire.py — merge and render `field_case`**

In `cli/src/modelable/parser/wire.py`, in `wire_targets_from_annotations`, add a `field_case` merge branch after the existing `overrides` branch (before `targets[target] = merged`):

```python
                if hint.field_case is not None:
                    if merged.field_case is not None and merged.field_case != hint.field_case:
                        raise ValueError(
                            f"conflicting wire field cases for target '{target}': "
                            f"{merged.field_case!r} vs {hint.field_case!r}"
                        )
                    merged.field_case = hint.field_case
                targets[target] = merged
```

(Only the new `if hint.field_case is not None:` block is added — `targets[target] = merged` already exists, just keep it after the new block.)

In `render_wire_annotation`, add a rendering branch after the `overrides` branch (before `if not parts:`):

```python
        if hint.overrides:
            overrides = ", ".join(
                f'{key}: "{value}"' for key, value in sorted(hint.overrides.items())
            )
            parts.append(f"{target}.overrides: {{ {overrides} }}")
        if hint.field_case is not None:
            parts.append(f'{target}.fieldCase: "{hint.field_case}"')
    if not parts:
```

- [x] **Step 7: Run tests to verify they pass**

Run: `cd /c/git/modelable && uv run pytest cli/tests/test_grammar.py -v -k field_case`

Expected: PASS (2 passed)

- [x] **Step 8: Run the full test suite to check for regressions**

Run: `cd /c/git/modelable && uv run pytest cli/tests/ -q`

Expected: all tests pass (no regressions from the grammar/IR changes)

- [x] **Step 9: Commit**

```bash
cd /c/git/modelable
git add cli/src/modelable/grammar/modelable.lark cli/src/modelable/parser/ir.py cli/src/modelable/parser/transformer.py cli/src/modelable/parser/wire.py cli/tests/test_grammar.py
git commit -m "feat(parser): support @wire(json.fieldCase: ...) on model/projection declarations"
```

---

### Task 2: Semantic validation — `json.fieldCase` vocabulary and attachment-point rules

**Files:**
- Modify: `cli/src/modelable/validation/semantic.py:29-37` (new constant), `:103-176` (`_validate_models`), `:179-215` (`_validate_projections`), `:370-435` (`_validate_json_wire_hint`), and a new `_validate_declaration_wire_annotations` function
- Test: `cli/tests/test_semantic.py`

- [x] **Step 1: Write the failing tests**

Append to `cli/tests/test_semantic.py`:

```python
def test_model_level_json_field_case_snake_case_passes():
    mdl = parse_text_to_ir("""
    domain tracing {
      owner: "test-team"

      @wire(json.fieldCase: "snake_case")
      entity Span @ 1 (additive) {
        @key spanId: string
        startTimeUnixNano: int
      }
    }
    """)

    errors = validate(mdl)

    assert errors == []


def test_model_level_json_field_case_invalid_value_is_rejected():
    mdl = parse_text_to_ir("""
    domain tracing {
      owner: "test-team"

      @wire(json.fieldCase: "kebab-case")
      entity Span @ 1 (additive) {
        @key spanId: string
        startTimeUnixNano: int
      }
    }
    """)

    errors = validate(mdl)

    assert any("unsupported json.fieldcase" in error.lower() for error in errors)


def test_field_level_json_field_case_is_rejected():
    mdl = parse_text_to_ir("""
    domain tracing {
      owner: "test-team"

      entity Span @ 1 (additive) {
        @key spanId: string
        @wire(json.fieldCase: "snake_case")
        startTimeUnixNano: int
      }
    }
    """)

    errors = validate(mdl)

    assert any("json.fieldcase" in error.lower() for error in errors)


def test_projection_level_json_field_case_snake_case_passes():
    mdl = parse_text_to_ir("""
    domain tracing {
      owner: "test-team"

      entity Span @ 1 (additive) {
        @key spanId: string
        startTimeUnixNano: int
      }

      @wire(json.fieldCase: "snake_case")
      projection SpanRow @ 1
        from tracing.Span @ 1 as s
      {
        spanId <- s.spanId
        startTimeUnixNano <- s.startTimeUnixNano
      }
    }
    """)

    errors = validate(mdl)

    assert errors == []


def test_model_level_wire_target_other_than_json_field_case_is_rejected():
    mdl = parse_text_to_ir("""
    domain tracing {
      owner: "test-team"

      @wire(rust.case: "snake_case")
      entity Span @ 1 (additive) {
        @key spanId: string
        startTimeUnixNano: int
      }
    }
    """)

    errors = validate(mdl)

    assert any("only @wire(json.fieldcase: ...)" in error.lower() for error in errors)
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd /c/git/modelable && uv run pytest cli/tests/test_semantic.py -v -k field_case`

Expected: FAIL — `test_model_level_json_field_case_snake_case_passes` and `test_projection_level_json_field_case_snake_case_passes` fail because nothing validates/permits the new annotation yet (they may currently pass by accident since nothing rejects it — but the rejection tests will fail because there's no validation logic producing those error messages).

- [x] **Step 3: Add `_VALID_TS_FIELD_CASE_VALUES`**

In `cli/src/modelable/validation/semantic.py`, add a new constant after `_VALID_RUST_CASE_VALUES` (lines 29-37):

```python
_VALID_RUST_CASE_VALUES = {
    "snake_case",
    "SCREAMING_SNAKE_CASE",
    "camelCase",
    "PascalCase",
    "kebab-case",
    "lowercase",
    "UPPERCASE",
}
_VALID_TS_FIELD_CASE_VALUES = {
    "snake_case",
    "SCREAMING_SNAKE_CASE",
    "camelCase",
    "PascalCase",
}
```

- [x] **Step 4: Add `_validate_declaration_wire_annotations` and call it from `_validate_models`/`_validate_projections`**

Add this new function in `cli/src/modelable/validation/semantic.py`, placed after `_validate_change_kind` (around line 263, before `_find_field`):

```python
def _validate_declaration_wire_annotations(
    fqn: str,
    version,
    diagnostics: list[Diagnostic],
    path: str | Path | None,
) -> None:
    try:
        version.wire_targets()
    except ValueError as exc:
        diagnostics.append(_diag("SEM", f"{fqn}: has conflicting @wire annotations: {exc}", path))
        return
    for annotation in version.annotations:
        if annotation.kind != "wire":
            continue
        for target_name, hint in annotation.targets.items():
            if target_name not in _VALID_WIRE_TARGETS:
                diagnostics.append(
                    _diag(
                        "SEM",
                        f"{fqn}: has unknown wire target '{target_name}'. "
                        f"Valid targets are: {', '.join(sorted(_VALID_WIRE_TARGETS))}",
                        path,
                    )
                )
                continue
            if (
                target_name != "json"
                or hint.field_case is None
                or hint.encoding is not None
                or hint.type is not None
                or hint.case is not None
                or hint.overrides
            ):
                diagnostics.append(
                    _diag(
                        "SEM",
                        f"{fqn}: only @wire(json.fieldCase: ...) is supported on model/projection declarations",
                        path,
                    )
                )
                continue
            if hint.field_case not in _VALID_TS_FIELD_CASE_VALUES:
                diagnostics.append(
                    _diag(
                        "SEM",
                        f"{fqn}: unsupported json.fieldCase '{hint.field_case}'. "
                        f"Valid values are: {', '.join(sorted(_VALID_TS_FIELD_CASE_VALUES))}",
                        path,
                    )
                )
```

Now call it from `_validate_models`. In the per-version loop (around lines 126-171), after the existing `has_change_kind` diagnostics block and before `key_fields = [...]`, add:

```python
            _validate_declaration_wire_annotations(
                f"{fqn}@{version.version}", version, diagnostics, path
            )
```

So the loop body starts:

```python
        for version in versions:
            if version.model_kind in (ModelKind.entity, ModelKind.aggregate, ModelKind.event) and not version.has_version_header:
                diagnostics.append(...)
            elif version.model_kind in (ModelKind.entity, ModelKind.aggregate, ModelKind.event) and not version.has_change_kind:
                diagnostics.append(...)
            _validate_declaration_wire_annotations(
                f"{fqn}@{version.version}", version, diagnostics, path
            )
            key_fields = [field for field in version.fields if field.is_key]
            ...
```

And call it from `_validate_projections`. In the per-version loop (around lines 188-215), add it once near the top of the `for version in versions:` body:

```python
    for projection_name, versions in projections.items():
        fqn = f"{domain_name}.{projection_name}"
        for version in versions:
            _validate_declaration_wire_annotations(
                f"{fqn}@{version.version}", version, diagnostics, path
            )
            has_group_by = bool(version.group_by)
            ...
```

- [x] **Step 5: Reject field-level `json.fieldCase` in `_validate_json_wire_hint`**

In `cli/src/modelable/validation/semantic.py`, at the start of `_validate_json_wire_hint` (lines 370-435), add a check before the existing `is_enum = isinstance(field_type, EnumType)` line:

```python
def _validate_json_wire_hint(
    fqn: str,
    field: FieldDef,
    hint,
    diagnostics: list[Diagnostic],
    path: str | Path | None,
    *,
    field_label: str | None = None,
    field_type=None,
) -> None:
    label = field_label or field.name
    if hint.field_case is not None:
        diagnostics.append(
            _diag(
                "SEM",
                f"{fqn}: field '{label}' may not use @wire(json.fieldCase: ...) — "
                "json.fieldCase is only valid on model/projection declarations",
                path,
            )
        )
        return
    is_enum = isinstance(field_type, EnumType)
    ...
```

(Keep the rest of the function body unchanged below this new block.)

- [x] **Step 6: Run tests to verify they pass**

Run: `cd /c/git/modelable && uv run pytest cli/tests/test_semantic.py -v -k field_case`

Expected: PASS (5 passed)

- [x] **Step 7: Run the full test suite to check for regressions**

Run: `cd /c/git/modelable && uv run pytest cli/tests/ -q`

Expected: all tests pass

- [x] **Step 8: Commit**

```bash
cd /c/git/modelable
git add cli/src/modelable/validation/semantic.py cli/tests/test_semantic.py
git commit -m "feat(validation): validate @wire(json.fieldCase: ...) vocabulary and attachment point"
```

---

### Task 3: TypeScript emitter — rename interface fields per `json.fieldCase`

**Files:**
- Modify: `cli/src/modelable/emitters/typescript.py:57-127` (`_emit_model`, `_emit_projection`)
- Test: `cli/tests/test_emit_typescript.py`

- [x] **Step 1: Write the failing tests**

Append to `cli/tests/test_emit_typescript.py`:

```python
def test_emit_typescript_model_level_field_case_snake_case(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain tracing {
  owner: "test-team"

  @wire(json.fieldCase: "snake_case")
  entity Span @ 1 (additive) {
    @key spanId: string
    traceId: string
    startTimeUnixNano: int
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    art = next(a for a in artifacts if a.ref == "tracing.Span@1")
    assert "span_id: string;" in art.content
    assert "trace_id: string;" in art.content
    assert "start_time_unix_nano: number;" in art.content
    assert "spanId" not in art.content
    assert "traceId" not in art.content


def test_emit_typescript_projection_level_field_case_independent_of_model(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain tracing {
  owner: "test-team"

  entity Span @ 1 (additive) {
    @key spanId: string
    traceId: string
  }

  @wire(json.fieldCase: "snake_case")
  projection SpanRow @ 1
    from tracing.Span @ 1 as s
  {
    spanId <- s.spanId
    traceId <- s.traceId
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")

    model_art = next(a for a in artifacts if a.ref == "tracing.Span@1")
    assert "spanId: string;" in model_art.content
    assert "traceId: string;" in model_art.content

    proj_art = next(a for a in artifacts if a.ref == "tracing.SpanRow@1")
    assert "span_id: string;" in proj_art.content
    assert "trace_id: string;" in proj_art.content


def test_emit_typescript_model_without_field_case_is_unchanged(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain tracing {
  owner: "test-team"
  entity Span @ 1 (additive) {
    @key spanId: string
    traceId: string
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    art = next(a for a in artifacts if a.ref == "tracing.Span@1")
    assert "spanId: string;" in art.content
    assert "traceId: string;" in art.content
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd /c/git/modelable && uv run pytest cli/tests/test_emit_typescript.py -v -k field_case`

Expected: FAIL — `test_emit_typescript_model_level_field_case_snake_case` and the projection-level test fail because field names are still emitted verbatim (camelCase); `test_emit_typescript_model_without_field_case_is_unchanged` passes already (regression baseline).

- [x] **Step 3: Apply `field_case` in `_emit_model`**

In `cli/src/modelable/emitters/typescript.py`, update `_emit_model` (lines 57-85):

```python
def _emit_model(domain: DomainDef, model_name: str, version: ModelVersion, out_dir: Path) -> EmittedArtifact:
    artifact_id = _artifact_id(domain.name, model_name, version.version)
    interface_name = _stable_interface_name(domain.name, model_name, version.version)
    lines = _metadata_lines(
        _domain_metadata_entries(
            domain,
            model_name,
            version.version,
            version.model_kind.value,
            version.change_kind.value,
        )
    )
    declaration_json_wire = version.wire_targets().get("json")
    field_case = declaration_json_wire.field_case if declaration_json_wire is not None else None
    lines.append(f"export interface {interface_name} {{")
    warnings: list[str] = []
    for field in version.fields:
        if isinstance(field.type, NamedType):
            warnings.append(missing_metadata(f"{domain.name}.{model_name}.{field.name}"))
        field_name = _apply_case(field.name, field_case) if field_case else field.name
        lines.append(f"  {field_name}{'?' if field.optional else ''}: {_type_to_ts(field.type, wire_targets=field.wire_targets())};")
    lines.append("}")
    lines.append(f"export type {model_name} = {interface_name};")
    return EmittedArtifact(
        target="typescript",
        ref=f"{domain.name}.{model_name}@{version.version}",
        artifact_id=artifact_id,
        path=out_dir / f"{artifact_id}.ts",
        content="\n".join(lines) + "\n",
        content_hash=compute_content_hash("\n".join(lines) + "\n"),
        warnings=warnings,
    )
```

- [x] **Step 4: Apply `field_case` in `_emit_projection`**

Update `_emit_projection` (lines 88-127):

```python
def _emit_projection(
    domain: DomainDef,
    projection_name: str,
    version: ProjectionVersion,
    out_dir: Path,
    mdl,
) -> EmittedArtifact:
    artifact_id = _artifact_id(domain.name, projection_name, version.version)
    interface_name = _stable_interface_name(domain.name, projection_name, version.version)
    lines = _metadata_lines(
        _domain_metadata_entries(
            domain,
            projection_name,
            version.version,
            "projection",
            source=f"{version.source.model}@{_version_label(version.source.version)}",
            where=version.where,
            group_by=", ".join(version.group_by) if version.group_by else None,
        )
    )
    declaration_json_wire = version.wire_targets().get("json")
    field_case = declaration_json_wire.field_case if declaration_json_wire is not None else None
    lines.append(f"export interface {interface_name} {{")
    warnings: list[str] = []
    for field in version.fields:
        field_type = _resolve_projection_field_type(field, version, mdl)
        if field_type is None:
            warnings.append(type_loss(f"{domain.name}.{projection_name}.{field.name}"))
        elif isinstance(field_type, NamedType):
            warnings.append(missing_metadata(f"{domain.name}.{projection_name}.{field.name}"))
        field_name = _apply_case(field.name, field_case) if field_case else field.name
        lines.append(f"  {field_name}: {_type_to_ts(field_type, wire_targets=field.wire_targets())};")
    lines.append("}")
    lines.append(f"export type {projection_name} = {interface_name};")
    return EmittedArtifact(
        target="typescript",
        ref=f"{domain.name}.{projection_name}@{version.version}",
        artifact_id=artifact_id,
        path=out_dir / f"{artifact_id}.ts",
        content="\n".join(lines) + "\n",
        content_hash=compute_content_hash("\n".join(lines) + "\n"),
        warnings=warnings,
    )
```

- [x] **Step 5: Run tests to verify they pass**

Run: `cd /c/git/modelable && uv run pytest cli/tests/test_emit_typescript.py -v -k field_case`

Expected: PASS (3 passed)

- [x] **Step 6: Run the full test suite to check for regressions**

Run: `cd /c/git/modelable && uv run pytest cli/tests/ -q`

Expected: all tests pass

- [x] **Step 7: Commit**

```bash
cd /c/git/modelable
git add cli/src/modelable/emitters/typescript.py cli/tests/test_emit_typescript.py
git commit -m "feat(typescript): rename interface fields per @wire(json.fieldCase: ...)"
```

---

### Task 4: End-to-end fixture test mirroring Observable's `tracing.Span`, full suite, version bump

**Files:**
- Test: `cli/tests/test_emit_typescript.py`
- Modify: `cli/pyproject.toml:7`

- [x] **Step 1: Write the end-to-end fixture test**

Append to `cli/tests/test_emit_typescript.py`. This mirrors the real shape of Observable's `tracing.Span@1` (`models/tracing.mdl`): a `@key` field, an enum with `@wire(json.case: "SCREAMING_SNAKE_CASE")`, a `@wire(rust.type: "u64")` int, an optional field, and a `map<string, json>` field — all under a model-level `@wire(json.fieldCase: "snake_case")`.

```python
def test_emit_typescript_tracing_span_field_case_end_to_end(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain tracing {
  owner: "platform-team"

  @wire(json.fieldCase: "snake_case")
  entity Span @ 1 (additive) {
    @key spanId: string
    traceId: string
    parentSpanId?: string
    tenantId: uuid
    @wire(json.case: "SCREAMING_SNAKE_CASE")
    spanKind: enum(Internal, Server, Client, Producer, Consumer)
    @wire(rust.type: "u64")
    startTimeUnixNano: int
    attributes: map<string, json>
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_typescript(workspace, tmp_path / "out")
    art = next(a for a in artifacts if a.ref == "tracing.Span@1")

    expected_fields = [
        "span_id: string;",
        "trace_id: string;",
        "parent_span_id?: string;",
        "tenant_id: string;",
        "start_time_unix_nano: number;",
        "attributes: Record<string, unknown>;",
    ]
    for expected in expected_fields:
        assert expected in art.content, art.content

    assert "'INTERNAL' | 'SERVER' | 'CLIENT' | 'PRODUCER' | 'CONSUMER'" in art.content
    assert "span_kind:" in art.content
```

- [x] **Step 2: Run the new test**

Run: `cd /c/git/modelable && uv run pytest cli/tests/test_emit_typescript.py -v -k tracing_span_field_case`

Expected: PASS (1 passed) — this confirms `json.fieldCase` composes correctly with the existing `json.case` (enum), `rust.type`, `map<string, json>`, and `optional` field handling.

- [x] **Step 3: Run the full test suite**

Run: `cd /c/git/modelable && uv run pytest cli/tests/ -q`

Expected: all tests pass

- [x] **Step 4: Bump the package version**

In `cli/pyproject.toml`, change line 7:

```toml
version = "0.3.0"
```

to:

```toml
version = "0.4.0"
```

- [x] **Step 5: Commit**

```bash
cd /c/git/modelable
git add cli/tests/test_emit_typescript.py cli/pyproject.toml
git commit -m "test(typescript): add tracing.Span-shaped end-to-end fixture for json.fieldCase; bump version to 0.4.0"
```

---

## After this plan

Once this branch is reviewed and merged, cut a `v0.4.0` release (per `docs/consuming-modelable.md`, mirroring the prior `v0.3.0` release flow) so Observable can pin to it. Then resume Observable's step 2.5: add `@wire(json.fieldCase: "snake_case")` to `tracing.Span@1`/`tracing.SpanEvent@1` in `models/tracing.mdl`, regenerate TypeScript, and wire the generated interfaces into `apps/frontend/src/api/traces.ts` — this is a separate brainstorm/plan in the Observable repo, not part of this branch.
