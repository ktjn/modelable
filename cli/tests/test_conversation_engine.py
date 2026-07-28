from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest
from support.conversation_simulator import ConversationSimulatorProvider

from modelable.llm.conversation_backend import ConversationReply
from modelable.llm.conversation_engine import ConversationEngine
from modelable.llm.conversation_plan import ChangeSetPlan, CompilePlan, QueryPlan
from modelable.llm.conversation_planner import (
    ConversationPlanner,
    PendingPlanRequest,
    PlannerContext,
    PlanningRequestError,
    ResumableConversationPlanner,
)
from modelable.llm.workspace_editor import ChangedDefinition


def valid_create_customer_plan() -> dict[str, object]:
    return {
        "kind": "change_set",
        "summary": "Create customer.Customer@1",
        "operations": [
            {
                "kind": "create_model",
                "domain": "customer",
                "name": "Customer",
                "model_kind": "entity",
                "fields": [
                    {
                        "name": "customerId",
                        "type": {"kind": "uuid"},
                        "annotations": [{"kind": "key"}],
                    }
                ],
            }
        ],
    }


@dataclass
class RecordingBackend:
    previewed_plans: list[ChangeSetPlan] = field(default_factory=list)
    previewed_session_editable_refs: list[frozenset[str]] = field(default_factory=list)
    applied_ids: list[str] = field(default_factory=list)
    discarded_ids: list[str] = field(default_factory=list)
    reset_calls: int = 0
    next_action: int = 1
    execute_query_called: bool = False

    def workspace_summary(self, focused_ref: str | None = None) -> str:
        return f"domain customer\n  owner: customer-team (focus: {focused_ref})"

    def execute_query(self, plan: QueryPlan) -> ConversationReply:
        self.execute_query_called = True
        return ConversationReply(kind="answer", text=f"query:{plan.query_kind}")

    def preview_source_change(
        self,
        plan: ChangeSetPlan,
        replaced_action_id: str | None,
        *,
        session_editable_refs: frozenset[str] = frozenset(),
    ) -> ConversationReply:
        self.previewed_plans.append(plan)
        self.previewed_session_editable_refs.append(session_editable_refs)
        action_id = f"change-{self.next_action}"
        self.next_action += 1
        return ConversationReply(
            kind="preview",
            text=f"preview:{action_id}:replaced:{replaced_action_id}",
            change_set_id=action_id,
            operation_kind="source_change",
            focused_ref="customer.Customer@1",
            changed=(ChangedDefinition(ref="customer.Customer@1", reason="created"),),
        )

    def preview_compilation(
        self,
        plan: CompilePlan,
        replaced_action_id: str | None,
    ) -> ConversationReply:
        return ConversationReply(
            kind="preview",
            text=f"compile:{plan.target}:replaced:{replaced_action_id}",
            change_set_id="compile-1",
            operation_kind="compile",
        )

    def apply(self, action_id: str) -> ConversationReply:
        self.applied_ids.append(action_id)
        return ConversationReply(
            kind="applied",
            text=f"applied:{action_id}",
            change_set_id=action_id,
            changed=(ChangedDefinition(ref="customer.Customer@1", reason="created"),),
        )

    def discard(self, action_id: str) -> ConversationReply:
        self.discarded_ids.append(action_id)
        return ConversationReply(kind="discarded", text=f"discarded:{action_id}", change_set_id=action_id)

    def reset(self) -> None:
        self.reset_calls += 1


def engine_with_request_ids(*request_ids: str) -> tuple[ConversationEngine, RecordingBackend]:
    ids = iter(request_ids)
    backend = RecordingBackend()
    engine = ConversationEngine(
        backend=backend,
        planner=ResumableConversationPlanner(id_factory=lambda: next(ids)),
    )
    return engine, backend


def test_engine_resumes_plan_and_tracks_exact_pending_action() -> None:
    engine, backend = engine_with_request_ids("request-1")
    pending = engine.begin_turn("Create a customer")
    assert isinstance(pending, PendingPlanRequest)

    reply = engine.resume_turn(
        pending.request_id,
        json.dumps(valid_create_customer_plan()),
    )

    assert reply.kind == "preview"
    assert reply.change_set_id == "change-1"
    assert engine.pending_action_id == "change-1"
    assert backend.previewed_plans[0].kind == "change_set"
    assert engine.history == [
        ("user", "Create a customer"),
        ("assistant", reply.text),
    ]


def test_begin_turn_forwards_direct_edit_mode_to_planner_context() -> None:
    captured_contexts: list[PlannerContext] = []

    class CapturingPlanner:
        def offline(self, message, context):
            captured_contexts.append(context)
            return ConversationPlanner._offline_plan(message, context)

        def begin(self, message, context):
            captured_contexts.append(context)
            return ConversationPlanner._offline_plan(message, context)

    engine = ConversationEngine(backend=RecordingBackend(), planner=CapturingPlanner())
    engine.begin_turn("make email optional", direct_edit_mode=True)

    assert captured_contexts[-1].direct_edit_mode is True


def test_engine_refinement_replaces_pending_action() -> None:
    engine, _ = engine_with_request_ids("request-1", "request-2")
    first = engine.begin_turn("Create a customer")
    assert isinstance(first, PendingPlanRequest)
    engine.resume_turn(first.request_id, json.dumps(valid_create_customer_plan()))

    second = engine.begin_turn("Add an email field")
    assert isinstance(second, PendingPlanRequest)
    reply = engine.resume_turn(second.request_id, json.dumps(valid_create_customer_plan()))

    assert reply.change_set_id == "change-2"
    assert "replaced:change-1" in reply.text
    assert engine.pending_action_id == "change-2"


def test_engine_apply_and_discard_use_exact_pending_id() -> None:
    engine, backend = engine_with_request_ids("request-1", "request-2")
    pending = engine.begin_turn("Create a customer")
    assert isinstance(pending, PendingPlanRequest)
    engine.resume_turn(pending.request_id, json.dumps(valid_create_customer_plan()))

    with pytest.raises(ValueError, match="does not match"):
        engine.apply("other")

    applied = engine.apply("change-1")
    assert applied.kind == "applied"
    assert backend.applied_ids == ["change-1"]
    assert engine.pending_action_id is None

    next_pending = engine.begin_turn("Create another customer")
    assert isinstance(next_pending, PendingPlanRequest)
    engine.resume_turn(next_pending.request_id, json.dumps(valid_create_customer_plan()))
    discarded = engine.discard("change-2")
    assert discarded.kind == "discarded"
    assert backend.discarded_ids == ["change-2"]
    assert engine.pending_action_id is None


def test_engine_lets_second_turn_edit_a_ref_applied_earlier_in_the_session() -> None:
    engine, backend = engine_with_request_ids("request-1", "request-2")

    pending = engine.begin_turn("Create a customer")
    assert isinstance(pending, PendingPlanRequest)
    preview_reply = engine.resume_turn(pending.request_id, json.dumps(valid_create_customer_plan()))
    assert preview_reply.kind == "preview"
    applied_reply = engine.apply(preview_reply.change_set_id)
    assert applied_reply.kind == "applied"

    pending_2 = engine.begin_turn("Rename customerId to id")
    assert isinstance(pending_2, PendingPlanRequest)
    engine.resume_turn(pending_2.request_id, json.dumps(valid_create_customer_plan()))

    assert backend.previewed_session_editable_refs[-1] == frozenset({"customer.Customer@1"})


def test_engine_records_deterministic_reply_without_completion() -> None:
    engine, _ = engine_with_request_ids("unused")

    reply = engine.begin_turn("/describe customer.Customer@1")

    assert isinstance(reply, ConversationReply)
    assert reply.kind == "answer"
    assert engine.history == [
        ("user", "/describe customer.Customer@1"),
        ("assistant", "query:summary"),
    ]


def test_reset_invalidates_pending_completion_and_preview() -> None:
    engine, backend = engine_with_request_ids("request-1")
    pending = engine.begin_turn("Create a customer")
    assert isinstance(pending, PendingPlanRequest)

    engine.reset()

    with pytest.raises(PlanningRequestError):
        engine.resume_turn(pending.request_id, "{}")
    assert backend.reset_calls == 1
    assert engine.pending_action_id is None
    assert engine.history == []


def test_engine_converts_completion_failure_into_completed_reply() -> None:
    engine, _ = engine_with_request_ids("request-1")
    pending = engine.begin_turn("Create a customer")
    assert isinstance(pending, PendingPlanRequest)

    reply = engine.fail_turn(pending.request_id, RuntimeError("provider unavailable"))

    assert reply.kind == "unsupported"
    assert "provider unavailable" in reply.text
    assert engine.history[-1] == ("assistant", reply.text)


def test_engine_returns_error_when_apply_has_no_pending_action() -> None:
    engine, _ = engine_with_request_ids("unused")

    reply = engine.begin_turn("/apply")

    assert isinstance(reply, ConversationReply)
    assert reply.kind == "error"
    assert "no pending action" in reply.text.lower()


def test_engine_without_completion_uses_offline_planner() -> None:
    backend = RecordingBackend()
    engine = ConversationEngine(
        backend=backend,
        planner=ResumableConversationPlanner(id_factory=lambda: "unused"),
        completion_enabled=False,
    )

    reply = engine.begin_turn("Create a customer")

    assert isinstance(reply, ConversationReply)
    assert reply.kind == "unsupported"
    assert "Configure an LLM provider" in reply.text


def test_semantic_simulator_drives_typed_conversation_planner() -> None:
    planner = ConversationPlanner(ConversationSimulatorProvider())

    plan = planner.plan(
        "Create an invoice with an invoice id",
        PlannerContext(
            workspace_summary="domain billing",
            focused_ref=None,
            history=(),
            pending_plan=None,
        ),
    )

    assert isinstance(plan, ChangeSetPlan)
    assert plan.operations[0].kind == "create_model"


def test_engine_synthesizes_conversational_query_with_provider() -> None:
    engine, backend = engine_with_request_ids("synthesis-1")

    pending = engine.begin_turn("describe the workspace")

    assert isinstance(pending, PendingPlanRequest)
    assert pending.request.response_format == "text"
    assert "Workspace facts:" in pending.request.user
    reply = engine.resume_turn(pending.request_id, "A concise explanation of the workspace.")

    assert reply.kind == "answer"
    assert reply.text == "A concise explanation of the workspace."
    assert engine.history[-1] == ("assistant", reply.text)
    assert backend.execute_query_called


def test_engine_keeps_slash_describe_deterministic() -> None:
    engine, backend = engine_with_request_ids("unused")

    reply = engine.begin_turn("/describe customer.Customer@1")

    assert isinstance(reply, ConversationReply)
    assert reply.kind == "answer"
    assert reply.text == "query:summary"
    assert backend.execute_query_called


def test_engine_synthesis_failure_falls_back_to_facts() -> None:
    engine, backend = engine_with_request_ids("synthesis-1")

    pending = engine.begin_turn("describe the workspace")

    assert isinstance(pending, PendingPlanRequest)
    reply = engine.fail_turn(pending.request_id, RuntimeError("provider unavailable"))

    assert reply.kind == "answer"
    assert reply.text == "query:summary"
    assert backend.execute_query_called


def test_engine_synthesis_empty_content_falls_back_to_facts() -> None:
    engine, backend = engine_with_request_ids("synthesis-1")

    pending = engine.begin_turn("describe the workspace")
    reply = engine.resume_turn(pending.request_id, "   ")

    assert reply.kind == "answer"
    assert reply.text == "query:summary"
    assert backend.execute_query_called
