# Language Server Protocol (LSP) Specification

> **Status:** Placeholder — deferred from `idl-parser-implementation-plan.md` and `idl-design-spec.md`.
>
> **Scope:** IDE support for `.mdl` files via `pygls`.

## Purpose

Define the LSP capabilities, message handlers, and federation-aware features for the Modellable language server.

## Capabilities

| Capability | MVP | Deferred |
|---|---|---|
| Syntax highlighting | Yes | — |
| Diagnostics (parse errors, semantic validation) | Yes | — |
| Go-to-definition (field → source model) | Yes | — |
| Find references | Yes | — |
| Auto-complete fields, types, model names | Yes | — |
| Hover (type info, lineage) | Yes | — |
| Rename refactoring | — | Post-MVP |
| Code actions (quick fixes) | — | Post-MVP |

## Federation Features

- Resolve `import domain … from registry "…"` against the local `mirror/` directory.
- Autocomplete foreign model names, field names, and version numbers from the mirror.
- Warn when an import references a peer not declared in `workspace.mdl`.
- Error when a `#`-pinned reference does not match the mirrored model.

## Dependencies

- `idl-design-spec.md` §5.2 — LSP references
- `distributed-lineage-spec.md` — registry and mirror semantics
