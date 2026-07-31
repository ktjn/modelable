# Modelable Documentation RAG Index Design

## Scope

This slice adds the retrieval foundation for Modelable documentation:

```text
Markdown documentation -> deterministic semantic chunks -> Searchable lexical index
```

It does not add a Searchable client, retrieval orchestration, evaluation corpus,
prompt construction, embeddings, reranking, or LLM calls. Existing `modelable
docs` and `modelable compile` behavior remains unchanged unless the new command
is explicitly invoked.

## User-facing command

Add an opt-in command:

```text
modelable docs-index SOURCE [--out DIRECTORY] [--base-url URL]
```

`SOURCE` is an existing directory recursively containing Markdown files. The
default output is `./dist/search-index`. `--base-url` is optional; when supplied,
it is joined with each source-relative Markdown path to produce the chunk URL.
When omitted, the URL is the normalized source-relative path. URL construction
does not affect stable chunk identity.

The command prints the source document count, chunk count, languages, output
directory, and validation failures. Invalid input or Searchable validation
errors fail the command; documents are never silently skipped.

## Chunk model and identity

Create `modelable.rag.model.DocumentationChunk` as a slotted dataclass with:

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

Source paths use `/` separators and are relative to `SOURCE`. The title is the
document's first level-one heading, falling back to the filename stem. Heading
paths contain the active heading hierarchy and are copied into every chunk so
the chunk can stand alone.

The external ID is the source path plus a Markdown anchor derived from the
section heading, for example:

```text
docs/configuration.md#database-connections
```

Documents without headings use the source path as their first chunk identity.
Duplicate heading anchors receive deterministic suffixes (`-2`, `-3`, and so
on) in source order. If a section is split into multiple chunks, the first
chunk keeps the heading anchor and later chunks receive a deterministic
`-part-2`, `-part-3`, etc. suffix. Numeric Searchable IDs are separate and are
never used as public identity.

## Markdown parsing and chunking

The parser scans Markdown lines into structural units while tracking fenced
code state. It recognizes ATX headings, paragraphs, unordered and ordered
lists, pipe tables, fenced code blocks, and blockquote/admonition blocks.

Chunking rules:

1. Heading levels update the active heading stack; skipped levels are preserved
   as written rather than invented.
2. A section's content includes its heading context and all structural units
   until the next heading at the same or higher level.
3. Adjacent small units are merged while the chunk is below the configurable
   target size.
4. Fenced code blocks, tables, and contiguous lists are indivisible units.
5. Oversized prose sections split first at paragraph boundaries, then at
   sentence boundaries. An indivisible unit may exceed the target size.
6. Empty sections and chunks containing only a heading are merged into the next
   available content where possible; a genuinely empty document produces no
   chunks.
7. Output is deterministic for identical bytes and independent of filesystem
   enumeration order.

The default target and maximum sizes are constants in Modelable's chunker and
are expressed as approximate word counts until a tokenizer is introduced. They
remain configurable through the library API; the CLI uses defaults in this
slice. Fixed windows are not the primary segmentation strategy.

## Searchable mapping and index build

Create a Modelable-owned field configuration:

```python
FIELD_DEFINITIONS = {
    "title": FieldDefinition(indexed=True, stored=True, boost=3.0),
    "heading": FieldDefinition(indexed=True, stored=True, boost=2.0),
    "content": FieldDefinition(indexed=True, stored=True, boost=1.0),
    "source_path": FieldDefinition(indexed=False, stored=True),
}
```

Each chunk becomes exactly one `searchable_indexer.document.IndexDocument`:

- `id`: deterministic positive integer assigned after globally sorting chunks;
- `external_id`, `url`, and `language`: copied from the chunk;
- indexed fields: `title`, `heading` (empty string when absent), and `content`;
- stored fields: the same searchable fields plus `source_path`;
- metadata: JSON-compatible `headingPath` and `chunkIndex` values.

Call `build_index_documents` and `write_index` with JSON document storage. The
index build validates every document and propagates errors. Rebuilding the
same source produces the same chunk order and Searchable content hashes.

The `searchable-indexer` dependency is declared from the Searchable Git
repository's Python package subdirectory. The local `client-search-framework`
checkout is configured only as a development source override; it is not part
of the published runtime contract.

## Module boundaries

- `cli/src/modelable/rag/model.py`: chunk dataclass and JSON-compatible types.
- `cli/src/modelable/rag/chunking.py`: Markdown parsing, heading state, and
  deterministic chunking.
- `cli/src/modelable/rag/index.py`: Searchable field definitions, chunk mapping,
  numeric ID assignment, build/write/report orchestration.
- `cli/src/modelable/commands/docs_index.py`: Click adapter and terminal output.

The RAG package does not import Click. The CLI adapter does not parse Markdown
or access Searchable internals beyond the Modelable index-build API.

## Error handling and reporting

- A missing or non-directory source is rejected by Click.
- Invalid UTF-8 Markdown input raises a clear source-path error.
- Searchable field/document/build validation errors fail the command with the
  originating message.
- Empty input is successful and reports zero documents/chunks while writing a
  valid empty index.
- No exception is converted into a warning-only or silently skipped document.

## Verification

Tests will cover:

- stable external IDs and duplicate heading suffixes;
- heading hierarchy and document titles;
- preservation of fenced code, lists, tables, and admonition blocks;
- deterministic splitting and ordering;
- complete Searchable stored fields and metadata;
- deterministic index manifest/document content across repeated builds;
- CLI success, empty input, invalid encoding, and validation failures.

The repository's required `cli/` checks remain the final gate:

```text
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```
