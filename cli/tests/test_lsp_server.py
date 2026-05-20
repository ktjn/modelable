from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module

from lsprotocol import types

from modelable.diagnostics.model import Diagnostic

lsp_server = import_module("modelable.lsp.server")


def test_lsp_server_is_configured():
    assert lsp_server.server.name == "modelable-lsp"
    assert lsp_server.server.version == "0.1.0"
    assert hasattr(lsp_server.server, "index")


def test_lsp_server_advertises_completion():
    result = lsp_server.initialize(
        lsp_server.server, types.InitializeParams(capabilities=types.ClientCapabilities())
    )

    assert result.capabilities.completion_provider is not None
    assert result.capabilities.completion_provider.trigger_characters == ["@", "."]


def test_lsp_server_advertises_references():
    result = lsp_server.initialize(
        lsp_server.server, types.InitializeParams(capabilities=types.ClientCapabilities())
    )

    assert result.capabilities.references_provider is True


def test_lsp_server_advertises_document_symbols():
    result = lsp_server.initialize(
        lsp_server.server, types.InitializeParams(capabilities=types.ClientCapabilities())
    )

    assert result.capabilities.document_symbol_provider is True


def test_lsp_server_advertises_workspace_symbols():
    result = lsp_server.initialize(
        lsp_server.server, types.InitializeParams(capabilities=types.ClientCapabilities())
    )

    assert result.capabilities.workspace_symbol_provider is not None


def test_lsp_server_advertises_formatting():
    result = lsp_server.initialize(
        lsp_server.server, types.InitializeParams(capabilities=types.ClientCapabilities())
    )

    assert result.capabilities.document_formatting_provider is True


def test_lsp_server_advertises_rename():
    result = lsp_server.initialize(
        lsp_server.server, types.InitializeParams(capabilities=types.ClientCapabilities())
    )

    assert result.capabilities.rename_provider is not None
    assert result.capabilities.rename_provider.prepare_provider is True


def test_lsp_server_advertises_code_actions():
    result = lsp_server.initialize(
        lsp_server.server, types.InitializeParams(capabilities=types.ClientCapabilities())
    )

    assert result.capabilities.code_action_provider is not None
    assert result.capabilities.code_action_provider.code_action_kinds == [types.CodeActionKind.QuickFix]


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

    lsp_server._publish_document_diagnostics(ls, "file:///workspace/customer.mdl")

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

    lsp_server._publish_document_diagnostics(ls, uri)

    assert len(ls.published) == 1
    params = ls.published[0]
    assert params.uri == uri
    assert [diagnostic.code for diagnostic in params.diagnostics] == ["SEM", "FED"]
    assert [diagnostic.message for diagnostic in params.diagnostics] == [
        "workspace error",
        "import warning",
    ]
