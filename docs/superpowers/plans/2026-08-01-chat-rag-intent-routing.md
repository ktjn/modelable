# Chat RAG Intent Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Route documentation-like ordinary chat questions through the shared RAG pipeline across CLI, VS Code, and Playground while preserving ordinary and mutation chat behavior.

**Architecture:** Add one pure Python intent router in `modelable.rag`, then invoke it at the existing chat entry points before workspace planning. High-confidence documentation routes use the existing lexical Searchable retriever and bounded answer generator; all other messages use the current planner. Add structured retrieval metadata to conversation replies so clients render citations without parsing answer text.

**Tech Stack:** Python 3.14, dataclasses/enum, Searchable JSON indexes, existing LLM provider protocol, Pyodide, TypeScript, React, Vitest, Playwright.

## Global Constraints

- Use a deterministic dependency-free intent router; do not add an LLM classifier.
- Explicit `/docs <question>` always forces retrieval, even when automatic retrieval is disabled.
- Never automatically retrieve for mutation, compile, apply/discard, provider-control, or other slash commands.
- Missing or failed indexes must preserve ordinary chat; only explicit `/docs` reports a documentation error.
- Use the existing bounded lexical retrieval/evidence limits and same-origin JSON browser index.
- Retrieved evidence must never enter a change-set or compile request.
- Keep automatic retrieval session-scoped with a client-visible opt-out.
- Before every commit from `cli/`, run `uv run ruff format .`, `uv run ruff check .`, the mypy baseline ratchet, and `uv run pytest --tb=short`.
- For web changes run `npm run check`, `npm test`, `npm run build`, `npm run check:budgets`, and the browser acceptance gate.

---

### Task 1: Add the shared deterministic intent router

**Files:**
- Create: `cli/src/modelable/rag/intent.py`
- Modify: `cli/src/modelable/rag/__init__.py`
- Test: `cli/tests/test_rag_intent.py`

**Interfaces:**
- Consumes: raw chat text and an `automatic_enabled: bool` flag.
- Produces: `RetrievalRoute`, `RetrievalDecision`, and `classify_retrieval_intent(message: str, *, automatic_enabled: bool = True) -> RetrievalDecision`.

- [ ] **Step 1: Write failing router tests**

Create table-driven tests covering:

```python
("How do I configure the registry?", "automatic_documentation")
("What is the Modelable syntax for a projection?", "automatic_documentation")
("Add a creditScore field to Customer", "none")
("/compile --target json-schema", "none")
("/docs How do I configure the registry?", "explicit_documentation")
(" /docs   explain the registry", "explicit_documentation")
```

Also assert that automatic routing is disabled when `automatic_enabled=False`, while explicit `/docs` still routes explicitly; blank `/docs` returns `none` with a stable reason.

- [ ] **Step 2: Run the focused tests and verify failure**

Run from `cli/`:

```bash
uv run pytest tests/test_rag_intent.py -q
```

Expected result: import or attribute failures because the route types and classifier do not exist.

- [ ] **Step 3: Implement the pure classifier**

Implement normalization, explicit command extraction, slash-command exclusion, mutation exclusion, documentation-signal matching, and stable reason strings in `rag/intent.py`. Evaluate exclusions before positive signals and return the extracted question for both automatic and explicit routes. Do not import CLI, LSP, browser, provider, or Searchable modules.

- [ ] **Step 4: Run focused tests and commit**

Run the focused test file and the four required CLI gates. Commit:

```bash
git add cli/src/modelable/rag/intent.py cli/src/modelable/rag/__init__.py cli/tests/test_rag_intent.py
git commit -m "feat(rag): add shared chat intent routing"
```

### Task 2: Make retrieval answers and reply metadata reusable

**Files:**
- Modify: `cli/src/modelable/rag/generation.py`
- Modify: `cli/src/modelable/llm/conversation_backend.py`
- Modify: `cli/src/modelable/llm/chat.py`
- Modify: `cli/src/modelable/llm/conversation_engine.py` only if reply construction needs the new metadata
- Test: `cli/tests/test_rag_generation.py`
- Test: `cli/tests/test_llm_features.py`

**Interfaces:**
- Consumes: `RetrievalDecision`, `DocumentationRetriever`, `LLMProvider`, and the existing evidence limits.
- Produces: a reusable documentation-answer result containing answer text, `tuple[RagCitation, ...]`, `retrieval_used: bool`, and `route_reason`; `ConversationReply` carries the metadata with defaults that preserve all existing callers.

- [ ] **Step 1: Add failing generation and reply-contract tests**

Assert that a successful retrieval result contains citations and route metadata, ordinary answers have `retrieval_used=False`, and existing `ConversationReply(kind="answer", text="...")` construction remains valid without new arguments.

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```bash
uv run pytest tests/test_rag_generation.py tests/test_llm_features.py -k "retrieval or citation or reply" -q
```

Expected result: failures for the missing structured result and reply fields.

- [ ] **Step 3: Implement the reusable result without changing routing yet**

Refactor the existing answer-generation path so explicit `/docs` and future automatic callers use one bounded helper. Preserve the current answer text and `Sources:` compatibility for CLI output, but keep citations as structured data alongside the text. Add default-valued reply metadata so previews, errors, apply/discard, and ordinary answers serialize exactly as before unless retrieval was used.

- [ ] **Step 4: Run focused tests and commit**

Run the focused tests plus the four CLI gates. Commit:

```bash
git add cli/src/modelable/rag/generation.py cli/src/modelable/llm/conversation_backend.py cli/src/modelable/llm/chat.py cli/src/modelable/llm/conversation_engine.py cli/tests/test_rag_generation.py cli/tests/test_llm_features.py
git commit -m "feat(rag): expose structured grounded answer metadata"
```

### Task 3: Integrate automatic routing into CLI and VS Code

**Files:**
- Modify: `cli/src/modelable/llm/chat.py`
- Modify: `cli/src/modelable/lsp/conversation_protocol.py`
- Modify: `cli/src/modelable/lsp/conversation_service.py`
- Test: `cli/tests/test_llm_features.py`
- Test: `cli/tests/test_lsp_conversation_service.py`
- Test: `cli/tests/test_lsp_conversation_integration.py` if participant serialization needs coverage

**Interfaces:**
- Consumes: `classify_retrieval_intent`, reusable grounded-answer result, and existing session retrievers.
- Produces: automatic documentation answers in CLI/LSP informational turns, session-scoped `automaticDocumentation` configuration, and unchanged mutation/compile behavior.

- [ ] **Step 1: Write failing CLI/LSP integration tests**

Cover automatic documentation success with a fake retriever/provider, no-index fallback to the existing planner, retrieval failure fallback, explicit `/docs` while automatic retrieval is disabled, and mutation text that never calls the retriever. Assert that serialized answers expose citations and `retrievalUsed`.

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```bash
uv run pytest tests/test_llm_features.py tests/test_lsp_conversation_service.py tests/test_lsp_conversation_integration.py -k "retrieval or documentation or intent" -q
```

Expected result: automatic documentation requests currently reach the ordinary planner and no session option exists.

- [ ] **Step 3: Integrate the router before existing planning**

In CLI `chat_turn` and LSP session handling, classify the message before command/planner dispatch. For `AUTOMATIC_DOCUMENTATION`, call the shared grounded-answer helper only when a retriever and provider are available; otherwise call the existing path. For explicit routing, preserve the current recoverable error behavior. Add the session option with a default of enabled when an index is configured and serialize metadata without changing mutation reply kinds.

- [ ] **Step 4: Verify mutation non-interference and compatibility**

Run the focused tests, then the full CLI gates. Add a regression test that a message producing a preview still has `retrievalUsed=False` and no documentation provider call.

- [ ] **Step 5: Commit**

```bash
git add cli/src/modelable/llm/chat.py cli/src/modelable/lsp/conversation_protocol.py cli/src/modelable/lsp/conversation_service.py cli/tests/test_llm_features.py cli/tests/test_lsp_conversation_service.py cli/tests/test_lsp_conversation_integration.py
git commit -m "feat(chat): route documentation questions through RAG"
```

### Task 4: Integrate automatic routing into the browser Playground

**Files:**
- Modify: `cli/src/modelable/browser/conversation.py`
- Modify: `cli/src/modelable/browser/dispatch.py`
- Modify: `web/src/client.ts`
- Modify: `web/src/App.tsx`
- Modify: `web/src/ai/chat-types.ts`
- Modify: `web/src/ai/ChatPanel.tsx`
- Test: `cli/tests/test_browser_conversation.py`
- Test: `cli/tests/test_browser_api.py`
- Test: `web/src/client.test.ts`
- Test: `web/src/App.test.tsx`
- Test: `web/src/ai/ChatPanel.test.tsx`

**Interfaces:**
- Consumes: browser-safe shared intent classifier and browser `BrowserDocumentationRetriever`.
- Produces: automatic documentation answers for ordinary informational messages, an `automaticDocumentation` session option, safe citation rendering, and unchanged `/docs`/mutation behavior.

- [ ] **Step 1: Write failing browser tests**

Assert that an ordinary documentation question loads the bundled JSON index, a mutation question does not load it, opt-out uses the planner, explicit `/docs` bypasses opt-out, and automatic replies render as the dedicated documentation message with safe links.

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```bash
uv run pytest cli/tests/test_browser_conversation.py cli/tests/test_browser_api.py -k "documentation or retrieval or intent" -q
cd web
npm test -- src/client.test.ts src/App.test.tsx src/ai/ChatPanel.test.tsx
```

Expected result: only explicit `/docs` uses the browser retriever and the client has no automatic-routing state.

- [ ] **Step 3: Add browser session policy and route metadata**

Extend dispatch validation and session binding with `automaticDocumentation` defaulting to true when the bundled index is present. Reuse the shared classifier before ordinary planning, keep index loading lazy, and return the same structured metadata used by CLI/LSP.

- [ ] **Step 4: Render automatic grounded answers**

Use reply metadata rather than checking whether the user typed `/docs` to choose the documentation message component. Render the answer as Markdown and citations through the existing safe HTTP(S)-only link helper; keep ordinary answers and mutation previews unchanged.

- [ ] **Step 5: Run web and browser gates and commit**

Run `npm run check`, `npm test`, `npm run build`, `npm run check:budgets`, and the full browser acceptance gate. Commit:

```bash
git add cli/src/modelable/browser/conversation.py cli/src/modelable/browser/dispatch.py cli/tests/test_browser_conversation.py cli/tests/test_browser_api.py web/src/client.ts web/src/App.tsx web/src/ai/chat-types.ts web/src/ai/ChatPanel.tsx web/src/client.test.ts web/src/App.test.tsx web/src/ai/ChatPanel.test.tsx
git commit -m "feat(browser): enable automatic documentation RAG"
```

### Task 5: Document, roll out, and move extensibility behind the new phase

**Files:**
- Modify: `ROADMAP.md`
- Modify: `docs/cli-reference.md`
- Modify: `docs/playground-design.md`
- Modify: `docs/integrations.md`
- Test: `cli/tests/test_release_workflow.py` only if changed routing surfaces alter release validation

**Interfaces:**
- Consumes: the shipped `automaticDocumentation` behavior and structured retrieval metadata.
- Produces: user-facing configuration documentation, explicit opt-out examples, rollout guidance, and an updated roadmap ordering.

- [ ] **Step 1: Write documentation tests or link assertions**

Add the exact CLI/LSP/Playground examples to the relevant documentation and test any command/configuration snippets already covered by repository documentation checks.

- [ ] **Step 2: Document behavior and safety boundaries**

State that documentation-like informational questions are grounded when an index is configured, mutation/compile requests are never automatically retrieved, `/docs` remains the force-retrieve command, and automatic retrieval can be disabled per session/client.

- [ ] **Step 3: Update roadmap ordering**

Insert “automatic chat RAG” as the active phase before extensibility. Keep vector/hybrid retrieval, user-supplied indexes, and structured binary browser shards as separate deferred work.

- [ ] **Step 4: Run final validation and documentation review**

Run all CLI gates, all web checks/build/budgets, the browser acceptance gate, and:

```bash
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
```

Run the four-phase doc/spec review before opening the PR. Confirm no ordinary chat or mutation path loads a retriever when the router returns `none`.

- [ ] **Step 5: Commit and publish the plan implementation**

Commit the documentation/roadmap closeout, open a PR, and include `Doc/spec review: all phases passed` plus the full validation evidence in the PR body. After merge, move the design and plan files into their corresponding archived directories per `AGENTS.md`.

## Completion Evidence

- The same pure classifier produces identical decisions for CLI, LSP, and Playground.
- High-confidence documentation questions are grounded automatically when an index is configured.
- `/docs` always forces retrieval and automatic opt-out does not disable it.
- Mutation, compile, apply/discard, and provider-control flows never load documentation retrieval automatically.
- Retrieval failures fall back safely for ordinary chat and remain user-visible for explicit `/docs`.
- Citations are structured and safely rendered in all three clients.
- CLI, browser, web, docs, and CI gates pass before extensibility work begins.
