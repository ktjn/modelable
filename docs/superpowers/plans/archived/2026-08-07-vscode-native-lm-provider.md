# VS Code Native Language Model Provider — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status:** Future / not yet scheduled. Do not start until the prerequisites in
> `docs/superpowers/specs/2026-08-07-vscode-native-lm-provider-design.md` are met and the
> user signals go. The goal is to record the intended shape so the Settings UI work stays
> compatible.

**Goal:** Let the `@modelable` VS Code chat participant generate turns through VS Code's
native `vscode.lm` language model API (the model in Chat's model picker, including a
local Ollama registered via `chatLanguageModels.json`), as an alternative to Modelable's
own server-side Ollama/Anthropic provider. Add a `"vscode"` provider option to the
extension settings dropdown.

**Architecture:** Add a `"vscode"` provider kind and a server→client LSP request,
`modelable/conversation/complete`, that mirrors `LLMProvider.complete` but lets the
extension perform the model call. The LSP service drives the existing planning loop
asynchronously, awaiting that request per `PendingPlanRequest` and feeding the returned
raw text back through the existing `resume_turn`/repair machinery. All prompt construction
and plan parsing/validation stay server-side; only the transport that performs a
`complete` call is swapped.

**Tech stack:** Python 3.14 (pygls LSP, stdlib), TypeScript/Node for the extension,
`pytest` with `pytest-xdist`, mocha for the extension smoke tests, `npm test` for the
extension gate.

## Global Constraints

- Transport swap only. Do **not** change the JSON plan format, the planner system
  prompts, or `parse_and_validate_plan`.
- Additive. Existing Ollama/Anthropic configs and the current sync `provider.complete`
  loop must remain unchanged and green.
- The `"vscode"` provider is only valid over the LSP↔extension boundary; non-VS Code
  clients (CLI, Playground) must reject it with a clear error.
- Follow the pre-commit convention: from `cli/` run `uv run ruff format`, `uv run ruff
  check`, the mypy baseline ratchet, and the relevant pytest file(s); for extension
  changes run `cd vscode && npm ci && npm run check && npm run build && npm test` when a
  real desktop run is feasible.
- Reference spec: `docs/superpowers/specs/2026-08-07-vscode-native-lm-provider-design.md`.

---

### Task 1: Resolve a `"vscode"` provider kind (server)

**Files:**
- Modify: `cli/src/modelable/llm/config.py` (`resolve_llm_config`: only needs to surface
  `provider="vscode"` untouched — it already returns the raw string)
- Modify: `cli/src/modelable/llm/providers.py` (`build_provider`: recognize `"vscode"` /
  `"native"` / `"vscode-lm"`)
- Modify: `cli/src/modelable/llm/conversation.py` (`ConversationSession`: `client_completion`
  mode flag; return a sentinel/marker instead of `no_provider_notice` when in this mode)
- Test: `cli/tests/test_llm_provider_integration.py`, `cli/tests/test_conversation.py`

- [ ] **Step 1: Add failing tests**

In `cli/tests/test_llm_provider_integration.py`, add cases proving:
- `build_provider("vscode", model=None, base_url=None)` returns a marker the LSP service
  recognizes as client-completion (no HTTP transport constructed).
- `"native"` and `"vscode-lm"` alias identically.
- In `cli/tests/test_conversation.py`, a session built with `client_completion=True`
  surfaces the client-completion marker rather than `no_provider_notice`.

- [ ] **Step 2: Implement**

In `providers.py`, before the final `raise ValueError(...)`, accept the aliases and return
a module-level `ClientCompletionProvider` sentinel (e.g. a `object()` typed
`LLMProvider` that raises `NotImplementedError("client-completion")` if ever
`complete`d synchronously). In `conversation.py`, add constructor flag
`client_completion: bool` and expose it alongside `no_provider_notice`.

- [ ] **Step 3: `modelable models`/CLI guard** — a `provider="vscode"` selected by a CLI
  user should error, not hang. Confirm existing unsupported-provider handling covers it
  or extend it.

- [ ] **Step 4:** `cd cli && uv run pytest tests/test_llm_provider_integration.py -k vscode tests/test_conversation.py -k client_completion`; then ruff, mypy ratchet, full files.

- [ ] **Step 5: Commit** `git commit -m "feat(llm): recognize a client-completion vscode provider kind (server)"`

---

### Task 2: LSP protocol — `modelable/conversation/complete`

**Files:**
- Modify: `cli/src/modelable/lsp/conversation_protocol.py` (add request name, dataclasses)
- Test: `cli/tests/test_lsp_conversation_service.py`, protocol serialization tests

- [ ] **Step 1: Add failing tests** for serialization of
  `{ id, system, user, temperature, response_format, schema? }` params and
  `{ content, model? }` result.

- [ ] **Step 2: Implement** the params/result dataclasses and serialize helpers following
  the existing `conversation_protocol.py` conventions (exact names TBD here; mirror
  `LLMRequest`/`LLMResponse` fields).

- [ ] **Step 3:** ruff, mypy ratchet, pytest. **Commit.**

---

### Task 3: Async turn loop in the LSP service

**Files:**
- Modify: `cli/src/modelable/lsp/conversation_service.py` (`turn`, session construction)
- Modify: `cli/src/modelable/llm/conversation.py` (factor the `PendingPlanRequest` loop
  into a shared helper with a `complete` callback so it can be awaited)
- Test: `cli/tests/test_lsp_conversation_service.py`

- [ ] **Step 1: Add failing tests** with a fake client responder driving
  `resume_turn`/repair iterations and cancellation via `fail_turn`.

- [ ] **Step 2: Implement** the loop factoring. Keep the existing synchronous
  `provider.complete` path untouched; add an async `client_completion` path that awaits
  `modelable/conversation/complete` per `PendingPlanRequest`.

- [ ] **Step 3:** ruff, mypy ratchet, pytest. **Commit.**

---

### Task 4: Extension — register the `complete` handler with `vscode.lm`

**Files:**
- Modify: `vscode/extension.js` (register a handler for `modelable/conversation/complete`)
- Modify: `vscode/conversationClient.js` (expose a `complete`/LM-select helper)
- Modify: `vscode/package.json` (add `modelable.llm.vscodeModel`; extend provider enum
  with `"vscode"`; point `LLM_ENV_VARIABLES` accordingly)
- Modify: `vscode/src/test/suite/lsp.test.ts` / a new unit test file

- [ ] **Step 1: Add `vscode.llm` feature-detect handler.** If `vscode.lm.selectChatModels`
  is unavailable or empty, return a structured error with the friendly hint from the
  spec.

- [ ] **Step 2: Model selection** — `modelable.llm.vscodeModel` → session model →
  `selectChatModels` default. Guard against the "Language model unavailable" case.

- [ ] **Step 3: Structured output** — pass `schema` as a `vscode.lm` tool request when the
  model advertises tool support; otherwise plain text.

- [ ] **Step 4: Wire the provider enum.** In `extension.js`, `LLM_ENV_VARIABLES` already
  maps `llm.provider` → `MODELABLE_LLM_PROVIDER`, so `"vscode"` flows through unchanged;
  add `"vscode"` to the `package.json` enum and document that `model`/`baseUrl` are
  ignored in that mode.

- [ ] **Step 5:** `node --check`, `npm run build`, and a desktop smoke test with a local
  BYOK/Ollama model. **Commit.**

---

### Task 5: Docs & verification

**Files:**
- Modify: `docs/getting-started.md` (Local Chat Testing section: the native-provider
  path, when available)
- Modify: `docs/cli-reference.md` (the `vscode` provider kind + guard)
- Modify: `docs/architecture.md` (LSP/VS Code boundary: native provider adapter note)
- Modify: `docs/maintainers.md` (manual conformance note)

- [ ] **Step 1:** Document the `"vscode"` provider option and the friendly
  no-native-model hint in `getting-started.md`.

- [ ] **Step 2:** Note the CLI/Playground rejection behavior in `cli-reference.md`.

- [ ] **Step 3:** Run the full `cli/` gate and, if a desktop machine is available,
  `cd vscode && npm test`. Record results in the PR.

- [ ] **Step 4: Commit.**

---

### Task 6 (follow-up, non-blocking): streaming + token metadata

Forward `vscode.lm` streaming parts to `response.stream` and surface
`provider`/`model`/token usage in reply metadata. Only if the single-shot contract proves
too slow. Not scheduled.
