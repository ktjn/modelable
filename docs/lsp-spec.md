# Language Server Protocol Specification

> **Status:** Approved for a first Phase 1 editor slice focused on diagnostics, workspace indexing, and workspace-aware completion, with federation features deferred until distributed mode.
>
> **Scope:** IDE support for `.mdl` files via a `pygls` language server.

## 1. Purpose

The Modelable language server gives authors fast feedback while editing `.mdl` files. It reuses the same parser, transformer, semantic validator, and registry index logic as the CLI so IDE diagnostics match `modelable validate`.

The LSP is an authoring aid. It must not become a separate source of validation rules.

## 2. Architecture

```text
Editor
  -> LSP JSON-RPC
  -> modelable-lsp server
  -> in-memory workspace index
  -> Lark parser + semantic validator
  -> diagnostics + hover + go-to-definition + completion + references
```

The server maintains an in-memory index per workspace root:

- Parsed documents.
- Domain declarations.
- Model and projection versions.
- Field tables by model version.
- Projection source aliases.
- Lineage edges for valid projections.
- Import and peer metadata when distributed mode is enabled.

The index is rebuilt incrementally for changed files and fully rebuilt when `workspace.mdl` changes.

## 3. Capabilities

| Capability | First slice | Deferred |
|---|---:|---|
| Syntax diagnostics | Yes | — |
| Semantic diagnostics | Yes | — |
| Hover for model and field summaries | Yes | — |
| Go-to-definition for model, projection, and field references | Yes | — |
| Completion for keywords and annotations | Yes | — |
| Completion for model, projection, and field names | Yes | — |
| Find references for model and field usage | Yes | — |
| Document symbols | — | Post-MVP |
| Workspace symbols | — | Post-MVP |
| Formatting | — | Post-MVP |
| Rename refactoring | — | Post-MVP |
| Code actions | — | Post-MVP |
| Federation-aware completion from mirrors | — | Post-MVP |

## 4. Diagnostics

The LSP reports the same diagnostic families as the CLI:

| Code Prefix | Source |
|---|---|
| `PARSE` | Lark parse errors |
| `SEM` | Semantic validation |
| `CEL` | CEL expression validation |
| `COMPAT` | Version and compatibility checks |
| `GOV` | Ownership, access, and classification checks |
| `FED` | Distributed import and content signature checks |

Diagnostics must include enough context to fix the issue without running the CLI: message, range, severity, source, and code.

Severity mapping:

- Error: blocks `modelable validate`.
- Warning: accepted by default but fails `modelable validate --strict`.
- Information: authoring hint only.

## 5. Completion Rules

Completion is read-only and uses the current in-memory workspace snapshot. The first slice offers:

- language keywords
- annotations
- domain names from the open workspace
- model and projection names from the open workspace
- field names from the active model or projection declaration

The server uses deterministic, scope-aware heuristics to keep suggestions narrow and stable rather than noisy.

Reference search is also read-only and uses the same workspace snapshot. The first slice covers:

- exact model and projection references by qualified name
- source field references resolved through projection aliases
- optional inclusion of the declaration location when requested by the client

## 6. Hover and Definition

Hover content in the first slice includes:

- Model and projection declarations: domain, kind, version, and change kind.
- Model fields: type, optionality, key flag, PII flag, and classification when available.
- Projection fields: source mapping or computed expression.

Go-to-definition in the first slice covers model declarations, projection declarations, and field declarations within the current workspace.

## 7. Federation Behavior

When `workspace.mdl` contains a `registry` block, the first slice does not fetch peers itself. Distributed mirror reads stay deferred until the later federation-aware editor work.

## 8. Performance Requirements

- Parse and diagnose a changed file in under 250 ms for typical files under 2,000 lines.
- Rebuild a workspace index for 1,000 `.mdl` files in under 5 seconds on a developer laptop.
- Debounce diagnostics by 150-300 ms while typing.
- Cache parsed trees and invalidate by file content hash.

## 9. Open Decisions

- Whether the LSP parser should remain Earley or move to LALR once the grammar stabilizes.
- Whether formatting is provided by the language server or a separate CLI command.
- Whether quick fixes should be generated from validation diagnostics or authored manually per diagnostic code.

## 10. Acceptance Criteria

- Opening a workspace reports parse and semantic diagnostics matching `modelable validate`.
- The first slice rebuilds an in-memory workspace index as files change.
- Hover shows model, projection, and field summaries for the current file.
- Go-to-definition jumps to the declaration for models, projections, and fields in the current workspace.
- Completion shows keywords, annotations, and workspace names without mutating state.
- Reference search finds model, projection, and field usages in the current workspace.
- Distributed imports are diagnosed against local mirrors in a later federation-aware slice.

## 11. Dependencies

- `idl-design-spec.md` — language syntax
- `distributed-lineage-spec.md` — registry and mirror semantics
- `cel-integration-spec.md` — expression diagnostics and lineage extraction
- `cli-spec.md` — validation behavior shared with the CLI
