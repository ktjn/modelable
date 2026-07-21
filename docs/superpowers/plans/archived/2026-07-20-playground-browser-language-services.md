# Playground Browser Language Services Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add browser-native diagnostics, completion, hover, definition,
references, and atomic rename over the durable multi-file Playground workspace
while sharing semantics with the desktop language server.

**Architecture:** Extract transport-neutral Python DTOs, workspace state, and
language builders into `modelable.language`. Keep desktop federation and
`lsprotocol` conversion in thin LSP adapters, expose local-only language methods
through browser compiler protocol v2, and coordinate Monaco providers through
one revision-aware TypeScript controller. Batch A ships the shared foundation,
live diagnostics, completion, and hover; Batch B adds navigation, references,
and rename.

**Tech Stack:** Python 3.11+, dataclasses, Modelable parser/compiler workspace,
pygls/lsprotocol adapters, Pyodide worker RPC, TypeScript, React, Monaco Editor,
Vitest, pytest, and Playwright.

**Design:**
[Playground Browser Language Services — Design](../../specs/archived/2026-07-20-playground-browser-language-services-design.md)

## Global Constraints

- `modelable.language` must not import `pygls` or `lsprotocol`.
- Browser source processing remains local and same-origin; no registry,
  federation, or remote completion requests are allowed.
- Browser positions are zero-based UTF-16 positions.
- Background workspace synchronization is debounced by 300 ms and only one
  `workspace.open` request may be in flight.
- Current documents always advance; the semantic workspace advances only when
  the complete workspace parses.
- Definition and reference results omit locations whose current content hash
  differs from the last parseable snapshot.
- Rename requires the exact current parseable workspace revision and returns
  all edits or no edits.
- Rename supports local entities, aggregates, events, values, projections, and
  their fields; it excludes domains, semantic types, files, registry mirrors,
  and federated symbols.
- Hover Markdown is untrusted CommonMark with no raw HTML, command links, or
  images.
- Diagnostics and language results are derived state and are never persisted.
- Warm-worker median budgets are 100 ms for completion and hover, 150 ms for
  definition and references, and 250 ms for prepare-rename and rename.
- Before every commit, run from `cli/`, in order:
  `uv run ruff format .`, `uv run ruff check .`,
  `uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes`,
  and `uv run pytest --tb=short`.
- Follow red-green-refactor for every behavior change and keep Batch A
  independently releasable before starting Batch B.

---

## File and interface map

### Shared Python language core

- Create `cli/src/modelable/language/__init__.py` to export the public neutral
  language API.
- Create `cli/src/modelable/language/dto.py` for immutable positions, ranges,
  locations, completion items, hover content, prepared rename results, text
  edits, and workspace edits.
- Create `cli/src/modelable/language/positions.py` for explicit Python
  code-point/UTF-16 conversion and range validation.
- Create `cli/src/modelable/language/workspace.py` for current documents,
  revisioned synchronization, last-parseable semantics, diagnostics, and safe
  semantic-location filtering.
- Create `cli/src/modelable/language/completion.py` and
  `cli/src/modelable/language/hover.py` for Batch A semantics.
- Create `cli/src/modelable/language/definition.py`,
  `cli/src/modelable/language/references.py`, and
  `cli/src/modelable/language/rename.py` for Batch B semantics.

### Desktop adapters

- Modify `cli/src/modelable/lsp/workspace.py` so `LspWorkspaceIndex` owns a
  `LanguageWorkspace` while preserving filesystem scanning and federation
  behavior.
- Modify the existing feature modules under `cli/src/modelable/lsp/` into
  neutral-to-LSP adapters.
- Modify `cli/src/modelable/lsp/server.py` only where adapter signatures need
  document versions or typed rename failures.
- Keep `cli/src/modelable/lsp/federation.py` desktop-only and feed its values
  through the neutral `CompletionCatalog` protocol.

### Browser Python adapter

- Modify `cli/src/modelable/browser/dto.py`, `api.py`, `dispatch.py`, and
  `__init__.py` for protocol v2 DTOs, stateful dispatch, typed errors, and
  language methods.
- Add shared cross-file fixtures under
  `cli/tests/conformance/language/`.
- Add focused tests in `cli/tests/test_language_*.py`,
  `cli/tests/test_browser_api.py`, and
  `cli/tests/test_browser_conformance.py`.

### TypeScript and Monaco

- Modify `web/src/protocol.ts`, `client.ts`, `compiler.worker.ts`, and their
  tests for protocol v2 and all typed language DTOs.
- Create `web/src/language/BrowserLanguageServiceController.ts` and its test
  for debounce, coalescing, revision safety, and edit validation.
- Create `web/src/language/monaco-providers.ts` and its test for Monaco-only
  DTO conversion and provider lifecycle.
- Modify `web/src/editor/SourceModelRegistry.ts`,
  `web/src/editor/SourceEditor.tsx`, and `web/src/editor/types.ts` to expose
  stable models, view-state navigation, and atomic workspace edits.
- Modify `web/src/App.tsx`, `app-state.ts`, and their tests for live diagnostic
  state, controller lifecycle, retry, and workspace mutation.
- Extend `web/tests/conformance.spec.ts` and
  `web/tests/playground.spec.ts` for native/browser parity and browser
  acceptance.

---

## Batch A — shared core, synchronization, diagnostics, completion, hover

### Task 1: Neutral DTOs and UTF-16 boundaries

**Files:**

- Create: `cli/src/modelable/language/__init__.py`
- Create: `cli/src/modelable/language/dto.py`
- Create: `cli/src/modelable/language/positions.py`
- Create: `cli/tests/test_language_dto.py`
- Create: `cli/tests/test_language_positions.py`

**Interfaces:**

- Consumes: no earlier task.
- Produces:
  `LanguagePosition`, `LanguageRange`, `LanguageLocation`,
  `LanguageCompletion`, `LanguageHover`, `LanguagePreparedRename`,
  `LanguageTextEdit`, `LanguageWorkspaceEdit`, `CompletionCatalog`,
  `codepoint_to_utf16()`, and `utf16_to_codepoint()`.

- [ ] **Step 1: Write failing immutable DTO and ordering tests**

```python
def test_locations_sort_by_uri_then_range() -> None:
    later = LanguageLocation("file:///z.mdl", LanguageRange.at(2, 1, 2, 4))
    earlier = LanguageLocation("file:///a.mdl", LanguageRange.at(9, 0, 9, 1))
    assert sorted((later, earlier)) == [earlier, later]


def test_workspace_edit_rejects_overlapping_ranges() -> None:
    edits = (
        LanguageTextEdit("file:///a.mdl", LanguageRange.at(0, 0, 0, 4), "A", 2, "hash"),
        LanguageTextEdit("file:///a.mdl", LanguageRange.at(0, 3, 0, 5), "B", 2, "hash"),
    )
    with pytest.raises(ValueError, match="overlap"):
        LanguageWorkspaceEdit.from_edits(edits)
```

- [ ] **Step 2: Run the DTO tests and confirm the missing package failure**

Run:

```bash
cd cli
uv run pytest tests/test_language_dto.py -q
```

Expected: FAIL because `modelable.language.dto` does not exist.

- [ ] **Step 3: Implement the neutral immutable contract**

```python
CompletionKind = Literal[
    "keyword", "annotation", "module", "class", "property", "reference", "value"
]


@dataclass(frozen=True, order=True)
class LanguagePosition:
    line: int
    character: int


@dataclass(frozen=True, order=True)
class LanguageRange:
    start: LanguagePosition
    end: LanguagePosition

    @classmethod
    def at(cls, start_line: int, start_character: int, end_line: int, end_character: int) -> Self:
        value = cls(
            LanguagePosition(start_line, start_character),
            LanguagePosition(end_line, end_character),
        )
        value.validate()
        return value


@dataclass(frozen=True, order=True)
class LanguageLocation:
    uri: str
    range: LanguageRange


class CompletionCatalog(Protocol):
    def domain_names(self) -> tuple[str, ...]: ...
    def references(self) -> tuple[tuple[str, str], ...]: ...
    def model_versions(self) -> tuple[tuple[str, str, int], ...]: ...
    def field_names(self, domain: str, name: str, version: int) -> tuple[str, ...]: ...
```

Implement `LanguageWorkspaceEdit.from_edits()` to sort by URI/range, reject
invalid and overlapping ranges, and retain expected version/hash metadata.
Export only public neutral names from `modelable.language.__init__`.

- [ ] **Step 4: Write and run UTF-16 conversion tests**

```python
@pytest.mark.parametrize(
    ("text", "codepoint", "utf16"),
    [("customer", 4, 4), ("a😀b", 2, 3), ("😀name", 1, 2)],
)
def test_codepoint_utf16_round_trip(text: str, codepoint: int, utf16: int) -> None:
    assert codepoint_to_utf16(text, codepoint) == utf16
    assert utf16_to_codepoint(text, utf16) == codepoint


def test_utf16_rejects_half_surrogate_position() -> None:
    with pytest.raises(ValueError, match="surrogate"):
        utf16_to_codepoint("😀", 1)
```

Run:

```bash
cd cli
uv run pytest tests/test_language_dto.py tests/test_language_positions.py -q
```

Expected: PASS.

- [ ] **Step 5: Run the mandatory pre-commit gate and commit**

Run the four commands from **Global Constraints**, then:

```bash
git add cli/src/modelable/language cli/tests/test_language_dto.py cli/tests/test_language_positions.py
git commit -m "refactor: add neutral language service contract"
```

### Task 2: Revisioned language workspace with last-parseable semantics

**Files:**

- Create: `cli/src/modelable/language/workspace.py`
- Create: `cli/tests/test_language_workspace.py`
- Modify: `cli/src/modelable/lsp/workspace.py`
- Modify: `cli/tests/test_lsp_workspace.py`

**Interfaces:**

- Consumes: Task 1 neutral ranges and positions.
- Produces:
  `LanguageDocument.from_text(uri, text, version)`,
  `LanguageWorkspace.synchronize(revision, documents)`,
  `LanguageSynchronization`, `current_document(uri)`,
  `semantic_workspace()`, `is_semantically_current()`, and
  `is_location_current(location)`.

- [ ] **Step 1: Write failing snapshot transition tests**

```python
def test_invalid_sync_advances_documents_but_keeps_last_parseable_workspace() -> None:
    state = LanguageWorkspace()
    valid = LanguageDocument.from_text("file:///a.mdl", VALID_MODEL, 1)
    first = state.synchronize(1, (valid,))
    invalid = LanguageDocument.from_text("file:///a.mdl", "domain broken {", 2)
    second = state.synchronize(2, (invalid,))

    assert first.revision == 1
    assert second.revision == 2
    assert second.diagnostics[0].severity == "error"
    assert state.current_document("file:///a.mdl") == invalid
    assert state.semantic_revision == 1
    assert state.workspace is not None
    assert not state.is_semantically_current()
```

Also test deterministic URI ordering, duplicate URI rejection, non-positive
versions, non-increasing revisions, source hashes during parse failure, and
semantic diagnostics that still advance the semantic snapshot.

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
cd cli
uv run pytest tests/test_language_workspace.py -q
```

Expected: FAIL because `LanguageWorkspace` is not implemented.

- [ ] **Step 3: Implement synchronization and safe-location filtering**

```python
@dataclass(frozen=True)
class LanguageDocument:
    uri: str
    text: str
    version: int
    content_hash: str

    @classmethod
    def from_text(cls, uri: str, text: str, version: int) -> Self:
        return cls(uri, text, version, sha256(text.encode("utf-8")).hexdigest())


@dataclass
class LanguageWorkspace:
    revision: int = 0
    documents: dict[str, LanguageDocument] = field(default_factory=dict)
    semantic_revision: int | None = None
    semantic_hashes: dict[str, str] = field(default_factory=dict)
    workspace: Workspace | None = None

    def synchronize(
        self, revision: int, documents: tuple[LanguageDocument, ...]
    ) -> LanguageSynchronization:
        self._validate_snapshot(revision, documents)
        self.revision = revision
        self.documents = {document.uri: document for document in documents}
        try:
            workspace = load_workspace_from_sources(self._sources())
        except ParseError:
            return self._parse_failure()
        self.workspace = workspace
        self.semantic_revision = revision
        self.semantic_hashes = {
            document.uri: document.content_hash for document in documents
        }
        return LanguageSynchronization(
            revision=revision,
            diagnostics=tuple(workspace.errors),
            source_hashes=self.current_hashes(),
        )
```

Use the existing per-document parse isolation from
`modelable.browser.api._load_workspace()` so parse diagnostics retain the
correct URI. `is_location_current()` must compare the current document hash
with `semantic_hashes[uri]`.

- [ ] **Step 4: Adapt `LspWorkspaceIndex` without changing desktop behavior**

Keep `_user_opened`, file scanning, close/reload, and the public `documents`
and `workspace` properties. Assign monotonically increasing internal revisions
and synchronize the neutral workspace after each mutation:

```python
@dataclass
class LspWorkspaceIndex:
    language: LanguageWorkspace = field(default_factory=LanguageWorkspace)
    _revision: int = 0

    @property
    def documents(self) -> dict[str, WorkspaceDocumentSource]:
        return {
            uri: WorkspaceDocumentSource(path=uri_to_path(uri), uri=uri, text=document.text)
            for uri, document in self.language.documents.items()
        }

    @property
    def workspace(self) -> Workspace | None:
        return self.language.workspace
```

Preserve last-parseable behavior during LSP edits and keep existing filesystem
fallback semantics. Track a positive per-URI document version internally:
increment it for user changes and background reloads, preserve it for no-op
text updates, and pass it to `LanguageDocument.from_text()`.

- [ ] **Step 5: Run neutral and existing LSP workspace tests**

Run:

```bash
cd cli
uv run pytest tests/test_language_workspace.py tests/test_lsp_workspace.py tests/test_lsp_diagnostics.py -q
```

Expected: PASS.

- [ ] **Step 6: Run the mandatory pre-commit gate and commit**

```bash
git add cli/src/modelable/language/workspace.py cli/src/modelable/lsp/workspace.py cli/tests/test_language_workspace.py cli/tests/test_lsp_workspace.py
git commit -m "refactor: share revisioned language workspace"
```

### Task 3: Shared completion semantics and desktop adapter

**Files:**

- Create: `cli/src/modelable/language/completion.py`
- Create: `cli/tests/test_language_completion.py`
- Modify: `cli/src/modelable/lsp/completion.py`
- Modify: `cli/tests/test_lsp_completion.py`
- Modify: `cli/tests/test_lsp_completion_mirrors.py`
- Modify: `cli/src/modelable/lsp/server.py`

**Interfaces:**

- Consumes: `LanguageWorkspace`, neutral completion DTOs, and
  `CompletionCatalog`.
- Produces:
  `complete(workspace, uri, position, catalog=None) -> tuple[LanguageCompletion, ...]`
  and `to_lsp_completion_list()`.

- [ ] **Step 1: Add failing neutral parity and invalid-text tests**

Move local completion cases from `test_lsp_completion.py` into shared fixture
tests and assert neutral values:

```python
def test_completion_uses_current_prefix_with_last_parseable_semantics() -> None:
    state = parsed_language_workspace()
    state.synchronize(
        2,
        replace_document(state, "file:///projection.mdl", "  customer_na"),
    )
    result = complete(state, "file:///projection.mdl", LanguagePosition(5, 13))
    assert [item.label for item in result] == ["customer_name"]
    assert result[0].kind == "property"
    assert result[0].replacement == LanguageRange.at(5, 2, 5, 13)
```

Cover keywords, annotations, local domains, declarations, versions, aliases,
model fields, projection fields, deterministic ordering, empty results,
invalid URI/position, and no remote candidates without a catalog.

- [ ] **Step 2: Run shared completion tests and confirm failure**

```bash
cd cli
uv run pytest tests/test_language_completion.py -q
```

Expected: FAIL because `modelable.language.completion.complete` is missing.

- [ ] **Step 3: Move semantic completion logic into the neutral builder**

Port the context patterns and candidate builders from
`modelable.lsp.completion`. Convert code-point match spans to UTF-16 replacement
ranges at the boundary and map kinds to the closed neutral string vocabulary:

```python
def complete(
    workspace: LanguageWorkspace,
    uri: str,
    position: LanguagePosition,
    catalog: CompletionCatalog | None = None,
) -> tuple[LanguageCompletion, ...]:
    document = workspace.current_document(uri)
    semantic = workspace.semantic_workspace()
    if document is None or semantic is None:
        return ()
    cursor = utf16_to_codepoint(document.line(position.line), position.character)
    candidates = _candidates(document.text, semantic, position.line, cursor, catalog)
    return tuple(
        LanguageCompletion(
            label=candidate.label,
            kind=candidate.kind,
            sort_text=f"{index:04d}",
            replacement=_replacement_range(document, position.line, candidate.prefix),
        )
        for index, candidate in enumerate(_dedupe(candidates))
    )
```

- [ ] **Step 4: Reduce the LSP module to an adapter**

Implement a desktop-only catalog backed by `modelable.lsp.federation`, call
`complete()`, and convert neutral completion kinds/ranges explicitly to
`lsprotocol.types`. Do not expose mirrors to the browser core by default.

- [ ] **Step 5: Run neutral and desktop completion suites**

```bash
cd cli
uv run pytest tests/test_language_completion.py tests/test_lsp_completion.py tests/test_lsp_completion_mirrors.py tests/test_lsp_integration.py -q
```

Expected: PASS with unchanged desktop candidate ordering and mirror behavior.

- [ ] **Step 6: Run the mandatory pre-commit gate and commit**

```bash
git add cli/src/modelable/language/completion.py cli/src/modelable/lsp/completion.py cli/src/modelable/lsp/server.py cli/tests/test_language_completion.py cli/tests/test_lsp_completion.py cli/tests/test_lsp_completion_mirrors.py
git commit -m "refactor: share completion semantics"
```

### Task 4: Shared hover semantics and desktop adapter

**Files:**

- Create: `cli/src/modelable/language/hover.py`
- Create: `cli/tests/test_language_hover.py`
- Modify: `cli/src/modelable/lsp/hover.py`
- Modify: `cli/tests/test_lsp_hover.py`
- Modify: `cli/src/modelable/lsp/server.py`

**Interfaces:**

- Consumes: `LanguageWorkspace`, `LanguagePosition`, and `LanguageHover`.
- Produces:
  `hover(workspace, uri, position) -> LanguageHover | None` and
  `to_lsp_hover()`.

- [ ] **Step 1: Add failing neutral hover and sanitization tests**

```python
def test_hover_uses_last_semantics_for_current_resolvable_text() -> None:
    state = parsed_language_workspace()
    state.synchronize(2, invalid_projection_documents())
    result = hover(state, "file:///projection.mdl", LanguagePosition(4, 10))
    assert result is not None
    assert "`sales.Customer@1`" in result.markdown


def test_hover_markdown_has_no_active_content() -> None:
    result = hover(workspace_with_metadata("<img src=x>"), URI, POSITION)
    assert result is not None
    assert "<" not in result.markdown
    assert "](" not in result.markdown
```

Cover declaration identity, field type/optionality, key/PII/classification/
deprecation metadata, projection mapping, unknown URI/position, and UTF-16
ranges.

- [ ] **Step 2: Run the neutral hover tests and verify failure**

```bash
cd cli
uv run pytest tests/test_language_hover.py -q
```

Expected: FAIL because `modelable.language.hover.hover` is missing.

- [ ] **Step 3: Port hover resolution into the neutral core**

Reuse `build_model_summary`, `build_projection_summary`, and local registry
resolution while producing only `LanguageHover(markdown, range)`. Escape raw
HTML characters and never emit Markdown links or images:

```python
def _safe_markdown(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("](", r"]\(")
    )
```

Use current document text to locate the cursor token and the last parseable
workspace to resolve its semantics.

- [ ] **Step 4: Replace LSP hover building with explicit conversion**

```python
def build_hover(index: LspWorkspaceIndex, uri: str, line: int, character: int) -> types.Hover | None:
    result = language_hover(index.language, uri, LanguagePosition(line, character))
    if result is None:
        return None
    return types.Hover(
        contents=types.MarkupContent(kind=types.MarkupKind.Markdown, value=result.markdown),
        range=to_lsp_range(result.range) if result.range is not None else None,
    )
```

- [ ] **Step 5: Run neutral and desktop hover suites**

```bash
cd cli
uv run pytest tests/test_language_hover.py tests/test_lsp_hover.py tests/test_lsp_integration.py -q
```

Expected: PASS.

- [ ] **Step 6: Run the mandatory pre-commit gate and commit**

```bash
git add cli/src/modelable/language/hover.py cli/src/modelable/lsp/hover.py cli/src/modelable/lsp/server.py cli/tests/test_language_hover.py cli/tests/test_lsp_hover.py
git commit -m "refactor: share hover semantics"
```

### Task 5: Browser protocol v2 and Batch A Python methods

**Files:**

- Modify: `cli/src/modelable/browser/dto.py`
- Modify: `cli/src/modelable/browser/api.py`
- Modify: `cli/src/modelable/browser/dispatch.py`
- Modify: `cli/src/modelable/browser/__init__.py`
- Modify: `cli/tests/test_browser_api.py`
- Modify: `cli/tests/test_browser_packaging.py`
- Create: `cli/tests/conformance/language/workspace-valid.json`
- Create: `cli/tests/conformance/language/workspace-invalid-current.json`

**Interfaces:**

- Consumes: Tasks 1–4 neutral language API.
- Produces:
  stateful module dispatch, revisioned `BrowserWorkspaceResult`,
  `language.completion`, `language.hover`, and typed browser language errors.

- [ ] **Step 1: Add failing stateful dispatch and exact-schema tests**

```python
def test_dispatch_syncs_revision_then_completes() -> None:
    opened = dispatch("workspace.open", {"workspaceRevision": 7, "sources": SOURCES})
    result = dispatch(
        "language.completion",
        {"workspaceRevision": 7, "uri": URI, "line": 3, "character": 8},
    )
    assert opened["result"]["workspace_revision"] == 7
    assert result["result"]["items"][0]["label"] == "customer_id"


def test_language_request_rejects_stale_revision_without_source_echo() -> None:
    result = dispatch(
        "language.hover",
        {"workspaceRevision": 6, "uri": URI, "line": 1, "character": 2},
    )
    assert result["error"]["code"] == "STALE_WORKSPACE"
    assert SOURCE_TEXT not in json.dumps(result)
```

Also test missing/unknown fields, booleans as integers, invalid URI/position,
invalid protocol-v1 method usage, last-parseable completion/hover, deterministic
serialization, and no source/symbol/result text in error messages.

- [ ] **Step 2: Run focused browser API tests and verify failure**

```bash
cd cli
uv run pytest tests/test_browser_api.py -q
```

Expected: FAIL because the v2 methods and stateful workspace are absent.

- [ ] **Step 3: Add v2 DTOs and stateful compiler methods**

```python
@dataclass(frozen=True)
class BrowserLanguagePosition:
    workspace_revision: int
    uri: str
    line: int
    character: int


class BrowserCompiler:
    def __init__(self) -> None:
        self.language = LanguageWorkspace()

    def open_workspace(
        self, workspace_revision: int, sources: tuple[BrowserSource, ...]
    ) -> BrowserWorkspaceResult:
        sync = self.language.synchronize(
            workspace_revision,
            tuple(LanguageDocument.from_text(s.uri, s.text, s.version) for s in sources),
        )
        return BrowserWorkspaceResult(
            workspace_revision=sync.revision,
            diagnostics=tuple(_browser_diagnostic(item) for item in sync.diagnostics),
            source_hashes=sync.source_hashes,
        )
```

Make one module-level `BrowserCompiler` instance in `dispatch.py` so successive
Pyodide calls share language state. Add a test-only reset helper used by pytest,
not a browser protocol method.

- [ ] **Step 4: Add completion and hover dispatch**

Validate exact payload keys and return deterministic `asdict()` results:

```python
if method == "language.completion":
    request = _language_position(payload)
    return compiler.completion(request)
if method == "language.hover":
    request = _language_position(payload)
    return compiler.hover(request)
```

Map stale state to `STALE_WORKSPACE`, absent semantics to
`LANGUAGE_UNAVAILABLE`, and invalid URI/position to `INVALID_POSITION`.

- [ ] **Step 5: Run browser API, packaging, and conformance tests**

```bash
cd cli
uv run pytest tests/test_browser_api.py tests/test_browser_packaging.py tests/test_browser_conformance.py -q
```

Expected: PASS and browser packaging imports no `pygls` or `lsprotocol`.

- [ ] **Step 6: Run the mandatory pre-commit gate and commit**

```bash
git add cli/src/modelable/browser cli/tests/test_browser_api.py cli/tests/test_browser_packaging.py cli/tests/test_browser_conformance.py cli/tests/conformance/language
git commit -m "feat: add browser language protocol v2 foundation"
```

### Task 6: TypeScript protocol v2, client, and synchronization controller

**Files:**

- Modify: `web/src/protocol.ts`
- Modify: `web/src/protocol.test.ts`
- Modify: `web/src/client.ts`
- Modify: `web/src/client.test.ts`
- Modify: `web/src/compiler.worker.ts`
- Modify: `web/src/worker-support.ts`
- Modify: `web/src/worker-support.test.ts`
- Create: `web/src/language/BrowserLanguageServiceController.ts`
- Create: `web/src/language/BrowserLanguageServiceController.test.ts`

**Interfaces:**

- Consumes: Task 5 browser protocol.
- Produces:
  `BROWSER_COMPILER_PROTOCOL_VERSION = 2`,
  typed client methods, and
  `BrowserLanguageServiceController.synchronize()`,
  `.completion()`, `.hover()`, `.retry()`, and `.dispose()`.

- [ ] **Step 1: Write failing strict protocol-v2 decoder tests**

```ts
expect(BROWSER_COMPILER_PROTOCOL_VERSION).toBe(2);
expect(
  isBrowserWorkspaceResult({
    workspace_revision: 4,
    diagnostics: [],
    source_hashes: { 'file:///a.mdl': 'abc' },
  }),
).toBe(true);
expect(isBrowserCompletionResult({ items: [{ label: 'x', extra: true }] }))
  .toBe(false);
```

Define exact validators for every nested range, location, completion, hover,
version, hash, and error object. Unknown fields must fail decoding.

- [ ] **Step 2: Run protocol/client tests and verify failure**

```bash
cd web
npm test -- --run src/protocol.test.ts src/client.test.ts
```

Expected: FAIL on protocol version and missing language methods.

- [ ] **Step 3: Implement protocol types and typed client methods**

```ts
export interface BrowserLanguagePosition {
  workspaceRevision: number;
  uri: string;
  line: number;
  character: number;
}

completion(position: BrowserLanguagePosition): Promise<BrowserCompletionResult> {
  return this.initializedRequest(
    'language.completion',
    languagePositionPayload(position),
    isBrowserCompletionResult,
  );
}
```

Make `request()` accept a result guard and transition to terminal failure on an
invalid success payload. Extend error codes with `STALE_WORKSPACE`,
`LANGUAGE_UNAVAILABLE`, `INVALID_POSITION`, `INVALID_RENAME`, and `STALE_EDIT`.

- [ ] **Step 4: Write failing controller scheduling tests with fake timers**

```ts
test('debounces for 300ms and coalesces to the newest workspace', async () => {
  const controller = createController(fakeClient);
  controller.observe(workspaceAt(2));
  controller.observe(workspaceAt(3));
  await vi.advanceTimersByTimeAsync(299);
  expect(fakeClient.openWorkspace).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(1);
  expect(fakeClient.openWorkspace).toHaveBeenCalledTimes(1);
  expect(fakeClient.openWorkspace).toHaveBeenCalledWith(3, sourcesAt(3));
});
```

Also test one sync in flight, forced provider synchronization, stale result
suppression, silent stale errors, retry, terminal error reporting, and dispose.

- [ ] **Step 5: Implement the controller state machine**

```ts
export class BrowserLanguageServiceController {
  private observed: PlaygroundWorkspace | undefined;
  private acceptedRevision = 0;
  private inFlight: Promise<void> | undefined;
  private timer: ReturnType<typeof setTimeout> | undefined;

  observe(workspace: PlaygroundWorkspace): void {
    this.observed = workspace;
    clearTimeout(this.timer);
    this.timer = setTimeout(() => void this.synchronize(workspace.revision), 300);
  }

  async completion(
    captured: PlaygroundWorkspace,
    uri: string,
    position: BrowserLanguagePositionValue,
  ): Promise<BrowserCompletionResult | undefined> {
    await this.ensureRevision(captured);
    const result = await this.client.completion(toRequest(captured, uri, position));
    return this.observed?.revision === captured.revision ? result : undefined;
  }
}
```

`ensureRevision()` must loop after an in-flight sync when its accepted revision
does not equal the captured revision. Synchronization callbacks publish
diagnostics only for the exact observed revision.

- [ ] **Step 6: Run TypeScript controller and worker tests**

```bash
cd web
npm test -- --run src/protocol.test.ts src/client.test.ts src/worker-support.test.ts src/language/BrowserLanguageServiceController.test.ts
npm run typecheck
```

Expected: PASS.

- [ ] **Step 7: Run the Python pre-commit gate plus web test/build and commit**

Run the four mandatory commands from `cli/`, then:

```bash
cd ../web
npm test
npm run build
git add src/protocol.ts src/protocol.test.ts src/client.ts src/client.test.ts src/compiler.worker.ts src/worker-support.ts src/worker-support.test.ts src/language
git commit -m "feat: coordinate browser language synchronization"
```

### Task 7: Monaco completion, hover, and live diagnostics

**Files:**

- Create: `web/src/language/monaco-providers.ts`
- Create: `web/src/language/monaco-providers.test.ts`
- Modify: `web/src/editor/SourceEditor.tsx`
- Modify: `web/src/editor/SourceEditor.test.tsx`
- Modify: `web/src/editor/types.ts`
- Modify: `web/src/App.tsx`
- Modify: `web/src/App.test.tsx`
- Modify: `web/src/app-state.ts`
- Modify: `web/src/app-state.test.ts`
- Modify: `web/tests/conformance.spec.ts`
- Modify: `web/tests/playground.spec.ts`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/playground-design.md`

**Interfaces:**

- Consumes: Task 6 controller and Batch A DTOs.
- Produces:
  `registerModelableProviders(monaco, controller, getWorkspace)`,
  debounced live diagnostics, and Batch A browser acceptance.

- [ ] **Step 1: Write failing provider conversion/lifecycle tests**

```ts
test('completion provider forwards the captured workspace revision', async () => {
  const registration = registerModelableProviders(
    fakeMonaco,
    controller,
    () => workspaceAt(8),
  );
  const result = await completionProvider.provideCompletionItems(
    model('file:///a.mdl'),
    { lineNumber: 2, column: 3 },
    completionContext,
    cancellationToken,
  );
  expect(controller.completion).toHaveBeenCalledWith(
    workspaceAt(8),
    'file:///a.mdl',
    { line: 1, character: 2 },
  );
  expect(result.suggestions[0].range).toEqual(monacoRange(2, 1, 2, 3));
  registration.dispose();
  expect(providerDisposables.every((item) => item.dispose.mock.calls.length === 1)).toBe(true);
});
```

Test completion kind mapping, `sortText`, replacement ranges, untrusted hover
Markdown, cancellation, missing/stale results, and provider disposal.

- [ ] **Step 2: Run provider tests and verify failure**

```bash
cd web
npm test -- --run src/language/monaco-providers.test.ts
```

Expected: FAIL because provider registration does not exist.

- [ ] **Step 3: Implement Batch A Monaco providers**

```ts
const completion = monaco.languages.registerCompletionItemProvider(
  'modelable',
  {
    provideCompletionItems(model, position, _context, token) {
      const captured = getWorkspace();
      return controller
        .completion(captured, model.uri.toString(), fromMonacoPosition(position))
        .then((result) =>
          token.isCancellationRequested || result === undefined
            ? { suggestions: [] }
            : { suggestions: result.items.map(toMonacoCompletion) },
        );
    },
  },
);
```

Render hover with `isTrusted: false` and `supportHtml: false`. Provider code
must only convert DTOs; it must not resolve Modelable symbols.

- [ ] **Step 4: Write failing App live-diagnostic tests**

Use fake timers to prove editing schedules a 300 ms sync, a provider can force
it earlier, only exact-revision diagnostics reach `app-state`, persistence does
not receive diagnostics, language failure exposes retry, and explicit Validate
still works on the synchronized workspace.

- [ ] **Step 5: Wire controller, editor providers, and state**

Add controller creation/disposal beside `BrowserCompilerClient`. Pass the
controller and a live workspace getter to `SourceEditor`. Keep the controller
observing immutable workspace snapshots:

```tsx
useEffect(() => {
  languageController.observe(workspace);
}, [languageController, workspace]);

<SourceEditor
  files={workspace.files}
  activeFile={workspace.activeFile}
  markersByUri={markersByUri}
  languageController={languageController}
  getWorkspace={() => workspaceRef.current}
  onContentChange={updateSource}
/>
```

Use a polite live region for synchronization/failure state without announcing
provider cancellation.

- [ ] **Step 6: Add cross-file Batch A browser acceptance**

In Playwright, create/import two files, edit a local syntax error, verify live
diagnostics appear without Validate, invoke completion and hover through
Monaco keyboard commands, and assert there are no off-origin source requests,
page overflow, or accessibility violations.

- [ ] **Step 7: Document the independently shipped Batch A boundary**

Update user-facing docs for live diagnostics, completion, hover, protocol v2,
and last-parseable behavior. Keep Phase 3b active and do not archive the spec
or plan.

- [ ] **Step 8: Run doc/spec review**

Run all four `doc-review` phases over the changed README, changelog,
architecture, spec, and plan references. Expected: PASS; put any warnings in
the Batch A PR body.

- [ ] **Step 9: Run Batch A release gates and commit**

```bash
cd cli
uv run pytest tests/test_language_dto.py tests/test_language_positions.py tests/test_language_workspace.py tests/test_language_completion.py tests/test_language_hover.py tests/test_browser_api.py tests/test_browser_conformance.py -q
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
cd ../web
npm test
npm run build
npx playwright test tests/conformance.spec.ts tests/playground.spec.ts
cd ..
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
git add README.md CHANGELOG.md docs/playground-design.md web/src web/tests
git commit -m "feat: add playground completion hover and live diagnostics"
```

Expected: all gates pass; this is the Batch A review/merge checkpoint.

---

## Batch B — definition, references, rename

### Task 8: Shared definition and reference semantics

**Files:**

- Create: `cli/src/modelable/language/definition.py`
- Create: `cli/src/modelable/language/references.py`
- Create: `cli/tests/test_language_definition.py`
- Create: `cli/tests/test_language_references.py`
- Modify: `cli/src/modelable/lsp/definition.py`
- Modify: `cli/src/modelable/lsp/references.py`
- Modify: `cli/src/modelable/lsp/highlight.py`
- Modify: `cli/tests/test_lsp_definition.py`
- Modify: `cli/tests/test_lsp_references.py`
- Modify: `cli/tests/test_lsp_highlight.py`
- Modify: `cli/src/modelable/lsp/server.py`

**Interfaces:**

- Consumes: Batch A language workspace and neutral locations.
- Produces:
  `definition(workspace, uri, position) -> LanguageLocation | None`,
  `references(workspace, uri, position, include_declaration) -> tuple[LanguageLocation, ...]`,
  and explicit LSP location adapters.

- [ ] **Step 1: Write failing neutral cross-file and stale-location tests**

```python
def test_definition_omits_changed_semantic_target() -> None:
    state = parsed_cross_file_workspace()
    state.synchronize(2, documents_with_invalid_changed_target())
    result = definition(state, SOURCE_URI, source_reference_position())
    assert result is None


def test_references_are_sorted_and_exclude_changed_files() -> None:
    state = workspace_with_one_stale_reference_file()
    result = references(state, DECL_URI, declaration_position(), True)
    assert result == tuple(sorted(result))
    assert STALE_URI not in {location.uri for location in result}
```

Cover versioned/unversioned declarations, model/projection fields, projection
aliases, include-declaration, unknown symbols, UTF-16, and local-only URIs.

- [ ] **Step 2: Run neutral tests and verify failure**

```bash
cd cli
uv run pytest tests/test_language_definition.py tests/test_language_references.py -q
```

Expected: FAIL because the neutral builders do not exist.

- [ ] **Step 3: Port definition and references into neutral modules**

Move existing resolution helpers while returning neutral locations. Filter
every candidate at the final boundary:

```python
def _safe_locations(
    workspace: LanguageWorkspace,
    locations: Iterable[LanguageLocation],
) -> tuple[LanguageLocation, ...]:
    return tuple(
        sorted(
            {
                location
                for location in locations
                if workspace.is_location_current(location)
            }
        )
    )
```

Do not resolve a location that is outside `LanguageWorkspace.documents`.

- [ ] **Step 4: Convert desktop modules and highlights to adapters**

Map neutral positions/locations to `lsprotocol` types. Preserve
`definition_location_for_ref()` for current callers by delegating through a
small neutral workspace view. Keep document highlights derived from the
neutral reference result.

- [ ] **Step 5: Run shared and desktop navigation suites**

```bash
cd cli
uv run pytest tests/test_language_definition.py tests/test_language_references.py tests/test_lsp_definition.py tests/test_lsp_references.py tests/test_lsp_highlight.py tests/test_lsp_integration.py -q
```

Expected: PASS.

- [ ] **Step 6: Run the mandatory pre-commit gate and commit**

```bash
git add cli/src/modelable/language/definition.py cli/src/modelable/language/references.py cli/src/modelable/lsp/definition.py cli/src/modelable/lsp/references.py cli/src/modelable/lsp/highlight.py cli/src/modelable/lsp/server.py cli/tests/test_language_definition.py cli/tests/test_language_references.py cli/tests/test_lsp_definition.py cli/tests/test_lsp_references.py cli/tests/test_lsp_highlight.py
git commit -m "refactor: share navigation and reference semantics"
```

### Task 9: Shared validated rename semantics

**Files:**

- Create: `cli/src/modelable/language/rename.py`
- Create: `cli/tests/test_language_rename.py`
- Modify: `cli/src/modelable/lsp/rename.py`
- Modify: `cli/src/modelable/lsp/server.py`
- Modify: `cli/tests/test_lsp_rename.py`

**Interfaces:**

- Consumes: language workspace, neutral ranges, and safe local locations.
- Produces:
  `prepare_rename(workspace, uri, position) -> LanguagePreparedRename | None`,
  `rename(workspace, uri, position, new_name) -> LanguageWorkspaceEdit`, and
  `InvalidRenameError`.

- [ ] **Step 1: Write failing rename safety tests**

```python
def test_rename_requires_exact_parseable_revision() -> None:
    state = workspace_with_invalid_current_text()
    with pytest.raises(InvalidRenameError, match="current workspace"):
        rename(state, URI, POSITION, "RenamedCustomer")


@pytest.mark.parametrize("new_name", ["", "1Customer", "Customer-name"])
def test_rename_rejects_invalid_identifier(new_name: str) -> None:
    with pytest.raises(InvalidRenameError, match="identifier"):
        rename(parsed_workspace(), URI, POSITION, new_name)


def test_rename_returns_all_cross_file_edits_with_versions_and_hashes() -> None:
    result = rename(parsed_cross_file_workspace(), URI, POSITION, "Client")
    assert {edit.uri for edit in result.edits} == {DECL_URI, PROJECTION_URI}
    assert all(edit.expected_version > 0 and edit.expected_hash for edit in result.edits)
```

Also test model/projection and field collisions, unsupported domain/semantic
type targets, declaration/reference completeness, deterministic descending edit
order per file, and overlap rejection.

- [ ] **Step 2: Run neutral rename tests and verify failure**

```bash
cd cli
uv run pytest tests/test_language_rename.py -q
```

Expected: FAIL because neutral rename is absent.

- [ ] **Step 3: Port target resolution and add validation**

```python
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def rename(
    workspace: LanguageWorkspace,
    uri: str,
    position: LanguagePosition,
    new_name: str,
) -> LanguageWorkspaceEdit:
    if not workspace.is_semantically_current():
        raise InvalidRenameError("Rename requires the current workspace to parse")
    if _IDENTIFIER.fullmatch(new_name) is None:
        raise InvalidRenameError("New name must be a valid Modelable identifier")
    target = _target_at(workspace, uri, position)
    _reject_unsupported_or_collision(workspace, target, new_name)
    return LanguageWorkspaceEdit.from_edits(
        _all_target_edits(workspace, target, new_name)
    )
```

Populate each edit's expected version/hash from the current document. Return no
partial result on any validation failure.

- [ ] **Step 4: Adapt desktop rename without weakening browser validation**

Convert `LanguagePreparedRename` to `types.Range` and
`LanguageWorkspaceEdit` to `types.WorkspaceEdit`. Desktop unsupported targets
continue returning `None`; the browser adapter in Task 10 will expose typed
errors.

- [ ] **Step 5: Run neutral and desktop rename suites**

```bash
cd cli
uv run pytest tests/test_language_rename.py tests/test_lsp_rename.py tests/test_lsp_integration.py -q
```

Expected: PASS.

- [ ] **Step 6: Run the mandatory pre-commit gate and commit**

```bash
git add cli/src/modelable/language/rename.py cli/src/modelable/lsp/rename.py cli/src/modelable/lsp/server.py cli/tests/test_language_rename.py cli/tests/test_lsp_rename.py
git commit -m "refactor: share validated rename semantics"
```

### Task 10: Browser Batch B methods and conformance

**Files:**

- Modify: `cli/src/modelable/browser/dto.py`
- Modify: `cli/src/modelable/browser/api.py`
- Modify: `cli/src/modelable/browser/dispatch.py`
- Modify: `cli/tests/test_browser_api.py`
- Modify: `cli/tests/test_browser_conformance.py`
- Modify: `cli/tests/conformance/language/workspace-valid.json`

**Interfaces:**

- Consumes: Tasks 8–9 neutral navigation and rename APIs.
- Produces:
  `language.definition`, `language.references`,
  `language.prepareRename`, and `language.rename`.

- [ ] **Step 1: Add failing browser method tests**

```python
def test_browser_rename_serializes_atomic_versioned_edits() -> None:
    open_revision(9, CROSS_FILE_SOURCES)
    result = dispatch(
        "language.rename",
        {
            "workspaceRevision": 9,
            "uri": DECL_URI,
            "line": 1,
            "character": 8,
            "newName": "Client",
        },
    )
    assert result["ok"] is True
    assert [edit["uri"] for edit in result["result"]["edits"]] == sorted(
        {DECL_URI, PROJECTION_URI}
    )


def test_browser_rename_rejects_stale_semantic_snapshot() -> None:
    open_revision(10, INVALID_CURRENT_SOURCES)
    result = dispatch("language.rename", rename_payload(10, "Client"))
    assert result["error"]["code"] == "INVALID_RENAME"
```

Cover all four methods, exact fields, include-declaration boolean validation,
safe URI filtering, `INVALID_RENAME`, `STALE_EDIT`, deterministic JSON, and
sanitized errors.

- [ ] **Step 2: Run browser API tests and verify failure**

```bash
cd cli
uv run pytest tests/test_browser_api.py -q
```

Expected: FAIL because Batch B dispatch is missing.

- [ ] **Step 3: Add DTO conversion and dispatch**

```python
if method == "language.references":
    request = _language_position(payload, extra_fields={"includeDeclaration"})
    return compiler.references(request, payload["includeDeclaration"])
if method == "language.rename":
    request = _language_position(payload, extra_fields={"newName"})
    return compiler.rename(request, payload["newName"])
```

Catch only expected neutral language exceptions and map them to typed
non-terminal errors. Unexpected exceptions remain `COMPILER_FAILED`.

- [ ] **Step 4: Extend native/browser cross-file conformance**

Run identical fixture requests against the neutral core and serialized browser
API. Normalize only adapter-specific envelope fields; assert exact labels,
Markdown, UTF-16 ranges, locations, versions, hashes, and edit text.

- [ ] **Step 5: Run Python browser and conformance suites**

```bash
cd cli
uv run pytest tests/test_browser_api.py tests/test_browser_conformance.py tests/test_language_definition.py tests/test_language_references.py tests/test_language_rename.py -q
```

Expected: PASS.

- [ ] **Step 6: Run the mandatory pre-commit gate and commit**

```bash
git add cli/src/modelable/browser cli/tests/test_browser_api.py cli/tests/test_browser_conformance.py cli/tests/conformance/language
git commit -m "feat: expose browser navigation and rename"
```

### Task 11: Monaco navigation, references, and atomic rename

**Files:**

- Modify: `web/src/protocol.ts`
- Modify: `web/src/protocol.test.ts`
- Modify: `web/src/client.ts`
- Modify: `web/src/client.test.ts`
- Modify: `web/src/language/BrowserLanguageServiceController.ts`
- Modify: `web/src/language/BrowserLanguageServiceController.test.ts`
- Modify: `web/src/language/monaco-providers.ts`
- Modify: `web/src/language/monaco-providers.test.ts`
- Modify: `web/src/editor/SourceModelRegistry.ts`
- Modify: `web/src/editor/SourceModelRegistry.test.ts`
- Modify: `web/src/editor/SourceEditor.tsx`
- Modify: `web/src/editor/SourceEditor.test.tsx`
- Modify: `web/src/editor/types.ts`
- Modify: `web/src/App.tsx`
- Modify: `web/src/App.test.tsx`
- Modify: `web/src/workspace.ts`
- Modify: `web/src/workspace.test.ts`

**Interfaces:**

- Consumes: Task 10 browser methods and the Batch A controller/providers.
- Produces: Monaco definition/reference/rename providers, versioned Monaco
  `WorkspaceEdit` conversion, editor-opener navigation, and same-tick
  multi-model change batching.

- [ ] **Step 1: Add strict Batch B decoder and client tests**

Reject unknown keys, unsafe URIs, invalid ranges, duplicate/overlapping edits,
non-positive versions, malformed hashes, and unexpected method results.
Verify all client payloads use the captured `workspaceRevision`.

- [ ] **Step 2: Add failing controller edit-validation tests**

```ts
test('rejects rename when any file version or hash changed', async () => {
  const captured = workspaceAt(11);
  fakeClient.rename.mockResolvedValue(renameEditFor(captured));
  controller.observe(updateFile(captured, 'projection.mdl', 'new text'));
  await expect(
    controller.rename(captured, DECL_URI, POSITION, 'Client'),
  ).rejects.toMatchObject({ code: 'STALE_EDIT' });
});
```

Also test missing/out-of-workspace URIs, overlaps, stale workspace revision,
one atomic apply call, coalesced synchronization afterward, and no partial
mutation.

- [ ] **Step 3: Implement Batch B controller methods and validation**

```ts
async rename(
  captured: PlaygroundWorkspace,
  uri: string,
  position: BrowserLanguagePositionValue,
  newName: string,
): Promise<BrowserWorkspaceEdit | undefined> {
  await this.ensureRevision(captured);
  const edit = await this.client.rename(toRenameRequest(captured, uri, position, newName));
  if (this.observed?.revision !== captured.revision) {
    return undefined;
  }
  validateEditAgainstWorkspace(edit, captured);
  return edit;
}
```

Validate normalized `.mdl` paths, versions, hashes, ranges, and overlap again
immediately before application.

- [ ] **Step 4: Add failing Monaco provider and editor tests**

Test target-file activation/focus/reveal through the standalone editor opener,
deterministic reference conversion, prepare-rename range/placeholder, one
standard Monaco `WorkspaceEdit` containing `versionId` for every text edit,
stable model reuse, same-tick content-change batching, and a single Monaco undo
that restores every edited model.

- [ ] **Step 5: Implement Monaco providers and atomic editor application**

Register definition, reference, and rename providers. Extend the editor handle:

```ts
export interface SourceEditorHandle {
  navigate(location: BrowserLanguageLocation): void;
}
```

After the controller validates the browser edit, convert it into one
`languages.WorkspaceEdit`. Each `WorkspaceTextEdit` must name the stable model
resource and its current Monaco `versionId`; Monaco's standard rename flow then
owns preview, atomic application, and global undo:

```ts
return {
  edits: edit.edits.map((item) => ({
    resource: monaco.Uri.parse(item.uri),
    versionId: requireModel(item.uri).getVersionId(),
    textEdit: {
      range: toMonacoRange(item.range),
      text: item.new_text,
    },
  })),
};
```

Register a standalone editor opener that activates the target workspace file,
restores its view state, reveals the exact range, and focuses the editor. Queue
model content-change notifications in one microtask and call
`onContentChanges(changes)` once; App applies those updates through one
`mutateWorkspaceBatch()` state transition so persistence never observes
partial rename state.

- [ ] **Step 6: Run focused TypeScript tests**

```bash
cd web
npm test -- --run src/protocol.test.ts src/client.test.ts src/language/BrowserLanguageServiceController.test.ts src/language/monaco-providers.test.ts src/editor/SourceModelRegistry.test.ts src/editor/SourceEditor.test.tsx src/workspace.test.ts src/App.test.tsx
npm run typecheck
```

Expected: PASS.

- [ ] **Step 7: Run the Python gate plus web test/build and commit**

```bash
cd cli
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
cd ../web
npm test
npm run build
git add src
git commit -m "feat: add playground navigation references and rename"
```

### Task 12: Browser acceptance, budgets, security, and Phase 3b closeout

**Files:**

- Modify: `web/tests/conformance.spec.ts`
- Modify: `web/tests/playground.spec.ts`
- Modify: `web/src/budgets.test.ts`
- Modify: `web/src/assets.test.ts`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `ROADMAP.md`
- Modify: `docs/playground-design.md`
- Move:
  `docs/superpowers/specs/2026-07-20-playground-browser-language-services-design.md`
  to
  `docs/superpowers/specs/archived/2026-07-20-playground-browser-language-services-design.md`
- Move:
  `docs/superpowers/plans/2026-07-20-playground-browser-language-services.md`
  to
  `docs/superpowers/plans/archived/2026-07-20-playground-browser-language-services.md`

**Interfaces:**

- Consumes: completed Batch A and Batch B behavior.
- Produces: Phase 3b release evidence and archived plan/spec bookkeeping.

- [ ] **Step 1: Add full browser acceptance scenarios**

Exercise completion and hover during invalid current text, cross-file
definition, sorted references, cross-file rename, reload persistence, one-step
undo, and concurrent-edit rejection. Assert exact file contents after rename
and after undo.

- [ ] **Step 2: Add performance budget measurements**

Use the representative cross-file fixture and a warm worker. Collect repeated
measurements with `performance.now()` around the full client call and assert
medians:

```ts
expect(median(completionSamples)).toBeLessThanOrEqual(100);
expect(median(hoverSamples)).toBeLessThanOrEqual(100);
expect(median(definitionSamples)).toBeLessThanOrEqual(150);
expect(median(referenceSamples)).toBeLessThanOrEqual(150);
expect(median(prepareRenameSamples)).toBeLessThanOrEqual(250);
expect(median(renameSamples)).toBeLessThanOrEqual(250);
```

Keep all existing initialization, bundle, wheel, Python, and Monaco budgets.

- [ ] **Step 3: Verify security, privacy, CSP, layout, and accessibility**

Assert no off-origin source requests, no raw/trusted hover content, no persisted
diagnostics/results/edits, no production inspection hooks without `?test=1`,
no CSP violations, no page overflow at supported viewports, keyboard provider
operation, focus after navigation, and zero automated accessibility violations.

- [ ] **Step 4: Update public documentation and archive completed plans**

Mark Phase 3b shipped, make visualization/analysis the active next slice,
document protocol v2 and all language features, add the changelog entry, move
this spec and plan into their `archived/` directories, and rebase every
relative link affected by the moves.

- [ ] **Step 5: Run doc/spec review**

Run all four `doc-review` phases: structural Markdown validation,
cross-reference consistency, coverage/ADR completeness, and corpus quality.
Expected: PASS with no blockers; record any warning in the PR body.

- [ ] **Step 6: Run the complete release gate**

```bash
cd cli
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
cd ../web
npm test
npm run build
npx playwright test
cd ..
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
git diff --check
```

Expected: all commands pass and all performance budgets remain within their
specified medians.

- [ ] **Step 7: Commit Phase 3b closeout**

```bash
git add README.md CHANGELOG.md ROADMAP.md docs web
git commit -m "docs: complete playground browser language services"
```

The final PR body must state `Doc/spec review: all phases passed`, summarize
both delivery batches, and list the release-gate evidence.
