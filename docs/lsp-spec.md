# Language Server Protocol Specification

> **Status:** Approved for Phase 1 editor support, with federation features deferred until distributed mode.
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
  -> diagnostics, completion, hover, definition, references
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

| Capability | Phase 1 | Deferred |
|---|---:|---|
| Syntax diagnostics | Yes | — |
| Semantic diagnostics | Yes | — |
| Completion for keywords and annotations | Yes | — |
| Completion for model names and fields | Yes | — |
| Hover for fields, types, ownership, classification, and lineage | Yes | — |
| Go-to-definition for models, projections, fields, and imports | Yes | — |
| Find references for model and field usage | Yes | — |
| Document symbols | Yes | — |
| Workspace symbols | Yes | — |
| Formatting | Minimal indentation normalization | Full formatter |
| Rename refactoring | — | Post-MVP |
| Code actions | — | Post-MVP |
| Federation-aware completion from mirrors | Basic mirror reads | Rich sync UX |

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

Completion is context-sensitive:

- Top-level: `workspace`, `import`, `domain`, `binding`.
- Domain body: `entity`, `aggregate`, `event`, `value`, `projection`, `auto projections`, `generate`.
- Field declaration: annotations, field names, built-in types, local `value` types.
- Projection source clauses: known domains, models, versions, aliases.
- Projection body: source alias fields and CEL function names.
- Binding block: known model/projection references and adapter names declared in adapter capability metadata.

Completion must never invent models, fields, or versions that are not present in the workspace index or mirror.

## 6. Hover and Definition

Hover content:

- Model or projection: domain, kind, version, change kind, owner, status.
- Field: type, optionality, annotations, classification, owner, lineage.
- Projection mapping: source field list and transformation expression.
- Binding: adapter target and capability summary.

Go-to-definition:

- `customer.Customer @ 2` opens the declaration of `Customer @ 2`.
- `c.email` opens the `email` field in the source model bound to alias `c`.
- `import domain customer` opens the local mirror file when distributed mode is enabled.

## 7. Federation Behavior

When `workspace.mdl` contains a `registry` block:

- The server reads mirror files from `.modelable/mirror/<peer-registry-id>/`.
- It does not fetch peers itself in Phase 1. Users run `modelable registry sync` or `modelable compile`.
- It warns when an imported peer is not declared in `workspace.mdl`.
- It errors when a `#`-pinned content signature does not match the mirrored model.
- It marks stale mirrors as warnings when the mirror metadata records an out-of-date git SHA.

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
- Completion suggests existing domains, models, versions, aliases, and fields.
- Hover shows field type, classification, owner, and lineage when available.
- Go-to-definition works for model references and projection source fields.
- Distributed imports are diagnosed against local mirrors without requiring a running registry server.

## 11. Dependencies

- `idl-design-spec.md` — language syntax
- `distributed-lineage-spec.md` — registry and mirror semantics
- `cel-integration-spec.md` — expression diagnostics and lineage extraction
- `cli-spec.md` — validation behavior shared with the CLI
