from pathlib import Path

import pytest

from modelable.compiler.workspace import load_workspace
from modelable.llm.chat import ChatState, chat_turn
from modelable.llm.conversation import ConversationSession
from modelable.llm.conversation_plan import (
    ChangeSetPlan,
    ClarificationPlan,
    ConversationPlan,
    CreateModel,
    FieldSpec,
    QueryPlan,
    UnsupportedPlan,
)
from modelable.llm.providers import LLMRequest, LLMResponse
from modelable.llm.workspace_editor import WorkspaceApplyError
from modelable.parser.ir import AnnKey, FieldDef, ObjectType, PrimitiveType


class FakeProvider:
    def __init__(self, plan: ChangeSetPlan) -> None:
        self.plan = plan

    def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            content=self.plan.model_dump_json(),
            provider="fake",
            model="test-model",
        )


class QueueProvider:
    def __init__(self, *plans: ConversationPlan) -> None:
        self.plans = list(plans)

    def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            content=self.plans.pop(0).model_dump_json(),
            provider="fake",
            model="test-model",
        )


def _create_model_plan(name: str) -> ChangeSetPlan:
    return ChangeSetPlan(
        summary=f"Create customer.{name}@1",
        operations=[
            CreateModel(
                domain="customer",
                name=name,
                model_kind="entity",
                fields=[
                    FieldSpec(
                        name=f"{name[0].lower()}{name[1:]}Id",
                        type=PrimitiveType(kind="uuid"),
                        annotations=[AnnKey()],
                    )
                ],
            )
        ],
    )


def _write_empty_customer_domain(tmp_path: Path) -> Path:
    source = tmp_path / "customer.mdl"
    source.write_text(
        'domain customer {\n  owner: "customer-team"\n}\n',
        encoding="utf-8",
    )
    return source


def test_preview_and_apply_complete_entity(tmp_path: Path) -> None:
    source = tmp_path / "customer.mdl"
    original = 'domain customer {\n  owner: "customer-team"\n}\n'
    source.write_text(original, encoding="utf-8")
    plan = ChangeSetPlan(
        summary="Create customer.Customer@1",
        assumptions=["Address is inline"],
        operations=[
            CreateModel(
                domain="customer",
                name="Customer",
                model_kind="entity",
                fields=[
                    FieldSpec(
                        name="customerId",
                        type=PrimitiveType(kind="uuid"),
                        annotations=[AnnKey()],
                    ),
                    FieldSpec(
                        name="address",
                        type=ObjectType(
                            fields=[
                                FieldDef(name="street", type=PrimitiveType(kind="string")),
                                FieldDef(name="city", type=PrimitiveType(kind="string")),
                                FieldDef(name="postalCode", type=PrimitiveType(kind="string")),
                                FieldDef(name="country", type=PrimitiveType(kind="string")),
                            ]
                        ),
                    ),
                ],
            )
        ],
    )
    session = ConversationSession(
        path=tmp_path,
        provider=FakeProvider(plan),
    )

    preview = session.turn("add a customer entity with address")

    assert preview.kind == "preview"
    assert "Summary" in preview.text
    assert "Assumptions" in preview.text
    assert "Changed definitions" in preview.text
    assert "Affected definitions" in preview.text
    assert "Compatibility and validation" in preview.text
    assert "Unified diff" in preview.text
    assert "customer.Customer@1" in preview.text
    assert "- create_model: customer.Customer@1" in preview.text
    assert "Address is inline" in preview.text
    assert preview.changed[0].ref == "customer.Customer@1"
    assert preview.affected == ()
    assert preview.change_set_id is not None
    assert len(preview.preview_files) == 1
    assert preview.preview_files[0].path == source
    assert preview.preview_files[0].existed_before is True
    assert preview.preview_files[0].before_text == original
    assert "entity Customer @ 1" in preview.preview_files[0].after_text
    assert session.pending is not None
    assert source.read_text(encoding="utf-8") == original

    applied = session.turn("apply")

    assert applied.kind == "applied"
    assert "customer.Customer@1" in applied.text
    assert applied.written_paths == (source,)
    assert applied.changed[0].ref == "customer.Customer@1"
    assert applied.focused_ref == "customer.Customer@1"
    assert session.pending is None
    assert session.focused_ref == "customer.Customer@1"
    assert "entity Customer @ 1" in source.read_text(encoding="utf-8")


def test_refinement_reports_replaced_pending_change_set(tmp_path: Path) -> None:
    _write_empty_customer_domain(tmp_path)
    session = ConversationSession(
        path=tmp_path,
        provider=QueueProvider(
            _create_model_plan("Customer"),
            _create_model_plan("Account"),
        ),
    )

    first = session.turn("add a customer")
    second = session.turn("make that an account instead")

    assert first.change_set_id is not None
    assert second.change_set_id is not None
    assert second.change_set_id != first.change_set_id
    assert second.text.startswith(f"Replaced pending change set {first.change_set_id} with {second.change_set_id}.")


@pytest.mark.parametrize("confirmation", ["apply it", "/apply"])
def test_natural_and_explicit_confirmation_apply_pending_change(
    tmp_path: Path,
    confirmation: str,
) -> None:
    source = _write_empty_customer_domain(tmp_path)
    session = ConversationSession(
        path=tmp_path,
        provider=FakeProvider(_create_model_plan("Customer")),
    )
    session.turn("add a customer")

    reply = session.turn(confirmation)

    assert reply.kind == "applied"
    assert "entity Customer @ 1" in source.read_text(encoding="utf-8")


def test_discard_clears_pending_change_without_writing(tmp_path: Path) -> None:
    source = _write_empty_customer_domain(tmp_path)
    original = source.read_text(encoding="utf-8")
    session = ConversationSession(
        path=tmp_path,
        provider=FakeProvider(_create_model_plan("Customer")),
    )
    preview = session.turn("add a customer")

    reply = session.turn("/discard")

    assert reply.kind == "discarded"
    assert preview.change_set_id in reply.text
    assert session.pending is None
    assert source.read_text(encoding="utf-8") == original


def test_query_does_not_replace_pending_change_set(tmp_path: Path) -> None:
    _write_empty_customer_domain(tmp_path)
    session = ConversationSession(
        path=tmp_path,
        provider=QueueProvider(
            _create_model_plan("Customer"),
            QueryPlan(
                query_kind="validation",
                refs=[],
                question="is the workspace valid?",
            ),
        ),
    )
    preview = session.turn("add a customer")

    answer = session.turn("is the workspace valid?")

    assert answer.kind == "answer"
    assert "validation passed" in answer.text
    assert session.pending is not None
    assert session.pending.change_set_id == preview.change_set_id


@pytest.mark.parametrize(
    ("plan", "expected_kind", "expected_text"),
    [
        (
            ClarificationPlan(
                question="Which domain should own the entity?",
                reason="Ownership is ambiguous.",
            ),
            "clarification",
            "Which domain",
        ),
        (
            UnsupportedPlan(
                request="publish it",
                reason="Publishing is outside conversational workspace planning.",
                roadmap_area="operations",
            ),
            "unsupported",
            "Roadmap area: operations",
        ),
    ],
)
def test_non_change_plans_do_not_stage_changes(
    tmp_path: Path,
    plan: ConversationPlan,
    expected_kind: str,
    expected_text: str,
) -> None:
    _write_empty_customer_domain(tmp_path)
    session = ConversationSession(path=tmp_path, provider=QueueProvider(plan))

    reply = session.turn("manage the workspace")

    assert reply.kind == expected_kind
    assert expected_text in reply.text
    assert session.pending is None


def test_apply_rejects_stale_source_fingerprint(tmp_path: Path) -> None:
    source = _write_empty_customer_domain(tmp_path)
    session = ConversationSession(
        path=tmp_path,
        provider=FakeProvider(_create_model_plan("Customer")),
    )
    preview = session.turn("add a customer")
    source.write_text(
        source.read_text(encoding="utf-8").replace("customer-team", "new-team"),
        encoding="utf-8",
    )

    reply = session.turn("/apply")

    assert reply.kind == "error"
    assert "changed after this change set was previewed" in reply.text
    assert reply.change_set_id == preview.change_set_id
    assert session.pending is not None


def test_apply_reports_rollback_failure_without_clearing_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_empty_customer_domain(tmp_path)
    session = ConversationSession(
        path=tmp_path,
        provider=FakeProvider(_create_model_plan("Customer")),
    )
    preview = session.turn("add a customer")

    def fail_apply(pending) -> None:
        raise WorkspaceApplyError("replacement failed; rollback restored the original")

    monkeypatch.setattr(session.editor, "apply", fail_apply)

    reply = session.turn("/apply")

    assert reply.kind == "error"
    assert "rollback restored the original" in reply.text
    assert reply.change_set_id == preview.change_set_id
    assert session.pending is not None


def test_post_apply_query_uses_reloaded_workspace(tmp_path: Path) -> None:
    _write_empty_customer_domain(tmp_path)
    session = ConversationSession(
        path=tmp_path,
        provider=QueueProvider(
            _create_model_plan("Customer"),
            QueryPlan(
                query_kind="summary",
                refs=["customer.Customer@1"],
                question="describe customer.Customer@1",
            ),
        ),
    )
    session.turn("add a customer")
    session.turn("/apply")

    answer = session.turn("describe customer.Customer@1")

    assert answer.kind == "answer"
    assert "customer.Customer@1" in answer.text
    assert "customerId" in answer.text


def test_apply_without_pending_change_writes_nothing(tmp_path: Path) -> None:
    source = _write_empty_customer_domain(tmp_path)
    original = source.read_bytes()
    session = ConversationSession(path=tmp_path, provider=None)

    reply = session.turn("/apply")

    assert reply.kind == "error"
    assert "no pending change set" in reply.text
    assert source.read_bytes() == original


def test_validation_query_works_when_workspace_has_errors(tmp_path: Path) -> None:
    (tmp_path / "invalid.mdl").write_text("domain customer {}\n", encoding="utf-8")
    session = ConversationSession(path=tmp_path, provider=None)

    reply = session.turn("is the workspace valid?")

    assert reply.kind == "answer"
    assert "must have an owner attribute" in reply.text


def test_chat_state_retains_session_from_preview_through_apply(tmp_path: Path) -> None:
    source = _write_empty_customer_domain(tmp_path)
    workspace = load_workspace(tmp_path)
    provider = FakeProvider(_create_model_plan("Customer"))
    state = ChatState()

    preview = chat_turn(
        workspace,
        "add a customer entity",
        path=tmp_path,
        state=state,
        provider=provider,
    )
    applied = chat_turn(
        workspace,
        "/apply",
        path=tmp_path,
        state=state,
        provider=provider,
    )
    described = chat_turn(
        workspace,
        "/describe",
        path=tmp_path,
        state=state,
        provider=provider,
    )

    assert "Apply change set" in preview
    assert "Applied change set" in applied
    assert "customer.Customer@1" in described
    assert "customerId" in described
    assert state.session is not None
    assert state.ref == "customer.Customer@1"
    assert "entity Customer @ 1" in source.read_text(encoding="utf-8")
