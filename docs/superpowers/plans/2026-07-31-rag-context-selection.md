# RAG Context Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic duplicate removal and source-diversity controls to the Modelable RAG context pipeline.

**Architecture:** `modelable.rag.context` owns candidate selection and remains independent of Searchable internals. `modelable.rag.generation` delegates candidate selection to that policy before prompt construction and citation creation. Retrieval scores and external source identity remain observable.

**Tech Stack:** Python 3.14, dataclasses, existing `RetrievedChunk`/`RagAnswer` types, pytest, uv, Ruff, mypy baseline ratchet.

## Global Constraints

- Preserve retrieval order among admitted chunks.
- Never silently truncate a chunk.
- Deduplicate by stable external ID and content hash where present.
- Keep numeric Searchable IDs out of prompts and citations.
- Keep adjacency expansion and reranking out of this slice because the current client cannot fetch neighbors or provide a measured reranker.
- Run the four required Modelable checks from `cli/` before completion.

---

### Task 1: Add the pure context-selection policy

**Files:**
- Create: `cli/src/modelable/rag/context.py`
- Modify: `cli/src/modelable/rag/__init__.py`
- Test: `cli/tests/test_rag_context.py`

**Interfaces:**
- Produces `select_context(chunks: Sequence[RetrievedChunk], *, max_context_words: int, max_chunks_per_source: int | None = None) -> tuple[RetrievedChunk, ...]`.

- [x] Write failing tests for duplicate external IDs, duplicate content hashes, per-source caps, whole-chunk budgeting, and stable order.
- [x] Run `uv run pytest tests/test_rag_context.py -q` and confirm the module is absent.
- [x] Implement validation and deterministic selection with no Searchable imports.
- [x] Run the focused tests until green.
- [x] Commit with `git commit -m "feat: add deterministic RAG context selection"`.

### Task 2: Integrate selection into answer generation

**Files:**
- Modify: `cli/src/modelable/rag/generation.py`
- Modify: `cli/tests/test_rag_generation.py`
- Modify: `docs/cli-reference.md`

**Interfaces:**
- `answer_with_retrieval(..., max_chunks_per_source: int | None = 2)` delegates candidate selection to `select_context`.

- [x] Add failing tests proving duplicate sources are absent from the prompt and citations, and that a source cap is honored.
- [x] Run the focused generation tests and confirm the new assertions fail.
- [x] Replace local budget selection with `select_context` while retaining the existing prompt and citation formats.
- [x] Document the default source cap and Python override path.
- [x] Run `uv run pytest tests/test_rag_context.py tests/test_rag_generation.py tests/test_cli_docs_ask.py -q`.
- [x] Commit with `git commit -m "feat: apply context selection to RAG answers"`.

### Task 3: Verify and hand off

**Files:**
- Modify: `docs/superpowers/plans/2026-07-31-rag-context-selection.md` (checklist only)

- [x] Run:

```bash
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

- [x] Run `uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict`.
- [x] Run doc/spec review and confirm the adjacency limitation is explicit.
- [x] Update this checklist and commit the verification.

## Follow-up

Implement adjacency expansion only after Searchable exposes a safe neighbor
lookup or Modelable gains an explicit index enumeration boundary. Measure any
reranker or score threshold against the existing lexical/vector/hybrid corpus
before making it part of the default policy.
