# Documentation Retriever Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Modelable-owned lexical retriever over Searchable documentation indexes.

**Architecture:** `DocumentationRetriever` owns validation and maps Searchable `Hit` objects into the stable `RetrievedChunk` dataclass. Searchable remains responsible for index loading and lexical ranking; no Searchable client types escape the RAG package API.

**Tech Stack:** Python 3.14, dataclasses, `searchable-client>=0.1.0`, pytest, uv, Ruff, mypy baseline ratchet.

## Global Constraints

- Keep vector, hybrid, embedding, reranking, prompting, and LLM work out of scope.
- Preserve Searchable result ordering and complete stored chunk content.
- Use stable `external_id` and URL for future citations; numeric IDs remain internal.
- Reject invalid query input and malformed stored documents rather than silently dropping data.
- Run all four required checks from `cli/` before completion.

### Task 1: Add the client dependency and Modelable result type

**Files:**
- Modify: `cli/pyproject.toml`
- Modify: `cli/uv.lock`
- Create: `cli/src/modelable/rag/retriever.py`
- Test: `cli/tests/test_rag_retriever.py`

- [x] Write failing tests for result mapping and input validation.
- [x] Run the focused tests and confirm they fail because the retriever is absent.
- [x] Add `searchable-client>=0.1.0` and regenerate the lockfile.
- [x] Implement `RetrievedChunk` and `DocumentationRetriever` with injected client support for tests.
- [x] Run focused tests until green.

### Task 2: Add real-index integration coverage

**Files:**
- Modify: `cli/tests/test_rag_retriever.py`
- Modify: `cli/src/modelable/rag/__init__.py`

- [x] Build a one-chunk JSON index with `build_documentation_index`.
- [x] Search it through `DocumentationRetriever` and assert content, metadata, URL, external ID, score, and content hash.
- [x] Export the Modelable-owned retriever types without exporting Searchable client classes.
- [x] Run all RAG tests and the complete required repository gate.

### Task 3: Review and handoff

- [x] Run strict documentation validation and review the diff for scope compliance.
- [x] Commit the implementation and present the branch/PR handoff.
