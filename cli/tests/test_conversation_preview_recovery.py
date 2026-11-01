import json
import sqlite3
from unittest.mock import Mock

import pytest
from test_compilation_failure_catalog import assert_no_publication
from test_compilation_failure_catalog import catalog_workspace as catalog_workspace

from modelable.llm.conversation import ConversationSession
from modelable.operations.compilation import CompilationError


@pytest.fixture
def preview_session(catalog_workspace):
    root, stages, request, service = catalog_workspace
    session = ConversationSession(path=root, provider=None, compilation_service=service)
    try:
        yield session, root, stages, request, service
    finally:
        session.close()


@pytest.mark.parametrize(
    "error", [json.JSONDecodeError("bad ledger", "{", 1), sqlite3.OperationalError("database unavailable")]
)
def test_first_preview_operational_failure_is_a_domain_error(preview_session, monkeypatch, error):
    session, root, stages, request, service = preview_session
    original = request.source.read_bytes()
    monkeypatch.setattr(service, "preview", Mock(side_effect=error))
    failed = session.turn("/compile rust")
    assert failed.kind == "error"
    assert "Could not preview compilation" in failed.text
    assert session.pending is None
    assert session.pending_action_id is None
    assert request.source.read_bytes() == original
    assert list(stages.iterdir()) == []
    assert_no_publication(root)


@pytest.mark.parametrize("kind", [RuntimeError, sqlite3.ProgrammingError])
def test_preview_programming_faults_still_propagate(preview_session, monkeypatch, kind):
    session, root, stages, _request, service = preview_session
    error = kind("unexpected programming fault")
    monkeypatch.setattr(service, "preview", Mock(side_effect=error))
    with pytest.raises(kind) as raised:
        session.turn("/compile rust")
    assert raised.value is error
    assert session.pending is None
    assert list(stages.iterdir()) == []
    assert_no_publication(root)


@pytest.mark.parametrize(
    "error",
    [
        CompilationError("preview rejected"),
        json.JSONDecodeError("bad ledger", "{", 1),
        sqlite3.OperationalError("database unavailable"),
    ],
)
def test_failed_replacement_keeps_pending_stage_until_close(preview_session, monkeypatch, error):
    session, root, stages, _request, service = preview_session
    first = session.turn("/compile rust")
    pending = session.pending
    assert pending is not None
    staged = {p.relative_to(pending.staging_dir): p.read_bytes() for p in pending.staging_dir.rglob("*") if p.is_file()}
    monkeypatch.setattr(service, "preview", Mock(side_effect=error))
    failed = session.turn("/compile go")
    assert failed.kind == "error"
    assert session.pending is pending
    assert session.pending_action_id == first.change_set_id
    assert {
        p.relative_to(pending.staging_dir): p.read_bytes() for p in pending.staging_dir.rglob("*") if p.is_file()
    } == staged
    assert_no_publication(root)
    session.close()
    assert list(stages.iterdir()) == []


def test_wire_error_keeps_existing_pending_source_action(catalog_workspace, monkeypatch):
    from test_conversation import QueueProvider, _create_model_plan

    from modelable.lsp.conversation_protocol import ConversationTurnParams
    from modelable.lsp.conversation_service import LspConversationService

    root, stages, source_request, service = catalog_workspace
    original = source_request.source.read_bytes()
    sessions = []

    def factory(root, focused_ref):
        session = ConversationSession(
            path=root, provider=QueueProvider(_create_model_plan("Invoice")), compilation_service=service
        )
        sessions.append(session)
        return session

    registry = LspConversationService(session_factory=factory)

    def params(message, create=False):
        return ConversationTurnParams.model_validate(
            {
                "protocolVersion": 2,
                "sessionId": "source-preview",
                "createSession": create,
                "workspaceUri": root.as_uri(),
                "message": message,
                "dirtyDocumentUris": [],
            }
        )

    try:
        first = registry.turn(params("create invoice", True))
        assert first["kind"] == "preview"
        assert first["operationKind"] == "source_change"
        pending = sessions[0].pending
        monkeypatch.setattr(service, "preview", Mock(side_effect=CompilationError("replacement rejected")))
        failed = registry.turn(params("/compile rust"))
        assert failed["kind"] == "error"
        assert failed["changeSetId"] == first["changeSetId"]
        assert failed["operationKind"] == "source_change"
        assert sessions[0].pending is pending
    finally:
        registry.close("source-preview")
    assert source_request.source.read_bytes() == original
    assert list(stages.iterdir()) == []
