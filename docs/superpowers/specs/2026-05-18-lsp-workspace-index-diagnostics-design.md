# LSP Workspace Index and Diagnostics Design

**Date:** 2026-05-18
**Status:** Draft
**Scope:** First LSP slice for Modelable Phase 1 editor support

## Goal

Ship a minimal `modelable-lsp` server that gives `.mdl` authors fast, CLI-matching diagnostics in the editor. The first slice must reuse the existing parser, semantic validator, CEL checks, compatibility logic, and governance logic instead of re-implementing validation rules inside the server.

The initial deliverable is intentionally narrow:

- Track opened `.mdl` documents in memory.
- Maintain a workspace index keyed by file content hash.
- Rebuild affected documents on change.
- Publish diagnostics that match `modelable validate` as closely as possible.
- Keep the architecture open for hover, completion, go-to-definition, and references later.

## Non-Goals

This first slice does not implement:

- completion
- hover
- go-to-definition
- references
- rename
- code actions
- formatting
- federation-aware mirror reads
- background syncing with remote registries

Those features are represented in the LSP spec, but they are not part of this design’s implementation scope.

## Why This Slice First

Three approaches were considered:

| Approach | Tradeoff | Decision |
|---|---|---|
| Diagnostics only | Fastest path to editor feedback, but no shared state structure for future features. | Rejected as too shallow for follow-on LSP work. |
| Workspace index + diagnostics | Slightly more work up front, but creates the shared foundation needed for every later editor feature. | Chosen. |
| Hover/completion first | Feels interactive, but depends on the same index and document model anyway. | Rejected as the wrong dependency order. |

The workspace index is the durable piece. Once it exists, later features can query it instead of re-parsing documents independently.

## Architecture

```text
Editor
  -> LSP JSON-RPC
  -> modelable-lsp
  -> workspace manager
  -> document cache + content hashes
  -> shared parser / validator / planner
  -> diagnostics published back to the editor
```

The server is a thin orchestration layer. It owns document lifecycle, cache invalidation, and transport concerns. Validation remains in the shared compiler stack.

### Components

#### 1. Workspace manager

Responsibilities:

- Track open documents by URI.
- Record the current text, version, and content hash for each file.
- Map a workspace root to its indexed files.
- Decide whether a change affects one file or requires a full workspace rebuild.

Dependencies:

- document cache
- file system watcher or LSP change notifications

#### 2. Document cache

Responsibilities:

- Store parsed source text and content hashes.
- Avoid re-validating unchanged files.
- Provide a stable snapshot for diagnostics and future symbol queries.

Dependencies:

- file text from LSP didOpen/didChange
- shared parsing entrypoint

#### 3. Shared validation bridge

Responsibilities:

- Reuse the CLI parsing and validation pipeline.
- Convert parse and semantic failures into LSP diagnostics.
- Preserve the same diagnostic codes and message text where practical.

Dependencies:

- `load_workspace`
- parse errors
- semantic validation errors
- CEL, compatibility, and governance checkers

#### 4. Index view

Responsibilities:

- Hold derived facts needed by future LSP features:
  - domains
  - models
  - projections
  - field names
  - aliases
  - lineage edges

In the first slice, the index exists primarily to support efficient diagnostic refresh and to establish a stable internal shape for later features.

## Data Flow

1. The editor opens a `.mdl` file.
2. The server stores the text in the document cache and computes a content hash.
3. The workspace manager identifies the affected file set.
4. The shared compiler pipeline parses and validates the affected workspace snapshot.
5. The server converts any failures into LSP diagnostics with ranges and severity.
6. The diagnostics are published for the changed document.

On workspace-affecting changes, such as `workspace.mdl`, the server should rebuild the entire index rather than attempting to do a narrow incremental update.

## Error Handling

Diagnostics must carry enough information to be actionable in the editor:

- message
- severity
- file range
- source code family
- stable diagnostic code when available

Severity mapping:

- parse and semantic errors become `Error`
- strict-mode-only issues become `Warning`
- informational hints remain `Information`

The server should never silently swallow parse or validation failures. If the shared CLI pipeline rejects the workspace, the editor must show that failure.

## Compatibility With CLI Behavior

The LSP must reuse the same validation logic as the CLI.

That means:

- no duplicate validation rules in the server
- no server-specific interpretation of model semantics
- no editor-only relaxation of published-contract semantics

If the CLI says a workspace is invalid, the editor must surface the same invalidity.

## Incremental Strategy

The server rebuilds work in two tiers:

- **Single-file refresh** for ordinary `.mdl` edits.
- **Workspace rebuild** when a root file or registry-related file changes.

The first implementation may start with coarse-grained rebuilds, but it must preserve the document-cache and content-hash structure so later incremental optimization can be added without changing the public protocol behavior.

## Testing Strategy

The first slice should be covered with focused tests for:

- workspace open and change events
- parse error translation
- semantic error translation
- strict-vs-nonstrict severity mapping
- stale document invalidation
- workspace rebuild on `workspace.mdl` changes
- parity with `modelable validate` for the same sample files

Suggested test shapes:

- unit tests for content hashing and cache invalidation
- unit tests for diagnostic translation
- integration tests using the sample MVP workspace
- regression tests confirming the editor diagnostics match CLI failures for representative invalid `.mdl` fixtures

## Open Decisions

- Whether the workspace index should live entirely in memory for Phase 1 or be partially backed by a small on-disk cache.
- Whether the first server package should be `pygls`-based from day one or use a thin LSP transport wrapper around the same internal service layer.
- Whether completion and hover should be introduced immediately after diagnostics or only after workspace indexing is fully stable.

## Success Criteria

The first LSP slice is successful when:

- Opening `samples/mvp/` produces no false-positive diagnostics.
- Opening an invalid `.mdl` file produces parse or semantic diagnostics that match the CLI.
- Editing a file updates diagnostics without requiring a manual CLI run.
- The server maintains a coherent workspace index that later LSP features can query.

