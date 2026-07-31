# RAG Vector and Hybrid Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate Modelable documentation retrieval with Searchable v1.0.5 vector and hybrid search while preserving lexical fallback and measured mode comparisons.

**Architecture:** `DocumentationRetriever` remains the Modelable-owned boundary. It constructs Searchable's injected `embed_query` configuration, forwards an explicit `SearchOptions.mode`, and maps every Searchable hit into the existing `RetrievedChunk`. Evaluation runs the same corpus through each mode and keeps metrics separated by mode; Modelable does not implement vector math or bundle an embedding model.

**Tech Stack:** Python 3.14, `searchable-client>=0.2.0`, `searchable-indexer>=0.1.1`, Click, pytest, YAML evaluation corpus, uv, Ruff, mypy baseline ratchet.

## Global Constraints

- Keep lexical retrieval as the default mode.
- Never silently downgrade vector or hybrid requests to lexical search.
- Inject `embed_query(text) -> list[float]`; do not add Transformers/Hugging Face dependencies to Modelable core.
- Pass provider metadata unchanged to Searchable for compatibility validation.
- Keep Searchable numeric IDs internal and preserve external IDs, URLs, content, scores, and metadata.
- Compare lexical, vector, and hybrid modes against the identical evaluation corpus before selecting a default.
- Run all four Modelable checks from `cli/` before completion.

---

### Task 1: Raise the Searchable dependency floor

**Files:**
- Modify: `cli/pyproject.toml`
- Modify: `cli/uv.lock`
- Test: `cli/tests/test_repository_release.py`

**Interfaces:**
- Consumes: published Searchable v1.0.5 packages.
- Produces: a lockfile resolving `searchable-client` 0.2.0 and `searchable-indexer` 0.1.1 or newer.

- [ ] **Step 1: Write the failing metadata assertion**

Add an assertion that the project dependency declarations require at least
`searchable-client>=0.2.0` and `searchable-indexer>=0.1.1`, and that the lock
resolves versions satisfying those floors.

- [ ] **Step 2: Run the focused test to verify it fails**

Run from `cli/`:

```bash
uv run pytest tests/test_dependency_constraints.py -q
```

Expected: FAIL because the current declarations still allow the 0.1.x client.

- [ ] **Step 3: Update dependency declarations and lockfile**

Change both lower bounds in `cli/pyproject.toml`, then run:

```bash
uv lock
```

Do not add model-runtime dependencies.

- [ ] **Step 4: Run the focused test to verify it passes**

Run the same focused test and confirm the resolved versions satisfy the floors.

- [ ] **Step 5: Commit the dependency floor**

```bash
git add cli/pyproject.toml cli/uv.lock cli/tests/test_dependency_constraints.py
git commit -m "build: require searchable vector client"
```

### Task 2: Add injected vector and hybrid retrieval modes

**Files:**
- Modify: `cli/src/modelable/rag/retriever.py`
- Modify: `cli/src/modelable/rag/__init__.py`
- Test: `cli/tests/test_rag_retriever.py`

**Interfaces:**
- Consumes: `Callable[[str], list[float]]`, provider descriptor `dict[str, object] | None`, and Searchable `SearchOptions`.
- Produces:
  - `SearchMode = Literal["lexical", "vector", "hybrid"]`
  - `DocumentationRetriever(..., embed_query=None, embedding_provider=None)`
  - `search(query, *, limit=8, mode="lexical") -> list[RetrievedChunk]`

- [ ] **Step 1: Write failing retriever tests**

Add tests proving:

```python
retriever = DocumentationRetriever(
    "index/manifest.json",
    client=client,
    embed_query=lambda text: [1.0, 0.0],
    embedding_provider={"type": "custom", "model": "test"},
)
retriever.search("semantic", mode="hybrid", limit=5)
assert client.options.mode == "hybrid"
assert client.options.limit == 5
```

Also assert lexical mode does not require or invoke the embedder, vector and
hybrid modes pass the injected configuration when constructing a real client,
and unsupported modes are rejected before Searchable is called.

- [ ] **Step 2: Run the focused tests to verify they fail**

```bash
uv run pytest tests/test_rag_retriever.py -q
```

Expected: FAIL because `DocumentationRetriever` has no embedding arguments or
mode parameter.

- [ ] **Step 3: Implement the Modelable boundary**

Use `SearchClient(str(index_url), embed_query=...)` only when an embedder was
provided. For a provider descriptor, pass the mapping form:

```python
embed_config = (
    {"embed": embed_query, "provider": embedding_provider}
    if embed_query is not None and embedding_provider is not None
    else embed_query
)
```

Construct `SearchOptions(mode=mode, limit=limit)` in `search`. Preserve the
existing query normalization and hit mapping. Let Searchable's explicit vector
configuration errors propagate as `ValueError`-compatible failures; do not
catch them and retry lexically.

- [ ] **Step 4: Run retriever tests and the existing RAG tests**

```bash
uv run pytest tests/test_rag_retriever.py tests/test_rag_*.py -q
```

- [ ] **Step 5: Commit the retrieval API**

```bash
git add cli/src/modelable/rag/retriever.py cli/src/modelable/rag/__init__.py cli/tests/test_rag_retriever.py
git commit -m "feat: add vector and hybrid documentation retrieval"
```

### Task 3: Add vector-enabled documentation index generation

**Files:**
- Modify: `cli/src/modelable/rag/index.py`
- Test: `cli/tests/test_rag_index.py`

**Interfaces:**
- Consumes: `embed: Callable[[list[str]], list[list[float]]] | None`, provider descriptor `dict[str, object] | None`, and Searchable vector quantization.
- Produces: `build_documentation_index(..., embed=..., embedding_provider=..., vector_quantization="int8")` with `content` as the vector field.

- [ ] **Step 1: Write failing index-generation tests**

Use a deterministic two-dimensional embedder and assert that the written
manifest contains vector dimensions and the exact provider descriptor. Assert
that a provider descriptor without an embedder is rejected.

- [ ] **Step 2: Run the focused tests to verify they fail**

```bash
uv run pytest tests/test_rag_index.py -q
```

- [ ] **Step 3: Implement optional vector generation**

Pass `embed`, `embedding_provider`, `vector_field="content"`, and
`vector_quantization` to Searchable only when an embedder is supplied. Keep
the existing lexical call path unchanged and reject a provider descriptor
without an embedder before writing any files.

- [ ] **Step 4: Run focused index and retriever tests**

```bash
uv run pytest tests/test_rag_index.py tests/test_rag_retriever.py -q
```

- [ ] **Step 5: Commit vector index generation**

```bash
git add cli/src/modelable/rag/index.py cli/tests/test_rag_index.py
git commit -m "feat: add vector documentation index generation"
```

### Task 4: Add mode-aware evaluation

**Files:**
- Modify: `cli/src/modelable/rag/evaluation.py`
- Modify: `cli/src/modelable/commands/docs_eval.py`
- Modify: `cli/src/modelable/rag/__init__.py`
- Test: `cli/tests/test_rag_evaluation.py`
- Test: `cli/tests/test_cli_docs_eval.py`
- Modify: `docs/cli-reference.md`

**Interfaces:**
- Consumes: `DocumentationRetriever.search(..., mode=...)` and the existing evaluation cases.
- Produces:
  - `evaluate_retrieval_modes(retriever, cases, modes=("lexical", "vector", "hybrid"), limit=10) -> dict[str, EvaluationReport]`
  - a library-only comparison API; the CLI remains lexical-only because Click cannot serialize an injected Python `embed_query` callable.

- [ ] **Step 1: Write failing pure-evaluation tests**

Use a fake retriever whose `search` records the requested mode and returns
mode-specific ranked chunks. Assert that each requested mode gets the same
cases and that the returned mapping preserves the order
`lexical`, `vector`, `hybrid`.

- [ ] **Step 2: Run focused evaluation tests to verify they fail**

```bash
uv run pytest tests/test_rag_evaluation.py -q
```

- [ ] **Step 3: Implement the mode-aware evaluator**

Add a mode parameter to the private evaluation protocol and thread it through
`evaluate_retrieval`. Keep metric calculations unchanged. Implement
`evaluate_retrieval_modes` as a thin deterministic loop that calls the existing
single-mode evaluator and returns a normal insertion-ordered dictionary.

- [ ] **Step 4: Keep the existing CLI lexical-only contract**

Add a regression assertion that `docs-eval` continues to use lexical retrieval
and document that vector/hybrid comparison is available through the Python API
where callers can inject `embed_query`.

- [ ] **Step 5: Run focused tests and commit**

```bash
uv run pytest tests/test_rag_evaluation.py tests/test_cli_docs_eval.py -q
git add cli/src/modelable/rag/evaluation.py cli/src/modelable/rag/__init__.py cli/tests/test_rag_evaluation.py cli/tests/test_cli_docs_eval.py docs/cli-reference.md
git commit -m "feat: compare documentation retrieval modes"
```

### Task 5: Wire `docs-ask` for embedding-aware callers without CLI model loading

**Files:**
- Modify: `cli/src/modelable/commands/docs_ask.py`
- Modify: `cli/src/modelable/commands/docs_index.py` only if an explicit vector-index validation/help option is needed
- Test: `cli/tests/test_cli_docs_ask.py`
- Modify: `docs/cli-reference.md`

**Interfaces:**
- Consumes: an already-constructed `DocumentationRetriever` with an injected embedder for library callers.
- Produces: unchanged lexical CLI behavior and an explicit, documented boundary that CLI flags cannot serialize Python callables.

- [ ] **Step 1: Write a regression test for lexical default**

Invoke `docs-ask` against the existing lexical fixture with no embedding
configuration and assert it continues to use lexical retrieval and produce the
same answer/citation behavior.

- [ ] **Step 2: Add an explicit mode boundary**

Do not add a fake `--provider` embedding model flag. If a mode option is added,
accept only `lexical` in the CLI and explain that vector/hybrid mode requires a
library caller to inject `embed_query`. Keep LLM provider flags separate from
embedding provider metadata.

- [ ] **Step 3: Document library usage**

Add a short Python example showing `DocumentationRetriever(...,
embed_query=..., embedding_provider=...)` and `search(..., mode="hybrid")`.

- [ ] **Step 4: Run CLI tests and commit**

```bash
uv run pytest tests/test_cli_docs_ask.py -q
git add cli/src/modelable/commands/docs_ask.py cli/tests/test_cli_docs_ask.py docs/cli-reference.md
git commit -m "docs: explain embedding-aware documentation queries"
```

### Task 6: Verify, review, and hand off

**Files:**
- Modify: `docs/superpowers/plans/2026-07-31-rag-vector-hybrid.md` (checklist only)

- [ ] **Step 1: Run the four required Modelable gates from `cli/`**

```bash
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

- [ ] **Step 2: Build strict documentation**

```bash
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
```

- [ ] **Step 3: Run doc/spec review**

Validate the numbered spec heading, cross-references, explicit no-ADR rationale,
and consistency between the spec, plan, CLI reference, and implementation.

- [ ] **Step 4: Run a real Searchable v1.0.5 smoke**

Build a vector-enabled fixture with a deterministic two-dimensional embedder,
construct `DocumentationRetriever` with the same provider descriptor, and
assert lexical, vector, and hybrid searches return complete `RetrievedChunk`
objects with stable external IDs. Run this only after the dependency lock has
resolved the published packages.

- [ ] **Step 5: Update the plan checklist and commit the final verification**

```bash
git add docs/superpowers/plans/2026-07-31-rag-vector-hybrid.md
git commit -m "chore: verify vector retrieval integration"
```

## Expected handoff

After this plan, Modelable will expose measured lexical/vector/hybrid retrieval
through its own retriever and evaluation APIs, while lexical remains the safe
default. The next RAG phase can use the selected mode in context selection and
answer generation without changing citation or prompt ownership.
