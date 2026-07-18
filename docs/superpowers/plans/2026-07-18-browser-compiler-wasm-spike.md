# Browser Compiler WASM Spike Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a static proof of concept that loads a browser-only Modelable wheel in Pyodide, validates and formats in-memory `.mdl` sources, generates JSON Schema, proves native/browser conformance, and publishes under the existing GitHub Pages artifact.

**Architecture:** Keep one maintained Python source tree. A deterministic build script stages the browser-compatible module closure into a `modelable-browser` wheel, while a compiler-owned facade returns JSON-compatible DTOs. A Vite-built module worker owns Pyodide and exposes protocol version 1 to a minimal proof UI; native and Playwright harnesses compare the same fixtures and enforce size and timing budgets.

**Tech Stack:** Python 3.14.2, Pyodide 314.0.2 (`pyemscripten_2026_0_wasm32`), Hatchling, Pydantic 2.12.5 in the browser lock, Lark 1.3.1, TypeScript 7.0.2, Vite 8.1.5, Vitest 4.1.10, Playwright 1.61.1, Node.js 26, GitHub Pages.

## Global Constraints

- Implement only the browser-compiler spike. Monaco, React, visualization, persistence, service workers, LLM providers, conversational planning, registry synchronization, publishing, and plugins remain out of scope.
- Keep `cli/src/modelable` as the single maintained Python source tree. Do not create a copied browser source tree or split the repository into multiple Python packages.
- The browser distribution is named `modelable-browser`, imports as `modelable`, requires CPython `>=3.14,<3.15`, and contains no imports of `click`, `rich`, `pygls`, `lsprotocol`, `psycopg`, `psycopg_binary`, `socket`, or `subprocess`.
- Pin Pyodide to `314.0.2`, CPython to `3.14.2`, and the platform to `pyemscripten_2026_0_wasm32`.
- Load Pyodide, Python wheels, fixtures, and the Modelable wheel from same-origin static assets at runtime.
- Use `/modelable/playground/` as the production base path. The existing docs workflow remains the sole GitHub Pages deployer.
- Every worker request and response uses `protocolVersion: 1`, a caller-generated string ID, and structured-clone-compatible data.
- Python owns parsing, normalized IR, validation, formatting, JSON Schema semantics, diagnostic normalization, and artifact content. TypeScript owns worker lifecycle, transport, presentation, and timing.
- Preserve existing CLI and VS Code behavior and public imports.
- Before every commit, run these exact commands from `cli/` and require zero exits:

```powershell
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

- Browser-facing commits must also run the focused `web/` commands named in their task.
- The final implementation commit must move this plan and its design spec into their respective `archived/` directories.

## Planned File Structure

```text
cli/
  browser/
    pyproject.toml
    browser-lock.json
  scripts/
    build_browser_wheel.py
    write_browser_conformance.py
  src/modelable/
    browser/
      __init__.py
      api.py
      dispatch.py
      dto.py
    compiler/
      render.py
    emitters/
      base.py
      json_schema.py
    llm/
      render.py
  tests/
    conformance/browser/
      invalid-parse.mdl
      invalid-reference.mdl
      invalid-semantic.mdl
      multi-domain-customer.mdl
      multi-domain-order.mdl
      single-valid.mdl
      snapshots/
        invalid-parse.json
        invalid-semantic.json
        multi-domain.json
        single-valid.json
    test_browser_api.py
    test_browser_conformance.py
    test_browser_packaging.py

web/
  index.html
  package.json
  package-lock.json
  playwright.config.ts
  tsconfig.json
  vite.config.ts
  public/
    fixtures/
    pyodide/
    python/
  scripts/
    check-budgets.mjs
    vendor-python-assets.mjs
  src/
    client.test.ts
    client.ts
    compiler.worker.ts
    main.ts
    protocol.test.ts
    protocol.ts
    style.css
  tests/
    conformance.spec.ts
    playground.spec.ts

.github/
  scripts/
    assemble_pages.py
    run_browser_spike.py
  workflows/
    docs.yml
    validate.yml

docs/
  architecture.md
  maintainers.md
  playground-design.md
```

---

### Task 1: Move Canonical Rendering and JSON Schema Artifacts Behind Compiler-Owned Interfaces

**Files:**
- Move: `cli/src/modelable/llm/render.py` → `cli/src/modelable/compiler/render.py`
- Create: `cli/src/modelable/llm/render.py`
- Modify: `cli/src/modelable/commands/workspace.py`
- Modify: `cli/src/modelable/llm/engine.py`
- Modify: `cli/src/modelable/llm/importers.py`
- Modify: `cli/src/modelable/llm/workspace_editor.py`
- Modify: `cli/src/modelable/registry/signature.py`
- Modify: `cli/src/modelable/emitters/base.py`
- Modify: `cli/src/modelable/emitters/json_schema.py`
- Modify: `cli/tests/test_emit_json_schema.py`
- Modify: `cli/tests/test_llm_render_roundtrip.py`
- Modify: `cli/tests/test_serialization_hints.py`

**Interfaces:**
- Consumes: existing `Workspace`, `MdlFile`, `EmittedArtifact`, and JSON Schema emitter behavior.
- Produces: `modelable.compiler.render.render_mdl(...)`, `render_model_version(...)`, `render_projection_version(...)`, signature renderers, `render_artifact_text(artifact) -> str`, and `emit_json_schema_artifacts(workspace) -> list[EmittedArtifact]`.

- [ ] **Step 1: Add failing tests for compiler-owned rendering and in-memory JSON Schema**

Add these focused assertions:

```python
from pathlib import PurePosixPath

from modelable.compiler.render import render_mdl
from modelable.emitters.base import render_artifact_text
from modelable.emitters.json_schema import emit_json_schema_artifacts


def test_json_schema_artifacts_are_relative_and_rendered_in_memory(tmp_path):
    source = tmp_path / "workspace.mdl"
    source.write_text(
        'domain customer {\n  owner: "team"\n'
        "  entity Customer @ 1 (additive) {\n"
        "    @key id: uuid\n  }\n}\n",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)

    artifacts = emit_json_schema_artifacts(workspace)

    assert [artifact.path for artifact in artifacts] == [
        PurePosixPath("customer.Customer.v1.json")
    ]
    rendered = render_artifact_text(artifacts[0])
    assert rendered.endswith("\n")
    assert '"title": "Customer"' in rendered
    assert not (tmp_path / "customer.Customer.v1.json").exists()


def test_canonical_renderer_is_compiler_owned():
    mdl = parse_text_to_ir(
        'domain customer {\n  owner: "team"\n'
        "  entity Customer @ 1 (additive) {\n"
        "    @key id: uuid\n  }\n}\n"
    )
    assert render_mdl(mdl).startswith("domain customer {")
```

- [ ] **Step 2: Run the focused tests and verify the new imports fail**

Run:

```powershell
uv run pytest tests/test_emit_json_schema.py tests/test_llm_render_roundtrip.py tests/test_serialization_hints.py --tb=short -q
```

Expected: collection fails because `modelable.compiler.render`,
`render_artifact_text`, and `emit_json_schema_artifacts` do not exist.

- [ ] **Step 3: Move the renderer and preserve the old public import**

Move the complete renderer without altering its behavior:

```powershell
git mv src/modelable/llm/render.py src/modelable/compiler/render.py
```

Create the compatibility module:

```python
from modelable.compiler.render import (
    render_mdl,
    render_model_version,
    render_projection_version,
    render_signature_model_version,
    render_signature_projection_version,
)

__all__ = [
    "render_mdl",
    "render_model_version",
    "render_projection_version",
    "render_signature_model_version",
    "render_signature_projection_version",
]
```

Update production imports to use `modelable.compiler.render`; retain the shim so
existing external imports of `modelable.llm.render` remain valid.

- [ ] **Step 4: Add artifact text rendering and the no-output-directory entry point**

In `emitters/base.py`, add:

```python
def render_artifact_text(artifact: EmittedArtifact) -> str:
    content = artifact.content
    if isinstance(content, bytes):
        raise TypeError(f"{artifact.target} artifact {artifact.artifact_id} is binary")
    if isinstance(content, dict):
        return json.dumps(content, indent=2, ensure_ascii=False) + "\n"
    return content
```

In `emitters/json_schema.py`, change path annotations from `Path` to
`PurePath`, import `PurePosixPath`, and add:

```python
def emit_json_schema_artifacts(workspace: Workspace) -> list[EmittedArtifact]:
    """Return deterministic JSON Schema artifacts without writing files."""
    return emit_json_schema(workspace, PurePosixPath())
```

Keep `emit_json_schema(workspace, out_dir)` unchanged as the CLI-facing adapter.

- [ ] **Step 5: Run focused and cross-surface tests**

Run:

```powershell
uv run pytest tests/test_emit_json_schema.py tests/test_cli_compile.py tests/test_llm_render_roundtrip.py tests/test_serialization_hints.py tests/test_registry_signature.py --tb=short -q
```

Expected: all selected tests pass, and the existing CLI still writes the same
JSON Schema bytes.

- [ ] **Step 6: Run the mandatory pre-commit gate and commit**

Run the four global CLI commands, then:

```powershell
git add cli/src/modelable cli/tests
git commit -m "refactor: expose compiler-owned browser primitives"
```

---

### Task 2: Add the Native Browser Compiler Facade and JSON Dispatch Boundary

**Files:**
- Create: `cli/src/modelable/browser/__init__.py`
- Create: `cli/src/modelable/browser/dto.py`
- Create: `cli/src/modelable/browser/api.py`
- Create: `cli/src/modelable/browser/dispatch.py`
- Create: `cli/tests/test_browser_api.py`

**Interfaces:**
- Consumes: `load_workspace_from_sources`, compiler-owned rendering, `emit_json_schema_artifacts`, and normalized diagnostics.
- Produces: immutable `BrowserSource`, `BrowserDiagnostic`, `BrowserArtifact`, result DTOs, `BrowserCompiler`, and `dispatch_browser_request(method: str, payload_json: str) -> str`.

- [ ] **Step 1: Write failing DTO and behavior tests**

Create tests covering valid open, duplicate URIs, invalid versions, parse errors,
semantic errors, canonical formatting, blocked compilation, successful JSON
Schema generation, unknown methods, and malformed JSON:

```python
import json

from modelable.browser import BrowserCompiler, BrowserSource, dispatch_browser_request

VALID = (
    'domain customer {\n  owner: "team"\n'
    "  entity Customer @ 1 (additive) {\n"
    "    @key id: uuid\n  }\n}\n"
)


def test_open_workspace_returns_hashes_and_no_diagnostics():
    result = BrowserCompiler().open_workspace(
        (BrowserSource(uri="inmemory:///customer.mdl", text=VALID, version=1),)
    )
    assert result.diagnostics == ()
    assert set(result.source_hashes) == {"inmemory:///customer.mdl"}
    assert len(result.source_hashes["inmemory:///customer.mdl"]) == 64


def test_format_source_returns_canonical_text():
    source = BrowserSource(
        uri="inmemory:///customer.mdl",
        text='domain customer { owner: "team" }',
        version=1,
    )
    result = BrowserCompiler().format_source(source)
    assert result.diagnostics == ()
    assert result.replacement_text == 'domain customer {\n  owner: "team"\n}\n'


def test_compile_json_schema_returns_text_artifact():
    result = BrowserCompiler().compile_json_schema(
        (BrowserSource(uri="inmemory:///customer.mdl", text=VALID, version=1),)
    )
    assert result.diagnostics == ()
    assert len(result.artifacts) == 1
    assert result.artifacts[0].path == "customer.Customer.v1.json"
    assert result.artifacts[0].media_type == "application/schema+json"
    assert result.artifacts[0].source_refs == ("customer.Customer@1",)


def test_dispatch_rejects_unknown_method_without_traceback():
    response = json.loads(dispatch_browser_request("shell.run", "{}"))
    assert response == {
        "ok": False,
        "error": {
            "code": "INVALID_REQUEST",
            "message": "Unsupported browser compiler method: shell.run",
        },
    }
```

- [ ] **Step 2: Run tests and verify the browser package is absent**

Run:

```powershell
uv run pytest tests/test_browser_api.py --tb=short -q
```

Expected: collection fails with `ModuleNotFoundError: modelable.browser`.

- [ ] **Step 3: Define immutable DTOs**

Implement these exact public fields in `dto.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BrowserSource:
    uri: str
    text: str
    version: int


@dataclass(frozen=True)
class BrowserDiagnostic:
    code: str
    severity: str
    message: str
    uri: str
    line: int | None
    column: int | None
    end_line: int | None
    end_column: int | None


@dataclass(frozen=True)
class BrowserArtifact:
    path: str
    media_type: str
    content: str
    source_refs: tuple[str, ...]


@dataclass(frozen=True)
class BrowserWorkspaceResult:
    diagnostics: tuple[BrowserDiagnostic, ...]
    source_hashes: dict[str, str]


@dataclass(frozen=True)
class BrowserFormatResult:
    diagnostics: tuple[BrowserDiagnostic, ...]
    replacement_text: str | None


@dataclass(frozen=True)
class BrowserCompileResult:
    diagnostics: tuple[BrowserDiagnostic, ...]
    artifacts: tuple[BrowserArtifact, ...]
```

- [ ] **Step 4: Implement `BrowserCompiler`**

`api.py` must validate source DTOs before parsing:

```python
def _validate_sources(sources: tuple[BrowserSource, ...]) -> None:
    if not sources:
        raise BrowserInputError("At least one source is required")
    uris = [source.uri for source in sources]
    if len(uris) != len(set(uris)):
        raise BrowserInputError("Source URIs must be unique")
    invalid = [source.uri for source in sources if source.version <= 0]
    if invalid:
        raise BrowserInputError(f"Source versions must be positive: {', '.join(invalid)}")
```

Convert sources through `WorkspaceDocumentSource(path=None, uri=..., text=...)`.
Catch `ParseError` and convert `error.diagnostic(source.uri)` into one
`BrowserDiagnostic`. For valid workspaces, preserve compiler diagnostic order.

`format_source` parses one source, runs `validate_diagnostics`, and returns
`render_mdl(mdl)` only when no error diagnostic exists.

`compile_json_schema` calls `open_workspace`; if it has any error diagnostic,
return no artifacts. Otherwise load the workspace once, call
`emit_json_schema_artifacts`, sort by `artifact.path.as_posix()`, and serialize
each artifact with `render_artifact_text`.

- [ ] **Step 5: Implement the JSON string boundary**

`dispatch.py` must accept only these method/payload shapes:

```python
_METHODS = {
    "workspace.open",
    "source.format",
    "compile.jsonSchema",
}
```

Use `json.loads(payload_json)`, require an object payload, construct
`BrowserSource` values from exact `uri`, `text`, and `version` fields, and
return:

```python
json.dumps(
    {"ok": True, "result": asdict(result)},
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
)
```

Catch `json.JSONDecodeError`, `KeyError`, `TypeError`, `ValueError`, and
`BrowserInputError` and return `INVALID_REQUEST` with no traceback, source text,
or local path. Do not catch `BaseException`.

Export the DTOs, compiler, and dispatcher from `browser/__init__.py`.

- [ ] **Step 6: Run focused and full native tests**

Run:

```powershell
uv run pytest tests/test_browser_api.py tests/test_emit_json_schema.py tests/test_diagnostics.py --tb=short -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Run the mandatory pre-commit gate and commit**

Run the four global CLI commands, then:

```powershell
git add cli/src/modelable/browser cli/tests/test_browser_api.py
git commit -m "feat: add browser compiler facade"
```

---

### Task 3: Build and Audit the Browser-Only Python Wheel

**Files:**
- Create: `cli/browser/pyproject.toml`
- Create: `cli/browser/browser-lock.json`
- Create: `cli/scripts/build_browser_wheel.py`
- Create: `cli/tests/test_browser_packaging.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: the `modelable.browser` facade and existing compiler source tree.
- Produces: `python cli/scripts/build_browser_wheel.py --output DIR`, a pure-Python `modelable_browser-<version>-py3-none-any.whl`, and `browser-manifest.json`.

- [ ] **Step 1: Write failing packaging policy tests**

Add tests that import the build script and assert:

```python
FORBIDDEN_IMPORTS = {
    "click",
    "rich",
    "pygls",
    "lsprotocol",
    "psycopg",
    "psycopg_binary",
    "socket",
    "subprocess",
}


def test_browser_module_selection_excludes_desktop_surfaces():
    selected = {path.as_posix() for path in selected_source_paths()}
    assert "modelable/browser/api.py" in selected
    assert "modelable/grammar/modelable.lark" in selected
    assert not any(path.startswith("modelable/commands/") for path in selected)
    assert not any(path.startswith("modelable/lsp/") for path in selected)
    assert not any(path.startswith("modelable/runtime/") for path in selected)
    assert "modelable/cli.py" not in selected


def test_forbidden_import_scan_reports_exact_module(tmp_path):
    source = tmp_path / "bad.py"
    source.write_text("from psycopg import connect\n", encoding="utf-8")
    assert scan_forbidden_imports([source]) == [(source, 1, "psycopg")]
```

Add a real wheel test that builds into `tmp_path`, opens the wheel as a ZIP,
reads `METADATA`, and asserts:

- distribution name is `modelable-browser`;
- `Requires-Python: <3.15,>=3.14`;
- no forbidden dependency appears;
- `modelable/browser/api.py` and the grammar are present; and
- desktop modules are absent.

- [ ] **Step 2: Run the packaging tests and verify the script is missing**

Run:

```powershell
uv run pytest tests/test_browser_packaging.py --tb=short -q
```

Expected: collection fails because `scripts/build_browser_wheel.py` and its
functions do not exist.

- [ ] **Step 3: Add browser package metadata and the committed dependency lock**

`cli/browser/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "modelable-browser"
version = "1.2.1"
description = "Browser compiler facade for Modelable"
requires-python = ">=3.14,<3.15"
dependencies = [
  "lark==1.3.1",
  "pydantic==2.12.5",
  "jsonschema==4.26.0",
  "referencing==0.37.0",
  "pyyaml==6.0.3",
]

[tool.hatch.build.targets.wheel]
packages = ["src/modelable"]
```

`browser-lock.json` records:

```json
{
  "schemaVersion": 1,
  "pyodide": "314.0.2",
  "python": "3.14.2",
  "platform": "pyemscripten_2026_0_wasm32",
  "roots": ["micropip", "pydantic", "jsonschema", "pyyaml"],
  "externalWheels": [
    {
      "name": "lark",
      "version": "1.3.1",
      "fileName": "lark-1.3.1-py3-none-any.whl",
      "url": "https://files.pythonhosted.org/packages/82/3d/14ce75ef66813643812f3093ab17e46d3a206942ce7376d31ec2d36229e7/lark-1.3.1-py3-none-any.whl",
      "sha256": "c629b661023a014c37da873b4ff58a817398d12635d3bbb2c5a03be7fe5d1e12"
    }
  ]
}
```

- [ ] **Step 4: Implement deterministic source staging and import scanning**

The build script selects:

```python
INCLUDE_TREES = (
    "browser",
    "compat",
    "compiler",
    "diagnostics",
    "expressions",
    "governance",
    "grammar",
    "parser",
    "planner",
    "validation",
)
INCLUDE_FILES = (
    "__init__.py",
    "_pydantic_py314_compat.py",
    "emitters/__init__.py",
    "emitters/base.py",
    "emitters/diagnostics.py",
    "emitters/json_schema.py",
    "registry/__init__.py",
    "registry/resolver.py",
    "registry/signature.py",
)
```

Parse every staged `.py` file with `ast.parse`. Record forbidden `ast.Import`
and `ast.ImportFrom` roots as `(path, lineno, root)`, sort them, print all
findings, and exit nonzero before building.

Use `tempfile.TemporaryDirectory`, copy package metadata and selected source
under `src/modelable`, then run:

```python
subprocess.run(
    ["uv", "build", "--wheel", "--out-dir", str(output_dir)],
    cwd=staging_root,
    check=True,
)
```

Compute SHA-256 over the wheel bytes and write the manifest from measured
values:

```python
manifest = {
    "schemaVersion": 1,
    "distribution": "modelable-browser",
    "version": browser_version,
    "commit": subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=repository_root,
        text=True,
    ).strip(),
    "wheel": wheel_path.name,
    "sha256": hashlib.sha256(wheel_path.read_bytes()).hexdigest(),
    "pyodide": browser_lock["pyodide"],
    "python": browser_lock["python"],
    "platform": browser_lock["platform"],
}
```

The script derives version `1.2.1` from the root CLI `pyproject.toml` and fails
when browser metadata differs.

- [ ] **Step 5: Build the wheel and test it in an isolated native target**

Run:

```powershell
uv run python scripts/build_browser_wheel.py --output dist/browser
uv run --isolated --with ./dist/browser/modelable_browser-1.2.1-py3-none-any.whl python -c "from modelable.browser import BrowserCompiler; print(BrowserCompiler)"
uv run pytest tests/test_browser_packaging.py --tb=short -q
```

Expected: wheel and manifest are created; the isolated import prints
`<class 'modelable.browser.api.BrowserCompiler'>`; focused tests pass.

- [ ] **Step 6: Ignore generated browser outputs**

Add:

```gitignore
cli/dist/browser/
web/public/pyodide/
web/public/python/
web/dist/
web/test-results/
web/playwright-report/
```

- [ ] **Step 7: Run the mandatory pre-commit gate and commit**

Run the four global CLI commands, then:

```powershell
git add .gitignore cli/browser cli/scripts/build_browser_wheel.py cli/tests/test_browser_packaging.py
git commit -m "build: produce browser-only Modelable wheel"
```

---

### Task 4: Scaffold the Static Browser Build and Vendor Same-Origin Python Assets

**Files:**
- Create: `web/package.json`
- Create: `web/package-lock.json`
- Create: `web/tsconfig.json`
- Create: `web/vite.config.ts`
- Create: `web/scripts/vendor-python-assets.mjs`
- Create: `web/src/assets.test.ts`
- Create: `web/index.html`

**Interfaces:**
- Consumes: `cli/browser/browser-lock.json`, generated browser wheel/manifest, and npm `pyodide@314.0.2`.
- Produces: `npm run prepare:python`, same-origin `public/pyodide/` and `public/python/`, and a Vite build rooted at `/modelable/playground/`.

- [ ] **Step 1: Add the exact browser package manifest**

Create:

```json
{
  "name": "modelable-browser-spike",
  "private": true,
  "type": "module",
  "scripts": {
    "prepare:python": "uv run --project ../cli python ../cli/scripts/build_browser_wheel.py --output ../web/public/python && node scripts/vendor-python-assets.mjs",
    "check": "tsc --noEmit",
    "test": "vitest run",
    "build": "npm run prepare:python && vite build",
    "preview": "vite preview --host 127.0.0.1",
    "test:e2e": "playwright test",
    "check:budgets": "node scripts/check-budgets.mjs"
  },
  "dependencies": {
    "pyodide": "314.0.2"
  },
  "devDependencies": {
    "@playwright/test": "1.61.1",
    "@types/node": "26.1.1",
    "typescript": "7.0.2",
    "vite": "8.1.5",
    "vitest": "4.1.10"
  }
}
```

Run `npm install --package-lock-only` and commit the resulting lock.

- [ ] **Step 2: Configure strict TypeScript and the repository-relative base**

`tsconfig.json` uses `strict: true`, `noUncheckedIndexedAccess: true`,
`module: "ESNext"`, `moduleResolution: "Bundler"`, `target: "ES2022"`, and
types `["node", "vitest/globals"]`.

`vite.config.ts`:

```typescript
import { defineConfig } from 'vitest/config';

export default defineConfig({
  base: '/modelable/playground/',
  publicDir: 'public',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  test: {
    environment: 'node',
  },
});
```

Create minimal semantic HTML with `lang="en"`, a heading, status element, input
textarea, action buttons, diagnostics `<pre>`, artifacts `<pre>`, and metrics
`<pre>`. Reference `/src/main.ts` as a module. Add a production-safe CSP meta
policy that defaults to the same origin, permits only the WebAssembly
evaluation needed by Pyodide, restricts workers and network connections to
`'self'`, and disables objects and base-URI changes:

```html
<meta
  http-equiv="Content-Security-Policy"
  content="default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self'; worker-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'"
>
```

- [ ] **Step 3: Write failing asset-closure tests**

Export pure functions from `vendor-python-assets.mjs` and test:

```typescript
expect(resolvePackageClosure(lock, ['pydantic'])).toEqual([
  'annotated-types',
  'pydantic',
  'pydantic-core',
  'typing-extensions',
  'typing-inspection',
]);
```

Also assert `verifySha256(bytes, expected)` rejects mismatches and that runtime
asset names are exactly:

```typescript
[
  'pyodide-lock.json',
  'pyodide.asm.mjs',
  'pyodide.asm.wasm',
  'pyodide.mjs',
  'python_stdlib.zip',
]
```

Read `index.html` in a unit test and assert that its CSP contains
`script-src 'self' 'wasm-unsafe-eval'`, `worker-src 'self'`,
`connect-src 'self'`, `object-src 'none'`, and `base-uri 'none'`.

- [ ] **Step 4: Run unit tests and verify the vendor module is missing**

Run:

```powershell
npm ci
npm test
```

Expected: tests fail because the exported asset functions do not exist.

- [ ] **Step 5: Implement same-origin asset vendoring**

The script must:

1. delete and recreate `public/pyodide`, create `public/python` if absent, and
   remove only the previously vendored dependency wheels and
   `runtime-manifest.json` from `public/python`;
2. copy the five runtime files from `node_modules/pyodide`;
3. parse npm's `pyodide-lock.json`;
4. recursively resolve the committed root packages through each entry's
   `depends`;
5. download each selected `file_name` from
   `https://cdn.jsdelivr.net/pyodide/v314.0.2/full/`;
6. verify each archive against its lock entry's SHA-256;
7. download and verify the committed Lark wheel;
8. retain the freshly generated Modelable wheel and manifest in
   `public/python`; and
9. write `public/python/runtime-manifest.json` containing sorted same-origin
   URLs for Lark and Modelable.

Use `fs.rm(path, {recursive: true, force: true})`, `fs.mkdir`, `fs.copyFile`,
global `fetch`, and `node:crypto`. Never continue after a checksum mismatch.

- [ ] **Step 6: Build and inspect the static output**

Run:

```powershell
npm run check
npm test
npm run build
Select-String -Path dist/index.html -Pattern '/modelable/playground/'
```

Expected: type checking and tests pass; Vite builds; the output references the
repository-relative base; all runtime files and wheels exist under `dist/`.

- [ ] **Step 7: Run the mandatory CLI gate and commit**

Run the four global CLI commands, then:

```powershell
git add web/package.json web/package-lock.json web/tsconfig.json web/vite.config.ts web/index.html web/scripts/vendor-python-assets.mjs web/src/assets.test.ts
git commit -m "build: vendor browser compiler runtime"
```

---

### Task 5: Implement Protocol Version 1, Worker Lifecycle, and Client

**Files:**
- Create: `web/src/protocol.ts`
- Create: `web/src/protocol.test.ts`
- Create: `web/src/client.ts`
- Create: `web/src/client.test.ts`
- Create: `web/src/compiler.worker.ts`

**Interfaces:**
- Consumes: same-origin Pyodide assets and Python `dispatch_browser_request`.
- Produces: `BrowserCompilerClient.initialize()`, `.openWorkspace(sources)`, `.formatSource(source)`, `.compileJsonSchema(sources)`, and typed protocol envelopes.

- [ ] **Step 1: Define protocol types and failing validators**

Use the exact methods:

```typescript
export type BrowserCompilerMethod =
  | 'runtime.initialize'
  | 'workspace.open'
  | 'source.format'
  | 'compile.jsonSchema';
```

Define request, success, and failure interfaces from the spec. Add runtime
validators that reject non-object values, protocol versions other than `1`,
missing IDs, unknown methods, and success envelopes without `result`.

Test malformed values individually; do not validate by TypeScript casts alone.

- [ ] **Step 2: Implement protocol validators and run unit tests**

Run:

```powershell
npm test -- protocol.test.ts
```

Expected: all protocol tests pass.

- [ ] **Step 3: Write failing client lifecycle tests with a fake worker**

Cover:

- `initialize()` sends one request when called concurrently;
- response IDs resolve only their matching promises;
- worker `error` rejects every pending request;
- typed failures reject with `BrowserCompilerError.code`;
- post-disposal calls reject without posting; and
- source DTOs preserve `uri`, `text`, and `version`.

The fake worker implements `postMessage`, `addEventListener`,
`removeEventListener`, and `terminate`; it records posted requests.

- [ ] **Step 4: Implement the client**

Use `crypto.randomUUID()` for request IDs and one
`Map<string, PendingRequest>`. Construct the production worker exactly as:

```typescript
new Worker(new URL('./compiler.worker.ts', import.meta.url), { type: 'module' })
```

Cache one initialization promise. Public methods await initialization before
posting compiler work. `dispose()` terminates the worker and rejects pending
requests with code `COMPILER_FAILED`.

- [ ] **Step 5: Implement the Pyodide worker**

The worker must:

1. initialize once with
   `loadPyodide({indexURL: new URL('../pyodide/', self.location.href).href})`;
2. call `loadPackage(['micropip', 'pydantic', 'jsonschema', 'pyyaml'])`;
3. fetch `../python/runtime-manifest.json`;
4. install Lark and Modelable same-origin wheel URLs with
   `micropip.install(urls, deps=False)`;
5. import `dispatch_browser_request` once through `pyimport`;
6. pass request method and `JSON.stringify(payload)` to Python;
7. parse the returned JSON and wrap it in the protocol response; and
8. destroy every `PyProxy` in `finally`.

Map malformed requests to `INVALID_REQUEST`, version mismatch to
`UNSUPPORTED_PROTOCOL`, initialization errors to `INITIALIZATION_FAILED`, and
unexpected dispatch errors to `COMPILER_FAILED`. Returned messages must omit
stack traces, checkout paths, environment variables, and source text. Log
detailed errors only to the worker console in development mode.

- [ ] **Step 6: Run TypeScript checks and unit tests**

Run:

```powershell
npm run check
npm test
npm run build
```

Expected: all commands pass and the worker is emitted as a separate production
asset.

- [ ] **Step 7: Run the mandatory CLI gate and commit**

Run the four global CLI commands, then:

```powershell
git add web/src/protocol.ts web/src/protocol.test.ts web/src/client.ts web/src/client.test.ts web/src/compiler.worker.ts
git commit -m "feat: run Modelable through a Pyodide worker"
```

---

### Task 6: Add the Proof UI and Native/Browser Conformance

**Files:**
- Create: `cli/tests/conformance/browser/single-valid.mdl`
- Create: `cli/tests/conformance/browser/multi-domain-customer.mdl`
- Create: `cli/tests/conformance/browser/multi-domain-order.mdl`
- Create: `cli/tests/conformance/browser/invalid-parse.mdl`
- Create: `cli/tests/conformance/browser/invalid-semantic.mdl`
- Create: `cli/tests/conformance/browser/snapshots/*.json`
- Create: `cli/scripts/write_browser_conformance.py`
- Create: `cli/tests/test_browser_conformance.py`
- Create: `web/src/main.ts`
- Create: `web/src/style.css`
- Create: `web/playwright.config.ts`
- Create: `web/tests/conformance.spec.ts`
- Create: `web/tests/playground.spec.ts`
- Modify: `web/index.html`
- Modify: `web/scripts/vendor-python-assets.mjs`

**Interfaces:**
- Consumes: browser client and Python facade.
- Produces: committed canonical snapshots, browser comparison tests, and a minimal Validate/Format/Generate proof.

- [ ] **Step 1: Add representative fixture sources**

`single-valid.mdl` contains a workspace, owned customer domain, one entity with
UUID key, optional string, nested object, and decimal field.

The multi-domain pair contains `customer.Customer@1` and
`sales.Order@1` with a `ref<customer.Customer@1>` field.

`invalid-parse.mdl` omits a closing entity brace.

`invalid-reference.mdl` declares an entity field referencing a missing model
version so the compiler returns a reference diagnostic.

`invalid-semantic.mdl` contains two identical
`customer.Customer@1` declarations so the compiler returns a duplicate-version
diagnostic.

- [ ] **Step 2: Write the native snapshot generator and tests**

`write_browser_conformance.py` invokes `BrowserCompiler` for:

- open/validate on every scenario;
- format on `single-valid`;
- JSON Schema compilation on the valid scenarios.

Write JSON with `indent=2`, `ensure_ascii=False`, `sort_keys=True`, and a final
newline. Normalize fixture URIs as `fixture:///filename.mdl`.

The test regenerates into `tmp_path` and byte-compares every committed snapshot.
It also asserts no absolute checkout path, backslash, timing, or traceback is
present.

- [ ] **Step 3: Generate snapshots and prove native determinism**

Run:

```powershell
uv run python scripts/write_browser_conformance.py --output tests/conformance/browser/snapshots
uv run pytest tests/test_browser_conformance.py --tb=short -q
```

Expected: snapshots are created and the determinism test passes.

- [ ] **Step 4: Copy fixtures and snapshots into the static build**

Extend `vendor-python-assets.mjs` to copy:

```text
../cli/tests/conformance/browser/*.mdl
../cli/tests/conformance/browser/snapshots/*.json
```

to `public/fixtures/`, preserving sorted relative names. The script fails when
the native snapshot set and fixture set do not match the expected scenario
manifest.

- [ ] **Step 5: Implement the minimal proof UI**

`main.ts`:

- creates one `BrowserCompilerClient`;
- exposes it as `globalThis.__modelableBrowserCompiler` only when the page URL
  contains the explicit `?test=1` opt-in used by browser tests;
- loads `single-valid.mdl` into the textarea;
- shows initialization transitions;
- disables action buttons until ready;
- Validate calls `openWorkspace`;
- Format calls `formatSource` and replaces text only when diagnostics are empty;
- Generate calls `compileJsonSchema`;
- renders text with `textContent`, never `innerHTML`; and
- records initialization and operation durations through `performance.now()`.

Every action catches `BrowserCompilerError` and renders its code plus sanitized
message. Source content is never logged.

- [ ] **Step 6: Add Playwright conformance and interaction tests**

Configure Chromium, `baseURL:
"http://127.0.0.1:4173/modelable/playground/"`, and:

```typescript
webServer: {
  command: 'npm run preview',
  port: 4173,
  reuseExistingServer: false,
}
```

Conformance tests navigate with `?test=1`, fetch each fixture/snapshot, call
the test client in `page.evaluate`, normalize object key order, and require
exact deep equality.

Interaction tests verify initialization, validation, formatting, JSON Schema
preview, invalid-source diagnostics, disabled buttons while busy, keyboard
focus order, and that every observed HTTP(S) request has origin
`http://127.0.0.1:4173`. Ignore non-network `data:` and `blob:` URLs in this
origin assertion. Submit source containing Python and JavaScript-looking
expressions and assert it is treated as Modelable text, produces diagnostics,
and does not execute or add globals.

- [ ] **Step 7: Run native and browser conformance**

Run:

```powershell
cd cli
uv run pytest tests/test_browser_api.py tests/test_browser_conformance.py --tb=short -q
cd ../web
npm run check
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

Expected: native snapshots and browser results match exactly; UI tests pass.

- [ ] **Step 8: Run the mandatory CLI gate and commit**

Run the four global CLI commands, then:

```powershell
git add cli/scripts/write_browser_conformance.py cli/tests/conformance/browser cli/tests/test_browser_conformance.py web
git commit -m "test: prove native and browser compiler conformance"
```

---

### Task 7: Enforce Asset and Runtime Performance Budgets

**Files:**
- Create: `web/scripts/check-budgets.mjs`
- Create: `web/src/budgets.test.ts`
- Modify: `web/tests/conformance.spec.ts`
- Create: `.github/scripts/run_browser_spike.py`
- Create: `cli/tests/test_browser_spike_runner.py`

**Interfaces:**
- Consumes: production `web/dist`, Playwright timing observations, and all focused native/browser commands.
- Produces: `npm run check:budgets` and
  `uv run python .github/scripts/run_browser_spike.py`.

- [ ] **Step 1: Write failing size categorization tests**

Export:

```typescript
export const BUDGETS = {
  modelableWheel: 2 * 1024 * 1024,
  application: 750 * 1024,
  additionalPython: 15 * 1024 * 1024,
} as const;
```

Test that:

- `python/modelable_browser-*.whl` counts only as `modelableWheel`;
- HTML, CSS, and Vite JS count as `application`;
- package wheels under `pyodide/` and Lark under `python/` count as
  `additionalPython`;
- `pyodide.asm.wasm`, `python_stdlib.zip`, and Pyodide loader files are
  excluded from all three; and
- gzip size is computed from file bytes with `gzipSync`.

- [ ] **Step 2: Implement the budget checker**

Walk `dist` in sorted order, calculate compressed bytes per category, and print
JSON:

```json
{
  "modelableWheel": {"measured": 0, "budget": 2097152},
  "application": {"measured": 0, "budget": 768000},
  "additionalPython": {"measured": 0, "budget": 15728640}
}
```

Use the actual measured values. Exit `1` if any measured value exceeds its
budget and include every violating category in stderr.

- [ ] **Step 3: Add hard timing assertions**

In Playwright, perform three isolated cold page loads and three reloads using
the browser cache. Sort each measurement set and assert the median:

```typescript
expect(coldInitializeMedian).toBeLessThanOrEqual(20_000);
expect(cachedInitializeMedian).toBeLessThanOrEqual(5_000);
expect(validateMedian).toBeLessThanOrEqual(500);
expect(compileMedian).toBeLessThanOrEqual(1_000);
```

Print measured medians in the test annotation so CI artifacts retain them.

- [ ] **Step 4: Add the cross-platform full spike runner**

The Python runner executes with `subprocess.run(check=True)`:

```python
COMMANDS = (
    ("cli", ("uv", "run", "ruff", "check", ".")),
    ("cli", ("uv", "run", "ruff", "format", "--check", ".")),
    (
        "cli",
        (
            "uv",
            "run",
            "python",
            "../.github/scripts/check_mypy_baseline.py",
            "--baseline",
            "mypy-baseline.txt",
            "--",
            "uv",
            "run",
            "mypy",
            "src/modelable",
            "--no-error-summary",
            "--show-error-codes",
        ),
    ),
    ("cli", ("uv", "run", "pytest", "--tb=short")),
    ("web", ("npm", "ci")),
    ("web", ("npm", "run", "check")),
    ("web", ("npm", "test")),
    ("web", ("npm", "run", "build")),
    ("web", ("npm", "run", "test:e2e")),
    ("web", ("npm", "run", "check:budgets")),
)
```

Resolve `npm.cmd` on Windows with `shutil.which`; do not use `shell=True`.
The runner accepts `--skip-install` for callers that already ran `npm ci`.

Unit-test command order and early failure by injecting a fake runner.

- [ ] **Step 5: Run all budget and runner tests**

Run:

```powershell
cd web
npm run build
npm run check:budgets
npm run test:e2e
cd ../cli
uv run pytest tests/test_browser_spike_runner.py --tb=short -q
```

Expected: all hard budgets pass and measured values are printed.

- [ ] **Step 6: Run the mandatory CLI gate and commit**

Run the four global CLI commands, then:

```powershell
git add web/scripts/check-budgets.mjs web/src/budgets.test.ts web/tests/conformance.spec.ts .github/scripts/run_browser_spike.py cli/tests/test_browser_spike_runner.py
git commit -m "test: enforce browser compiler budgets"
```

---

### Task 8: Add Browser Surface CI and Compose One GitHub Pages Artifact

**Files:**
- Modify: `.github/scripts/detect_validate_surfaces.py`
- Modify: `cli/tests/test_validate_surface_detection.py`
- Modify: `.github/workflows/validate.yml`
- Modify: `.github/workflows/docs.yml`
- Create: `.github/scripts/assemble_pages.py`
- Create: `cli/tests/test_pages_assembly.py`
- Modify: `docs/maintainers.md`

**Interfaces:**
- Consumes: complete browser spike gate and `web/dist`.
- Produces: `browser` change-surface output, a dedicated Validate job, and one combined `site/` Pages artifact containing `/playground/`.

- [ ] **Step 1: Write failing change-surface tests**

Add `browser` to expected outputs and assert:

```python
assert detect_surfaces(["web/src/main.ts"])["browser"] is True
assert detect_surfaces(["cli/src/modelable/browser/api.py"])["browser"] is True
assert detect_surfaces(["cli/scripts/build_browser_wheel.py"])["browser"] is True
assert detect_surfaces(["docs/playground-design.md"])["browser"] is True
assert detect_surfaces(["README.md"])["browser"] is False
```

Workflow policy changes still enable every surface.

- [ ] **Step 2: Implement browser surface routing**

Add `browser` to `SURFACE_NAMES`. Enable it for:

```text
web/
cli/browser/
cli/src/modelable/browser/
cli/scripts/build_browser_wheel.py
cli/scripts/write_browser_conformance.py
cli/tests/conformance/browser/
cli/tests/test_browser_
docs/playground-design.md
docs/superpowers/specs/*browser-compiler-wasm*
docs/superpowers/plans/*browser-compiler-wasm*
```

Compiler, parser, validation, JSON Schema emitter, and compiler renderer changes
enable both `cli` and `browser`.

- [ ] **Step 3: Write failing Pages assembly tests**

Create temporary `site` and `web_dist` directories and assert
`assemble_pages(site, web_dist)`:

- copies the proof to `site/playground`;
- refuses a missing `index.html`;
- replaces an existing `site/playground` deterministically;
- rejects HTML containing `src="/assets/` or `href="/assets/`; and
- preserves existing MkDocs files.

- [ ] **Step 4: Implement Pages assembly**

Use `shutil.copytree(web_dist, site / "playground", dirs_exist_ok=False)` after
removing only the resolved `site/playground` directory. Verify both resolved
paths remain under the repository root before removal. Parse every HTML file as
text and reject origin-root asset URLs.

- [ ] **Step 5: Add the Validate browser job**

The changes job exports `browser`. Add a job using Ubuntu, Python 3.14, Node 26,
`uv sync --extra dev --frozen`, `npm ci`, Playwright Chromium installation with
dependencies, and:

```yaml
- name: Run browser compiler spike gate
  run: uv run python .github/scripts/run_browser_spike.py --skip-install
```

Upload Playwright report and `web/dist` on failure with
`actions/upload-artifact@v7.0.1`.

- [ ] **Step 6: Compose the docs deployment**

In `docs.yml`, set up Python and Node 26, build `web/`, build strict MkDocs, run:

```yaml
- name: Assemble Pages artifact
  run: uv run --project cli python .github/scripts/assemble_pages.py --site site --web-dist web/dist
```

Keep the existing single `upload-pages-artifact` and single `deploy-pages`
steps. Do not create another Pages workflow or environment.

- [ ] **Step 7: Document local maintainer commands**

Add:

```powershell
uv run python .github/scripts/run_browser_spike.py
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
uv run --project cli python .github/scripts/assemble_pages.py --site site --web-dist web/dist
```

State that only pushes to `main` deploy and PRs only build/test.

- [ ] **Step 8: Verify routing, workflow syntax, and Pages layout**

Run:

```powershell
cd cli
uv run pytest tests/test_validate_surface_detection.py tests/test_pages_assembly.py tests/test_release_workflow.py --tb=short -q
cd ..
uv run --project cli python .github/scripts/assemble_pages.py --site site --web-dist web/dist
Test-Path site/playground/index.html
```

Expected: tests pass and the final command prints `True`.

- [ ] **Step 9: Run the mandatory CLI gate and commit**

Run the four global CLI commands, then:

```powershell
git add .github cli/tests/test_validate_surface_detection.py cli/tests/test_pages_assembly.py docs/maintainers.md
git commit -m "ci: validate and publish browser compiler spike"
```

---

### Task 9: Document Measured Results, Mark the Spike Shipped, and Archive Its Documents

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `ROADMAP.md`
- Modify: `docs/architecture.md`
- Modify: `docs/playground-design.md`
- Modify: `docs/maintainers.md`
- Move: `docs/superpowers/specs/2026-07-18-browser-compiler-wasm-spike-design.md` → `docs/superpowers/specs/archived/2026-07-18-browser-compiler-wasm-spike-design.md`
- Move: `docs/superpowers/plans/2026-07-18-browser-compiler-wasm-spike.md` → `docs/superpowers/plans/archived/2026-07-18-browser-compiler-wasm-spike.md`

**Interfaces:**
- Consumes: shipped behavior and measured values from Tasks 1–8.
- Produces: truthful user/maintainer documentation, restored VS Code Language Model adapter priority, and no completed active WASM plan/spec.

- [ ] **Step 1: Capture final evidence**

Run:

```powershell
uv run python .github/scripts/run_browser_spike.py
node web/scripts/check-budgets.mjs > browser-budget-results.json
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
uv run --project cli python .github/scripts/assemble_pages.py --site site --web-dist web/dist
```

Copy the measured size and timing values into the documentation; do not commit
`browser-budget-results.json`.

- [ ] **Step 2: Document the shipped architecture**

Add this implemented dependency direction to `docs/architecture.md`:

```text
Minimal browser UI
  -> BrowserCompilerClient protocol v1
  -> module Web Worker
  -> pinned same-origin Pyodide
  -> modelable.browser BrowserCompiler
  -> parser, validator, canonical renderer, JSON Schema emitter
```

State that the browser wheel is staged from the existing source tree, excludes
desktop surfaces, and is not a second semantic implementation.

- [ ] **Step 3: Record user-visible behavior and measured budgets**

In `docs/playground-design.md`, mark Phase 1 shipped and list:

- deployed `/modelable/playground/` proof;
- supported Validate, Format, and Generate JSON Schema actions;
- exact Pyodide/Python versions;
- measured wheel/application/Python payload sizes;
- cold/cached initialization medians;
- validation and generation medians; and
- explicit deferral of editor, visualization, persistence, and AI phases.

Update maintainer troubleshooting for checksum, initialization, conformance,
budget, and Pages-base failures.

- [ ] **Step 4: Update changelog and roadmap**

Add an Unreleased changelog entry for the browser compiler proof.

Change roadmap item 3 from `Next` to `Shipped`, link to the archived spec, and
make the optional VS Code Language Model API adapter `Next`. Keep operational
management after that adapter.

- [ ] **Step 5: Archive the completed plan and spec**

Run:

```powershell
git mv docs/superpowers/specs/2026-07-18-browser-compiler-wasm-spike-design.md docs/superpowers/specs/archived/2026-07-18-browser-compiler-wasm-spike-design.md
git mv docs/superpowers/plans/2026-07-18-browser-compiler-wasm-spike.md docs/superpowers/plans/archived/2026-07-18-browser-compiler-wasm-spike.md
```

Repair every relative link and confirm the filenames exist only under
`archived/`.

- [ ] **Step 6: Run documentation review**

Run all four doc-review phases. Required result:

```text
Overall: PASS
Warnings requiring PR acknowledgement: 0
Blockers requiring fix before PR: 0
```

Run strict MkDocs again after link repairs.

- [ ] **Step 7: Run final complete verification**

Run:

```powershell
uv run python .github/scripts/run_browser_spike.py
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
git diff --check
git status --short
```

Expected:

- every command exits zero;
- 984 or more CLI tests pass, with only documented opt-in skips;
- native/browser conformance snapshots match;
- all size and timing budgets pass;
- the combined Pages artifact contains `site/playground/index.html`;
- the worktree contains only intended documentation changes before commit; and
- the completed plan and spec exist only under archived directories.

- [ ] **Step 8: Run the mandatory pre-commit gate and commit**

Run the four global CLI commands, then:

```powershell
git add CHANGELOG.md ROADMAP.md docs
git commit -m "docs: document browser compiler WASM spike"
```

## Final Verification Checklist

- [ ] `modelable-browser` is pure Python, deterministic, audited, and importable.
- [ ] Browser runtime fetches only same-origin assets.
- [ ] Validate, Format, and Generate JSON Schema work through protocol v1.
- [ ] Native and Pyodide results match committed snapshots.
- [ ] Size and timing budgets pass with measured values recorded.
- [ ] Validate CI routes browser-relevant changes to the browser job.
- [ ] MkDocs and the proof are composed into one Pages artifact.
- [ ] Existing CLI, LSP, VS Code, emitter, and registry tests remain green.
- [ ] Strict MkDocs succeeds.
- [ ] Doc/spec review passes without warnings.
- [ ] Completed plan and spec are archived.
