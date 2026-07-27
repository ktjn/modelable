from __future__ import annotations

from modelable.llm.conversation_backend import ConversationBackend, ConversationReply
from modelable.llm.conversation_plan import (
    ChangeSetPlan,
    ClarificationPlan,
    CompilePlan,
    ConversationPlan,
    QueryPlan,
    UnsupportedPlan,
)
from modelable.llm.conversation_planner import (
    PendingPlanRequest,
    PlannerContext,
    PlanningRequestError,
    ResumableConversationPlanner,
    parse_compile_command,
)

type ConversationOutcome = ConversationReply | PendingPlanRequest


class ConversationEngine:
    def __init__(
        self,
        *,
        backend: ConversationBackend,
        planner: ResumableConversationPlanner,
        focused_ref: str | None = None,
        completion_enabled: bool = True,
    ) -> None:
        self.backend = backend
        self.planner = planner
        self.focused_ref = focused_ref
        self.completion_enabled = completion_enabled
        self.history: list[tuple[str, str]] = []
        self.pending_action_id: str | None = None
        self.pending_operation_kind: str | None = None
        self._pending_change_plan: ChangeSetPlan | None = None
        self._pending_request_id: str | None = None
        self._pending_message: str | None = None

    def begin_turn(self, message: str) -> ConversationOutcome:
        if self._pending_request_id is not None:
            raise PlanningRequestError(
                f"Planning request {self._pending_request_id} must be resumed or reset before starting another turn"
            )
        normalized = message.strip()
        lowered = normalized.lower()
        if message == "/apply":
            return self._complete_turn(message, self._apply_from_turn())
        if self.pending_operation_kind == "compile" and normalized.lower() == "/apply":
            return self._complete_turn(
                message,
                ConversationReply(
                    kind="error",
                    text=(
                        "Compilation requires the exact case-sensitive /apply command with no surrounding whitespace. "
                        "Use /discard to cancel or another request to replace the preview."
                    ),
                    change_set_id=self.pending_action_id,
                    operation_kind="compile",
                ),
            )
        if normalized == "/apply" or lowered in {"apply", "apply it", "confirm"}:
            if self.pending_operation_kind == "compile":
                reply = ConversationReply(
                    kind="error",
                    text=(
                        "Compilation requires the exact case-sensitive /apply command. "
                        "Use /discard to cancel or another request to replace the preview."
                    ),
                    change_set_id=self.pending_action_id,
                    operation_kind="compile",
                )
            else:
                reply = self._apply_from_turn()
            return self._complete_turn(message, reply)
        if lowered in {"discard", "discard it", "cancel"} or normalized == "/discard":
            return self._complete_turn(message, self._discard_from_turn())

        command = normalized.split(maxsplit=1)
        if command and command[0] == "/compile":
            return self._complete_plan(normalized, parse_compile_command(normalized))
        context = PlannerContext(
            workspace_summary=self.backend.workspace_summary(),
            focused_ref=self.focused_ref,
            history=tuple(self.history),
            pending_plan=self._pending_change_plan,
        )
        outcome = (
            self.planner.begin(normalized, context)
            if self.completion_enabled
            else self.planner.offline(normalized, context)
        )
        if isinstance(outcome, PendingPlanRequest):
            self._pending_request_id = outcome.request_id
            self._pending_message = normalized
            return outcome
        return self._complete_plan(normalized, outcome)

    def resume_turn(self, request_id: str, content: str) -> ConversationOutcome:
        if request_id != self._pending_request_id or self._pending_message is None:
            raise PlanningRequestError(f"Unknown or completed planning request: {request_id}")
        message = self._pending_message
        outcome = self.planner.resume(request_id, content)
        if isinstance(outcome, PendingPlanRequest):
            self._pending_request_id = outcome.request_id
            return outcome
        self._pending_request_id = None
        self._pending_message = None
        return self._complete_plan(message, outcome)

    def fail_turn(self, request_id: str, error: Exception) -> ConversationReply:
        if request_id != self._pending_request_id or self._pending_message is None:
            raise PlanningRequestError(f"Unknown or completed planning request: {request_id}")
        message = self._pending_message
        plan = self.planner.fail(request_id, error)
        self._pending_request_id = None
        self._pending_message = None
        return self._complete_plan(message, plan)

    def apply(self, action_id: str) -> ConversationReply:
        self._assert_pending_action(action_id)
        return self._complete_turn("/apply", self._apply(action_id))

    def discard(self, action_id: str) -> ConversationReply:
        self._assert_pending_action(action_id)
        return self._complete_turn("/discard", self._discard(action_id))

    def reset(self) -> None:
        if self._pending_request_id is not None:
            self.planner.cancel(self._pending_request_id)
        self.backend.reset()
        self.focused_ref = None
        self.history.clear()
        self.pending_action_id = None
        self.pending_operation_kind = None
        self._pending_change_plan = None
        self._pending_request_id = None
        self._pending_message = None

    def synchronize_pending_action(
        self,
        action_id: str | None,
        operation_kind: str | None,
    ) -> None:
        self.pending_action_id = action_id
        self.pending_operation_kind = operation_kind
        if action_id is None:
            self._pending_change_plan = None

    def record_completed_reply(self, message: str, reply: ConversationReply) -> ConversationReply:
        return self._complete_turn(message, reply)

    def _complete_plan(self, message: str, plan: ConversationPlan) -> ConversationReply:
        reply = self._execute_plan(plan)
        return self._complete_turn(message, reply)

    def _execute_plan(self, plan: ConversationPlan) -> ConversationReply:
        if isinstance(plan, QueryPlan):
            return self.backend.execute_query(plan)
        if isinstance(plan, ClarificationPlan):
            return ConversationReply(
                kind="clarification",
                text=f"{plan.question}\n\nReason: {plan.reason}",
            )
        if isinstance(plan, UnsupportedPlan):
            roadmap = f"\n\nRoadmap area: {plan.roadmap_area}" if plan.roadmap_area else ""
            return ConversationReply(kind="unsupported", text=f"{plan.reason}{roadmap}")
        if isinstance(plan, ChangeSetPlan):
            reply = self.backend.preview_source_change(plan, self.pending_action_id)
            if reply.kind == "preview" and reply.change_set_id is not None:
                self._track_preview(reply)
                self._pending_change_plan = plan
            return reply
        if isinstance(plan, CompilePlan):
            reply = self.backend.preview_compilation(plan, self.pending_action_id)
            if reply.kind == "preview" and reply.change_set_id is not None:
                self._track_preview(reply)
                self._pending_change_plan = None
            return reply
        return ConversationReply(kind="error", text="The request produced an unknown conversation plan.")

    def _apply(self, action_id: str) -> ConversationReply:
        reply = self.backend.apply(action_id)
        if reply.kind == "applied":
            self._clear_pending_action()
            if reply.focused_ref is not None:
                self.focused_ref = reply.focused_ref
        return reply

    def _discard(self, action_id: str) -> ConversationReply:
        reply = self.backend.discard(action_id)
        if reply.kind == "discarded":
            self._clear_pending_action()
        return reply

    def _apply_from_turn(self) -> ConversationReply:
        if self.pending_action_id is None:
            return ConversationReply(kind="error", text="There is no pending action to apply.")
        return self._apply(self.pending_action_id)

    def _discard_from_turn(self) -> ConversationReply:
        if self.pending_action_id is None:
            return ConversationReply(kind="error", text="There is no pending action to discard.")
        return self._discard(self.pending_action_id)

    def _track_preview(self, reply: ConversationReply) -> None:
        self.pending_action_id = reply.change_set_id
        self.pending_operation_kind = reply.operation_kind
        if reply.focused_ref is not None:
            self.focused_ref = reply.focused_ref

    def _clear_pending_action(self) -> None:
        self.pending_action_id = None
        self.pending_operation_kind = None
        self._pending_change_plan = None

    def _assert_pending_action(self, action_id: str) -> None:
        if action_id != self.pending_action_id:
            raise ValueError(f"Action ID {action_id!r} does not match pending action {self.pending_action_id!r}")

    def _complete_turn(self, message: str, reply: ConversationReply) -> ConversationReply:
        self.history.append(("user", message))
        self.history.append(("assistant", reply.text))
        return reply
