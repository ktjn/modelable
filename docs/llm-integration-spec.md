# LLM Integration Specification

> **Status:** Approved for CLI-assisted authoring.
>
> **Scope:** AI-powered commands: `generate`, `describe`, `update`, `transform`, `suggest-projection`, and `chat`.

## 1. Purpose

LLM integration helps authors create and understand `.mdl` definitions faster, while preserving Modelable's contract guarantees. AI output is never trusted as authoritative until it passes the normal parser, semantic validator, compatibility checks, and governance checks.

The CLI must make generated changes reviewable and reproducible enough for source control.

## 2. Model Configuration

The AI model is configurable.

Resolution order:

1. Command flag: `--model MODEL`.
2. Environment variable: `MODELABLE_LLM_MODEL`.
3. Workspace config in `workspace.mdl`.
4. CLI default.

Example:

```mdl
workspace "commerce-platform" {
  ai {
    provider: "ollama"
    model:    "llama3.1"
  }
}
```

The current implementation supports a provider-backed local Ollama workflow through `MODELABLE_LLM_PROVIDER=ollama`, `MODELABLE_LLM_MODEL=<installed-model>`, and optional `MODELABLE_LLM_BASE_URL` or `OLLAMA_HOST`. The CLI default remains the deterministic heuristic fallback when no provider is configured. The spec intentionally avoids requiring "latest" because reproducibility matters for generated contract files.

## 3. Commands

| Command | Input | Output | Writes Files |
|---|---|---|---|
| `modelable generate` | Natural language, DDL, JSON Schema, OpenAPI, Avro, Protobuf, or existing `.mdl` context | Proposed `.mdl` | Only with `--output` |
| `modelable describe` | `.mdl` file, directory, model ref, or projection ref | Natural-language summary | No |
| `modelable update` | Model or projection ref plus natural-language edit instruction | Updated `.mdl` | Only with `--output` |
| `modelable transform` | Model/projection ref and target | Artifact plus explanation | Optional `--out` |
| `modelable suggest-projection` | Source ref and consumer domain | Proposed projection `.mdl` | Only with `--output` |
| `modelable chat` | Workspace path, optional ref, and natural-language message | Conversational answer or model-guided edit suggestion | No |

## 4. Prompt Context

System prompt context must include:

- Modelable design principles.
- Current `.mdl` syntax summary.
- Versioning and immutability rules.
- Projection and lineage requirements.
- Governance and classification rules.
- Phase scope, so the model does not emit unsupported runtime commitments for Phase 1 tasks.

User/workspace context may include:

- Relevant source `.mdl` files.
- Selected model or projection definitions.
- Compiler diagnostics.
- Target format constraints.
- Existing sample scenario snippets.

The CLI must avoid sending secrets. Binding values that look like credentials, tokens, private keys, or passwords are redacted before prompt construction.

## 5. Validation Pipeline

When a command produces `.mdl`, the CLI validates it before writing:

```text
LLM response
  -> extract fenced mdl block or full response
  -> parse with Lark
  -> transform to IR
  -> semantic validation
  -> compatibility and governance checks where applicable
  -> write only if valid or show diagnostics
```

If validation fails, the CLI may perform one repair attempt by sending diagnostics back to the model. If the repaired output still fails, the CLI prints diagnostics and does not write files.

## 6. Command Behavior

### 6.1 `generate`

`generate` creates new `.mdl` definitions from source material. It should prefer canonical domain models first, then projections, then bindings. It must not silently weaken governance annotations from source material.

Required options:

- `--from <path-or-text>` for non-interactive use.
- `--output <file>` to write.
- `--model <model>` to override the configured model.

### 6.2 `describe`

`describe` explains definitions without changing them. It must report:

- Domains and owners.
- Model kinds, keys, versions, and change kinds.
- Projection sources and lineage.
- PII/restricted fields and governance notes.
- Deferred runtime constructs if present in samples.

### 6.3 `transform`

`transform` emits a target artifact and explains mapping decisions. For Phase 1 targets, it delegates artifact creation to normal emitters and uses the LLM only for explanation. For deferred targets, it may produce a preview only if clearly labelled as non-authoritative.

### 6.4 `update`

`update` applies a natural-language edit instruction to an existing model or projection version. It must:

- Resolve the target model version explicitly.
- Support `--preview` so authors can inspect the rendered patch before writing.
- Produce a patchable `.mdl` update rather than freeform prose.
- Validate the edited model before writing.
- Refuse ambiguous or unsupported edits instead of guessing.
- Use the configured provider when `MODELABLE_LLM_PROVIDER` or workspace `ai.provider` is set, and fall back to the deterministic local path when no provider is configured.

### 6.5 `suggest-projection`

`suggest-projection` proposes a projection for a consumer domain. It must:

- Pin source versions explicitly.
- Preserve lineage with `<-` or `=`.
- Exclude restricted fields unless the prompt context includes an explicit permission grant.
- Prefer optional fields for consumer-facing additions.
- Include comments only when they clarify a non-obvious governance or lineage choice.

### 6.6 `chat`

`chat` starts an interactive conversation with the configured model about the current workspace. It must:

- Load the workspace summary once and reuse it across turns.
- Support one-shot mode via `--message` for scripting and tests.
- Use the same provider configuration as `generate` and `update`.
- Reuse existing workspace summaries when no provider is configured.
- Never write files directly from chat; edits must flow through `update`.

## 7. Error Handling

| Failure | Behavior |
|---|---|
| Missing API key | Exit 1 with setup guidance |
| Provider timeout | Retry once with backoff, then exit 1 |
| Invalid generated `.mdl` | Show validation diagnostics, do not write |
| Unsafe prompt content | Redact and warn |
| Unsupported target | Exit 1 and list supported targets |
| Model unavailable | Exit 1 and show configured model source |

## 8. Auditability

When writing files, the CLI should emit a sidecar summary to stdout:

- Provider and model.
- Input sources used.
- Validation status.
- Files written.
- Diagnostics repaired, if any.

The CLI does not commit generated files. Git workflow remains user-controlled.

## 9. Open Decisions

- Whether multiple LLM providers are supported in the first implementation or only Anthropic.
- Whether generated output should include a machine-readable provenance sidecar.
- Whether repair attempts should be configurable beyond one retry.

## 10. Acceptance Criteria

- Users can configure the model by flag, environment variable, or workspace config.
- Generated `.mdl` is parsed and semantically validated before file writes.
- Invalid generated output is not written.
- Sensitive binding values are redacted from prompts.
- `describe` produces lineage and governance-aware summaries.
- `suggest-projection` never includes restricted fields without explicit permission context.
- `update` only writes a change when the resulting `.mdl` still passes parser and semantic validation.

## 11. Dependencies

- `cli-spec.md` — command syntax
- `idl-design-spec.md` — `.mdl` language
- `cel-integration-spec.md` — expression validation
- `ownership-permissions-spec.md` — governance and access checks
