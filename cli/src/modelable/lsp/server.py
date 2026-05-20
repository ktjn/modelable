from __future__ import annotations

from pygls.lsp.server import LanguageServer
from lsprotocol import types

from modelable.lsp.completion import build_completion
from modelable.lsp.code_actions import build_code_actions
from modelable.lsp.federation import build_import_diagnostics
from modelable.lsp.document_symbols import build_document_symbols
from modelable.lsp.definition import build_definition
from modelable.lsp.diagnostics import to_lsp_diagnostics
from modelable.lsp.formatting import build_document_formatting
from modelable.lsp.hover import build_hover
from modelable.lsp.references import build_references
from modelable.lsp.semantic_tokens import build_semantic_tokens, semantic_tokens_legend
from modelable.lsp.rename import build_prepare_rename, build_rename
from modelable.lsp.workspace_symbols import build_workspace_symbols
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
            definition_provider=True,
            references_provider=True,
            document_symbol_provider=True,
            workspace_symbol_provider=types.WorkspaceSymbolOptions(resolve_provider=False),
            document_formatting_provider=True,
            code_action_provider=types.CodeActionOptions(
                code_action_kinds=[types.CodeActionKind.QuickFix],
                resolve_provider=False,
            ),
            rename_provider=types.RenameOptions(prepare_provider=True),
            semantic_tokens_provider=types.SemanticTokensOptions(
                legend=semantic_tokens_legend(),
                full=True,
                range=False,
            ),
            completion_provider=types.CompletionOptions(
                trigger_characters=["@", "."],
            ),
            workspace=types.WorkspaceOptions(
                workspace_folders=types.WorkspaceFoldersServerCapabilities(
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
    ls.text_document_publish_diagnostics(
        types.PublishDiagnosticsParams(uri=params.text_document.uri, diagnostics=[])
    )


@server.feature(types.TEXT_DOCUMENT_HOVER)
def hover(ls: ModelableLanguageServer, params: types.HoverParams) -> types.Hover | None:
    return build_hover(
        ls.index,
        params.text_document.uri,
        params.position.line,
        params.position.character,
    )


@server.feature(types.TEXT_DOCUMENT_DEFINITION)
def definition(
    ls: ModelableLanguageServer, params: types.DefinitionParams
) -> types.Location | list[types.Location] | None:
    return build_definition(
        ls.index,
        params.text_document.uri,
        params.position.line,
        params.position.character,
    )


@server.feature(types.TEXT_DOCUMENT_REFERENCES)
def references(
    ls: ModelableLanguageServer, params: types.ReferenceParams
) -> list[types.Location] | None:
    return build_references(
        ls.index,
        params.text_document.uri,
        params.position.line,
        params.position.character,
        params.context.include_declaration,
    )


@server.feature(types.TEXT_DOCUMENT_COMPLETION)
def completion(
    ls: ModelableLanguageServer, params: types.CompletionParams
) -> types.CompletionList:
    return build_completion(
        ls.index,
        params.text_document.uri,
        params.position.line,
        params.position.character,
    )


@server.feature(types.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
def document_symbol(
    ls: ModelableLanguageServer, params: types.DocumentSymbolParams
) -> list[types.DocumentSymbol] | None:
    return build_document_symbols(ls.index, params.text_document.uri)


@server.feature(types.WORKSPACE_SYMBOL)
def workspace_symbol(
    ls: ModelableLanguageServer, params: types.WorkspaceSymbolParams
) -> list[types.WorkspaceSymbol] | None:
    return build_workspace_symbols(ls.index, params.query)


@server.feature(types.TEXT_DOCUMENT_FORMATTING)
def document_formatting(
    ls: ModelableLanguageServer, params: types.DocumentFormattingParams
) -> list[types.TextEdit] | None:
    return build_document_formatting(
        ls.index,
        params.text_document.uri,
        params.options.tab_size,
        params.options.insert_spaces,
    )


@server.feature(types.TEXT_DOCUMENT_CODE_ACTION)
def code_action(
    ls: ModelableLanguageServer, params: types.CodeActionParams
) -> list[types.CodeAction] | None:
    return build_code_actions(
        ls.index,
        params.text_document.uri,
        params.range.start.line,
        params.range.start.character,
        list(params.context.diagnostics),
    )


@server.feature(types.TEXT_DOCUMENT_SEMANTIC_TOKENS_FULL)
def semantic_tokens_full(
    ls: ModelableLanguageServer, params: types.SemanticTokensParams
) -> types.SemanticTokens | None:
    source = ls.index.documents.get(params.text_document.uri)
    if source is None:
        return types.SemanticTokens(data=[])
    return build_semantic_tokens(source.text)


@server.feature(types.TEXT_DOCUMENT_PREPARE_RENAME)
def prepare_rename(
    ls: ModelableLanguageServer, params: types.PrepareRenameParams
) -> types.Range | None:
    return build_prepare_rename(
        ls.index,
        params.text_document.uri,
        params.position.line,
        params.position.character,
    )


@server.feature(types.TEXT_DOCUMENT_RENAME)
def rename(
    ls: ModelableLanguageServer, params: types.RenameParams
) -> types.WorkspaceEdit | None:
    return build_rename(
        ls.index,
        params.text_document.uri,
        params.position.line,
        params.position.character,
        params.new_name,
    )


def _publish_document_diagnostics(ls: ModelableLanguageServer, uri: str) -> None:
    workspace = ls.index.workspace
    if workspace is None:
        ls.text_document_publish_diagnostics(
            types.PublishDiagnosticsParams(uri=uri, diagnostics=[])
        )
        return
    diagnostics = []
    for diagnostic in workspace.errors:
        if diagnostic.path == uri:
            diagnostics.append(diagnostic)
        elif diagnostic.path == "<workspace>":
            diagnostics.append(diagnostic)
    diagnostics.extend(build_import_diagnostics(ls.index, uri))
    ls.text_document_publish_diagnostics(
        types.PublishDiagnosticsParams(uri=uri, diagnostics=to_lsp_diagnostics(diagnostics))
    )


def main() -> None:
    server.start_io()
