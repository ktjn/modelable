# Multi-Language Codegen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add first-class generated-language targets for C#, Java, Python, Rust, and Go without weakening Modelable's `.mdl` source-of-truth pipeline.

**Architecture:** Introduce a language-neutral codegen description derived from the normalized registry graph, then render each language from that shared shape. Keep target selection and metadata in the existing `codegen` and `compile` commands, but make each backend responsible only for naming, typing, file layout, and emitted language conventions. Preserve JSON Schema, Markdown, and TypeScript behavior while adding the new languages one at a time so each backend can be tested independently.

**Tech Stack:** Python 3.14+, Click, Pydantic, Rich, the existing parser/registry/planner stack, `jsonschema`, and the repo's `uv` workflow.

---

### Task 1: Add a shared codegen target registry and language-neutral type description

**Files:**
- Create: `cli/src/modelable/emitters/targets.py`
- Create: `cli/src/modelable/emitters/shapes.py`
- Modify: `cli/src/modelable/commands/codegen.py`
- Modify: `cli/src/modelable/commands/compile.py`
- Modify: `cli/src/modelable/emitters/base.py`
- Test: `cli/tests/test_codegen_targets.py`

- [ ] **Step 1: Write the failing tests for target inventory and type-shape conversion**

```python
def test_codegen_formats_list_all_supported_and_deferred_targets():
    result = runner.invoke(cli, ["codegen", "formats"])
    assert "json-schema" in result.output
    assert "markdown" in result.output
    assert "typescript" in result.output
    assert "csharp" in result.output
    assert "java" in result.output
    assert "python" in result.output
    assert "rust" in result.output
    assert "go" in result.output

def test_type_shape_preserves_nullability_and_collections():
    shape = TypeShape.from_field("array<uuid>?", optional=True)
    assert shape.kind == "array"
    assert shape.optional is True
```

- [ ] **Step 2: Implement a language-neutral `TypeShape` and target registry**

```python
@dataclass(frozen=True)
class TypeShape:
    kind: str
    optional: bool = False
    nullable: bool = False
    element: "TypeShape | None" = None
    key: "TypeShape | None" = None
    value: "TypeShape | None" = None
    ref: str | None = None
    enum_values: tuple[str, ...] = ()
```

```python
CODEGEN_TARGETS = [
    {"name": "json-schema", "status": "implemented"},
    {"name": "markdown", "status": "implemented"},
    {"name": "typescript", "status": "implemented"},
    {"name": "csharp", "status": "deferred"},
    {"name": "java", "status": "deferred"},
    {"name": "python", "status": "deferred"},
    {"name": "rust", "status": "deferred"},
    {"name": "go", "status": "deferred"},
]
```

- [ ] **Step 3: Wire the registry into `codegen formats` and `codegen types`**

```python
def list_codegen_targets() -> list[dict[str, object]]:
    return CODEGEN_TARGETS
```

- [ ] **Step 4: Run the focused target-registry tests**

Run: `uv run pytest tests/test_codegen_targets.py -v`
Expected: supported and deferred targets are listed consistently.

- [ ] **Step 5: Commit**

```bash
git add cli/src/modelable/emitters/targets.py cli/src/modelable/emitters/shapes.py cli/src/modelable/commands/codegen.py cli/src/modelable/commands/compile.py cli/src/modelable/emitters/base.py cli/tests/test_codegen_targets.py
git commit -m "feat: add shared multi-language codegen registry"
```

---

### Task 2: Implement the first new backend for C#

**Files:**
- Create: `cli/src/modelable/emitters/csharp.py`
- Test: `cli/tests/test_emit_csharp.py`

- [ ] **Step 1: Write failing tests for namespace, file layout, and nullable types**

```python
def test_emit_csharp_model_and_projection(tmp_path):
    workspace = load_workspace(tmp_path / "workspace")
    artifacts = emit_csharp(workspace, tmp_path / "out")
    assert any(art.path.suffix == ".cs" for art in artifacts)
    assert "namespace" in artifacts[0].content
    assert "string?" in artifacts[0].content
```

- [ ] **Step 2: Implement the C# emitter**

```python
def _emit_model(domain: DomainDef, model_name: str, version: ModelVersion, out_dir: Path) -> EmittedArtifact:
    class_name = f"{domain.name.title()}{model_name}V{version.version}"
    # emit one partial class or record per published version
```

- [ ] **Step 3: Run the focused C# tests**

Run: `uv run pytest tests/test_emit_csharp.py -v`
Expected: one `.cs` file per model/projection version, stable names, and nullable properties.

- [ ] **Step 4: Commit**

```bash
git add cli/src/modelable/emitters/csharp.py cli/tests/test_emit_csharp.py
git commit -m "feat: add csharp codegen backend"
```

---

### Task 3: Implement the Java backend

**Files:**
- Create: `cli/src/modelable/emitters/java.py`
- Test: `cli/tests/test_emit_java.py`

- [ ] **Step 1: Write failing tests for package names, optionality, and collection mapping**

```python
def test_emit_java_model_and_projection(tmp_path):
    artifacts = emit_java(workspace, tmp_path / "out")
    assert any(art.path.suffix == ".java" for art in artifacts)
    assert "package" in artifacts[0].content
    assert "Optional<" in artifacts[0].content
```

- [ ] **Step 2: Implement the Java emitter**

```python
def _java_type(shape: TypeShape) -> str:
    if shape.optional:
        return f"Optional<{_java_type(shape.without_optional())}>"
    if shape.kind == "array":
        return f"List<{_java_type(shape.element)}>"
```

- [ ] **Step 3: Run the focused Java tests**

Run: `uv run pytest tests/test_emit_java.py -v`
Expected: one `.java` file per published version, with package and collection conventions.

- [ ] **Step 4: Commit**

```bash
git add cli/src/modelable/emitters/java.py cli/tests/test_emit_java.py
git commit -m "feat: add java codegen backend"
```

---

### Task 4: Implement the Python backend

**Files:**
- Create: `cli/src/modelable/emitters/python.py`
- Test: `cli/tests/test_emit_python.py`

- [ ] **Step 1: Write failing tests for module layout and typing**

```python
def test_emit_python_model_and_projection(tmp_path):
    artifacts = emit_python(workspace, tmp_path / "out")
    assert any(art.path.suffix == ".py" for art in artifacts)
    assert "from __future__ import annotations" in artifacts[0].content
    assert "Optional[" in artifacts[0].content
```

- [ ] **Step 2: Implement the Python emitter**

```python
def _python_type(shape: TypeShape) -> str:
    if shape.optional:
        return f"Optional[{_python_type(shape.without_optional())}]"
    if shape.kind == "array":
        return f"list[{_python_type(shape.element)}]"
```

- [ ] **Step 3: Run the focused Python tests**

Run: `uv run pytest tests/test_emit_python.py -v`
Expected: generated modules are importable and use stable class names.

- [ ] **Step 4: Commit**

```bash
git add cli/src/modelable/emitters/python.py cli/tests/test_emit_python.py
git commit -m "feat: add python codegen backend"
```

---

### Task 5: Implement the Rust backend

**Files:**
- Create: `cli/src/modelable/emitters/rust.py`
- Test: `cli/tests/test_emit_rust.py`

- [x] **Step 1: Write failing tests for module names and serde-ready shapes**

```python
def test_emit_rust_model_and_projection(tmp_path):
    artifacts = emit_rust(workspace, tmp_path / "out")
    assert any(art.path.suffix == ".rs" for art in artifacts)
    assert "#[derive" in artifacts[0].content
    assert "Option<" in artifacts[0].content
```

- [x] **Step 2: Implement the Rust emitter**

```python
def _rust_type(shape: TypeShape) -> str:
    if shape.optional:
        return f"Option<{_rust_type(shape.without_optional())}>"
    if shape.kind == "array":
        return f"Vec<{_rust_type(shape.element)}>"
```

- [x] **Step 3: Run the focused Rust tests**

Run: `uv run pytest tests/test_emit_rust.py -v`
Expected: generated structs and enums use serde-friendly naming and optionality.
- Completed: the Rust emitter now generates deterministic struct modules with pointer optionals and nested type definitions.

- [x] **Step 4: Commit**

```bash
git add cli/src/modelable/emitters/rust.py cli/tests/test_emit_rust.py
git commit -m "feat: add rust codegen backend"
```

---

### Task 6: Implement the Go backend

**Files:**
- Create: `cli/src/modelable/emitters/go.py`
- Test: `cli/tests/test_emit_go.py`

- [x] **Step 1: Write failing tests for package names and pointer-based optionals**

```python
def test_emit_go_model_and_projection(tmp_path):
    artifacts = emit_go(workspace, tmp_path / "out")
    assert any(art.path.suffix == ".go" for art in artifacts)
    assert "package" in artifacts[0].content
    assert "*string" in artifacts[0].content or "*bool" in artifacts[0].content
```

- [x] **Step 2: Implement the Go emitter**

```python
def _go_type(shape: TypeShape) -> str:
    if shape.optional:
        return f"*{_go_type(shape.without_optional())}"
    if shape.kind == "array":
        return f"[]{_go_type(shape.element)}"
```

- [x] **Step 3: Run the focused Go tests**

Run: `uv run pytest tests/test_emit_go.py -v`
Expected: generated packages compile logically with pointer optionals and JSON tags.
- Completed: the Go emitter now generates deterministic structs with JSON tags, pointer optionals, and nested object types.

- [x] **Step 4: Commit**

```bash
git add cli/src/modelable/emitters/go.py cli/tests/test_emit_go.py
git commit -m "feat: add go codegen backend"
```

---

### Task 7: Update CLI help, docs, and sample smoke coverage

**Files:**
- Modify: `docs/cli-spec.md`
- Modify: `docs/emitter-spec.md`
- Modify: `docs/modelable-system-spec.md`
- Modify: `docs/mvp-implementation-plan.md`
- Modify: `cli/tests/test_cli.py`
- Modify: `cli/tests/test_samples.py`

- [ ] **Step 1: Add tests that the CLI advertises all language targets once implemented**

```python
def test_codegen_formats_lists_all_language_targets():
    result = runner.invoke(cli, ["codegen", "formats"])
    assert "csharp" in result.output
    assert "java" in result.output
    assert "python" in result.output
    assert "rust" in result.output
    assert "go" in result.output
```

- [ ] **Step 2: Update the CLI and docs to reflect the new supported formats**

```markdown
- Supported generated-language targets: TypeScript, C#, Java, Python, Rust, Go
- Phase 1 contract: `.mdl` remains the source of truth for every backend
```

- [ ] **Step 3: Extend the sample smoke tests to compile the MVP sample through every supported language target**

```python
for target, suffix in [
    ("typescript", ".ts"),
    ("csharp", ".cs"),
    ("java", ".java"),
    ("python", ".py"),
    ("rust", ".rs"),
    ("go", ".go"),
]:
    result = runner.invoke(cli, ["compile", str(sample_path), "--target", target, "--out", str(out_dir / target)])
    assert result.exit_code == 0, result.output
    assert any((out_dir / target).glob(f"*{suffix}"))
```

- [ ] **Step 4: Run the full CLI suite and a clean sample smoke workflow**

Run:
`uv run pytest tests/ -v`
`uv run modelable validate ../samples/mvp --strict`
`uv run modelable compile ../samples/mvp --target csharp --out ../dist/csharp`
`uv run modelable compile ../samples/mvp --target java --out ../dist/java`
`uv run modelable compile ../samples/mvp --target python --out ../dist/python`
`uv run modelable compile ../samples/mvp --target rust --out ../dist/rust`
`uv run modelable compile ../samples/mvp --target go --out ../dist/go`

Expected: all targets compile deterministically and the corpus remains green.

- [ ] **Step 5: Commit**

```bash
git add docs/cli-spec.md docs/emitter-spec.md docs/modelable-system-spec.md docs/mvp-implementation-plan.md cli/tests/test_cli.py cli/tests/test_samples.py
git commit -m "docs: and tests: add multi-language codegen coverage"
```

---

### Task 8: Final verification and release notes

**Files:**
- Modify: `README.md`
- Modify: `docs/README.md`
- Modify: `docs/technology-evaluation.md` if the supported-target matrix changes

- [ ] **Step 1: Review the language-target matrix for consistency**

Check that every place listing codegen targets uses the same names and the same implementation status.

- [ ] **Step 2: Run the release gate**

Run:
`uv sync --extra dev --frozen`
`uv run pytest --tb=short`
`uv run modelable validate ../samples/mvp --strict`

Expected: clean repo-wide verification from a fresh checkout.

- [ ] **Step 3: Write release notes**

Summarize the new generated-language targets, the shared codegen boundary, and any deferred pieces that remain.
