from __future__ import annotations

import asyncio
from dataclasses import dataclass
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock, patch

from lsprotocol import types

from modelable.diagnostics.model import Diagnostic

lsp_server = import_module("modelable.lsp.server")


def test_lsp_server_is_configured():
    assert lsp_server.server.name == "modelable-lsp"
    assert lsp_server.server.version == "0.1.0"
    assert hasattr(lsp_server.server, "index")


def test_lsp_server_advertises_completion():
    result = lsp_server.initialize(lsp_server.server, types.InitializeParams(capabilities=types.ClientCapabilities()))

    assert result.capabilities.completion_provider is not None
    assert result.capabilities.completion_provider.trigger_characters == ["@", "."]


def test_lsp_server_advertises_references():
    result = lsp_server.initialize(lsp_server.server, types.InitializeParams(capabilities=types.ClientCapabilities()))

    assert result.capabilities.references_provider is True


def test_lsp_server_advertises_document_symbols():
    result = lsp_server.initialize(lsp_server.server, types.InitializeParams(capabilities=types.ClientCapabilities()))

    assert result.capabilities.document_symbol_provider is True


def test_lsp_server_advertises_workspace_symbols():
    result = lsp_server.initialize(lsp_server.server, types.InitializeParams(capabilities=types.ClientCapabilities()))

    assert result.capabilities.workspace_symbol_provider is not None


def test_lsp_server_advertises_formatting():
    result = lsp_server.initialize(lsp_server.server, types.InitializeParams(capabilities=types.ClientCapabilities()))

    assert result.capabilities.document_formatting_provider is True


def test_lsp_server_advertises_rename():
    result = lsp_server.initialize(lsp_server.server, types.InitializeParams(capabilities=types.ClientCapabilities()))

    assert result.capabilities.rename_provider is not None
    assert result.capabilities.rename_provider.prepare_provider is True


def test_lsp_server_advertises_code_actions():
    result = lsp_server.initialize(lsp_server.server, types.InitializeParams(capabilities=types.ClientCapabilities()))

    assert result.capabilities.code_action_provider is not None
    assert result.capabilities.code_action_provider.code_action_kinds == [types.CodeActionKind.QuickFix]


def test_lsp_server_advertises_conversation_protocol_version() -> None:
    result = lsp_server.initialize(
        lsp_server.server,
        types.InitializeParams(capabilities=types.ClientCapabilities()),
    )

    assert result.capabilities.experimental == {
        "modelableConversation": {
            "protocolVersion": 2,
        }
    }


def test_conversation_turn_validates_and_delegates() -> None:
    service = Mock()
    service.turn.return_value = {"kind": "answer", "text": "valid"}
    index = object()
    ls = SimpleNamespace(
        conversations=service,
        index_for=Mock(return_value=index),
    )
    payload = {
        "protocolVersion": 2,
        "sessionId": "session-1",
        "createSession": True,
        "workspaceUri": "file:///workspace",
        "message": "is the workspace valid?",
        "activeDocumentUri": "file:///workspace/customer.mdl",
        "dirtyDocumentUris": [],
    }

    result = lsp_server.conversation_turn(ls, payload)

    assert result == {"kind": "answer", "text": "valid"}
    params = service.turn.call_args.args[0]
    assert params.session_id == "session-1"
    service.turn.assert_called_once_with(params, index=index)


def test_conversation_apply_and_discard_validate_and_delegate() -> None:
    service = Mock()
    service.apply.return_value = {"kind": "applied"}
    service.discard.return_value = {"kind": "discarded"}
    ls = SimpleNamespace(conversations=service)
    payload = {
        "protocolVersion": 2,
        "sessionId": "session-1",
        "changeSetId": "change-1",
        "dirtyDocumentUris": [],
    }

    assert lsp_server.conversation_apply(ls, payload) == {"kind": "applied"}
    assert lsp_server.conversation_discard(ls, payload) == {"kind": "discarded"}
    assert service.apply.call_args.args[0].change_set_id == "change-1"
    assert service.discard.call_args.args[0].change_set_id == "change-1"


def test_conversation_close_is_idempotently_delegated() -> None:
    service = Mock()
    ls = SimpleNamespace(conversations=service)
    payload = {
        "protocolVersion": 2,
        "sessionId": "session-1",
    }

    assert lsp_server.conversation_close(ls, payload) is None
    assert lsp_server.conversation_close(ls, payload) is None

    assert service.close.call_count == 2
    service.close.assert_called_with("session-1")


@dataclass
class _Workspace:
    errors: list[Diagnostic]


class _Index:
    def __init__(self, workspace: _Workspace | None) -> None:
        self.workspace = workspace


class _ServerStub:
    def __init__(self, workspace: _Workspace | None) -> None:
        self.index = _Index(workspace)
        self.published: list[types.PublishDiagnosticsParams] = []

    def text_document_publish_diagnostics(self, params: types.PublishDiagnosticsParams) -> None:
        self.published.append(params)


def test_publish_document_diagnostics_clears_diagnostics_with_the_pygls_api():
    ls = _ServerStub(None)

    lsp_server._publish_document_diagnostics(ls, "file:///workspace/customer.mdl", ls.index)

    assert len(ls.published) == 1
    assert ls.published[0].uri == "file:///workspace/customer.mdl"
    assert ls.published[0].diagnostics == []


def test_publish_document_diagnostics_publishes_workspace_and_import_findings(monkeypatch):
    uri = "file:///workspace/customer.mdl"
    workspace = _Workspace(
        errors=[
            Diagnostic(
                code="SEM",
                message="workspace error",
                severity="error",
                path=uri,
                line=1,
                column=1,
            )
        ]
    )
    ls = _ServerStub(workspace)
    monkeypatch.setattr(
        lsp_server,
        "build_import_diagnostics",
        lambda _index, _uri: [
            Diagnostic(
                code="FED",
                message="import warning",
                severity="warning",
                path=uri,
                line=2,
                column=3,
            )
        ],
    )

    lsp_server._publish_document_diagnostics(ls, uri, ls.index)

    assert len(ls.published) == 1
    params = ls.published[0]
    assert params.uri == uri
    assert [diagnostic.code for diagnostic in params.diagnostics] == ["SEM", "FED"]
    assert [diagnostic.message for diagnostic in params.diagnostics] == [
        "workspace error",
        "import warning",
    ]


def test_did_change_debounce_cancels_previous_task():
    """Rapid successive did_change calls produce a single diagnostics publish after the delay."""

    async def _run():
        publish_calls = []

        class _FakeIndex:
            def __init__(self):
                self.workspace = None
                self.documents: dict = {}

            def upsert_document(self, uri, text):
                pass

        class _FakeDocument:
            uri = "inmemory://test.mdl"
            source = "domain x {}"

        class _FakeWorkspace:
            def get_text_document(self, uri):
                return _FakeDocument()

        class _FakeServer:
            def __init__(self):
                self.index = _FakeIndex()
                self._debounce_tasks: dict = {}
                self.workspace = _FakeWorkspace()

            def index_for(self, uri):
                return self.index

            def text_document_publish_diagnostics(self, params):
                publish_calls.append(params)

        ls = _FakeServer()

        with patch.object(
            lsp_server, "_publish_document_diagnostics", side_effect=lambda _ls, _uri, _idx: publish_calls.append(_uri)
        ):
            params = types.DidChangeTextDocumentParams(
                text_document=types.VersionedTextDocumentIdentifier(uri="inmemory://test.mdl", version=1),
                content_changes=[types.TextDocumentContentChangeWholeDocument(text="domain x {}")],
            )
            await lsp_server.did_change(ls, params)
            await lsp_server.did_change(ls, params)
            await lsp_server.did_change(ls, params)

            assert len(publish_calls) == 0

            await asyncio.sleep(lsp_server._DEBOUNCE_DELAY + 0.05)

            assert len(publish_calls) == 1

    asyncio.run(_run())


def test_did_close_cancels_pending_debounce_task():
    """did_close should cancel the pending debounce task so no diagnostics fire after close."""

    async def _run():
        publish_calls = []

        class _FakeIndex:
            def __init__(self) -> None:
                self.workspace = None
                self.documents: dict = {}

            def upsert_document(self, uri, text):
                pass

            def remove_document(self, uri):
                pass

            def close_document(self, uri):
                pass

        class _FakeDocument:
            uri = "inmemory://test.mdl"
            source = "domain x {}"

        class _FakeWorkspace:
            def get_text_document(self, uri):
                return _FakeDocument()

        class _FakeServer:
            def __init__(self) -> None:
                self.index = _FakeIndex()
                self._debounce_tasks: dict = {}
                self.workspace = _FakeWorkspace()

            def index_for(self, uri):
                return self.index

            def text_document_publish_diagnostics(self, params):
                publish_calls.append(params)

        ls = _FakeServer()

        with patch.object(
            lsp_server,
            "_publish_document_diagnostics",
            side_effect=lambda _ls, _uri, _idx: publish_calls.append(_uri),
        ):
            change_params = types.DidChangeTextDocumentParams(
                text_document=types.VersionedTextDocumentIdentifier(uri="inmemory://test.mdl", version=1),
                content_changes=[types.TextDocumentContentChangeWholeDocument(text="domain x {}")],
            )
            await lsp_server.did_change(ls, change_params)
            assert len(publish_calls) == 0  # debounce not fired yet

            close_params = types.DidCloseTextDocumentParams(
                text_document=types.TextDocumentIdentifier(uri="inmemory://test.mdl")
            )
            lsp_server.did_close(ls, close_params)

            await asyncio.sleep(lsp_server._DEBOUNCE_DELAY + 0.05)

            # _publish_document_diagnostics appends URI strings; none should be present after close
            debounce_publishes = [c for c in publish_calls if isinstance(c, str)]
            assert debounce_publishes == []

    asyncio.run(_run())
