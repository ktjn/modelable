# 2026-08-02 Ship Bundled Documentation Index with the Python Package

## Goal

Ship the Modelable documentation search index inside the `modelable` Python wheel so CLI chat, `docs-ask`, and LSP/VSCode chat can answer `/docs` questions out of the box. Users may still override the bundled index with `--docs-index` or `documentationIndexUri`.

## Decisions

- The wheel generates and includes its own Searchable index at build time; the existing `dist/search-index/` at the repository root remains unchanged for the web playground and docs site.
- A Hatchling custom build hook generates the bundled index by running the existing `modelable.rag.chunking` and `modelable.rag.index` logic against `docs/`.
- The bundled index lives under `src/modelable/data/docs-index/` inside the wheel and is discovered at runtime through `importlib.resources`.
- The bundled index is the default for CLI chat, `docs-ask`, and LSP chat. Explicit user-provided indexes still take precedence.
- `docs-ask` changes from `docs-ask INDEX QUESTION` to `docs-ask QUESTION [--docs-index PATH]` to match the `chat --docs-index` option and to make the index optional.
- LSP workspace-root containment validation applies only to user-supplied `documentationIndexUri`; the bundled index is trusted because it ships with the package.

## Architecture

### Build-time packaging

`cli/pyproject.toml` adds `searchable-indexer>=0.1.1` to `[build-system] requires`. A new `cli/hatch_build.py` registers a Hatchling `CustomBuildHook` that runs during wheel and sdist builds. The hook:

1. Locates the Markdown documentation root. From a source checkout this is `../../docs` relative to `cli/`; from an sdist it is the included `docs/` directory. The sdist configuration includes the repository `docs/` tree so the hook can regenerate the index during wheel builds from the sdist.
2. Imports `modelable.rag.chunking` and `modelable.rag.index` from `src/` by temporarily adding `src` to `sys.path`.
3. Calls `load_documentation_chunks(docs_root, base_url="https://ktjn.github.io/modelable/")` and `build_documentation_index(...)` to write `src/modelable/data/docs-index/`.
4. Creates `src/modelable/data/__init__.py` so `importlib.resources.files("modelable.data")` can resolve the shipped directory.

Because the generated files sit under `src/modelable`, Hatchling includes them in the wheel automatically.

### Runtime default behavior

A new module `modelable.rag.bundled_index` exposes:

```python
def bundled_documentation_index_path() -> Path: ...
```

The helper resolves `importlib.resources.files("modelable.data") / "docs-index" / "manifest.json"` and returns a `Path`. It raises a clear `RuntimeError` if the bundled index is missing, which can happen when running directly from source without building.

Callers:

- `modelable.commands.llm.chat`: if `--docs-index` is omitted, construct the retriever from `bundled_documentation_index_path()`.
- `modelable.commands.docs_ask`: the positional `INDEX` argument is removed; the command becomes `docs-ask QUESTION [--docs-index PATH]`. When `--docs-index` is omitted, use the bundled index.
- `modelable.lsp.conversation_service.LspConversationService.turn`: when `documentation_index_uri` is `None`, create a retriever from the bundled index. The existing workspace-root and shard-containment checks are skipped for the bundled path; they still apply to any supplied URI.

### Error handling and safety

- Missing bundled index: callers surface a user-visible message explaining that the index is missing and, where applicable, suggest using `--docs-index`.
- User-provided index: existing validation and error handling remain unchanged.
- LSP: only user-supplied URIs are validated against the workspace root; the bundled package index is not subject to that restriction.
- Build hook: if the docs root is missing, the hook fails the build with a descriptive error rather than silently omitting the index.

## Testing and acceptance

- Unit tests for `bundled_documentation_index_path()` covering present and missing index cases.
- Update `docs-ask` tests for the new `QUESTION [--docs-index PATH]` signature, including default-to-bundled and override behavior.
- Add CLI chat tests that exercise `/docs` without `--docs-index` when the bundled index is present.
- Add LSP conversation service tests that exercise `/docs` without `documentationIndexUri` when the bundled index is present.
- Provide `cli/scripts/build_bundled_docs_index.py`, runnable as `uv run python scripts/build_bundled_docs_index.py` from `cli/`, which generates `src/modelable/data/docs-index/` from `docs/` so tests and local runs can use the bundled index without a full wheel build.
- Run the standard pre-commit checks from `cli/`: `ruff format`, `ruff check`, `check_mypy_baseline.py`, and `pytest`.

## Non-goals

- Changing the web playground index flow; `web/public/docs-index/` continues to be built separately.
- Removing the `docs-index` command or the `dist/search-index/` artifact at the repository root.
- Vector embeddings in the bundled index; the initial bundled index is lexical only, matching the current default.
- Automatic documentation retrieval for ordinary chat messages without an explicit `/docs` trigger or automatic-documentation signal.
