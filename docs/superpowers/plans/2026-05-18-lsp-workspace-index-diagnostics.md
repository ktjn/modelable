# LSP Workspace Index and Diagnostics Implementation Plan

**Date:** 2026-05-18  
**Status:** Ready for review  
**Scope:** Phase 1 editor support

## Goal

Add a first LSP slice for Modelable that gives `.mdl` authors CLI-matching syntax and semantic diagnostics in the editor, backed by a shared in-memory workspace index. The server must reuse the same parser, semantic validation, CEL validation, compatibility, lineage, and governance logic as the CLI so the IDE never becomes a separate source of truth.

This plan intentionally starts with diagnostics and workspace indexing, and the first shipped slice also includes basic hover summaries for model and field references. Completion, go-to-definition, references, rename, formatting, and federation-aware mirror reads remain for later iterations.

## Source Documents

The implementation must follow these documents:

- `docs/modelable-system-spec.md`
- `docs/lsp-spec.md`
- `docs/cli-spec.md`
- `docs/cel-integration-spec.md`
- `docs/idl-parser-implementation-plan.md`
- `docs/agent-governance.md`

## Proposed Stack

- `pygls>=2.1.1,<3` for the language server runtime and LSP protocol plumbing.
- Existing Modelable parser, semantic validation, compiler workspace, and registry code.
- `uv` for dependency management and test execution in `cli/`.

## Milestone 1: Shared Diagnostics Core

**Goal:** Introduce a structured diagnostic model that the CLI and LSP can both consume.

**Primary files:**

- `cli/src/modelable/diagnostics/__init__.py`
- `cli/src/modelable/diagnostics/model.py`
- `cli/src/modelable/parser/parse.py`
- `cli/src/modelable/validation/semantic.py`
- `cli/src/modelable/compiler/workspace.py`
- `cli/tests/test_diagnostics.py`

**Tasks:**

- [x] Add a structured diagnostic type that captures code, message, severity, file path, line, column, and optional end position.
  - Introduce a model such as:

    ```python
    @dataclass(frozen=True)
    class Diagnostic:
        code: str
        message: str
        severity: Literal["error", "warning", "information"]
        path: str
        line: int | None = None
        column: int | None = None
        end_line: int | None = None
        end_column: int | None = None
    ```

- [x] Refactor parse and semantic validation paths so they can return structured diagnostics instead of only strings.
  - Keep the existing CLI behavior stable by rendering those diagnostics back to human-readable Rich output.
  - Preserve current error codes and messages where possible so existing tests continue to pass with minimal churn.

- [x] Add a small adapter that converts structured diagnostics to the current CLI reporting format.

- [x] Add unit tests that cover:
  - parse errors with file and line information
  - semantic errors with file and line information
  - warnings and information-level findings remaining non-fatal

**Acceptance checks:**

```bash
cd cli
uv run pytest tests/test_diagnostics.py tests/test_grammar.py tests/test_semantic.py tests/test_cli.py
```

## Milestone 2: In-Memory Workspace Inputs

**Goal:** Make the compiler workspace loader work with editor buffers, not only files on disk.

**Primary files:**

- `cli/src/modelable/compiler/workspace.py`
- `cli/src/modelable/lsp/workspace.py`
- `cli/tests/test_workspace.py`
- `cli/tests/test_lsp_workspace.py`

**Tasks:**

- [x] Introduce a document-source abstraction for workspace loading.
  - Support on-disk files and in-memory text with stable URIs.
  - Keep file discovery behavior unchanged for the CLI.

- [x] Refactor workspace loading so it can accept a list of document sources.
  - Preserve the existing `load_workspace(path)` CLI entrypoint.
  - Add a memory-backed path for unsaved LSP buffers.

- [x] Build a workspace index that stores:
  - parsed documents
  - document hashes
  - domain declarations
  - model and projection versions
  - field tables
  - projection source aliases
  - lineage edges
  - diagnostic output per document

- [x] Ensure a changed document can be reindexed independently, while a `workspace.mdl` change still triggers a full rebuild.

- [x] Add tests for:
  - indexing a single in-memory document
  - indexing a multi-document workspace
  - cache invalidation by content hash
  - a full rebuild when `workspace.mdl` changes

**Acceptance checks:**

```bash
cd cli
uv run pytest tests/test_workspace.py tests/test_lsp_workspace.py
```

## Milestone 3: LSP Server Scaffold

**Goal:** Add a minimal `pygls` server that opens a workspace, tracks document changes, and publishes diagnostics.

**Primary files:**

- `cli/pyproject.toml`
- `cli/src/modelable/lsp/__init__.py`
- `cli/src/modelable/lsp/__main__.py`
- `cli/src/modelable/lsp/server.py`
- `cli/src/modelable/lsp/diagnostics.py`
- `cli/src/modelable/commands/lsp.py`
- `cli/src/modelable/cli.py`
- `cli/tests/test_lsp_server.py`

**Tasks:**

- [x] Add `pygls>=2.1.1,<3` to the CLI runtime dependencies in `cli/pyproject.toml`.

- [x] Create an LSP command entrypoint:

  ```python
  @click.command("lsp")
  def lsp() -> None:
      ...
  ```

- [x] Implement the server bootstrap and lifecycle handlers:
  - `initialize`
  - `did_open`
  - `did_change`
  - `did_close`
  - `workspace/did_change_watched_files` only if needed for the first slice

- [x] Wire diagnostics publishing to the shared diagnostic core.
  - Parse diagnostics must use the same message and severity mapping as the CLI.
  - Semantic diagnostics must be emitted with ranges when available.

- [x] Keep the server stateless outside the workspace cache and per-document index.

- [x] Add tests that verify:
  - the server starts
  - open/change events update the workspace cache
  - diagnostics are published for invalid input
  - valid documents clear stale diagnostics

**Acceptance checks:**

```bash
cd cli
uv run pytest tests/test_lsp_server.py tests/test_lsp_workspace.py tests/test_diagnostics.py
```

## Milestone 4: CLI and Documentation Integration

**Goal:** Make the new LSP command discoverable and document the first slice clearly.

**Primary files:**

- `docs/lsp-spec.md`
- `docs/README.md`
- `README.md`
- `docs/mvp-implementation-plan.md`

**Tasks:**

- [x] Update the LSP spec to state that the first shipped slice covers diagnostics, workspace indexing, and basic hover summaries, not completion or go-to-definition.

- [x] Add a brief `modelable lsp` usage example to the docs.

- [x] Update the implementation-plan docs to link the new LSP slice and keep the staged rollout explicit.

- [x] Verify the documentation stays aligned with the system spec language and does not overpromise editor features.

**Acceptance checks:**

```bash
git diff --check
```

## Milestone 5: Verification Gate

**Goal:** Prove the first LSP slice behaves the same way as the CLI for invalid and valid workspace state.

**Tasks:**

- [x] Run the focused LSP and shared-diagnostics tests.
- [x] Run the full local CLI test suite from `cli/`.
- [x] Run `modelable validate ../samples/mvp` to confirm the MVP sample remains healthy after the shared workspace refactor.
- [x] Review the final diff for any fallback logic that would make the CLI and LSP drift apart.

**Required commands:**

```bash
cd cli
uv run pytest tests/test_diagnostics.py tests/test_workspace.py tests/test_lsp_workspace.py tests/test_lsp_server.py tests/test_semantic.py tests/test_cli.py
uv run pytest tests/ -v
uv run modelable validate ../samples/mvp
```

## Assumptions

- The first LSP release is diagnostics-first and does not need completion, go-to-definition, references, or formatting to be useful.
- The shared diagnostic model will be introduced once and reused by both CLI and LSP entrypoints.
- The workspace index should be reusable later for completion and symbol queries, so it must retain document-level and symbol-level structure rather than only flattened diagnostics.
- `pygls` is the right runtime for the current Python CLI stack and should be added only after the dependency version is confirmed.

## Out of Scope

- Completion, go-to-definition, references, rename, formatting, and code actions.
- Federation-aware mirror reads and distributed sync UX.
- Non-editor LSP features beyond diagnostics and workspace index maintenance.
