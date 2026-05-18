# Language Server Protocol Specification

> **Status:** Approved for a first Phase 1 editor slice focused on diagnostics, workspace indexing, workspace-aware completion, local mirror-aware name completion, and raw-text federation diagnostics, with peer fetch/writeback behavior still deferred.
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
  -> diagnostics + hover + go-to-definition + completion + references + document symbols + workspace symbols + formatting + rename + code actions
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
| Document symbols | Yes | — |
| Workspace symbols | Yes | — |
| Formatting | Yes | — |
| Rename refactoring | Yes | — |
| Code actions | Yes | Narrow quick-fix slice |
| Federation-aware completion from mirrors | Yes | Local mirror cache only |

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
- mirrored domain, model, and projection names from the local `.modelable/mirror/` cache when available
- mirrored version numbers for pinned foreign references when the current buffer is already inside an `@` version clause, including typed digits such as `@1`
- mirrored model and projection names after `at <domain>.<prefix>` in pinned imports
- mirrored field names for alias references on `from` and `join` lines, including typed prefixes such as `s.su`, that point at mirrored foreign models

The server uses deterministic, scope-aware heuristics to keep suggestions narrow and stable rather than noisy.

Reference search is also read-only and uses the same workspace snapshot. The first slice covers:

- exact model and projection references by qualified name
- source field references resolved through projection aliases
- optional inclusion of the declaration location when requested by the client

Document symbols are also read-only and use the current file snapshot. The first slice covers:

- domains as top-level outline entries
- model and projection declarations nested under their owning domain
- fields nested under their owning declaration

Workspace symbols are also read-only and query the current workspace snapshot. The first slice covers:

- filtered domain names
- filtered model and projection names
- filtered field names from the current workspace

Formatting is also read-only and rewrites indentation based on brace nesting. The first slice covers:

- whole-document reindentation
- stable two-space indentation when the client requests spaces
- stable tab indentation when the client requests tabs

Rename refactoring is workspace-aware and rewrites the declaration plus exact qualified or aliased references for the targeted symbol. The first slice covers:

- model and projection declarations
- model fields and their source-field references
- deterministic workspace edits for the current open workspace

Code actions are limited to deterministic quick fixes derived from parser failures. The first slice covers:

- inserting a missing closing brace when a parse error reaches end-of-input
- inserting `@key` for entity or aggregate models that are missing an identity field
- returning a single `QuickFix` action for the current buffer snapshot

## 6. Hover and Definition

Hover content in the first slice includes:

- Model and projection declarations: domain, kind, version, and change kind.
- Model fields: type, optionality, key flag, PII flag, and classification when available.
- Projection fields: source mapping or computed expression.

Go-to-definition in the first slice covers model declarations, projection declarations, and field declarations within the current workspace.

## 7. Federation Behavior

The server does not fetch peers itself. If a local mirror cache is present on disk, completion may reuse those mirrored names without mutating workspace state.

Import declarations and pinned foreign references are scanned from the current buffer text. The first slice reports:

- warnings when an import references a peer that is not declared in `workspace.mdl`
- errors when the imported domain is not present in the local mirror cache
- errors when a pinned reference target is not present in the local mirror cache
- errors when a `#`-pinned import or projection reference does not match the cached mirror signature

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
- Document symbols provide a nested outline for the current file.
- Workspace symbols search the open workspace without changing state.
- Formatting normalizes indentation without changing semantics.
- Rename refactoring updates the targeted symbol and its references in the open workspace.
- Code actions provide a narrow quick fix for unterminated blocks.
- Completion can include names from the local mirror cache without fetching peers.
- Distributed imports and pinned foreign references are diagnosed against local mirrors in the current buffer without fetching peers.

## 11. Dependencies

- `idl-design-spec.md` — language syntax
- `distributed-lineage-spec.md` — registry and mirror semantics
- `cel-integration-spec.md` — expression diagnostics and lineage extraction
- `cli-spec.md` — validation behavior shared with the CLI
