# LLM Integration Specification

> **Status:** Placeholder — deferred from `idl-parser-implementation-plan.md` and `idl-design-spec.md`.
>
> **Scope:** AI-powered commands (`generate`, `describe`, `transform`, `suggest-projection`).

## Purpose

Define the prompt engineering strategy, model selection, context window management, and safety guardrails for LLM-assisted Modellable authoring.

## Commands

| Command | Input | Output |
|---|---|---|
| `modellable generate --from "<description>"` | Freeform text or DDL/JSON Schema | `.mdl` file |
| `modellable describe <PATH>` | `.mdl` file | Natural-language summary + governance metadata |
| `modellable transform <Entity>@<v> --to <target> --explain` | Model reference + target format | Artifact + explanation |
| `modellable suggest-projection --source <Entity>@<v> --consumer <domain>` | Source model + consumer domain | Proposed projection `.mdl` |

## Open Questions

- Model version pinning (`claude-opus-4-7` vs. always-latest).
- Token budget for large domains (context window limits).
- Retry and fallback strategy for API failures.
- How to validate generated `.mdl` before presenting to the user.

## Dependencies

- `cli-spec.md` §3.7 — AI integration
- `idl-design-spec.md` §5.1 — transform and suggest-projection semantics
