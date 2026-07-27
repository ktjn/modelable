# Shared Conversation Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make CLI, VS Code, and the browser playground use one Python-owned typed conversation engine while WebLLM and other providers supply schema-constrained plans rather than raw Modelable source.

**Architecture:** Extract browser-safe provider types and a resumable typed planner, then place conversation lifecycle logic behind a platform-neutral engine and environment port. Preserve CLI and VS Code through a filesystem adapter; add a Pyodide in-memory adapter and a TypeScript completion driver for the browser.

**Tech Stack:** Python 3.14, Pydantic 2, JSON Schema 2020-12, Pyodide, TypeScript 7, React 19, Web Workers, `@mlc-ai/web-llm`, Vitest, Playwright, VS Code LSP/chat APIs, Ollama `/api/chat`.

**Design:** [Shared Conversation Engine Design](../../specs/archived/2026-07-27-shared-conversation-engine-design.md)

## Global Constraints

- Python owns prompts, typed plans, validation, canonical rendering, previews, and lifecycle semantics.
- TypeScript interfaces own presentation and transport only.
- Models return closed typed plans; no provider output is interpreted as raw `.mdl` source.
- Every source mutation and artifact promotion requires an exact preview and explicit confirmation.
- Browser inference remains local through WebLLM.
- Ollama is an opt-in developer conformance provider, not a web UI provider.
- Browser chat history lasts only for the current page session.
- Streaming tokens, remote operations, autonomous tools, and persistent browser chat are out of scope.
- Full JSON schemas must reach WebLLM and Ollama, and responses must still be independently validated.
- Existing CLI and VS Code conversation behavior must remain compatible throughout migration.
- Run all four commands from `cli/` before every commit:
  `uv run ruff format .`,
  `uv run ruff check .`,
  the mypy baseline ratchet, and
  `uv run pytest --tb=short`.

---

## File Map

### Shared Python conversation core

- Create `cli/src/modelable/llm/provider_types.py`: browser-safe `LLMRequest`, `LLMResponse`, and `LLMProvider`.
- Modify `cli/src/modelable/llm/providers.py`: transport implementations only.
- Modify `cli/src/modelable/llm/conversation_planner.py`: resumable planning plus synchronous compatibility driver.
- Create `cli/src/modelable/llm/conversation_backend.py`: environment port and common preview/apply records.
- Create `cli/src/modelable/llm/conversation_engine.py`: platform-neutral history, planning, pending-action, and reply lifecycle.
- Modify `cli/src/modelable/llm/conversation.py`: filesystem compatibility facade over the shared engine.
- Create `cli/src/modelable/llm/filesystem_conversation.py`: filesystem workspace and compilation adapter.

### Browser Python adapter

- Create `cli/src/modelable/browser/conversation.py`: in-memory backend and bounded browser session registry.
- Modify `cli/src/modelable/browser/api.py`: retain synchronized source snapshots and expose conversation operations.
- Modify `cli/src/modelable/browser/dto.py`: browser conversation request/reply DTOs.
- Modify `cli/src/modelable/browser/dispatch.py`: `conversation.*` methods and serializers.
- Modify `cli/scripts/build_browser_wheel.py`: include browser-safe shared conversation modules.

### Browser TypeScript interface

- Modify `web/src/ai/types.ts`: full-schema provider request remains canonical.
- Modify `web/src/ai/ai.worker.ts`: schema-constrained WebLLM requests.
- Rename `web/src/ai/heuristic-provider.ts` to `web/src/ai/simulator-provider.ts`: deterministic semantic test provider.
- Modify `web/src/client.ts` and `web/src/protocol.ts`: resumable browser conversation transport.
- Modify `web/src/editor/types.ts` and `web/src/editor/SourceEditor.tsx`: expose active cursor position.
- Modify `web/src/ai/chat-types.ts`, `web/src/ai/ChatPanel.tsx`, and `web/src/App.tsx`: common reply rendering and lifecycle.

### Tests and documentation

- Add focused Python tests for provider types, resumable planning, engine contracts, filesystem compatibility, browser sessions, and Ollama conformance.
- Extend WebLLM worker/provider, client/protocol, App, ChatPanel, and Playwright tests.
- Preserve and extend VS Code conversation tests.
- Update `docs/cli-reference.md`, `docs/playground-design.md`, `docs/maintainers.md`, and `vscode/README.md`.

---

### Task 1: Separate Browser-Safe Provider Types and Pass Full Schemas to Ollama

**Files:**
- Create: `cli/src/modelable/llm/provider_types.py`
- Modify: `cli/src/modelable/llm/providers.py`
- Modify: `cli/src/modelable/llm/__init__.py`
- Modify: `cli/src/modelable/llm/conversation_planner.py`
- Modify: `cli/src/modelable/llm/update_plan.py`
- Modify: `cli/tests/test_llm_provider_integration.py`
- Modify: `cli/scripts/build_browser_wheel.py`
- Test: `cli/tests/test_browser_packaging.py`

**Interfaces:**
- Produces: `LLMRequest`, `LLMResponse`, and `LLMProvider` from `modelable.llm.provider_types`.
- Produces: `OllamaProvider.complete()` sending `request.schema` as `/api/chat.format` when present.

- [ ] **Step 1: Write failing provider and browser-package tests**

Add a transport assertion:

```python
def test_ollama_provider_posts_full_json_schema(monkeypatch):
    schema = {
        "type": "object",
        "properties": {"kind": {"const": "query"}},
        "required": ["kind"],
        "additionalProperties": False,
    }
    captured = install_ollama_response(monkeypatch, '{"kind":"query"}')
    provider = OllamaProvider(
        base_url="http://localhost:11434",
        model="qwen2.5-coder:14b",
    )

    provider.complete(
        LLMRequest(
            system="Return a plan.",
            user="Describe the workspace.",
            response_format="json",
            schema=schema,
        )
    )

    assert captured["payload"]["format"] == schema
```

Extend the browser wheel selection test to require:

```python
assert Path("modelable/llm/provider_types.py") in selected_source_paths()
```

- [ ] **Step 2: Run the focused tests and confirm the red state**

Run:

```powershell
cd cli
uv run pytest tests/test_llm_provider_integration.py -k "full_json_schema" -v
uv run pytest tests/test_browser_packaging.py -k "module_selection" -v
```

Expected: the Ollama payload contains `"json"` instead of the schema, and `provider_types.py` is absent.

- [ ] **Step 3: Extract provider-neutral types**

Create `provider_types.py` with:

```python
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LLMRequest:
    system: str
    user: str
    temperature: float = 0.2
    response_format: str = "text"
    schema: dict[str, object] | None = None


@dataclass(frozen=True)
class LLMResponse:
    content: str
    provider: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMProvider(Protocol):
    def complete(self, request: LLMRequest) -> LLMResponse: ...
```

Import these types from `providers.py`, `conversation_planner.py`, and
`update_plan.py`. Re-export them from `modelable.llm`.

- [ ] **Step 4: Send the exact schema through Ollama**

Replace the generic format branch with:

```python
if request.schema is not None:
    payload["format"] = request.schema
elif request.response_format == "json":
    payload["format"] = "json"
```

Add `llm/provider_types.py` to `INCLUDE_FILES`.

- [ ] **Step 5: Run provider, planner, and browser-build tests**

Run:

```powershell
cd cli
uv run pytest tests/test_llm_provider_integration.py tests/test_conversation_plan.py tests/test_browser_packaging.py -v
```

Expected: PASS.

- [ ] **Step 6: Run mandatory gates and commit**

Run the four required `cli/` commands, then:

```powershell
git add cli/src/modelable/llm/provider_types.py `
  cli/src/modelable/llm/providers.py `
  cli/src/modelable/llm/__init__.py `
  cli/src/modelable/llm/conversation_planner.py `
  cli/src/modelable/llm/update_plan.py `
  cli/scripts/build_browser_wheel.py `
  cli/tests/test_llm_provider_integration.py `
  cli/tests/test_browser_packaging.py
git commit -m "refactor: separate llm provider contracts"
```

---

### Task 2: Add a Resumable Typed Conversation Planner

**Files:**
- Modify: `cli/src/modelable/llm/conversation_planner.py`
- Modify: `cli/src/modelable/llm/__init__.py`
- Modify: `cli/scripts/build_browser_wheel.py`
- Test: `cli/tests/test_conversation_plan.py`
- Test: `cli/tests/test_browser_packaging.py`

**Interfaces:**
- Consumes: `LLMRequest`, `LLMResponse`, and `LLMProvider` from Task 1.
- Produces: `PendingPlanRequest`.
- Produces: `ResumableConversationPlanner.begin(message, context)`.
- Produces: `ResumableConversationPlanner.resume(request_id, content)`.
- Preserves: `ConversationPlanner.plan(message, context) -> ConversationPlan`.

- [ ] **Step 1: Write failing begin/resume/repair tests**

Add tests covering a valid response and a repair:

```python
def test_resumable_planner_returns_request_then_valid_plan():
    planner = ResumableConversationPlanner(id_factory=lambda: "request-1")
    pending = planner.begin("Create customer.Customer", planner_context())

    assert isinstance(pending, PendingPlanRequest)
    assert pending.request_id == "request-1"
    assert pending.request.schema == conversation_plan_json_schema()

    plan = planner.resume(
        "request-1",
        json.dumps(valid_create_customer_plan()),
    )
    assert isinstance(plan, ChangeSetPlan)


def test_resumable_planner_requests_one_bounded_repair():
    ids = iter(("initial", "repair"))
    planner = ResumableConversationPlanner(
        repair_attempts=1,
        id_factory=lambda: next(ids),
    )
    initial = planner.begin("Create customer.Customer", planner_context())
    repair = planner.resume(initial.request_id, "{malformed")

    assert isinstance(repair, PendingPlanRequest)
    assert repair.request_id == "repair"
    assert repair.attempt == 1
    assert "validation error" in repair.request.user.lower()
```

Also test that late, duplicate, and unknown request IDs raise
`PlanningRequestError`.

- [ ] **Step 2: Run the focused tests and confirm they fail**

Run:

```powershell
cd cli
uv run pytest tests/test_conversation_plan.py -k "resumable" -v
```

Expected: imports fail because the resumable types do not exist.

- [ ] **Step 3: Implement the resumable state machine**

Add:

```python
@dataclass(frozen=True)
class PendingPlanRequest:
    request_id: str
    request: LLMRequest
    attempt: int


@dataclass
class _PendingPlanningState:
    message: str
    context: PlannerContext
    attempt: int


class PlanningRequestError(ValueError):
    pass
```

`ResumableConversationPlanner` stores pending state by request ID. `begin()`
returns deterministic offline plans immediately and otherwise creates the
initial completion request. `resume()` consumes the request ID exactly once,
parses the response, and either returns a plan or registers the next bounded
repair request. Exhaustion returns the same typed `UnsupportedPlan` currently
used by `ConversationPlanner`.

- [ ] **Step 4: Drive the resumable planner from the synchronous API**

Refactor `ConversationPlanner.plan()` to:

```python
outcome = self.resumable.begin(message, context)
while isinstance(outcome, PendingPlanRequest):
    if self.provider is None:
        raise RuntimeError("Pending planning requires a provider")
    response = self.provider.complete(outcome.request)
    outcome = self.resumable.resume(outcome.request_id, response.content)
return outcome
```

Preserve current provider-failure and repair error wording.

- [ ] **Step 5: Add planner modules to the browser wheel**

Add `llm/conversation_plan.py` and `llm/conversation_planner.py` to
`INCLUDE_FILES`. Assert both are selected and contain no forbidden imports.

- [ ] **Step 6: Run the complete planner and provider suite**

Run:

```powershell
cd cli
uv run pytest tests/test_conversation_plan.py tests/test_conversation.py tests/test_llm_provider_integration.py tests/test_browser_packaging.py -v
```

Expected: PASS with existing synchronous behavior unchanged.

- [ ] **Step 7: Run mandatory gates and commit**

Run the four required `cli/` commands, then:

```powershell
git add cli/src/modelable/llm/conversation_planner.py `
  cli/src/modelable/llm/__init__.py `
  cli/scripts/build_browser_wheel.py `
  cli/tests/test_conversation_plan.py `
  cli/tests/test_browser_packaging.py
git commit -m "feat: add resumable conversation planning"
```

---

### Task 3: Extract the Platform-Neutral Conversation Engine

**Files:**
- Create: `cli/src/modelable/llm/conversation_backend.py`
- Create: `cli/src/modelable/llm/conversation_engine.py`
- Modify: `cli/src/modelable/llm/conversation.py`
- Modify: `cli/src/modelable/llm/__init__.py`
- Test: `cli/tests/test_conversation_engine.py`

**Interfaces:**
- Consumes: `ResumableConversationPlanner`, `PendingPlanRequest`, and `ConversationPlan`.
- Produces: `ConversationBackend` protocol.
- Produces: `ConversationEngine.begin_turn()`, `resume_turn()`, `apply()`, `discard()`, and `reset()`.
- Produces: `ConversationOutcome = ConversationReply | PendingPlanRequest`.

- [ ] **Step 1: Write a fake-backend engine contract test**

Create a `RecordingBackend` that implements:

```python
class ConversationBackend(Protocol):
    def workspace_summary(self) -> str: ...
    def execute_query(self, plan: QueryPlan) -> ConversationReply: ...
    def preview_source_change(
        self,
        plan: ChangeSetPlan,
        replaced_action_id: str | None,
    ) -> ConversationReply: ...
    def preview_compilation(
        self,
        plan: CompilePlan,
        replaced_action_id: str | None,
    ) -> ConversationReply: ...
    def apply(self, action_id: str) -> ConversationReply: ...
    def discard(self, action_id: str) -> ConversationReply: ...
    def reset(self) -> None: ...
```

Test:

```python
def test_engine_resumes_plan_and_tracks_exact_pending_action():
    engine, backend = engine_with_scripted_plan(valid_create_customer_plan())
    pending = engine.begin_turn("Create a customer")
    reply = engine.resume_turn(
        pending.request_id,
        json.dumps(valid_create_customer_plan()),
    )

    assert reply.kind == "preview"
    assert reply.change_set_id == "change-1"
    assert engine.pending_action_id == "change-1"
    assert backend.previewed_plans[0].kind == "change_set"
```

Add cases for deterministic query, refinement replacing a pending action,
exact apply/discard IDs, reset, and history updates only after a completed
reply.

- [ ] **Step 2: Run the engine tests and confirm they fail**

Run:

```powershell
cd cli
uv run pytest tests/test_conversation_engine.py -v
```

Expected: the new modules are missing.

- [ ] **Step 3: Move common reply types out of the filesystem session**

Move `ReplyKind`, `ConversationPreviewFile`, and `ConversationReply` to
`conversation_backend.py`. Re-export them from `conversation.py` and
`modelable.llm` so existing imports remain valid.

Keep `ConversationPreviewFile.path` as `Path` for compatibility. Browser
logical document paths will use safe relative `Path` values and serialize back
to browser URIs at the adapter boundary.

- [ ] **Step 4: Implement `ConversationEngine`**

The constructor accepts:

```python
def __init__(
    self,
    *,
    backend: ConversationBackend,
    planner: ResumableConversationPlanner,
    focused_ref: str | None = None,
) -> None:
```

`begin_turn()` handles apply/discard aliases and deterministic `/compile`
parsing before starting the planner. `resume_turn()` accepts only the current
pending request ID. `_execute_plan()` delegates query, source preview, and
compilation preview to the backend, updates pending action identity from the
reply, and records history.

- [ ] **Step 5: Verify stale and cancellation semantics**

Add:

```python
def test_reset_invalidates_pending_completion_and_preview():
    pending = engine.begin_turn("Create a customer")
    engine.reset()

    with pytest.raises(PlanningRequestError):
        engine.resume_turn(pending.request_id, "{}")
    assert backend.reset_calls == 1
    assert engine.pending_action_id is None
```

Run:

```powershell
cd cli
uv run pytest tests/test_conversation_engine.py -v
```

Expected: PASS.

- [ ] **Step 6: Run existing conversation tests**

Run:

```powershell
cd cli
uv run pytest tests/test_conversation.py tests/test_conversation_plan.py -v
```

Expected: PASS; the compatibility exports prevent import churn.

- [ ] **Step 7: Run mandatory gates and commit**

Run the four required `cli/` commands, then:

```powershell
git add cli/src/modelable/llm/conversation_backend.py `
  cli/src/modelable/llm/conversation_engine.py `
  cli/src/modelable/llm/conversation.py `
  cli/src/modelable/llm/__init__.py `
  cli/tests/test_conversation_engine.py
git commit -m "refactor: extract shared conversation engine"
```

---

### Task 4: Move Filesystem Effects Behind a Compatibility Adapter

**Files:**
- Create: `cli/src/modelable/llm/filesystem_conversation.py`
- Modify: `cli/src/modelable/llm/conversation.py`
- Modify: `cli/src/modelable/lsp/conversation_service.py`
- Test: `cli/tests/test_conversation.py`
- Test: `cli/tests/test_lsp_conversation_service.py`
- Test: `cli/tests/test_lsp_conversation_integration.py`
- Test: `vscode/src/test/suite/conversation.test.ts`

**Interfaces:**
- Consumes: `ConversationBackend` and `ConversationEngine` from Task 3.
- Produces: `FilesystemConversationBackend`.
- Preserves: `ConversationSession` constructor, properties, and `turn()` API.

- [ ] **Step 1: Add compatibility assertions before refactoring**

Extend tests to assert:

```python
class OneResponseProvider:
    def __init__(self, plan: ConversationPlan) -> None:
        self.plan = plan

    def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            content=self.plan.model_dump_json(),
            provider="test",
            model="one-response",
        )


def test_conversation_session_remains_filesystem_compatible(tmp_path):
    session = ConversationSession(
        path=write_customer_workspace(tmp_path),
        provider=OneResponseProvider(valid_add_email_plan()),
    )

    preview = session.turn("Add an email field")
    applied = session.turn("/apply")

    assert preview.kind == "preview"
    assert applied.kind == "applied"
    assert session.pending_action_id is None
```

Retain existing compilation cleanup, rollback, LSP serialization, dirty-buffer,
and VS Code protocol tests.

- [ ] **Step 2: Run the compatibility tests in their green pre-refactor state**

Run:

```powershell
cd cli
uv run pytest tests/test_conversation.py tests/test_lsp_conversation_service.py tests/test_lsp_conversation_integration.py -v
```

Expected: PASS before moving code.

- [ ] **Step 3: Implement `FilesystemConversationBackend`**

Move filesystem-specific logic from `ConversationSession`:

- `WorkspaceEditor` creation and preview;
- `CompilationService` staging;
- pending `PendingChangeSet` or `PendingCompilation`;
- exact apply/discard and cleanup;
- workspace reload;
- preview file construction; and
- query execution.

The backend owns the concrete pending object. It rejects an `action_id` that
does not match `_pending_id(self.pending)`.

- [ ] **Step 4: Turn `ConversationSession` into a compatibility facade**

Construct:

```python
self.backend = FilesystemConversationBackend(
    path=path,
    compilation_service=compilation_service,
    provider_name=provider_name,
    model_name=model_name,
    confirmation_surface=confirmation_surface,
)
self.engine = ConversationEngine(
    backend=self.backend,
    planner=ResumableConversationPlanner(repair_attempts=repair_attempts),
    focused_ref=focused_ref,
)
```

`turn()` drives pending plan requests synchronously through the configured
provider. Proxy `pending`, `pending_action_id`, `pending_operation_kind`,
`workspace`, `history`, `focused_ref`, cleanup, and close behavior for LSP and
CLI callers.

- [ ] **Step 5: Run CLI, LSP, and VS Code tests**

Run:

```powershell
cd cli
uv run pytest tests/test_conversation.py `
  tests/test_workspace_editor.py `
  tests/test_lsp_conversation_protocol.py `
  tests/test_lsp_conversation_service.py `
  tests/test_lsp_conversation_integration.py -v
cd ..\vscode
npm run check
npm run build
npm test
```

Expected: PASS with unchanged public behavior.

- [ ] **Step 6: Run mandatory gates and commit**

Run the four required `cli/` commands, then:

```powershell
git add cli/src/modelable/llm/filesystem_conversation.py `
  cli/src/modelable/llm/conversation.py `
  cli/src/modelable/lsp/conversation_service.py `
  cli/tests/test_conversation.py `
  cli/tests/test_lsp_conversation_service.py `
  cli/tests/test_lsp_conversation_integration.py `
  vscode/src/test/suite/conversation.test.ts
git commit -m "refactor: adapt filesystem conversations"
```

---

### Task 5: Add Deterministic Semantic Simulation

**Files:**
- Create: `cli/tests/support/__init__.py`
- Create: `cli/tests/support/conversation_simulator.py`
- Create: `web/src/ai/simulator-provider.ts`
- Create: `web/src/ai/simulator-provider.test.ts`
- Delete: `web/src/ai/heuristic-provider.ts`
- Delete: `web/src/ai/heuristic-provider.test.ts`
- Modify: `web/src/App.tsx`
- Modify: `web/src/App.test.tsx`
- Test: `cli/tests/test_conversation_engine.py`

**Interfaces:**
- Consumes: full-schema `LLMRequest`.
- Produces: deterministic valid, malformed-then-repaired, clarification, and provider-failure responses.
- Browser test selector changes from `ai=heuristic` to `ai=simulator`.

- [ ] **Step 1: Write failing simulator behavior tests**

Add TypeScript tests:

```typescript
it('returns a typed create-model plan for an invoice request', async () => {
  const provider = new SimulatorProvider();
  const response = await provider.complete(conversationRequest(
    'Create an invoice with an invoice id',
  ));
  expect(JSON.parse(response.content)).toMatchObject({
    kind: 'change_set',
    operations: [{ kind: 'create_model', name: 'Invoice' }],
  });
});

it('returns malformed output once then a valid repair', async () => {
  const provider = new SimulatorProvider({ malformedFirst: true });
  expect((await provider.complete(initialRequest)).content).toBe('{malformed');
  expect(JSON.parse((await provider.complete(repairRequest)).content).kind)
    .toBe('change_set');
});
```

Add Python engine tests using `ScriptedConversationProvider`.

- [ ] **Step 2: Run tests and confirm failure**

Run:

```powershell
cd web
npm test -- --run src/ai/simulator-provider.test.ts
cd ..\cli
uv run pytest tests/test_conversation_engine.py -k "simulator" -v
```

Expected: simulator modules are missing.

- [ ] **Step 3: Implement semantic simulator providers**

The simulator recognizes these deterministic intent phrases:

- `describe the workspace` -> `QueryPlan(summary)`;
- `create an invoice` -> `ChangeSetPlan(CreateModel)`;
- `suggest a projection` -> `ChangeSetPlan(CreateProjection)`;
- `add email` -> append-version plus add-field operations;
- `/compile json-schema` -> `CompilePlan`;
- ambiguous `create a projection` -> `ClarificationPlan`.

It returns JSON plans only and never renders `.mdl`. Repair mode detects
`"Previous response validation error"` in the request and returns the valid
plan on the next call.

- [ ] **Step 4: Replace browser heuristic test activation**

Use `SimulatorProvider` only when the explicit test query parameter selects it.
Without WebGPU, production still supports deterministic engine questions but
does not pretend the simulator is a real model.

- [ ] **Step 5: Run focused web and engine tests**

Run:

```powershell
cd web
npm test -- --run src/ai src/App.test.tsx
cd ..\cli
uv run pytest tests/test_conversation_engine.py tests/test_conversation_plan.py -v
```

Expected: PASS.

- [ ] **Step 6: Run mandatory gates and commit**

Run the four required `cli/` commands, then:

```powershell
git add cli/tests/support/conversation_simulator.py `
  cli/tests/support/__init__.py `
  cli/tests/test_conversation_engine.py `
  web/src/ai/simulator-provider.ts `
  web/src/ai/simulator-provider.test.ts `
  web/src/ai/heuristic-provider.ts `
  web/src/ai/heuristic-provider.test.ts `
  web/src/App.tsx `
  web/src/App.test.tsx
git commit -m "test: add semantic conversation simulator"
```

---

### Task 6: Implement the In-Memory Browser Conversation Backend

**Files:**
- Create: `cli/src/modelable/browser/conversation.py`
- Modify: `cli/src/modelable/browser/api.py`
- Modify: `cli/src/modelable/browser/dto.py`
- Modify: `cli/src/modelable/browser/__init__.py`
- Modify: `cli/scripts/build_browser_wheel.py`
- Test: `cli/tests/test_browser_conversation.py`
- Test: `cli/tests/test_browser_packaging.py`

**Interfaces:**
- Consumes: `ConversationEngine`, `ConversationBackend`, and resumable planning.
- Produces: `BrowserConversationService.turn()`, `resume()`, `apply()`, `discard()`, and `reset()`.
- Produces: `BrowserConversationPendingResult` and `BrowserConversationReply`.

- [ ] **Step 1: Write failing browser service tests**

Cover a complete projection flow:

```python
def valid_projection_plan() -> dict[str, object]:
    return {
        "kind": "change_set",
        "summary": "Add a billing projection for Customer",
        "operations": [
            {
                "kind": "create_projection",
                "source_ref": "customer.Customer",
                "consumer_domain": "billing",
                "name": "CustomerProjection",
                "fields": ["id", "name"],
            }
        ],
    }


def test_browser_conversation_previews_and_applies_projection():
    compiler = browser_compiler_with_customer_and_billing()
    service = BrowserConversationService(compiler)

    pending = service.turn(
        session_id="session-1",
        workspace_revision=1,
        message="Suggest a projection for billing",
        active_document_uri=CUSTOMER_URI,
        line=3,
        character=10,
    )
    preview = service.resume(
        session_id="session-1",
        request_id=pending.request_id,
        workspace_revision=1,
        content=json.dumps(valid_projection_plan()),
    )
    applied = service.apply(
        session_id="session-1",
        action_id=preview.change_set_id,
        workspace_revision=1,
    )

    assert preview.kind == "preview"
    assert "projection" in preview.preview_files[0].after_text
    assert applied.workspace_revision == 2
```

Add tests for focus resolution, clarification with no focus, stale revision,
late completion, repair, source-change replacement, compilation artifact
promotion, discard, reset, and a bounded session registry.

- [ ] **Step 2: Run tests and confirm failure**

Run:

```powershell
cd cli
uv run pytest tests/test_browser_conversation.py -v
```

Expected: browser conversation service is missing.

- [ ] **Step 3: Retain exact synchronized sources in `BrowserCompiler`**

Store the latest validated `BrowserSource` tuple on `open_workspace()`. Expose a
read-only `sources` property. Updating the browser workspace must continue to
advance `LanguageWorkspace.revision` through the existing synchronization
path.

- [ ] **Step 4: Implement `BrowserConversationBackend`**

For source previews:

- convert browser URIs to safe relative logical `Path` identifiers;
- load a pathful in-memory `Workspace`;
- call the real `WorkspaceEditor.preview()` only;
- retain `PendingChangeSet` without invoking filesystem apply; and
- on apply, restage against current hashes, update the compiler's sources, and
  synchronize the next workspace revision.

For compilation:

- call existing in-memory browser compilation for the requested target;
- retain exact artifact content and hashes;
- return those bytes only after matching Apply; and
- discard without modifying output state.

- [ ] **Step 5: Implement bounded session and completion state**

Use a maximum of 32 sessions and 30-minute monotonic idle expiry, matching the
LSP service. Each session owns one engine, one active completion request, and
one pending action. Reset or expiry invalidates all three.

- [ ] **Step 6: Include browser-safe modules in the wheel**

Add:

```text
llm/conversation_backend.py
llm/conversation_engine.py
llm/conversation_plan.py
llm/conversation_planner.py
llm/provider_types.py
llm/workspace_editor.py
llm/workspace_query.py
```

Include `workspace_editor.py`, but have the browser backend call only its pure
`preview()` path. Add a browser test that replaces `WorkspaceEditor.apply()`
with a function that fails immediately, proving browser preview/apply never
uses the filesystem mutation path. Keep the forbidden-import scan unchanged.

- [ ] **Step 7: Run browser Python tests**

Run:

```powershell
cd cli
uv run pytest tests/test_browser_conversation.py `
  tests/test_browser_ai.py `
  tests/test_browser_packaging.py `
  tests/test_workspace_editor.py -v
```

Expected: PASS.

- [ ] **Step 8: Run mandatory gates and commit**

Run the four required `cli/` commands, then:

```powershell
git add cli/src/modelable/browser/conversation.py `
  cli/src/modelable/browser/api.py `
  cli/src/modelable/browser/dto.py `
  cli/src/modelable/browser/__init__.py `
  cli/scripts/build_browser_wheel.py `
  cli/tests/test_browser_conversation.py `
  cli/tests/test_browser_packaging.py
git commit -m "feat: add browser conversation backend"
```

---

### Task 7: Add Browser Conversation Protocol and Schema-Constrained WebLLM

**Files:**
- Modify: `cli/src/modelable/browser/dispatch.py`
- Modify: `cli/tests/test_browser_conversation.py`
- Modify: `web/src/protocol.ts`
- Modify: `web/src/protocol.test.ts`
- Modify: `web/src/client.ts`
- Modify: `web/src/client.test.ts`
- Modify: `web/src/ai/ai.worker.ts`
- Modify: `web/src/ai/webgpu-provider.test.ts`
- Modify: `web/src/ai/types.ts`

**Interfaces:**
- Consumes: browser service methods from Task 6.
- Produces: `conversation.turn`, `conversation.resume`, `conversation.apply`, `conversation.discard`, and `conversation.reset`.
- Produces: `BrowserCompilerClient.conversationTurn()` and lifecycle methods.

- [ ] **Step 1: Write failing strict protocol tests**

Add Python and TypeScript fixtures for:

```json
{
  "status": "pending_llm",
  "session_id": "session-1",
  "request_id": "request-1",
  "attempt": 0,
  "llm_request": {
    "system": "Return a plan.",
    "user": "Create an invoice.",
    "temperature": 0.1,
    "response_format": "json",
    "schema": {"type": "object"}
  }
}
```

Assert exact keys, request ID reuse rejection, workspace revision checks, and
common final reply validation.

- [ ] **Step 2: Write a failing WebLLM schema test**

Extract completion request construction as `createWebLlmCompletionRequest()` and
assert:

```typescript
expect(createWebLlmCompletionRequest(request).response_format).toEqual({
  type: 'json_object',
  schema: request.schema,
});
```

- [ ] **Step 3: Run focused tests and confirm failure**

Run:

```powershell
cd cli
uv run pytest tests/test_browser_conversation.py -k "dispatch" -v
cd ..\web
npm test -- --run src/protocol.test.ts src/client.test.ts src/ai/webgpu-provider.test.ts
```

Expected: conversation methods and schema forwarding are absent.

- [ ] **Step 4: Implement strict Python dispatch methods**

Validate exact fields for every method. `conversation.resume` must require
`sessionId`, `requestId`, `workspaceRevision`, and `llmResponseContent`.
Serialize schemas without altering keys or values.

- [ ] **Step 5: Implement TypeScript protocol types and guards**

Add discriminated `BrowserConversationPendingResult` and
`BrowserConversationReply` types. Keep pending LLM and final replies distinct;
do not accept unknown reply kinds or extra protocol fields.

- [ ] **Step 6: Implement the TypeScript completion loop**

`conversationTurn()` sends the initial request and loops:

```typescript
while (isBrowserConversationPendingResult(result)) {
  const response = await provider.complete(toLlmRequest(result.llm_request));
  result = await this.conversationResume({
    sessionId,
    requestId: result.request_id,
    workspaceRevision,
    llmResponseContent: response.content,
  });
}
return result;
```

The loop accepts an `AbortSignal`, stops on reset/dispose, and records provider
metadata only in the UI-side message.

- [ ] **Step 7: Pass schemas to WebLLM**

For JSON requests with a schema, send:

```typescript
response_format: {
  type: 'json_object',
  schema: request.schema,
}
```

For generic JSON without a schema, send `{ type: 'json_object' }`. Text
explanation replies no longer need a separate raw-source path; grounded
deterministic answers come from Python.

- [ ] **Step 8: Run Python and web protocol tests**

Run:

```powershell
cd cli
uv run pytest tests/test_browser_conversation.py tests/test_browser_ai.py -v
cd ..\web
npm test -- --run src/protocol.test.ts src/client.test.ts src/ai
npm run check
```

Expected: PASS.

- [ ] **Step 9: Run mandatory gates and commit**

Run the four required `cli/` commands, then:

```powershell
git add cli/src/modelable/browser/dispatch.py `
  cli/tests/test_browser_conversation.py `
  web/src/protocol.ts `
  web/src/protocol.test.ts `
  web/src/client.ts `
  web/src/client.test.ts `
  web/src/ai/ai.worker.ts `
  web/src/ai/webgpu-provider.test.ts `
  web/src/ai/types.ts
git commit -m "feat: bridge browser conversations to webllm"
```

---

### Task 8: Move the Playground Chat UI onto the Shared Engine

**Files:**
- Modify: `web/src/editor/types.ts`
- Modify: `web/src/editor/SourceEditor.tsx`
- Modify: `web/src/editor/SourceEditor.test.tsx`
- Modify: `web/src/ai/chat-types.ts`
- Modify: `web/src/ai/ChatPanel.tsx`
- Modify: `web/src/ai/ChatPanel.test.tsx`
- Modify: `web/src/App.tsx`
- Modify: `web/src/App.test.tsx`
- Modify: `web/src/style.css`

**Interfaces:**
- Consumes: `BrowserCompilerClient.conversationTurn()` and lifecycle methods from Task 7.
- Produces: free-form shared chat, focused shortcuts, common preview rendering, apply/discard/reset, and artifact promotion.

- [ ] **Step 1: Add failing editor-focus tests**

Extend `SourceEditorHandle`:

```typescript
getPosition(): {
  uri: string;
  line: number;
  character: number;
} | null;
```

Test that it returns the active Monaco model URI and zero-based cursor position,
and returns `null` before editor initialization.

- [ ] **Step 2: Add failing App conversation tests**

Cover:

```typescript
test('free-form chat calls conversationTurn instead of aiGenerate', async () => {
  await sendChat('Create an invoice');
  expect(client.conversationTurn).toHaveBeenCalledWith(
    expect.objectContaining({ message: 'Create an invoice' }),
    expect.anything(),
    expect.anything(),
  );
  expect(client.aiGenerate).not.toHaveBeenCalled();
});

test('suggest projection sends focused cursor context', async () => {
  await user.click(screen.getByRole('button', { name: 'Suggest projection' }));
  expect(client.conversationTurn).toHaveBeenCalledWith(
    expect.objectContaining({
      message: 'Suggest a projection for the focused model',
      activeDocumentUri: 'file:///customer.mdl',
      position: { line: 3, character: 8 },
    }),
    expect.anything(),
    expect.anything(),
  );
});
```

Add tests for clarification, multi-file preview, refinement, exact Apply,
Discard, Reset, stale reply, provider error, and compilation artifact
promotion.

- [ ] **Step 3: Run UI tests and confirm failure**

Run:

```powershell
cd web
npm test -- --run src/editor/SourceEditor.test.tsx src/ai/ChatPanel.test.tsx src/App.test.tsx
```

Expected: cursor API and conversation UI behavior are absent.

- [ ] **Step 4: Expose cursor position**

Read `editorRef.current?.getPosition()` and the active model URI from Monaco.
Convert Monaco's one-based line/column to zero-based protocol values.

- [ ] **Step 5: Replace browser-specific chat message variants**

Use one assistant message type carrying:

- common reply kind and text;
- pending status;
- action ID and operation kind;
- preview files;
- compilation files;
- diagnostics;
- provider/model metadata; and
- accepted/discarded outcome.

Render Markdown for textual replies, exact diffs for source previews, artifact
lists for compilation previews, and context-appropriate lifecycle buttons.

- [ ] **Step 6: Route chat and shortcuts through the conversation client**

Free-form send uses the exact entered message. Shortcuts submit:

- Explain: `Describe the focused definition or workspace`.
- Generate: retain the user's natural-language description.
- Suggest Projection: `Suggest a projection for the focused model`.

Do not construct `sourceRef` or `consumerDomain` in TypeScript. Python resolves
focus and clarifies consumer intent.

- [ ] **Step 7: Apply exact source and artifact results**

For source changes, update every returned virtual document in one workspace
state transition and synchronize the returned workspace revision. For
compilation, promote returned exact artifacts into the existing output panel
and download collection. Never regenerate during Apply.

- [ ] **Step 8: Remove obsolete browser AI methods**

After all UI tests use conversation methods, remove `ai.generate`,
`ai.explain`, `runAiGenerate`, `runAiExplain`, and raw-source result types from
the browser protocol and client. Retain a migration assertion that no web source
references those method names.

- [ ] **Step 9: Run complete web unit, type, and build gates**

Run:

```powershell
cd web
npm test
npm run check
npm run build
```

Expected: all pass.

- [ ] **Step 10: Run mandatory gates and commit**

Run the four required `cli/` commands, then:

```powershell
git add web/src/editor/types.ts `
  web/src/editor/SourceEditor.tsx `
  web/src/editor/SourceEditor.test.tsx `
  web/src/ai/chat-types.ts `
  web/src/ai/ChatPanel.tsx `
  web/src/ai/ChatPanel.test.tsx `
  web/src/App.tsx `
  web/src/App.test.tsx `
  web/src/style.css `
  web/src/client.ts `
  web/src/protocol.ts `
  cli/src/modelable/browser/dispatch.py
git commit -m "feat: align playground conversations"
```

---

### Task 9: Add Cross-Surface and Browser End-to-End Coverage

**Files:**
- Modify: `web/tests/ai-actions.spec.ts`
- Modify: `web/tests/helpers.ts`
- Modify: `cli/tests/test_conversation_engine.py`
- Modify: `cli/tests/test_lsp_conversation_integration.py`
- Modify: `vscode/src/test/suite/conversation.test.ts`

**Interfaces:**
- Consumes: the shared engine, filesystem adapter, browser adapter, and simulator.
- Produces: parity assertions across CLI, VS Code, and browser.

- [ ] **Step 1: Add failing browser conversation scenarios**

Replace heuristic tests with simulator-backed scenarios:

- grounded workspace question;
- create entity preview/apply;
- focused projection preview/apply with canonical braces;
- ambiguous projection clarification;
- refine a pending model change;
- discard without mutation;
- compile JSON Schema preview/apply/download;
- malformed-first response repaired;
- reset invalidates pending state; and
- stale workspace blocks Apply.

For source generation, assert compiler validation succeeds after Apply rather
than checking only visible text.

- [ ] **Step 2: Add a common semantic parity table**

In Python, parameterize expected reply kinds:

```python
@pytest.mark.parametrize(
    ("message", "expected_kind"),
    [
        ("Describe the workspace", "answer"),
        ("Create an invoice", "preview"),
        ("Suggest a projection for billing", "preview"),
        ("Create a projection", "clarification"),
        ("/compile json-schema", "preview"),
    ],
)
def test_engine_reply_kind_parity(message, expected_kind, engine_driver):
    assert engine_driver.turn(message).kind == expected_kind
```

Run the same cases through filesystem and in-memory backend fixtures.

- [ ] **Step 3: Extend VS Code tests without changing its interface**

Assert the VS Code participant still renders shared reply text, exact diffs,
Apply/Discard follow-ups, and compilation previews after the engine refactor.

- [ ] **Step 4: Run all conversation-focused suites**

Run:

```powershell
cd cli
uv run pytest tests/test_conversation_engine.py `
  tests/test_conversation.py `
  tests/test_browser_conversation.py `
  tests/test_lsp_conversation_integration.py -v
cd ..\web
npx playwright test tests/ai-actions.spec.ts --project=chromium
cd ..\vscode
npm run check
npm run build
npm test
```

Expected: PASS.

- [ ] **Step 5: Run mandatory gates and commit**

Run the four required `cli/` commands, then:

```powershell
git add web/tests/ai-actions.spec.ts `
  web/tests/helpers.ts `
  cli/tests/test_conversation_engine.py `
  cli/tests/test_lsp_conversation_integration.py `
  vscode/src/test/suite/conversation.test.ts
git commit -m "test: verify cross-surface conversation parity"
```

---

### Task 10: Add Opt-In Ollama Conformance, Documentation, and Final Verification

**Files:**
- Create: `cli/tests/test_ollama_conversation_conformance.py`
- Modify: `cli/pyproject.toml`
- Modify: `docs/maintainers.md`
- Modify: `docs/cli-reference.md`
- Modify: `docs/playground-design.md`
- Modify: `vscode/README.md`
- Modify: `docs/superpowers/specs/2026-07-27-shared-conversation-engine-design.md`
- Modify: `docs/superpowers/plans/2026-07-27-shared-conversation-engine.md`

**Interfaces:**
- Consumes: the complete shared conversation implementation.
- Produces: opt-in real-model verification and accurate public/maintainer documentation.

- [ ] **Step 1: Write the opt-in Ollama conformance module**

Register:

```toml
"ollama: requires a developer-controlled local Ollama server and model (opt-in via MODELABLE_OLLAMA_TESTS=1)"
```

Skip unless `MODELABLE_OLLAMA_TESTS=1`. Require
`MODELABLE_OLLAMA_MODEL`; use `MODELABLE_LLM_BASE_URL` or
`http://127.0.0.1:11434`.

Test entity creation, grounded projection, update, clarification, and repair.
Assertions must validate typed plans and canonical rendered source, not exact
prose or field ordering beyond semantic requirements.

- [ ] **Step 2: Run conformance against the local server**

Run:

```powershell
cd cli
$env:MODELABLE_OLLAMA_TESTS='1'
$env:MODELABLE_OLLAMA_MODEL='qwen2.5-coder:14b'
uv run pytest tests/test_ollama_conversation_conformance.py -v
```

Expected: every case either produces the required valid semantic result or the
documented bounded actionable failure. Tests must not download or mutate
models.

- [ ] **Step 3: Update user and maintainer documentation**

Document:

- one shared engine and interface-specific adapters;
- browser session-only history;
- schema-constrained WebLLM planning;
- focused projection clarification;
- exact source and artifact previews;
- simulator-based browser tests;
- opt-in Ollama commands and environment variables; and
- the absence of an Ollama web provider.

Keep the design and plan status active throughout the implementation PR. After
that PR merges, archive both files in the required follow-up on `main`.

- [ ] **Step 4: Run doc/spec review**

Run structural, cross-reference, coverage, and quality review across every
changed `docs/` file. Include `Doc/spec review: all phases passed` in the PR
body or list every warning.

- [ ] **Step 5: Run full CLI gates**

From `cli/`:

```powershell
uv run ruff format .
uv run ruff check .
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
uv run pytest --tb=short
```

Expected: all pass.

- [ ] **Step 6: Run full web gates**

From `web/`:

```powershell
npm test
npm run check
npm run build
npx playwright test --project=chromium
npm run check:budgets
```

Expected: all pass.

- [ ] **Step 7: Run full VS Code gates**

From `vscode/`:

```powershell
npm run check
npm run build
npm test
npm run package
```

Expected: all pass.

- [ ] **Step 8: Verify obsolete paths and repository state**

Run:

```powershell
rg -n "ai\\.generate|ai\\.explain|HeuristicProvider|llmResponseContent" web/src cli/src/modelable/browser
git diff --check
git status -sb
```

Expected: no obsolete browser AI path remains, diff check passes, and only
intended files are modified.

- [ ] **Step 9: Commit final docs and conformance tests**

```powershell
git add cli/tests/test_ollama_conversation_conformance.py `
  cli/pyproject.toml `
  docs/maintainers.md `
  docs/cli-reference.md `
  docs/playground-design.md `
  vscode/README.md `
  docs/superpowers/specs/2026-07-27-shared-conversation-engine-design.md `
  docs/superpowers/plans/2026-07-27-shared-conversation-engine.md
git commit -m "docs: document shared conversation engine"
```

---

## Completion Checklist

- [ ] CLI, VS Code, and browser use the same planner and conversation engine.
- [ ] Browser free-form chat no longer routes unconditionally to entity generation.
- [ ] Suggest Projection grounds focus or returns clarification.
- [ ] WebLLM and Ollama receive the full closed JSON schema.
- [ ] LLM responses contain typed plans rather than raw Modelable source.
- [ ] Python renders and validates canonical source.
- [ ] Filesystem and browser adapters promote exact staged effects.
- [ ] Simulator tests cover normal, repair, clarification, and failure paths.
- [ ] Opt-in Ollama conformance covers entity, projection, update, clarification, and repair.
- [ ] CLI, web, browser E2E, VS Code, package, and budget gates pass.
- [ ] Doc/spec review passes.
- [ ] Design and plan remain active until the implementation PR merges.
