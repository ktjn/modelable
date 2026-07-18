from __future__ import annotations

from pathlib import Path

import pytest

from modelable.compiler.workspace import load_workspace
from modelable.llm.conversation import ConversationSession
from modelable.llm.conversation_plan import ChangeSetPlan, CreateModel, FieldSpec
from modelable.llm.providers import LLMRequest, LLMResponse
from modelable.lsp import definition, document_symbols
from modelable.lsp import workspace as lsp_workspace
from modelable.lsp.conversation_protocol import (
    ConversationChangeSetParams,
    ConversationPosition,
    ConversationTurnParams,
)
from modelable.lsp.conversation_service import (
    ConversationSessionError,
    LspConversationService,
)
from modelable.lsp.workspace import LspWorkspaceIndex
from modelable.parser.ir import AnnKey, PrimitiveType


def test_find_focused_ref_returns_containing_definition(tmp_path: Path) -> None:
    source = tmp_path / "customer.mdl"
    source.write_text(
        "domain customer {\n"
        '  owner: "customer-team"\n'
        "  entity Customer @ 1 (additive) {\n"
        "    @key customerId: uuid\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    index = LspWorkspaceIndex()
    index.upsert_document(source.as_uri(), source.read_text(encoding="utf-8"))

    assert document_symbols.find_focused_ref(index, source.as_uri(), 3, 8) == "customer.Customer@1"
    assert document_symbols.find_focused_ref(index, source.as_uri(), 0, 0) is None


def test_find_workspace_root_uses_nearest_manifest(tmp_path: Path) -> None:
    root = tmp_path / "modelable"
    nested = root / "domains" / "customer"
    nested.mkdir(parents=True)
    (root / "workspace.mdl").write_text('workspace "example" {}\n', encoding="utf-8")
    source = nested / "customer.mdl"
    source.write_text('domain customer { owner: "customer-team" }\n', encoding="utf-8")

    assert lsp_workspace.find_workspace_root(source) == root
    assert lsp_workspace.find_workspace_root(tmp_path / "outside.mdl") is None


def test_definition_location_for_ref_exposes_existing_resolver(tmp_path: Path) -> None:
    source = tmp_path / "customer.mdl"
    source.write_text(
        "domain customer {\n"
        '  owner: "customer-team"\n'
        "  entity Customer @ 1 (additive) {\n"
        "    @key customerId: uuid\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )

    location = definition.definition_location_for_ref(
        load_workspace(tmp_path),
        "customer.Customer@1",
    )

    assert location is not None
    assert location.uri == source.as_uri()
    assert location.range.start.line == 2


def _write_customer_workspace(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    source = root / "customer.mdl"
    source.write_text(
        "domain customer {\n"
        '  owner: "customer-team"\n'
        "  entity Customer @ 1 (additive) {\n"
        "    @key customerId: uuid\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    return source


def _session_factory(root: Path, focused_ref: str | None) -> ConversationSession:
    return ConversationSession(
        path=root,
        provider=None,
        focused_ref=focused_ref,
    )


def _turn_params(
    root: Path,
    *,
    session_id: str = "session-1",
    create_session: bool,
    dirty_document_uris: tuple[str, ...] = (),
) -> ConversationTurnParams:
    return ConversationTurnParams.model_validate(
        {
            "protocolVersion": 1,
            "sessionId": session_id,
            "createSession": create_session,
            "workspaceUri": root.as_uri(),
            "message": "is the workspace valid?",
            "dirtyDocumentUris": list(dirty_document_uris),
        }
    )


def test_registry_requires_create_flag_for_unknown_session(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    service = LspConversationService(
        session_factory=_session_factory,
        clock=lambda: 10.0,
    )

    with pytest.raises(ConversationSessionError, match="expired"):
        service.turn(_turn_params(root, create_session=False))

    reply = service.turn(_turn_params(root, create_session=True))

    assert reply["kind"] == "answer"
    assert reply["sessionId"] == "session-1"


def test_registry_expires_idle_sessions(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    now = [0.0]
    service = LspConversationService(
        session_factory=_session_factory,
        clock=lambda: now[0],
    )
    service.turn(_turn_params(root, create_session=True))
    now[0] = 1801.0

    with pytest.raises(ConversationSessionError, match="expired"):
        service.turn(_turn_params(root, create_session=False))


def test_registry_evicts_the_least_recently_used_session(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    now = [0.0]
    service = LspConversationService(
        max_sessions=2,
        session_factory=_session_factory,
        clock=lambda: now[0],
    )
    service.turn(_turn_params(root, session_id="session-1", create_session=True))
    now[0] = 1.0
    service.turn(_turn_params(root, session_id="session-2", create_session=True))
    now[0] = 2.0
    service.turn(_turn_params(root, session_id="session-1", create_session=False))
    now[0] = 3.0
    service.turn(_turn_params(root, session_id="session-3", create_session=True))

    with pytest.raises(ConversationSessionError, match="expired"):
        service.turn(_turn_params(root, session_id="session-2", create_session=False))

    assert service.turn(_turn_params(root, session_id="session-1", create_session=False))["kind"] == "answer"


def test_registry_caps_sessions_at_32_and_evicts_the_lru_id(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    now = [0.0]
    service = LspConversationService(
        session_factory=_session_factory,
        clock=lambda: now[0],
    )
    for number in range(1, 32):
        now[0] = float(number)
        service.turn(
            _turn_params(
                root,
                session_id=f"session-{number}",
                create_session=True,
            )
        )
    now[0] = 32.0
    service.turn(_turn_params(root, session_id="session-1", create_session=False))
    now[0] = 33.0
    service.turn(_turn_params(root, session_id="session-32", create_session=True))
    now[0] = 34.0
    service.turn(_turn_params(root, session_id="session-33", create_session=True))

    with pytest.raises(ConversationSessionError, match="expired"):
        service.turn(_turn_params(root, session_id="session-2", create_session=False))

    assert service.turn(_turn_params(root, session_id="session-1", create_session=False))["kind"] == "answer"


def test_registry_binds_sessions_and_filters_dirty_files_by_root(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    source = _write_customer_workspace(root)
    other_root = tmp_path / "other"
    other_source = _write_customer_workspace(other_root)
    service = LspConversationService(session_factory=_session_factory)
    service.turn(_turn_params(root, create_session=True))

    with pytest.raises(ConversationSessionError, match="different workspace"):
        service.turn(
            _turn_params(
                other_root,
                create_session=False,
            )
        )

    with pytest.raises(ConversationSessionError, match="Save these files"):
        service.turn(
            _turn_params(
                root,
                create_session=False,
                dirty_document_uris=(source.as_uri(),),
            )
        )

    reply = service.turn(
        _turn_params(
            root,
            create_session=False,
            dirty_document_uris=(other_source.as_uri(),),
        )
    )

    assert reply["kind"] == "answer"


def test_registry_rejects_duplicate_creation_and_updates_focus(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    source = _write_customer_workspace(root)
    (root / "workspace.mdl").write_text('workspace "example" {}\n', encoding="utf-8")
    index = LspWorkspaceIndex()
    index.upsert_document(source.as_uri(), source.read_text(encoding="utf-8"))
    sessions: list[ConversationSession] = []

    def capture_session(root: Path, focused_ref: str | None) -> ConversationSession:
        session = _session_factory(root, focused_ref)
        sessions.append(session)
        return session

    params = _turn_params(root, create_session=True).model_copy(
        update={
            "active_document_uri": source.as_uri(),
            "position": ConversationPosition(line=3, character=8),
        }
    )
    service = LspConversationService(session_factory=capture_session)

    service.turn(params, index=index)

    assert sessions[0].focused_ref == "customer.Customer@1"
    with pytest.raises(ConversationSessionError, match="already exists"):
        service.turn(params, index=index)


def test_registry_close_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_customer_workspace(root)
    service = LspConversationService(session_factory=_session_factory)
    service.turn(_turn_params(root, create_session=True))

    service.close("session-1")
    service.close("session-1")

    with pytest.raises(ConversationSessionError, match="expired"):
        service.turn(_turn_params(root, create_session=False))


class _CreateAccountProvider:
    def complete(self, request: LLMRequest) -> LLMResponse:
        plan = ChangeSetPlan(
            summary="Create customer.Account@1",
            operations=[
                CreateModel(
                    domain="customer",
                    name="Account",
                    model_kind="entity",
                    fields=[
                        FieldSpec(
                            name="accountId",
                            type=PrimitiveType(kind="uuid"),
                            annotations=[AnnKey()],
                        )
                    ],
                )
            ],
        )
        return LLMResponse(
            content=plan.model_dump_json(),
            provider="fake",
            model="test-model",
        )


def _editing_session_factory(root: Path, focused_ref: str | None) -> ConversationSession:
    return ConversationSession(
        path=root,
        provider=_CreateAccountProvider(),
        focused_ref=focused_ref,
    )


def _change_set_params(
    *,
    session_id: str,
    change_set_id: str,
    dirty_document_uris: tuple[str, ...] = (),
) -> ConversationChangeSetParams:
    return ConversationChangeSetParams.model_validate(
        {
            "protocolVersion": 1,
            "sessionId": session_id,
            "changeSetId": change_set_id,
            "dirtyDocumentUris": list(dirty_document_uris),
        }
    )


def test_apply_requires_the_exact_pending_change_set_id(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    source = _write_customer_workspace(root)
    service = LspConversationService(session_factory=_editing_session_factory)
    preview = service.turn(
        _turn_params(root, create_session=True).model_copy(update={"message": "add an account entity"})
    )
    change_set_id = preview["changeSetId"]
    assert isinstance(change_set_id, str)

    with pytest.raises(ConversationSessionError, match="current pending change set"):
        service.apply(
            _change_set_params(
                session_id="session-1",
                change_set_id="wrong-id",
            )
        )
    with pytest.raises(ConversationSessionError, match="Save these files"):
        service.apply(
            _change_set_params(
                session_id="session-1",
                change_set_id=change_set_id,
                dirty_document_uris=(source.as_uri(),),
            )
        )

    reply = service.apply(
        _change_set_params(
            session_id="session-1",
            change_set_id=change_set_id,
        )
    )

    assert reply["kind"] == "applied"
    assert reply["changeSetId"] == change_set_id
    assert source.as_uri() in reply["writtenPaths"]


def test_discard_requires_the_exact_pending_change_set_id(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    source = _write_customer_workspace(root)
    service = LspConversationService(session_factory=_editing_session_factory)
    preview = service.turn(
        _turn_params(root, create_session=True).model_copy(update={"message": "add an account entity"})
    )
    change_set_id = preview["changeSetId"]
    assert isinstance(change_set_id, str)

    with pytest.raises(ConversationSessionError, match="current pending change set"):
        service.discard(
            _change_set_params(
                session_id="session-1",
                change_set_id="wrong-id",
            )
        )
    with pytest.raises(ConversationSessionError, match="Save these files"):
        service.discard(
            _change_set_params(
                session_id="session-1",
                change_set_id=change_set_id,
                dirty_document_uris=(source.as_uri(),),
            )
        )

    reply = service.discard(
        _change_set_params(
            session_id="session-1",
            change_set_id=change_set_id,
        )
    )

    assert reply["kind"] == "discarded"
    assert reply["changeSetId"] == change_set_id
