# LSP Workspace-Aware Completion Design

**Date:** 2026-05-18  
**Status:** Draft  
**Scope:** Next LSP slice for Phase 1 editor support

## Goal

Ship a completion engine for `modelable-lsp` that helps authors write `.mdl` files faster by offering workspace-aware suggestions. The first completion slice should reuse the existing LSP workspace index and stay read-only.

The initial deliverable is intentionally narrow:

- suggest language keywords and annotations from a small static list
- suggest domain, model, and projection names from the current workspace
- suggest field names when the cursor is inside a model or projection scope
- keep completion logic deterministic and testable
- avoid expression-aware completion, import-based completion, or rename coupling for now

## Non-Goals

This design does not implement:

- expression-aware completion inside CEL or mapping expressions
- import path completion
- reference search
- rename refactoring
- code actions
- formatting
- signature help
- schema discovery outside the open workspace
- federation-aware completion from mirrors

Those features may be useful later, but they are not part of the first completion slice.

## Why This Slice First

Three approaches were considered:

| Approach | Tradeoff | Decision |
|---|---|---|
| Syntax-first completion | Fastest to ship, but only offers generic keywords and snippet-like help. | Rejected as too limited for real workspace authoring. |
| Workspace-aware names | Adds keywords plus names and fields from the open workspace, which is high-value and still bounded. | Chosen. |
| Full semantic completion | Could include expression and import intelligence, but it depends on more infrastructure and risks scope creep. | Rejected for the first slice. |

Workspace-aware completion gives immediate value because authors usually need the names and fields that already exist in their current workspace. It also reuses the same workspace index that diagnostics and hover already depend on.

## Architecture

```text
Editor
  -> LSP JSON-RPC
  -> modelable-lsp
  -> workspace index
  -> context detection
  -> completion candidate builder
  -> completion items returned to the editor
```

The server should remain thin. It should not re-parse or re-derive symbols in a second, separate pipeline. Completion should be a read-only query over the current workspace snapshot.

### Components

#### 1. Completion trigger detector

Responsibilities:

- Determine whether the cursor is in a keyword, annotation, type, declaration, or field position.
- Recognize common edit contexts such as:
  - after `domain`
  - after `entity`, `aggregate`, `event`, `value`, or `projection`
  - after `from`, `join`, or `as`
  - inside a model field list
  - inside a projection field list

Dependencies:

- current document text
- cursor position

#### 2. Workspace symbol source

Responsibilities:

- Provide names from the active workspace index:
  - domain names
  - model names
  - projection names
  - field names for the active declaration
- Filter suggestions to the current scope where possible.

Dependencies:

- `LspWorkspaceIndex`
- current workspace snapshot

#### 3. Static keyword and annotation source

Responsibilities:

- Return a small fixed set of language suggestions:
  - `domain`
  - `entity`
  - `aggregate`
  - `event`
  - `value`
  - `projection`
  - `from`
  - `join`
  - `as`
  - `group by`
  - `@key`
  - `@pii`
  - `@classification`
  - `@deprecated`
  - `@owner`
  - `@server`

Dependencies:

- none beyond the static list

#### 4. Completion adapter

Responsibilities:

- Convert internal candidates into `lsprotocol` completion items.
- Set label, insert text, kind, and sort order.
- Return a partial or full completion response depending on context.

Dependencies:

- completion candidate builder
- LSP protocol types

## Data Flow

1. The editor requests completion at a cursor position.
2. The server reads the active document from the workspace cache.
3. The completion trigger detector classifies the local context.
4. The workspace symbol source gathers names and fields from the current index.
5. The static keyword source adds the fixed language suggestions.
6. The adapter converts candidates into LSP completion items.
7. The editor receives only the suggestions relevant to the current scope.

The server should favor deterministic ranking:

- exact scope matches first
- workspace names next
- static keywords and annotations after that

## Completion Rules

### Keyword completion

The server should offer keywords and annotations when the cursor is in a declaration or annotation context. These suggestions should be stable and minimal, with no generated prose.

### Model and projection name completion

When the cursor is in a type-like or reference-like position, the server should suggest names available in the current workspace. The first slice should focus on names that already exist in the opened workspace rather than trying to infer project-wide semantics.

### Field completion

When the cursor is inside a model or projection body, the server should suggest field names from the active declaration where available. The field list should come from the current workspace snapshot, not from a separate symbol index.

### Scope detection

The first implementation may use a small amount of line-based heuristics to identify completion context. That is acceptable if:

- it is deterministic
- it is covered by tests
- it can be replaced later with richer parsing if needed

### Ranking and filtering

Suggestions should be filtered aggressively rather than over-generated. If a context is ambiguous, the server should return fewer, more relevant items instead of a noisy superset.

## Error Handling

Completion should fail safely:

- If the workspace is unavailable, return no suggestions.
- If the document is outside the workspace cache, return no suggestions.
- If scope detection is uncertain, prefer a small candidate list.
- If the workspace contains duplicate names, return deterministic ordering rather than trying to disambiguate in the first slice.

Completion should never mutate workspace state or trigger validation side effects.

## Compatibility With CLI Behavior

This feature does not change CLI validation or compiler behavior. It only surfaces editor suggestions based on the same workspace graph the CLI already understands.

That means:

- no new semantics for `.mdl`
- no relaxed validation in the server
- no LSP-only language rules
- no generated code paths that bypass the shared parser or index

## Incremental Strategy

The first completion slice can start with coarse-grained workspace reads:

- refresh suggestions on each completion request
- use the current in-memory index as the only source of truth
- avoid caching a separate completion graph until the feature proves useful

Later slices may add a dedicated symbol cache or more precise parsing if performance data shows it is needed.

## Testing Strategy

The first completion slice should be covered with focused tests for:

- keyword suggestions in declaration contexts
- model, projection, and field name suggestions from the current workspace
- scope detection for model bodies and projection bodies
- deterministic ordering of completion items
- no-suggestion behavior outside known contexts
- no-suggestion behavior when the workspace is unavailable

Suggested test shapes:

- unit tests for context detection and candidate building
- integration tests using small in-memory `.mdl` workspaces
- regression tests that verify suggestions stay stable for representative sample files

## Open Decisions

- Whether completion should return snippets for common declaration templates in the first slice or stay label-only.
- Whether the completion adapter should eventually use `CompletionItemKind` distinctions for keywords, fields, models, and projections.
- Whether completion ranking should become frequency-aware once the workspace index is richer.

## Success Criteria

The first completion slice is successful when:

- typing in a `.mdl` file offers relevant keyword, name, and field suggestions from the open workspace
- suggestions are deterministic across repeated requests on the same document state
- completion does not require re-running the CLI
- completion does not produce noisy cross-scope candidates that would confuse authors
