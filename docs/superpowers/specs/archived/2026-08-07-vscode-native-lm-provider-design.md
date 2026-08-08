# 2026-08-07 VS Code Native Language Model Provider — Design

## Status

Proposed / future. This design is the "leave room for it" path that the extension
Settings UI work (provider/model dropdowns) is shaped around, so the architecture
doesn't paint us into a corner. It is **not** the current behavior and is not
scheduled until the prerequisites below land.

## Motivation

Today the `@modelable` VS Code chat participant generates turns by calling a Modelable
*server-side* LLM provider: Ollama or Anthropic, configured via environment variables,
CLI flags, or the workspace `ai:` block (mapped into the LSP child process by the new
`modelable.llm.*` settings). The `@modelable` participant itself does not use VS Code's
language model API at all.

Modern VS Code (1.121+) ships bring-your-own-key native language models: users register
any model — including a **local Ollama server** via `chatLanguageModels.json`, or any
OpenAI-compatible endpoint — into VS Code Chat's model picker, with **no Copilot login**
needed. Users reasonably expect `@modelable` to use the model they already picked in VS
Code, rather than re-configuring a second, separate provider.

**Goal:** Let the `@modelable` participant generate its turns through the VS Code native
language model API (`vscode.lm`) — the model the user selected in Chat — as an
alternative to Modelable's own server-side provider config. This makes `@modelable` work
against a local Ollama with *only* the VS Code model picker configured (no
`MODELABLE_LLM_*`), and lets future providers be added purely through VS Code.

## Non-goals

- No change to non-VS Code clients. The `vscode` provider kind is only meaningful over
  the LSP↔extension boundary (CLI and the Playground keep their own providers).
- No embeddings, code completion, or RAG encoding via `vscode.lm` — chat turn generation
  only.
- No in-chat model browsing/switching; the model comes from the VS Code model picker.
- No change to the JSON plan format or the Python planner/engine semantics.

## Current architecture (background)

- `ConversationEngine` emits a `PendingPlanRequest` carrying an `LLMRequest`
  (`system`, `user`, `temperature`, `response_format`, optional `schema` JSON) when it
  needs the model (`cli/src/modelable/llm/conversation_engine.py`).
- `ConversationSession.turn` (`cli/src/modelable/llm/conversation.py`) drives the loop:
  while the outcome is a `PendingPlanRequest`, it calls the injected
  `LLMProvider.complete(request)` and feeds the raw text back via `resume_turn`.
- `LLMProvider` is a small Protocol (`cli/src/modelable/llm/provider_types.py`):
  `complete(LLMRequest) -> LLMResponse(content, provider, model)`.
- The LSP service builds the session with a provider from `build_provider`
  (`cli/src/modelable/lsp/conversation_service.py:_build_session`).
- The extension's `ConversationClient` already issues LSP requests server→client
  (`modelable/conversation/turn`, etc.) and awaits their replies.

Key implication: **all prompt construction and all plan parsing/validation already live
server-side. The only thing to replace is the transport that performs a `complete`
call.** That makes the "native provider" design a transport swap, not a prompting
rewrite.

## Design

### 1. A "vscode" provider kind

Extend provider resolution so `provider == "vscode"` (also accept `"native"` and
`"vscode-lm"` as aliases) is recognized. Unlike Ollama/Anthropic, `build_provider` does
*not* construct an HTTP-backed provider for it. Instead `ConversationSession` is
constructed in a `client_completion` mode where generation is delegated out to the
extension.

`resolve_llm_config` (`cli/src/modelable/llm/config.py`) learns to surface
`provider="vscode"` from the new setting (mapped to `MODELABLE_LLM_PROVIDER=vscode` by
the extension) and/or the workspace `ai:` block. `model` and `base_url` are ignored in
this mode (the model selection happens in VS Code).

### 2. Server → client completion call

Add one LSP custom request, server → client:

```text
modelable/conversation/complete
Params: { id, system, user, temperature, response_format, schema? }
Result: { content, model? }
```

Semantics mirror `LLMProvider.complete` but the *client* (extension) performs the work.
`temperature`/`schema` map to what the client can pass to `vscode.lm`. The `schema` JSON
is offered to the client so a model with tool-calling can produce a conforming plan via
structured output; the server still hard-validates the returned `content` with the
existing `parse_and_validate_plan`, so a weaker model degrades to the existing repair
loop rather than silently corrupting.

### 3. Async hosting of the turn loop

Today `ConversationSession.turn` blocks on a synchronous `provider.complete`. With a
client round-trip we must await a response, so the *LSP service* drives the planning loop
asynchronously:

- After `session.turn(...)` returns a `PendingPlanRequest`, the service awaits
  `modelable/conversation/complete` for that request's `LLMRequest`, then calls
  `session.resume_turn(request_id, content)`.
- It iterates until a concrete `ConversationReply` is produced, factoring the loop
  currently inside `ConversationSession.turn` into a shared helper, or generalizing
  `ConversationSession` with an injectable *async* `complete` callback while keeping a
  synchronous adapter for the current HTTP providers.
- Cancellation: the extension forwards the turn's `CancellationToken` to the `vscode.lm`
  request and, on cancel, the pending request is failed/closed via the existing
  `fail_turn` path.

### 4. Extension side

The extension registers a handler for `modelable/conversation/complete`:

- Feature-detect `vscode.lm.selectChatModels()`. If no native model is available, return a
  structured error the participant surfaces as: "No VS Code Chat language model is
  available. Pick a model in Chat's model picker, or configure a `modelable.llm.provider`
  (Ollama/Anthropic)."
- Select the model: prefer `modelable.llm.vscodeModel` if set, else the Chat model used
  for the session (`request.model`), else the default from `selectChatModels`.
- Send messages (`vscode.LanguageModelChatMessage` user/system) and, when the request has
  a `schema`, request structured/tool output if the model advertises tool support; else
  plain text. Return concatenated `LanguageModelTextPart` as `content`.
- Optionally surface `response.provider`/`response.model` and token usage for reply
  metadata.

### 5. Settings

- `modelable.llm.provider` enum gains `"vscode"` ("Use the model selected in VS Code
  Chat"). With this value, `model`/`baseUrl` are ignored.
- New optional `modelable.llm.vscodeModel` (string): pin the native model id; empty =
  follow the Chat model picker.
- `chatLanguageModels.json` / BYOK remains outside Modelable's control (it is standard
  VS Code).

## Prerequisites / sequencing

1. Confirm the `@modelable` participant is already usable once *some* LM is registered
   (that is, the "Language model unavailable" prerequisite is satisfied by BYOK) — this
   is the behavior the merged Settings/docs work (#301 and the follow-up) is designed
   against. The native-provider work then *replaces* the separate server-side config for
   users who prefer the model picker.
2. VS Code stable where `vscode.lm` model picker + `chatLanguageModels.json` work without
   a Copilot login. The extension gates on `vscode.lm` presence and degrades to the
   current provider path otherwise.

## Backwards compatibility

- Entirely additive. Existing Ollama/Anthropic configs are unchanged.
- If the extension does not support `modelable/conversation/complete`, the server falls
  back to a configuration error at session creation explaining only the existing
  Ollama/Anthropic paths are available.
- A `provider="vscode"` used by a non-VS Code client (CLI/Playground) is rejected with a
  clear "only available from the VS Code extension" error, mirroring the existing
  unsupported-provider handling.

## Open questions (resolve during planning)

- Streaming: forward `vscode.lm` streaming parts to `response.stream`, or keep the
  single-shot `content` contract? Single-shot is simpler and matches `LLMResponse`.
  Default: single-shot, with streaming as a follow-up enhancement.
- Exact scope of `schema` → `vscode.lm` tool mapping across models (varies by vendor).
  Default: attempt structured output, accept plain-text fallback.

## Alternatives considered

- **Client-side prompting (build prompts in TS).** Rejected: duplicates the Python
  planner system prompts and JSON plan logic, risking divergence between CLI/Playground
  and VS Code outputs.
- **Two-process provider (server proxied through the extension for all calls).**
  Equivalent to the chosen design; the chosen shape reuses `PendingPlanRequest` and the
  existing repair loop without new prompt code.
- **Rely on `vscode.lm` inside the participant handler for the whole turn.** Rejected:
  the handler does not hold the planner context or the plan-validation machinery;
  duplicating it in TS is the same failure mode as client-side prompting.
