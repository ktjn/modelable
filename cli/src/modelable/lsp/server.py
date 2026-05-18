from __future__ import annotations

from pygls.lsp.server import LanguageServer
from lsprotocol import types

from modelable.lsp.diagnostics import to_lsp_diagnostics
from modelable.lsp.hover import build_hover
from modelable.lsp.workspace import LspWorkspaceIndex


class ModelableLanguageServer(LanguageServer):
    def __init__(self) -> None:
        super().__init__("modelable-lsp", "0.1.0")
        self.index = LspWorkspaceIndex()


server = ModelableLanguageServer()


@server.feature(types.INITIALIZE)
def initialize(ls: ModelableLanguageServer, _params: types.InitializeParams) -> types.InitializeResult:
        return types.InitializeResult(
            capabilities=types.ServerCapabilities(
                text_document_sync=types.TextDocumentSyncOptions(
                    open_close=True,
                    change=types.TextDocumentSyncKind.Incremental,
                    save=types.SaveOptions(include_text=True),
                ),
                hover_provider=True,
                workspace=types.WorkspaceOptions(
                    workspace_folders=types.WorkspaceFoldersOptions(
                        supported=True,
                        change_notifications=True,
                    )
            ),
        )
    )


@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
def did_open(ls: ModelableLanguageServer, params: types.DidOpenTextDocumentParams) -> None:
    ls.index.upsert_document(params.text_document.uri, params.text_document.text)
    _publish_document_diagnostics(ls, params.text_document.uri)


@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
def did_change(ls: ModelableLanguageServer, params: types.DidChangeTextDocumentParams) -> None:
    document = ls.workspace.get_text_document(params.text_document.uri)
    ls.index.upsert_document(document.uri, document.source)
    _publish_document_diagnostics(ls, document.uri)


@server.feature(types.TEXT_DOCUMENT_DID_CLOSE)
def did_close(ls: ModelableLanguageServer, params: types.DidCloseTextDocumentParams) -> None:
    ls.index.remove_document(params.text_document.uri)
    ls.publish_diagnostics(params.text_document.uri, [])


@server.feature(types.TEXT_DOCUMENT_HOVER)
def hover(ls: ModelableLanguageServer, params: types.HoverParams) -> types.Hover | None:
    return build_hover(
        ls.index,
        params.text_document.uri,
        params.position.line,
        params.position.character,
    )


def _publish_document_diagnostics(ls: ModelableLanguageServer, uri: str) -> None:
    workspace = ls.index.workspace
    if workspace is None:
        ls.publish_diagnostics(uri, [])
        return
    diagnostics = []
    for diagnostic in workspace.errors:
        if diagnostic.path == uri:
            diagnostics.append(diagnostic)
        elif diagnostic.path == "<workspace>":
            diagnostics.append(diagnostic)
    ls.publish_diagnostics(uri, to_lsp_diagnostics(diagnostics))


def main() -> None:
    server.start_io()
