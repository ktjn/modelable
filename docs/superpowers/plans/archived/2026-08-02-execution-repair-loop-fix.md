# Execution Repair Loop Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `ConversationEngine`'s execution-repair loop so `execution_repair_attempts` actually governs multiple corrective rounds (today it silently caps at one regardless of the configured value), raise the browser playground's budget to 2, and replace the raw internal error text with a clearer message when the loop ultimately gives up.

**Architecture:** All changes are in `cli/src/modelable/llm/conversation_engine.py` (the `_PendingExecutionRepair` dataclass and `ConversationEngine._begin_execution_repair` / `_complete_execution_repair` / `_complete_plan`) plus the two `ConversationEngine(...)` construction sites in `cli/src/modelable/browser/conversation.py`. No protocol, schema, or TypeScript changes.

**Tech Stack:** Python 3.14, pytest, dataclasses.

## Global Constraints

- Design spec: `docs/superpowers/specs/2026-08-02-execution-repair-loop-fix-design.md` — follow its decisions exactly; do not expand scope beyond what it states.
- No changes to `cli/src/modelable/llm/conversation_planner.py` (the schema/parse-level repair loop is unrelated and already correct).
- No changes to `cli/src/modelable/llm/conversation.py` (the CLI's `ConversationSession` already threads `llm_config.repair_attempts` through and is untouched by this fix).
- Every task must leave `pytest cli/tests/test_conversation_engine.py` and `pytest cli/tests/test_browser_conversation.py` green.

---

### Task 1: Carry `PlannerContext` through the execution-repair loop

**Files:**
- Modify: `cli/src/modelable/llm/conversation_engine.py:45-49` (`_PendingExecutionRepair`), `:322-334` (`_begin_execution_repair`), `:336-350` (`_complete_execution_repair`)
- Test: `cli/tests/test_conversation_engine.py`

**Interfaces:**
- Consumes: existing `PlannerContext` (from `modelable.llm.conversation_planner`), already imported in `conversation_engine.py`.
- Produces: `_PendingExecutionRepair.context: PlannerContext` — a new field later tasks (Task 2) rely on being non-`None` whenever a repair round is in flight.

This is the root-cause fix. `_PendingExecutionRepair` currently stores only `request_id` and `message`, so `_complete_execution_repair` always calls `_complete_plan(..., context=None)`. `_complete_plan`'s retry gate requires `context is not None`, so a second repair round is impossible no matter what `execution_repair_attempts` is set to. `test_engine_repairs_change_set_plan_after_workspace_edit_error` (already in the suite) proves one round works; the new test below proves a second round currently cannot happen, then passes once fixed.

- [ ] **Step 1: Write the failing test**

Add to `cli/tests/test_conversation_engine.py` (after `test_engine_gives_up_after_execution_repair_budget_exhausted`, around line 313):

```python
def test_engine_attempts_second_execution_repair_round_when_budget_allows() -> None:
    ids = iter(("request-1",))
    backend = FailThenSucceedBackend(fail_calls_remaining=2)
    engine = ConversationEngine(
        backend=backend,
        planner=ResumableConversationPlanner(id_factory=lambda: next(ids)),
        execution_repair_attempts=2,
    )

    pending = engine.begin_turn("Add a field to Customer")
    assert isinstance(pending, PendingPlanRequest)

    first_repair = engine.resume_turn(pending.request_id, json.dumps(valid_create_customer_plan()))
    assert isinstance(first_repair, PendingPlanRequest)

    second_repair = engine.resume_turn(first_repair.request_id, json.dumps(valid_create_customer_plan()))
    assert isinstance(second_repair, PendingPlanRequest)

    reply = engine.resume_turn(second_repair.request_id, json.dumps(valid_create_customer_plan()))

    assert isinstance(reply, ConversationReply)
    assert reply.kind == "preview"
    assert backend.fail_calls_remaining == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cli && python -m pytest tests/test_conversation_engine.py::test_engine_attempts_second_execution_repair_round_when_budget_allows -v`
Expected: FAIL — `second_repair` is a `ConversationReply` with `kind == "error"`, not a `PendingPlanRequest` (the assertion `assert isinstance(second_repair, PendingPlanRequest)` fails), because the current code cannot start a second repair round.

- [ ] **Step 3: Add `context` to `_PendingExecutionRepair`**

In `cli/src/modelable/llm/conversation_engine.py`, change:

```python
@dataclass(frozen=True)
class _PendingExecutionRepair:
    request_id: str
    message: str
```

to:

```python
@dataclass(frozen=True)
class _PendingExecutionRepair:
    request_id: str
    message: str
    context: PlannerContext
```

- [ ] **Step 4: Store the context when a repair round begins**

Change `_begin_execution_repair`:

```python
def _begin_execution_repair(
    self,
    message: str,
    context: PlannerContext,
    error_text: str,
) -> PendingPlanRequest:
    request_id = self.id_factory()
    self._pending_execution_repair = _PendingExecutionRepair(request_id=request_id, message=message)
    return PendingPlanRequest(
        request_id=request_id,
        request=build_repair_request(message=message, context=context, error=error_text),
        attempt=1,
    )
```

to:

```python
def _begin_execution_repair(
    self,
    message: str,
    context: PlannerContext,
    error_text: str,
) -> PendingPlanRequest:
    request_id = self.id_factory()
    self._pending_execution_repair = _PendingExecutionRepair(request_id=request_id, message=message, context=context)
    return PendingPlanRequest(
        request_id=request_id,
        request=build_repair_request(message=message, context=context, error=error_text),
        attempt=1,
    )
```

- [ ] **Step 5: Pass the stored context back into `_complete_plan`**

Change `_complete_execution_repair`'s last line:

```python
        return self._complete_plan(repair.message, plan, None)
```

to:

```python
        return self._complete_plan(repair.message, plan, repair.context)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd cli && python -m pytest tests/test_conversation_engine.py -v`
Expected: PASS — all tests in the file pass, including the new one and the pre-existing `test_engine_gives_up_after_execution_repair_budget_exhausted` (that test uses `execution_repair_attempts=1`, so it still gives up after exactly one round — the fix only changes behavior when budget allows more than one round).

- [ ] **Step 7: Commit**

```bash
git add cli/src/modelable/llm/conversation_engine.py cli/tests/test_conversation_engine.py
git commit -m "fix: carry planner context through execution-repair rounds

execution_repair_attempts previously had no effect beyond 1 because
_PendingExecutionRepair discarded the PlannerContext needed to attempt
a second round. Store and reuse it so the configured budget is honored."
```

---

### Task 2: Wrap the final error message once repairs are exhausted

**Files:**
- Modify: `cli/src/modelable/llm/conversation_engine.py` (imports, `_complete_plan`)
- Test: `cli/tests/test_conversation_engine.py`

**Interfaces:**
- Consumes: `self.execution_repair_attempts` and `self._execution_repairs_remaining` (already existing engine attributes, set in `__init__` and reset in `begin_turn`).
- Produces: no new public interface — this changes the `text` of the `ConversationReply` returned by `_complete_plan` on the give-up path only.

When a `ChangeSetPlan` still errors after every repair round is used up, the raw backend error (e.g. `Could not preview workspace changes: Unknown model version: billing.Customer@1`) is shown to the user verbatim. Wrap it in an explanatory message that states how many attempts were made and suggests a remedy, but only when at least one repair round actually happened — if no repair was attempted (e.g. `execution_repair_attempts=0`), keep today's raw message since there's nothing to explain.

- [ ] **Step 1: Write the failing tests**

Add to `cli/tests/test_conversation_engine.py`:

```python
def test_engine_wraps_final_error_after_execution_repairs_exhausted() -> None:
    ids = iter(("request-1",))
    backend = FailThenSucceedBackend(
        fail_calls_remaining=3,
        failure_text="Unknown model version: billing.Customer@1",
    )
    engine = ConversationEngine(
        backend=backend,
        planner=ResumableConversationPlanner(id_factory=lambda: next(ids)),
        execution_repair_attempts=2,
    )

    pending = engine.begin_turn("Add a field to Customer")
    assert isinstance(pending, PendingPlanRequest)
    first_repair = engine.resume_turn(pending.request_id, json.dumps(valid_create_customer_plan()))
    assert isinstance(first_repair, PendingPlanRequest)
    second_repair = engine.resume_turn(first_repair.request_id, json.dumps(valid_create_customer_plan()))
    assert isinstance(second_repair, PendingPlanRequest)

    reply = engine.resume_turn(second_repair.request_id, json.dumps(valid_create_customer_plan()))

    assert isinstance(reply, ConversationReply)
    assert reply.kind == "error"
    assert "couldn't produce a valid change after 3 attempts" in reply.text
    assert "Unknown model version: billing.Customer@1" in reply.text
    assert backend.fail_calls_remaining == 0


def test_engine_keeps_raw_error_when_no_repair_budget_configured() -> None:
    ids = iter(("request-1",))
    backend = FailThenSucceedBackend(
        fail_calls_remaining=1,
        failure_text="Unknown model version: billing.Customer@1",
    )
    engine = ConversationEngine(
        backend=backend,
        planner=ResumableConversationPlanner(id_factory=lambda: next(ids)),
        execution_repair_attempts=0,
    )

    pending = engine.begin_turn("Add a field to Customer")
    assert isinstance(pending, PendingPlanRequest)

    reply = engine.resume_turn(pending.request_id, json.dumps(valid_create_customer_plan()))

    assert isinstance(reply, ConversationReply)
    assert reply.kind == "error"
    assert reply.text == "Unknown model version: billing.Customer@1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cli && python -m pytest tests/test_conversation_engine.py::test_engine_wraps_final_error_after_execution_repairs_exhausted tests/test_conversation_engine.py::test_engine_keeps_raw_error_when_no_repair_budget_configured -v`
Expected: The first test FAILs (`"couldn't produce a valid change after 3 attempts"` is not in `reply.text`, since today's code returns the raw error unwrapped). The second test PASSes already (today's unwrapped behavior is what it expects) — that's fine, it's here to lock in the "no wrapping without a repair attempt" branch before Step 3 changes any code.

- [ ] **Step 3: Add `replace` to the dataclasses import**

In `cli/src/modelable/llm/conversation_engine.py`, change:

```python
from dataclasses import dataclass
```

to:

```python
from dataclasses import dataclass, replace
```

- [ ] **Step 4: Wrap the final error in `_complete_plan`**

Change `_complete_plan`:

```python
    def _complete_plan(
        self,
        message: str,
        plan: ConversationPlan,
        context: PlannerContext | None,
    ) -> ConversationOutcome:
        if isinstance(plan, QueryPlan) and self.completion_enabled and _is_conversational(message):
            reply = self.backend.execute_query(plan)
            return self._begin_synthesis(message, reply.text)
        reply = self._execute_plan(plan)
        if (
            isinstance(plan, ChangeSetPlan)
            and reply.kind == "error"
            and context is not None
            and self._execution_repairs_remaining > 0
        ):
            self._execution_repairs_remaining -= 1
            return self._begin_execution_repair(message, context, reply.text)
        return self._complete_turn(message, reply)
```

to:

```python
    def _complete_plan(
        self,
        message: str,
        plan: ConversationPlan,
        context: PlannerContext | None,
    ) -> ConversationOutcome:
        if isinstance(plan, QueryPlan) and self.completion_enabled and _is_conversational(message):
            reply = self.backend.execute_query(plan)
            return self._begin_synthesis(message, reply.text)
        reply = self._execute_plan(plan)
        if isinstance(plan, ChangeSetPlan) and reply.kind == "error":
            if context is not None and self._execution_repairs_remaining > 0:
                self._execution_repairs_remaining -= 1
                return self._begin_execution_repair(message, context, reply.text)
            repairs_used = self.execution_repair_attempts - self._execution_repairs_remaining
            if repairs_used > 0:
                reply = replace(
                    reply,
                    text=(
                        f"The AI assistant couldn't produce a valid change after {repairs_used + 1} attempts "
                        f"(last error: {reply.text}). Try a larger local model, or be more specific about the "
                        'domain and model (e.g. "customer.Customer").'
                    ),
                )
        return self._complete_turn(message, reply)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd cli && python -m pytest tests/test_conversation_engine.py -v`
Expected: PASS — every test in the file, including both new tests and the pre-existing `test_engine_gives_up_after_execution_repair_budget_exhausted` (its `"expected 3" in reply.text` assertion still holds because the raw error text is preserved verbatim inside the wrapped message).

- [ ] **Step 6: Commit**

```bash
git add cli/src/modelable/llm/conversation_engine.py cli/tests/test_conversation_engine.py
git commit -m "fix: replace raw error with explanation when execution repairs are exhausted

Users saw the internal backend error verbatim (e.g. 'Unknown model
version: billing.Customer@1') once every repair round failed. Wrap it
with attempt count and a suggestion, but only when a repair was
actually attempted; otherwise keep the raw message unchanged."
```

---

### Task 3: Raise the browser playground's repair budget to 2 and update the changelog

**Files:**
- Modify: `cli/src/modelable/browser/conversation.py:479` and `:493` (`ConversationEngine(...)` construction inside `_session`)
- Modify: `CHANGELOG.md` (`[Unreleased]` → `### Fixed`)
- Test: `cli/tests/test_browser_conversation.py`

**Interfaces:**
- Consumes: `ConversationEngine.__init__(..., execution_repair_attempts: int = 1, ...)` from Task 1/2 (signature unchanged, only the call-site argument changes).
- Produces: nothing new consumed by later tasks — this is the last task in the plan.

The browser's `BrowserConversationService._session` constructs `ConversationEngine` at two places (fresh session, and revision-changed session) without passing `execution_repair_attempts`, so it silently uses the default of 1. Explicitly pass 2 at both sites so the fix from Tasks 1–2 actually gives the small local WebGPU models a second corrective round in the playground.

- [ ] **Step 1: Write the failing test**

Add to `cli/tests/test_browser_conversation.py` (near the top-level tests, after the imports section):

```python
def test_browser_conversation_service_configures_two_execution_repair_attempts() -> None:
    compiler = BrowserCompiler()
    compiler.open_workspace(
        1,
        (BrowserSource(uri=CUSTOMER_URI, text=CUSTOMER_SOURCE, version=1),),
    )
    service = BrowserConversationService(compiler, id_factory=lambda: "request-1")

    service.turn(
        session_id="session-1",
        workspace_revision=1,
        message="Suggest a projection for billing",
        active_document_uri=CUSTOMER_URI,
        line=3,
        character=10,
    )

    session = service._sessions["session-1"]
    assert session.engine.execution_repair_attempts == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cli && python -m pytest tests/test_browser_conversation.py::test_browser_conversation_service_configures_two_execution_repair_attempts -v`
Expected: FAIL — `session.engine.execution_repair_attempts == 1` (the default), not 2.

- [ ] **Step 3: Pass `execution_repair_attempts=2` at both construction sites**

In `cli/src/modelable/browser/conversation.py`, there are two `ConversationEngine(...)` calls inside `_session` (one for a brand-new session, one when the workspace revision changed). Change both from:

```python
                engine=ConversationEngine(
                    backend=backend,
                    planner=ResumableConversationPlanner(id_factory=self.id_factory),
                ),
```

to:

```python
                engine=ConversationEngine(
                    backend=backend,
                    planner=ResumableConversationPlanner(id_factory=self.id_factory),
                    execution_repair_attempts=2,
                ),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cli && python -m pytest tests/test_browser_conversation.py -v`
Expected: PASS — every test in the file, including the new one.

- [ ] **Step 5: Update the changelog**

`CHANGELOG.md` already has a `### Fixed` subsection under `## [Unreleased]` (line 88, ending before `## [1.2.1]` at line 109). Add this as the last bullet in that subsection, immediately after the existing "Playground graph panel: graph nodes no longer claim..." bullet:

```markdown
- Playground chat: a change request that the AI model gets wrong (e.g.
  referencing a model/version that doesn't exist) now gets two automatic
  corrective retries instead of one, and if it still fails, the chat shows
  a clear explanation instead of the raw internal error text.
```

- [ ] **Step 6: Run the full CLI test suite**

Run: `cd cli && python -m pytest tests/test_conversation_engine.py tests/test_browser_conversation.py tests/test_llm_provider_integration.py -v`
Expected: PASS — no regressions in any conversation-engine-adjacent suite.

- [ ] **Step 7: Commit**

```bash
git add cli/src/modelable/browser/conversation.py cli/tests/test_browser_conversation.py CHANGELOG.md
git commit -m "fix: give the browser playground 2 execution-repair attempts

The browser session relied on ConversationEngine's default of 1, which
(combined with the Task 1 fix) now correctly allows the small local
WebGPU models a second corrective retry before giving up."
```

## Self-Review Notes

- **Spec coverage:** every "Decisions" bullet in the design spec maps to a task — context-carry fix (Task 1), browser budget bump (Task 3), friendlier give-up message (Task 2). Testing/acceptance bullets are covered: multi-round test (Task 1), wrapped-message and raw-message-preserved tests (Task 2), browser wiring test (Task 3), full suite check (Task 3 Step 6).
- **Placeholder scan:** no TBDs; every step has literal code or an exact command.
- **Type consistency:** `_PendingExecutionRepair.context: PlannerContext` (Task 1) is the same type `_begin_execution_repair` already receives as its `context` parameter and the same type `_complete_plan`'s `context` parameter expects — no renaming across tasks.
