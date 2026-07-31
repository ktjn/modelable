# RAG Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an evidence-only RAG answer pipeline and CLI over documentation retrieval.

**Architecture:** `modelable.rag.generation` owns context budgeting, prompt construction, citation labels, and answer shaping. It depends only on Modelable's retriever and the existing `LLMProvider` contract; provider transport remains in `modelable.llm.providers`.

**Tech Stack:** Python 3.14, dataclasses, Click, existing LLM provider types, pytest, uv, Ruff, mypy baseline ratchet.

## Global Constraints

- Never cite numeric Searchable IDs to users.
- Never call an LLM when retrieval returns no evidence.
- Never silently truncate a retrieved chunk; context budgeting may omit whole chunks.
- Keep prompts and citation formatting independent of Searchable client internals.
- Run all four required checks from `cli/` before completion.

### Task 1: Add the pure generation pipeline

**Files:**
- Create: `cli/src/modelable/rag/generation.py`
- Modify: `cli/src/modelable/rag/__init__.py`
- Test: `cli/tests/test_rag_generation.py`

- [x] Write failing tests for evidence prompt labels, whole-chunk budgeting, insufficient evidence, fake-provider calls, and citation rendering.
- [x] Run the focused tests and confirm the generation module is absent.
- [x] Implement `RagAnswer`, citation types, prompt construction, and `answer_with_retrieval`.
- [x] Run focused tests until green.

### Task 2: Add the `docs-ask` CLI

**Files:**
- Create: `cli/src/modelable/commands/docs_ask.py`
- Modify: `cli/src/modelable/cli.py`
- Test: `cli/tests/test_cli_docs_ask.py`
- Modify: `docs/cli-reference.md`

- [x] Write failing tests for provider-backed text output, JSON output, and empty retrieval.
- [x] Register `docs-ask INDEX QUESTION` and resolve provider flags through existing conventions.
- [x] Render structured sources separately in JSON and as a source block in text.
- [x] Document evidence-only behavior and options.
- [x] Run focused CLI tests.

### Task 3: Verify and hand off

- [x] Run the complete repository gate and strict docs build.
- [x] Run doc/spec review and inspect scope.
- [x] Commit and publish the branch.
