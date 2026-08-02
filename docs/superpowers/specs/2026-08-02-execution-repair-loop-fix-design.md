# 2026-08-02 Execution Repair Loop Fix Design

## Goal

Fix a latent bug in `ConversationEngine`'s execution-repair loop (`cli/src/modelable/llm/conversation_engine.py`) that silently caps it at exactly one corrective round regardless of the configured `execution_repair_attempts` budget, raise the browser playground's budget to 2 rounds, and give users a clearer message when the loop ultimately gives up.

## Background

When a `ChangeSetPlan` produced by the LLM planner references a model/version/domain that doesn't actually exist in the workspace (e.g. `billing.Customer@1` when the model actually lives at `customer.Customer@2`), `WorkspaceEditor.preview` raises `WorkspaceEditError`, which `BrowserConversationBackend.preview_source_change` turns into a `ConversationReply(kind="error", ...)` (`cli/src/modelable/browser/conversation.py:130`).

`ConversationEngine._complete_plan` (`cli/src/modelable/llm/conversation_engine.py:228`) is meant to catch this and retry: if the reply is an error for a `ChangeSetPlan` and repair budget remains, it calls `_begin_execution_repair`, which sends the error text back to the model for a corrective retry. This is intentional, tested behavior (`test_engine_repairs_change_set_plan_after_workspace_edit_error`).

The bug: `_PendingExecutionRepair` (`conversation_engine.py:45`) only stores `request_id` and `message` — not the `PlannerContext` used to build the repair prompt. `_complete_execution_repair` (`conversation_engine.py:336`) always calls `self._complete_plan(repair.message, plan, None)` — passing `context=None`. `_complete_plan`'s retry gate requires `context is not None` (`conversation_engine.py:238-245`), so once a repair round has happened once, no further round is ever possible — even if `execution_repair_attempts` is configured higher than 1. `test_engine_gives_up_after_execution_repair_budget_exhausted` currently exercises `execution_repair_attempts=1`, so it passes without exposing the bug; it just happens to match the one-round-only behavior the bug produces regardless of the configured value.

This was discovered while investigating a real report: a user on the web playground, running the smallest local WebGPU model (Qwen2.5 0.5B), asked to add a field to `customer` and got a raw `Could not preview workspace changes: Unknown model version: billing.Customer@1` error surfaced verbatim in chat. The model got the ref wrong twice in a row (initial attempt + the one available repair), then the loop gave up and returned the raw internal error text.

## Decisions

- Add `context: PlannerContext` to `_PendingExecutionRepair`. `_begin_execution_repair` stores the context it already receives; `_complete_execution_repair` passes `repair.context` instead of `None` into `_complete_plan`. This is the root-cause fix — it lets the existing `_execution_repairs_remaining` budget actually govern multiple rounds instead of hard-capping at one.
- The `PlannerContext` reused across repair rounds is the same object captured at the start of the turn (workspace summary, history, focused ref, pending plan). The workspace hasn't changed between rounds (nothing is applied until `/apply`), so re-using it — rather than rebuilding it — is correct and avoids an extra backend call per round.
- Raise the browser playground's engine construction to `execution_repair_attempts=2` at both call sites in `cli/src/modelable/browser/conversation.py` (`_session`, lines ~479 and ~493). The CLI path (`cli/src/modelable/llm/conversation.py:81`) already threads `llm_config.repair_attempts` through and is unchanged by this work — this fix only changes the *browser* engine's default, and only fixes the loop mechanics (which benefits every caller, browser and CLI alike).
- When a `ChangeSetPlan` finally gives up — no repair round left to attempt (`context is None` or `_execution_repairs_remaining <= 0`) — and at least one repair round was actually used this turn, wrap the raw backend error text instead of returning it verbatim:
  `"The AI assistant couldn't produce a valid change after {attempts} attempts (last error: {raw_error}). Try a larger local model, or be more specific about the domain and model (e.g. \"customer.Customer\")."`
  `{attempts}` is `self.execution_repair_attempts - self._execution_repairs_remaining + 1` (repair rounds used, plus the initial attempt). If zero repair rounds were used (e.g. a deployment configures `execution_repair_attempts=0`, or the plan wasn't a retryable `ChangeSetPlan` error at all), the raw message is returned unchanged as it is today — there's nothing to explain when no retry happened.
- No change to the schema/parse-level repair loop in `conversation_planner.py` (`ResumableConversationPlanner`) — that mechanism is unrelated and already correctly bounded by its own `repair_attempts`.

## Architecture

All changes are confined to `ConversationEngine` in `cli/src/modelable/llm/conversation_engine.py`, plus the two `ConversationEngine(...)` construction sites in `cli/src/modelable/browser/conversation.py`. No changes to `WorkspaceEditor`, the planner's system prompt, the browser protocol, or any TypeScript/web code — the playground UI already renders whatever `ConversationReply.text` it receives, so a friendlier string flows through unchanged.

`_PendingExecutionRepair` gains one field (`context: PlannerContext`); `_begin_execution_repair` and `_complete_execution_repair` are updated to set/read it. `_complete_plan` gains the give-up message formatting, gated on a new local computation of "repairs used this turn" derived from the existing `self.execution_repair_attempts` / `self._execution_repairs_remaining` counters already on the engine — no new state needed for that part.

## Error handling and safety

- The friendlier give-up message still includes the raw underlying error (`last error: ...`), so users/developers debugging a stuck workspace aren't losing information — it's additive framing, not a replacement.
- No behavior changes for non-`ChangeSetPlan` errors (query errors, apply/discard mismatches, compile errors) — the wrapping is scoped specifically to the execution-repair give-up path inside `_complete_plan`.
- Raising the budget from 1 to 2 doubles the worst-case number of LLM round-trips for a failing edit request in the browser; this is an accepted latency/cost trade-off for better correctness on small local models, consistent with why the mechanism exists at all.

## Testing and acceptance

- New test: with `execution_repair_attempts=2` and a backend that fails twice then succeeds, the engine now reaches a `preview` reply (proves a second repair round actually executes — this is the behavior that is currently impossible regardless of configured budget).
- Update/extend `test_engine_gives_up_after_execution_repair_budget_exhausted`-style coverage: with `execution_repair_attempts=2` and a backend that fails all three times, assert the final reply is `kind == "error"`, contains the friendly wrapper text ("couldn't produce a valid change after"), and still contains the raw underlying error text.
- Keep a case where `execution_repair_attempts=0` (or a plan that never entered repair) still returns the raw error unchanged, to lock in the "nothing to explain" branch.
- Full existing `test_conversation_engine.py` and `test_browser_conversation.py` suites stay green.

## ADR impact

No new ADR required. This is a bug fix to already-accepted conversation-repair architecture (see `docs/superpowers/plans/2026-07-28-conversation-engine-editing-fixes.md`) plus a config value change; it doesn't introduce new concepts or change the plan/preview/apply protocol.

## Non-goals

- Changing the CLI's `repair_attempts` / `execution_repair_attempts` configuration or behavior beyond the shared bug fix.
- Changing the planner's system prompt, examples, or the underlying WebGPU model choice/tiering.
- Building any new retry mechanism — the mechanism already exists and is being fixed, not replaced.
- Surfacing repair-attempt counts or history in the playground UI beyond the final chat message text.
