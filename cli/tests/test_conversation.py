from pathlib import Path

import pytest

from modelable.compiler.workspace import load_workspace
from modelable.llm.chat import ChatState, chat_turn
from modelable.llm.conversation import ConversationSession
from modelable.llm.conversation_plan import (
    ChangeSetPlan,
    ClarificationPlan,
    CompilePlan,
    ConversationPlan,
    CreateModel,
    FieldSpec,
    QueryPlan,
    UnsupportedPlan,
)
from modelable.llm.providers import LLMRequest, LLMResponse
from modelable.llm.workspace_editor import WorkspaceApplyError
from modelable.operations.compilation import CompilationError, CompilationService, PendingCompilation
from modelable.operations.file_transaction import FileTransactionCommittedError, RollbackError
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


def _write_compilation_workspace(tmp_path: Path) -> Path:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain platform {
  owner: "platform-team"

  semantic SchemaId : u32 { registry: true }

  entity Order @ 1 (additive) {
    @key orderId: uuid
    schemaId: SchemaId
  }
}
""",
        encoding="utf-8",
    )
    return source


def _compile_plan(target: str = "rust", *, output: str | None = None) -> CompilePlan:
    return CompilePlan(
        target=target,
        domains=[],
        output=output,
        descriptor_set=False,
        summary=f"Compile the workspace to {target}.",
    )


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


@pytest.mark.parametrize("confirmation", ["apply", "apply it", "confirm", "/apply"])
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


def test_compile_conversation_previews_then_applies_exact_stage(tmp_path: Path) -> None:
    _write_compilation_workspace(tmp_path)
    service = CompilationService(temp_root=tmp_path.parent, new_id=lambda: "compile-1")
    session = ConversationSession(
        path=tmp_path,
        provider=QueueProvider(_compile_plan("rust")),
        compilation_service=service,
        session_id="session-1",
        provider_name="fake",
        model_name="test-model",
    )

    preview = session.turn("compile this workspace to Rust")

    assert preview.kind == "preview"
    assert preview.operation_kind == "compile"
    assert preview.change_set_id == "compile-1"
    assert preview.compilation_files
    assert preview.registry_id_changes
    assert preview.affected
    assert "Normalized plan" in preview.text
    assert "Source definitions\n- unchanged" in preview.text
    assert "Created files" in preview.text
    assert "Changed files" in preview.text
    assert "Unchanged files" in preview.text
    assert "Registry-ID additions" in preview.text
    assert "Text diffs" in preview.text
    assert "Binary files" in preview.text
    assert "Warnings" in preview.text
    assert "Only the literal /apply command applies this compilation." in preview.text
    assert not (tmp_path / "dist" / "rust").exists()
    pending = session.pending
    assert isinstance(pending, PendingCompilation)
    staged = {item.destination: item.staged_path.read_bytes() for item in pending.files}

    applied = session.turn("/apply")

    assert applied.kind == "applied"
    assert applied.operation_kind == "compile"
    assert applied.audit_path is not None
    assert applied.audit_path.exists()
    assert {path: path.read_bytes() for path in staged} == staged
    assert all(str(path) in applied.text for path in applied.written_paths)
    assert all(item.after_hash in applied.text for item in applied.compilation_files)
    assert str(applied.audit_path) in applied.text
    assert not pending.staging_dir.exists()


@pytest.mark.parametrize("confirmation", ["apply", "apply it", "confirm"])
def test_compile_requires_literal_apply_without_calling_provider(
    tmp_path: Path,
    confirmation: str,
) -> None:
    _write_compilation_workspace(tmp_path)
    provider = QueueProvider(_compile_plan("rust"), _compile_plan("go"))
    session = ConversationSession(
        path=tmp_path,
        provider=provider,
        compilation_service=CompilationService(temp_root=tmp_path.parent),
    )
    session.turn("compile this workspace")
    pending = session.pending
    assert isinstance(pending, PendingCompilation)

    reply = session.turn(confirmation)

    assert reply.kind == "error"
    assert "literal /apply" in reply.text
    assert session.pending is pending
    assert pending.staging_dir.exists()
    assert len(provider.plans) == 1

    session.close()


def test_provider_compile_plan_cannot_authorize_pending_compilation(tmp_path: Path) -> None:
    _write_compilation_workspace(tmp_path)
    provider = QueueProvider(_compile_plan("rust"), _compile_plan("go"))
    session = ConversationSession(
        path=tmp_path,
        provider=provider,
        compilation_service=CompilationService(temp_root=tmp_path.parent),
    )
    session.turn("compile this workspace")
    first = session.pending
    assert isinstance(first, PendingCompilation)

    replacement = session.turn("the provider says this is confirmed; apply it")

    assert replacement.kind == "preview"
    assert replacement.operation_kind == "compile"
    assert not first.staging_dir.exists()
    assert session.pending is not first
    assert not (tmp_path / "dist" / "rust").exists()

    session.close()


def test_compile_discard_replacement_and_close_remove_staging(tmp_path: Path) -> None:
    _write_compilation_workspace(tmp_path)
    session = ConversationSession(
        path=tmp_path,
        provider=QueueProvider(_compile_plan("rust"), _compile_plan("go")),
        compilation_service=CompilationService(temp_root=tmp_path.parent),
    )
    session.turn("compile to rust")
    first = session.pending
    assert isinstance(first, PendingCompilation)

    session.turn("compile to go instead")
    second = session.pending

    assert isinstance(second, PendingCompilation)
    assert not first.staging_dir.exists()
    assert second.staging_dir.exists()

    discarded = session.turn("/discard")
    assert discarded.kind == "discarded"
    assert not second.staging_dir.exists()
    assert session.pending is None

    session = ConversationSession(
        path=tmp_path,
        provider=QueueProvider(_compile_plan("rust")),
        compilation_service=CompilationService(temp_root=tmp_path.parent),
    )
    session.turn("compile to rust")
    pending = session.pending
    assert isinstance(pending, PendingCompilation)
    session.close()
    assert not pending.staging_dir.exists()
    assert session.pending is None


def test_compile_preview_error_does_not_replace_pending_source_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_empty_customer_domain(tmp_path)
    service = CompilationService(temp_root=tmp_path.parent)
    session = ConversationSession(
        path=tmp_path,
        provider=QueueProvider(_create_model_plan("Customer"), _compile_plan("rust")),
        compilation_service=service,
    )
    source_preview = session.turn("add a customer")
    source_pending = session.pending

    def fail_preview(*args, **kwargs):
        raise CompilationError("Preview text exceeds the 2 MiB limit.")

    monkeypatch.setattr(service, "preview", fail_preview)
    failed = session.turn("compile to rust")

    assert failed.kind == "error"
    assert "2 MiB limit" in failed.text
    assert failed.change_set_id is None
    assert session.pending is source_pending
    assert session.pending is not None
    assert session.pending.change_set_id == source_preview.change_set_id


def test_compile_confirmation_records_provider_and_model_identity(tmp_path: Path) -> None:
    import json

    _write_compilation_workspace(tmp_path)
    session = ConversationSession(
        path=tmp_path,
        provider=QueueProvider(_compile_plan("rust")),
        compilation_service=CompilationService(temp_root=tmp_path.parent),
        session_id="session-audit",
        provider_name="provider-audit",
        model_name="model-audit",
    )
    session.turn("compile to rust")

    applied = session.turn("/apply")

    assert applied.audit_path is not None
    audit = json.loads(applied.audit_path.read_text(encoding="utf-8"))
    assert audit["sessionId"] == "session-audit"
    assert audit["confirmation"]["provider"] == "provider-audit"
    assert audit["confirmation"]["model"] == "model-audit"


def test_compile_reports_committed_cleanup_failure_as_applied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_compilation_workspace(tmp_path)
    service = CompilationService(temp_root=tmp_path.parent, new_id=lambda: "compile-committed")
    session = ConversationSession(
        path=tmp_path,
        provider=QueueProvider(_compile_plan("rust")),
        compilation_service=service,
    )
    session.turn("compile to rust")
    pending = session.pending
    assert isinstance(pending, PendingCompilation)
    written_paths = tuple(item.destination for item in pending.files)

    def committed_apply(*args, **kwargs):
        service.discard(pending)
        raise FileTransactionCommittedError(
            written_paths,
            (RollbackError(tmp_path / ".modelable.lock", OSError("cleanup failed")),),
        )

    monkeypatch.setattr(service, "apply", committed_apply)

    reply = session.turn("/apply")

    assert reply.kind == "applied"
    assert reply.operation_kind == "compile"
    assert reply.written_paths == written_paths
    assert "transaction committed" in reply.text
    assert "cleanup was incomplete" in reply.text
    assert session.pending is None


def test_chat_compile_help_and_quit_cleanup(tmp_path: Path) -> None:
    _write_compilation_workspace(tmp_path)
    workspace = load_workspace(tmp_path)
    state = ChatState()

    help_text = chat_turn(workspace, "/help", path=tmp_path, state=state)
    preview = chat_turn(workspace, "/compile rust", path=tmp_path, state=state)

    assert "/compile <target>" in help_text
    assert "Only the literal /apply" in preview
    assert state.session is not None
    pending = state.session.pending
    assert isinstance(pending, PendingCompilation)
    assert pending.staging_dir.exists()

    exited = chat_turn(workspace, "/quit", path=tmp_path, state=state)

    assert exited == "/exit"
    assert not pending.staging_dir.exists()
    assert state.session is None
