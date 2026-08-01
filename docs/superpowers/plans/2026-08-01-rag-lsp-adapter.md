# Modelable LSP RAG Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional workspace-bound binary Searchable index to the Modelable conversation protocol and route LSP `/docs` turns through the shared RAG answer pipeline.

**Architecture:** Extend `ConversationTurnParams` with optional `documentationIndexUri`. `LspConversationService` resolves and validates the URI only when creating a session, stores one `DocumentationRetriever` and canonical URI in the session entry, and dispatches `/docs` through `documentation_chat_reply`; all other turns continue through `ConversationSession` unchanged.

**Tech Stack:** Python 3.11+, Pydantic, pygls/lsprotocol, pytest, existing `searchable-client`, Modelable RAG and conversation modules.

## Global Constraints

- The index is the single binary Searchable `manifest.json` and must resolve inside the conversation workspace.
- `documentationIndexUri` is optional; protocol version remains 2 and existing clients without the field remain valid.
- A session binds its documentation index on creation; a later different URI is rejected and never replaces the retriever.
- Reuse `documentation_chat_reply` and `answer_with_retrieval`; do not duplicate RAG prompt, citation, or provider-error logic in the LSP layer.
- `/docs` answers are serialized as ordinary `ConversationReply(kind="answer")` responses with no edit/change-set side effects.
- No new runtime dependency, bundled embedding provider, index copying, web playground, or Pyodide implementation is included.
- Before a PR, run from `cli/`: `uv run ruff format .`, `uv run ruff check .`, `uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes`, and `uv run pytest --tb=short`.

---

### Task 1: Extend and validate the conversation protocol field

**Files:**
- Modify: `cli/src/modelable/lsp/conversation_protocol.py`
- Test: `cli/tests/test_lsp_conversation_protocol.py`

**Interfaces:**
- Consumes: existing `ConversationTurnParams` JSON aliases and protocol version 2.
- Produces: `ConversationTurnParams.documentation_index_uri: str | None`, serialized from/to `documentationIndexUri`.

- [ ] **Step 1: Write the failing protocol tests**

Add tests proving the optional field accepts a file URI and remains absent by default, while unknown fields remain rejected:

```python
def test_turn_params_accept_optional_documentation_index_uri() -> None:
    params = ConversationTurnParams.model_validate(
        {
            "protocolVersion": 2,
            "sessionId": "session-1",
            "createSession": True,
            "workspaceUri": "file:///workspace",
            "message": "/docs how do I install it?",
            "documentationIndexUri": "file:///workspace/dist/search-index/manifest.json",
            "dirtyDocumentUris": [],
        }
    )

    assert params.documentation_index_uri == "file:///workspace/dist/search-index/manifest.json"


def test_turn_params_default_documentation_index_uri_is_none() -> None:
    params = ConversationTurnParams.model_validate(
        {
            "protocolVersion": 2,
            "sessionId": "session-1",
            "createSession": True,
            "workspaceUri": "file:///workspace",
            "message": "describe the customer model",
            "dirtyDocumentUris": [],
        }
    )
    assert params.documentation_index_uri is None
```

- [ ] **Step 2: Run the focused tests to verify they fail**

```bash
uv run pytest tests/test_lsp_conversation_protocol.py -k "documentation_index_uri" -q
```

Expected: FAIL because the field is not defined and `extra="forbid"` rejects the payload.

- [ ] **Step 3: Add the optional aliased field**

Add this field to `ConversationTurnParams` immediately after `workspace_uri`:

```python
documentation_index_uri: str | None = Field(default=None, alias="documentationIndexUri")
```

Do not add a protocol-version change or a permissive extra-field mode.

- [ ] **Step 4: Run the focused protocol tests**

```bash
uv run pytest tests/test_lsp_conversation_protocol.py -k "documentation_index_uri or turn_params" -q
```

Expected: PASS, with existing closed-payload/version tests still passing.

- [ ] **Step 5: Commit the protocol slice**

```bash
git add cli/src/modelable/lsp/conversation_protocol.py cli/tests/test_lsp_conversation_protocol.py
git commit -m "feat: add LSP documentation index parameter"
```

### Task 2: Bind a workspace-safe retriever to each LSP session

**Files:**
- Modify: `cli/src/modelable/lsp/conversation_service.py`
- Test: `cli/tests/test_lsp_conversation_service.py`

**Interfaces:**
- Consumes: `ConversationTurnParams.documentation_index_uri`, `uri_to_path`, workspace root, and `DocumentationRetriever`.
- Produces: `_SessionEntry.documentation_index_uri: str | None`, `_SessionEntry.documentation_retriever: DocumentationRetriever | None`, and session validation for index reuse.

- [ ] **Step 1: Write failing session-binding tests**

Add tests using a real temporary documentation index and a fake provider/session factory. Cover creation, reuse without resupplying the field, outside-workspace rejection, and URI mutation rejection:

```python
def test_lsp_docs_index_is_bound_to_new_session_and_reused(tmp_path: Path) -> None:
    index_uri = _make_documentation_index(tmp_path).as_uri()
    service = LspConversationService(session_factory=_session_factory)

    first = service.turn(_turn_params(root, create_session=True, documentation_index_uri=index_uri, message="/docs install"))
    second = service.turn(_turn_params(root, create_session=False, message="/docs install"))

    assert "Sources:" in first["text"]
    assert first["text"] == second["text"]


def test_lsp_rejects_documentation_index_outside_workspace(tmp_path: Path) -> None:
    outside = tmp_path / "outside" / "manifest.json"
    with pytest.raises(ConversationSessionError, match="inside the conversation workspace"):
        service.turn(_turn_params(root, create_session=True, documentation_index_uri=outside.as_uri()))


def test_lsp_rejects_documentation_index_change_on_existing_session(tmp_path: Path) -> None:
    first_uri = _make_documentation_index(root).as_uri()
    second_uri = _make_documentation_index(root / "other").as_uri()
    service.turn(_turn_params(root, create_session=True, documentation_index_uri=first_uri))

    with pytest.raises(ConversationSessionError, match="documentation index"):
        service.turn(_turn_params(root, create_session=False, documentation_index_uri=second_uri))
```

Define `_make_documentation_index(root: Path) -> Path` in the test module. It must create `root / "search-index"`, call `build_documentation_index` with one `DocumentationChunk(external_id="guide.md#install", source_path="guide.md", url="https://example.test/guide/#install", language="en", title="Guide", heading="Install", heading_path=["Guide", "Install"], content="Install with uv.", chunk_index=0)`, and return `search-index / "manifest.json"`. Define `_docs_session_factory` with a provider returning `LLMResponse(content="Use [S1] to install it.", provider="fake", model="test")`; use the same fixture shape already used by `test_cli_docs_ask.py`.

- [ ] **Step 2: Run the focused service tests to verify they fail**

```bash
uv run pytest tests/test_lsp_conversation_service.py -k "docs_index or documentation" -q
```

Expected: FAIL because session entries do not store index configuration and the service does not resolve the field.

- [ ] **Step 3: Implement workspace-safe session binding**

Add a helper with this behavior:

```python
def _documentation_retriever(
    self,
    root: Path,
    documentation_index_uri: str | None,
) -> tuple[str | None, DocumentationRetriever | None]:
```

Return `(None, None)` when the URI is absent. Otherwise require `uri_to_path(uri)` to return a path, resolve it, require `resolved.is_relative_to(root.resolve())`, and construct `DocumentationRetriever(resolved)`. Wrap `ValueError`, `OSError`, and retriever validation failures in `ConversationSessionError` with the original cause.

At session creation, store the returned canonical URI (`resolved.as_uri()`) and retriever. For an existing session, if the request supplies a URI, resolve it and require its canonical URI to equal the stored value; otherwise leave the stored configuration unchanged. Do this validation before calling `entry.session.turn`.

- [ ] **Step 4: Run the focused service tests**

```bash
uv run pytest tests/test_lsp_conversation_service.py -k "docs_index or documentation" -q
```

Expected: PASS.

- [ ] **Step 5: Run existing LSP service regressions**

```bash
uv run pytest tests/test_lsp_conversation_service.py --tb=short
```

Expected: all existing service tests plus the new index-binding tests pass.

- [ ] **Step 6: Commit session binding**

```bash
git add cli/src/modelable/lsp/conversation_service.py cli/tests/test_lsp_conversation_service.py
git commit -m "feat: bind documentation indexes to LSP sessions"
```

### Task 3: Route LSP `/docs` turns through the shared adapter

**Files:**
- Modify: `cli/src/modelable/lsp/conversation_service.py`
- Test: `cli/tests/test_lsp_conversation_service.py`, `cli/tests/test_lsp_conversation_integration.py`

**Interfaces:**
- Consumes: session-bound `DocumentationRetriever`, `ConversationSession.provider`, and `documentation_chat_reply`.
- Produces: serialized answer replies for `/docs` with citations, insufficient evidence, missing-provider guidance, and provider-error recovery.

- [ ] **Step 1: Write failing routing and error tests**

Add service tests that assert `/docs` bypasses `ConversationSession.turn` only for the explicit command, returns `kind == "answer"`, contains citations, and remains usable after a provider error:

```python
def test_lsp_docs_turn_returns_citations_without_edit_side_effects(tmp_path: Path) -> None:
    service = LspConversationService(session_factory=_docs_session_factory)
    index_uri = _make_documentation_index(root).as_uri()
    reply = service.turn(
        _turn_params(root, create_session=True, documentation_index_uri=index_uri, message="/docs install")
    )

    assert reply["kind"] == "answer"
    assert "[S1]" in reply["text"]
    assert reply["changeSetId"] is None


def test_lsp_docs_provider_failure_is_an_answer_and_session_survives(tmp_path: Path) -> None:
    service = LspConversationService(session_factory=_failing_docs_session_factory)
    index_uri = _make_documentation_index(root).as_uri()
    failed = service.turn(
        _turn_params(root, create_session=True, documentation_index_uri=index_uri, message="/docs install")
    )
    normal = service.turn(_turn_params(root, create_session=False, message="/help"))

    assert "configured provider failed" in failed["text"]
    assert normal["kind"] == "answer"
```

Add one real JSON-RPC test to `test_lsp_conversation_integration.py` that sends `documentationIndexUri` and verifies the returned answer contains `Sources:` and the source external ID.

The integration fixture should build the index under `tmp_path / "search-index"`, pass its `manifest.json` URI in the turn payload, and configure the test workspace/provider path using the same server-test setup already used by the existing conversation integration tests.

- [ ] **Step 2: Run the focused tests to verify they fail**

```bash
uv run pytest tests/test_lsp_conversation_service.py tests/test_lsp_conversation_integration.py -k "docs" -q
```

Expected: FAIL because the service currently sends `/docs` to the normal conversation engine.

- [ ] **Step 3: Implement shared-adapter routing**

Import `ConversationReply`, `documentation_chat_reply`, and the retriever type. In `turn`, after session/index validation:

```python
if entry.documentation_retriever is not None or params.message.strip().lower().startswith("/docs"):
    documentation_text = documentation_chat_reply(
        params.message,
        retriever=entry.documentation_retriever,
        provider=entry.session.provider,
    )
else:
    documentation_text = None
if documentation_text is not None:
    reply = ConversationReply(kind="answer", text=documentation_text)
else:
    reply = entry.session.turn(params.message)
```

The adapter must be called for `/docs` even when no index is configured so it returns the actionable missing-index response. Do not route ordinary messages through it. Preserve the existing first-turn no-provider notice behavior for normal turns; `/docs` uses the adapter's own evidence/provider response.

- [ ] **Step 4: Run the focused and integration tests**

```bash
uv run pytest tests/test_lsp_conversation_service.py tests/test_lsp_conversation_integration.py -k "docs" -q
```

Expected: PASS.

- [ ] **Step 5: Run the complete LSP regression set**

```bash
uv run pytest tests/test_lsp_conversation_protocol.py tests/test_lsp_conversation_service.py tests/test_lsp_conversation_integration.py --tb=short
```

Expected: PASS with no changes to existing protocol, focus, apply/discard, or compilation behavior.

- [ ] **Step 6: Commit LSP RAG routing**

```bash
git add cli/src/modelable/lsp/conversation_service.py cli/tests/test_lsp_conversation_service.py cli/tests/test_lsp_conversation_integration.py
git commit -m "feat: route LSP documentation chat through RAG"
```

### Task 4: Archive the completed CLI RAG plan and finish validation

**Files:**
- Rename: `docs/superpowers/plans/2026-08-01-rag-cli-chat-adapter.md` -> `docs/superpowers/plans/archived/2026-08-01-rag-cli-chat-adapter.md`
- Rename: `docs/superpowers/specs/2026-08-01-rag-cli-chat-adapter-design.md` -> `docs/superpowers/specs/archived/2026-08-01-rag-cli-chat-adapter-design.md`
- Modify: `docs/cli-reference.md` only if the LSP capability needs a user-facing note

**Interfaces:**
- Consumes: merged CLI RAG behavior and the new LSP contract.
- Produces: no completed CLI plan/spec left in the active directories and documentation that distinguishes explicit CLI/LSP `/docs` support from future automatic normal-chat retrieval.

- [ ] **Step 1: Move completed CLI documents into archived directories**

Use Git renames and preserve filenames. Do not modify the content during the move.

- [ ] **Step 2: Add only necessary LSP documentation**

If `docs/cli-reference.md` describes conversation protocol consumers, add a short note that clients may supply `documentationIndexUri` for explicit `/docs` turns. Do not document automatic RAG for ordinary chat; that remains future work.

- [ ] **Step 3: Run all required Modelable gates from `cli/`**

```bash
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

- [ ] **Step 4: Run strict documentation validation from the repository root**

```bash
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.7.6 mkdocs build --strict
```

- [ ] **Step 5: Review and commit the archive/validation result**

```bash
git diff --check
git status --short
git add docs cli
git commit -m "docs: archive completed CLI RAG plan"
```

The branch is ready for PR review only after all four CLI gates, the LSP regression set, and strict MkDocs build pass.
