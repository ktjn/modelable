# Modelable Documentation RAG Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic semantic Markdown chunking and an opt-in `modelable docs-index` command that writes a lexical Searchable structured index.

**Architecture:** Modelable owns Markdown parsing, chunk identity, semantic chunking, Searchable mapping, and build reporting. A small Click adapter exposes the library API without importing Click into the RAG package. Searchable remains an indexing dependency only; retrieval, embeddings, evaluation, prompting, and LLM calls are out of scope.

**Tech Stack:** Python 3.14, dataclasses, Click, pytest, Searchable Python `searchable-indexer`, uv, Ruff, mypy baseline ratchet.

## Global Constraints

- The new flow is opt-in; existing `modelable docs` and `modelable compile` behavior must remain unchanged.
- Every chunk has a deterministic external ID based on normalized source path and heading anchor; numeric Searchable IDs are separate.
- Fenced code blocks, tables, and contiguous lists are never split.
- Searchable structured document storage must use JSON.
- Invalid documents/build errors fail the command rather than being silently skipped.
- No Searchable client, retrieval orchestration, vector search, hybrid search, reranking, prompt construction, or LLM call is added.
- Run all four required checks from `cli/` before completion:
  `uv run ruff format .`, `uv run ruff check .`, `uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes`, and `uv run pytest --tb=short`.

---

### Task 1: Add Searchable dependency and RAG package skeleton

**Files:**
- Modify: `cli/pyproject.toml`
- Modify: `cli/uv.lock`
- Create: `cli/src/modelable/rag/__init__.py`
- Create: `cli/src/modelable/rag/model.py`
- Test: `cli/tests/test_rag_model.py`

**Interfaces:**
- Produces `DocumentationChunk` for all later tasks.
- Produces the Searchable dependency import path used by the index builder.

- [ ] **Step 1: Write the failing model test**

```python
from modelable.rag.model import DocumentationChunk


def test_documentation_chunk_preserves_source_addressable_fields():
    chunk = DocumentationChunk(
        external_id="docs/configuration.md#database-connections",
        source_path="docs/configuration.md",
        url="https://ktjn.github.io/modelable/configuration/",
        language="en",
        title="Configuration",
        heading="Database connections",
        heading_path=["Configuration", "Database connections"],
        content="Configure the database URL.",
        chunk_index=0,
    )

    assert chunk.external_id.endswith("#database-connections")
    assert chunk.heading_path == ["Configuration", "Database connections"]
    assert chunk.content == "Configure the database URL."
```

- [ ] **Step 2: Run the focused test to verify the expected failure**

Run from `cli/`:

```text
uv run pytest tests/test_rag_model.py::test_documentation_chunk_preserves_source_addressable_fields -q
```

Expected: collection fails because `modelable.rag.model` does not exist.

- [ ] **Step 3: Add the dependency and minimal model**

Add `searchable-indexer` to `cli/pyproject.toml` using the Searchable Git
repository Python package subdirectory, and add a `[tool.uv.sources]` local
development override pointing to
`../../client-search-framework/python/searchable-indexer`. Regenerate
`cli/uv.lock` with `uv lock`.

Create `DocumentationChunk` with the exact fields from the approved spec:

```python
@dataclass(slots=True)
class DocumentationChunk:
    external_id: str
    source_path: str
    url: str
    language: str
    title: str
    heading: str | None
    heading_path: list[str]
    content: str
    chunk_index: int
```

Define a `JsonValue` recursive type alias in `model.py` for the JSON-compatible
Searchable metadata/report types, and export only Modelable-owned types from
`modelable.rag`.

- [ ] **Step 4: Run the focused test to verify it passes**

Run:

```text
uv run pytest tests/test_rag_model.py::test_documentation_chunk_preserves_source_addressable_fields -q
```

Expected: PASS.

- [ ] **Step 5: Commit the independently testable package/dependency slice**

```text
git add cli/pyproject.toml cli/uv.lock cli/src/modelable/rag cli/tests/test_rag_model.py
git commit -m "feat: add documentation chunk model"
```

### Task 2: Implement deterministic Markdown chunking

**Files:**
- Create: `cli/src/modelable/rag/chunking.py`
- Modify: `cli/src/modelable/rag/__init__.py`
- Test: `cli/tests/test_rag_chunking.py`

**Interfaces:**
- Consumes: `DocumentationChunk` from Task 1.
- Produces:

```python
DEFAULT_TARGET_WORDS: int
DEFAULT_MAX_WORDS: int

def chunk_markdown(
    content: str,
    *,
    source_path: str,
    url: str,
    language: str = "en",
    target_words: int = DEFAULT_TARGET_WORDS,
    max_words: int = DEFAULT_MAX_WORDS,
) -> list[DocumentationChunk]: ...

def discover_markdown_files(source: Path) -> list[Path]: ...

def load_documentation_chunks(
    source: Path,
    *,
    base_url: str | None = None,
    language: str = "en",
    target_words: int = DEFAULT_TARGET_WORDS,
    max_words: int = DEFAULT_MAX_WORDS,
) -> list[DocumentationChunk]: ...
```

- [ ] **Step 1: Write failing tests for heading identity and hierarchy**

```python
def test_chunk_markdown_preserves_heading_path_and_stable_anchor():
    chunks = chunk_markdown(
        "# Configuration\n\nIntro.\n\n## Database connections\n\nUse DATABASE_URL.",
        source_path="docs/configuration.md",
        url="https://example.test/configuration/",
    )

    assert [chunk.external_id for chunk in chunks] == [
        "docs/configuration.md#configuration",
        "docs/configuration.md#database-connections",
    ]
    assert chunks[1].heading_path == ["Configuration", "Database connections"]
    assert "Use DATABASE_URL." in chunks[1].content
```

```python
def test_duplicate_headings_get_deterministic_suffixes():
    chunks = chunk_markdown(
        "# Guide\n\n## Install\n\nFirst.\n\n## Install\n\nSecond.",
        source_path="guide.md",
        url="guide/",
    )

    assert [chunk.external_id for chunk in chunks] == [
        "guide.md#guide",
        "guide.md#install",
        "guide.md#install-2",
    ]
```

- [ ] **Step 2: Run the tests to verify they fail for the missing chunker**

Run:

```text
uv run pytest tests/test_rag_chunking.py -q
```

Expected: collection fails because `modelable.rag.chunking` does not exist.

- [ ] **Step 3: Add structural Markdown scanning**

Implement a line scanner that emits private structural units for headings,
paragraphs, fenced code blocks, contiguous list items, pipe tables, and
blockquote/admonition blocks. Track fence delimiter and language until the
matching closing fence. Treat blank lines as paragraph/list/table boundaries,
but never as boundaries inside a fence or table continuation.

Normalize line endings, preserve source text inside units, and reject invalid
UTF-8 in `load_documentation_chunks` with the source path in the exception.

- [ ] **Step 4: Add heading context, anchors, and deterministic section chunks**

Maintain an active heading stack by level. Slugify heading text by lowercasing,
removing punctuation, converting runs of non-alphanumeric characters to `-`,
and trimming leading/trailing hyphens. Track used slugs per document and append
`-2`, `-3`, etc. to duplicates.

Group units into sections, prefix each chunk's content with its heading path,
merge adjacent small units up to `target_words`, and split oversized prose at
paragraph boundaries then sentence boundaries. Keep fenced code, tables, and
lists as indivisible units. When a section produces multiple chunks, append
`-part-2`, `-part-3`, etc. to the base anchor. Assign `chunk_index` in final
document order.

- [ ] **Step 5: Add failing preservation and deterministic-order tests**

```python
def test_chunker_never_splits_fenced_code_tables_or_lists():
    content = """# Examples

```python
def connect():
    return database.connect()
```

| setting | value |
| --- | --- |
| host | localhost |

- first item
- second item
"""
    chunks = chunk_markdown(content, source_path="examples.md", url="examples/")

    combined = "\n".join(chunk.content for chunk in chunks)
    assert "def connect():\n    return database.connect()" in combined
    assert "| setting | value |\n| --- | --- |\n| host | localhost |" in combined
    assert "- first item\n- second item" in combined
```

```python
def test_discovery_order_is_path_sorted(tmp_path):
    (tmp_path / "z.md").write_text("# Z\n\nText.", encoding="utf-8")
    (tmp_path / "a.md").write_text("# A\n\nText.", encoding="utf-8")

    chunks = load_documentation_chunks(tmp_path)

    assert [chunk.source_path for chunk in chunks] == ["a.md", "z.md"]
```

- [ ] **Step 6: Run all chunking tests and refactor only while green**

Run:

```text
uv run pytest tests/test_rag_chunking.py -q
```

Expected: all chunking tests PASS, including oversized-section and empty-input
cases. Keep the implementation deterministic and independent of filesystem
enumeration order.

- [ ] **Step 7: Commit the chunking slice**

```text
git add cli/src/modelable/rag cli/tests/test_rag_chunking.py
git commit -m "feat: add deterministic documentation chunking"
```

### Task 3: Map chunks to Searchable and build/write indexes

**Files:**
- Create: `cli/src/modelable/rag/index.py`
- Modify: `cli/src/modelable/rag/__init__.py`
- Test: `cli/tests/test_rag_index.py`

**Interfaces:**
- Consumes: `DocumentationChunk` and `load_documentation_chunks` from Tasks 1–2.
- Produces:

```python
FIELD_DEFINITIONS: dict[str, FieldDefinition]

def to_index_document(chunk: DocumentationChunk, numeric_id: int) -> IndexDocument: ...

@dataclass(slots=True, frozen=True)
class IndexBuildReport:
    source_document_count: int
    chunk_count: int
    languages: tuple[str, ...]
    output_directory: Path
    validation_errors: tuple[str, ...]

def build_documentation_index(
    chunks: Sequence[DocumentationChunk],
    output_directory: Path,
) -> IndexBuildReport: ...
```

- [ ] **Step 1: Write the failing Searchable mapping test**

```python
def test_to_index_document_stores_complete_chunk_and_metadata():
    chunk = DocumentationChunk(
        external_id="guide.md#install",
        source_path="guide.md",
        url="https://example.test/guide/#install",
        language="en",
        title="Guide",
        heading="Install",
        heading_path=["Guide", "Install"],
        content="Install with uv.",
        chunk_index=2,
    )

    document = to_index_document(chunk, 17)

    assert document.id == 17
    assert document.external_id == "guide.md#install"
    assert document.indexed_fields["content"] == "Install with uv."
    assert document.stored_fields["content"] == "Install with uv."
    assert document.metadata == {"headingPath": ["Guide", "Install"], "chunkIndex": 2}
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```text
uv run pytest tests/test_rag_index.py::test_to_index_document_stores_complete_chunk_and_metadata -q
```

Expected: collection fails because `modelable.rag.index` does not exist.

- [ ] **Step 3: Implement field definitions, mapping, and deterministic ID assignment**

Import `FieldDefinition`, `IndexDocument`, `build_index_documents`, and
`write_index` from Searchable. Define boosted title/heading/content fields and
stored source path exactly as the approved spec requires. Sort chunks by
`(source_path, chunk_index, external_id)` before assigning IDs starting at 1.
Reject duplicate external IDs and non-positive/duplicate chunk indexes with
clear `ValueError`s before invoking Searchable.

- [ ] **Step 4: Run mapping tests to verify they pass**

Run:

```text
uv run pytest tests/test_rag_index.py::test_to_index_document_stores_complete_chunk_and_metadata -q
```

Expected: PASS.

- [ ] **Step 5: Write the failing build/write integration test**

```python
def test_build_documentation_index_writes_json_searchable_documents(tmp_path):
    chunks = [
        DocumentationChunk(
            external_id="guide.md#install",
            source_path="guide.md",
            url="https://example.test/guide/#install",
            language="en",
            title="Guide",
            heading="Install",
            heading_path=["Guide", "Install"],
            content="Install with uv.",
            chunk_index=0,
        )
    ]

    report = build_documentation_index(chunks, tmp_path / "index")
    manifest = json.loads((tmp_path / "index" / "manifest.json").read_text())
    doc_file = tmp_path / "index" / manifest["shards"]["docs"][0]["file"]
    documents = json.loads(doc_file.read_text())

    assert report.source_document_count == 1
    assert report.chunk_count == 1
    assert report.languages == ("en",)
    assert report.validation_errors == ()
    assert documents["1"]["externalId"] == "guide.md#install"
    assert documents["1"]["storedFields"]["content"] == "Install with uv."
```

- [ ] **Step 6: Run the integration test to verify it fails**

Run:

```text
uv run pytest tests/test_rag_index.py::test_build_documentation_index_writes_json_searchable_documents -q
```

Expected: FAIL because the build orchestration is not implemented.

- [ ] **Step 7: Implement build/report orchestration and JSON output**

Convert sorted chunks to Searchable documents, call
`build_index_documents(..., field_definitions=FIELD_DEFINITIONS)`, and call
`write_index(..., doc_store_format="json")`. Compute source count from unique
`source_path` values, languages as a sorted tuple, and return the output path.
Allow Searchable exceptions to propagate so callers can report them as build
failures. Use `Path` consistently and create the output directory through
Searchable's writer.

- [ ] **Step 8: Run index tests and deterministic rebuild assertions**

Run:

```text
uv run pytest tests/test_rag_index.py -q
```

Expected: PASS, including repeated-build equality of manifest JSON and stored
document content hashes.

- [ ] **Step 9: Commit the index-builder slice**

```text
git add cli/src/modelable/rag cli/tests/test_rag_index.py
git commit -m "feat: build Searchable documentation indexes"
```

### Task 4: Add the opt-in `docs-index` CLI command

**Files:**
- Create: `cli/src/modelable/commands/docs_index.py`
- Modify: `cli/src/modelable/cli.py`
- Test: `cli/tests/test_cli_docs_index.py`
- Modify: `docs/cli-reference.md`
- Modify: `docs/getting-started.md`

**Interfaces:**
- Consumes: `load_documentation_chunks` and `build_documentation_index` from Tasks 2–3.
- Produces: `modelable docs-index SOURCE [--out DIR] [--base-url URL]`.

- [ ] **Step 1: Write failing CLI tests**

```python
def test_docs_index_builds_searchable_index_and_reports_counts(tmp_path):
    source = tmp_path / "docs"
    source.mkdir()
    (source / "guide.md").write_text("# Guide\n\nInstall with uv.", encoding="utf-8")
    output = tmp_path / "dist" / "search-index"

    result = CliRunner().invoke(
        cli,
        ["docs-index", str(source), "--out", str(output), "--base-url", "https://example.test/docs/"],
    )

    assert result.exit_code == 0, result.output
    assert "Source documents: 1" in result.output
    assert "Chunks: 1" in result.output
    assert (output / "manifest.json").exists()
```

```python
def test_docs_index_empty_source_writes_empty_index(tmp_path):
    source = tmp_path / "docs"
    source.mkdir()
    output = tmp_path / "index"

    result = CliRunner().invoke(cli, ["docs-index", str(source), "--out", str(output)])

    assert result.exit_code == 0, result.output
    assert "Source documents: 0" in result.output
    assert (output / "manifest.json").exists()
```

- [ ] **Step 2: Run the CLI tests to verify the command is missing**

Run:

```text
uv run pytest tests/test_cli_docs_index.py -q
```

Expected: FAIL because `docs-index` is not registered.

- [ ] **Step 3: Implement the Click adapter and registration**

Create `register_docs_index_commands` and register it from `modelable.cli`.
Use Click path validation for an existing directory and `Path` values. Default
`--out` to `./dist/search-index`; pass `--base-url` into chunk discovery; print
counts, sorted languages, and output path. Catch `OSError`, `ValueError`, and
Searchable validation exceptions and raise `click.ClickException` with the
source path or underlying validation message. Do not call `sys.exit(0)` from
the reusable library; the command may return normally after printing.

- [ ] **Step 4: Run focused CLI tests to verify they pass**

Run:

```text
uv run pytest tests/test_cli_docs_index.py -q
```

Expected: PASS for successful, empty, and invalid-input cases.

- [ ] **Step 5: Document the command**

Add the command and options to the CLI reference, including the generated
Searchable output and the fact that indexing is opt-in. Add a short getting
started example showing:

```text
modelable docs-index ./docs --out ./dist/search-index --base-url https://ktjn.github.io/modelable/
```

State explicitly that this first slice is lexical-index generation only and
does not call an LLM.

- [ ] **Step 6: Run docs-focused checks and commit the CLI slice**

Run:

```text
uv run pytest tests/test_cli_docs_index.py tests/test_cli_compile.py -q
git diff --check
```

Then commit:

```text
git add cli/src/modelable/commands/docs_index.py cli/src/modelable/cli.py cli/tests/test_cli_docs_index.py docs/cli-reference.md docs/getting-started.md
git commit -m "feat: add documentation index command"
```

### Task 5: Run the complete repository gate and review the slice

**Files:**
- Modify only files identified by the verification commands if formatting or
  baseline line-shift repair is required.

- [ ] **Step 1: Review the complete diff and generated-file status**

Run from the repository root:

```text
git diff main...HEAD --stat
git status --short
git diff --check
```

Remove only generated test outputs under the task's temporary directories; do
not remove user changes or unrelated files.

- [ ] **Step 2: Run the required formatter and linter from `cli/`**

```text
uv run ruff format .
uv run ruff check .
```

If formatting changes files, inspect the diff and include only intended changes.

- [ ] **Step 3: Run the Modelable mypy baseline ratchet**

```text
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
```

If existing errors shift because new lines were inserted, compare messages and
counts against the prior baseline before changing it. Regenerate only pure
line-shift entries; fix any genuinely new type errors.

- [ ] **Step 4: Run the full test suite**

```text
uv run pytest --tb=short
```

Expected: all tests pass, including the new chunking/index/CLI coverage.

- [ ] **Step 5: Run the repository documentation validation**

From the repository root, run the same pinned strict docs build used by CI:

```text
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
```

Confirm the new CLI references resolve and no existing docs links regress.

- [ ] **Step 6: Perform the final contract review**

Confirm the diff contains no LLM/provider code, no embeddings, no Searchable
client dependency, no numeric-ID citations, no silent document skips, and no
changes to the existing Markdown compiler path. Confirm the output stores full
chunk content and stable external IDs.

- [ ] **Step 7: Commit any verification-only fixes**

```text
git add cli/pyproject.toml cli/uv.lock cli/src/modelable/rag cli/src/modelable/commands/docs_index.py cli/src/modelable/cli.py cli/tests/test_rag_model.py cli/tests/test_rag_chunking.py cli/tests/test_rag_index.py cli/tests/test_cli_docs_index.py docs/cli-reference.md docs/getting-started.md
git commit -m "chore: verify documentation index foundation"
```
