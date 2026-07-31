# RAG Retrieval Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a reproducible, LLM-free lexical retrieval baseline for Modelable documentation.

**Architecture:** A pure evaluation module consumes `DocumentationRetriever` results and stable external-ID relevance cases. A Click adapter loads YAML cases and renders a human or JSON report; it does not own metric calculations.

**Tech Stack:** Python 3.14, dataclasses, PyYAML, Click, pytest, uv, Ruff, mypy baseline ratchet.

## Global Constraints

- Use stable chunk external IDs, never numeric Searchable IDs, as relevance labels.
- Keep evaluation deterministic and independent of LLMs or embeddings.
- Preserve the existing retriever and index format.
- Run all four required checks from `cli/` before completion.

### Task 1: Add evaluation models and metrics

**Files:**
- Create: `cli/src/modelable/rag/evaluation.py`
- Test: `cli/tests/test_rag_evaluation.py`

- [x] Write failing tests for case parsing, Recall@K, MRR, nDCG@10, zero-result, and duplicate-source metrics.
- [x] Run the focused tests and confirm the evaluation module is absent.
- [x] Implement immutable evaluation dataclasses, pure metric helpers, and `evaluate_retrieval`.
- [x] Run focused tests until green.

### Task 2: Add the corpus loader and baseline corpus

**Files:**
- Create: `cli/src/modelable/rag/evaluation_corpus.py`
- Create: `cli/src/modelable/rag/evaluation_corpus.yaml`
- Modify: `cli/src/modelable/rag/__init__.py`
- Test: `cli/tests/test_rag_evaluation.py`

- [x] Load and validate YAML cases with non-empty questions and relevant IDs.
- [x] Add 50 representative cases covering configuration, concepts, troubleshooting, migration, architecture, API usage, and examples.
- [x] Assert corpus count and stable ID shape in tests.
- [x] Run the corpus tests.

### Task 3: Add the reproducible CLI report

**Files:**
- Create: `cli/src/modelable/commands/docs_eval.py`
- Modify: `cli/src/modelable/cli.py`
- Test: `cli/tests/test_cli_docs_eval.py`
- Modify: `docs/cli-reference.md`

- [x] Write failing CLI tests for human and JSON output plus invalid corpus input.
- [x] Register `docs-eval INDEX CORPUS` with `--limit` and `--json`.
- [x] Render all metrics with stable names and JSON keys.
- [x] Document lexical-baseline usage and the LLM-free constraint.
- [x] Run focused CLI tests.

### Task 4: Verify and hand off

- [x] Run the complete repository gate and strict docs build.
- [x] Run doc/spec review and inspect the full diff for scope compliance.
- [ ] Commit and publish the branch.
