# RAG Retrieval Baseline Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the lexical retrieval baseline measurable and diagnosable before generation work begins.

**Architecture:** Evaluation remains a pure consumer of `DocumentationRetriever`. It groups results by case category, records misses, and renders diagnostics. The retriever only normalizes punctuation; ranking remains Searchable's responsibility.

**Tech Stack:** Python 3.14, dataclasses, PyYAML, Click, pytest, uv, Ruff, mypy baseline ratchet.

## Global Constraints

- Do not add embeddings, vector search, prompts, LLM calls, or reranking.
- Keep stable external IDs as the only relevance labels.
- Preserve the existing public retriever result shape and Searchable index format.
- Run all four required checks from `cli/` before completion.

### Task 1: Add categorized diagnostics

**Files:**
- Modify: `cli/src/modelable/rag/evaluation.py`
- Modify: `cli/src/modelable/rag/__init__.py`
- Modify: `cli/src/modelable/commands/docs_eval.py`
- Test: `cli/tests/test_rag_evaluation.py`
- Test: `cli/tests/test_cli_docs_eval.py`

- [x] Add category metrics and failed-query records test-first.
- [x] Parse optional categories, defaulting to `challenge`.
- [x] Render category summaries and failed-query diagnostics in text and JSON.

### Task 2: Harden natural-language queries and corpus

**Files:**
- Modify: `cli/src/modelable/rag/retriever.py`
- Modify: `cli/tests/test_rag_retriever.py`
- Modify: `cli/src/modelable/rag/evaluation_corpus.yaml`

- [x] Add a punctuation-normalization regression test.
- [x] Normalize ordinary query punctuation before Searchable search.
- [x] Split the corpus into 25 controlled lexical cases and 25 paraphrase challenges.
- [x] Run the real index evaluation and record both category results.

### Task 3: Document and verify

- [x] Add this design and plan documentation.
- [x] Update CLI documentation with category and diagnostic behavior.
- [x] Run the full repository gate, strict docs build, and doc/spec review.
- [x] Commit and publish the branch.
