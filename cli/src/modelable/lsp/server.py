from __future__ import annotations

import asyncio
import contextlib
import inspect
from pathlib import Path

from lsprotocol import types
from pygls import feature_manager
from pygls.lsp.server import LanguageServer
from pygls.protocol import json_rpc

from modelable.lsp.code_actions import build_code_actions
from modelable.lsp.completion import build_completion
from modelable.lsp.conversation_protocol import PROTOCOL_VERSION
from modelable.lsp.definition import build_definition
from modelable.lsp.diagnostics import to_lsp_diagnostics
from modelable.lsp.document_symbols import build_document_symbols
from modelable.lsp.federation import build_import_diagnostics
from modelable.lsp.folding import build_folding_ranges
from modelable.lsp.formatting import build_document_formatting
from modelable.lsp.highlight import build_document_highlight
from modelable.lsp.hover import build_hover
from modelable.lsp.inlay_hints import build_inlay_hints
from modelable.lsp.references import build_references
from modelable.lsp.rename import build_prepare_rename, build_rename
from modelable.lsp.semantic_tokens import build_semantic_tokens, semantic_tokens_legend
from modelable.lsp.workspace import LspWorkspaceIndex, find_workspace_root, uri_to_path
from modelable.lsp.workspace_symbols import build_workspace_symbols

feature_manager.asyncio.iscoroutinefunction = inspect.iscoroutinefunction
json_rpc.asyncio.iscoroutinefunction = inspect.iscoroutinefunction

_DEBOUNCE_DELAY = 0.2


class ModelableLanguageServer(LanguageServer):
    def __init__(self) -> None:
        super().__init__("modelable-lsp", "0.1.0")
        self.index = LspWorkspaceIndex()
        self._indexes: dict[Path, LspWorkspaceIndex] = {}
        self._debounce_tasks: dict[str, asyncio.Task] = {}
        self._root_uri: str | None = None
        self._scanned_dirs: set[Path] = set()

    def index_for(self, uri: str) -> LspWorkspaceIndex:
        path = uri_to_path(uri)
        if path is not None:
            # Keep index routing stable even when no workspace.mdl exists:
            # use the file's parent directory as the effective root.
            root = find_workspace_root(path) or path.parent
            if root not in self._indexes:
                self._indexes[root] = LspWorkspaceIndex()
            return self._indexes[root]
        return self.index


server = ModelableLanguageServer()


@server.feature(types.INITIALIZE)
def initialize(ls: ModelableLanguageServer, params: types.InitializeParams) -> types.InitializeResult:
    ls._root_uri = params.root_uri
    return _build_initialize_result()


def _build_initialize_result() -> types.InitializeResult:
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
            document_highlight_provider=True,
            folding_range_provider=True,
            inlay_hint_provider=types.InlayHintOptions(resolve_provider=False),
            completion_provider=types.CompletionOptions(
                trigger_characters=["@", "."],
            ),
            workspace=types.WorkspaceOptions(
                workspace_folders=types.WorkspaceFoldersServerCapabilities(
                    supported=True,
                    change_notifications=True,
                )
            ),
            experimental={
                "modelableConversation": {
                    "protocolVersion": PROTOCOL_VERSION,
                }
            },
        )
    )


@server.feature(types.INITIALIZED)
def initialized(ls: ModelableLanguageServer, _params: types.InitializedParams) -> None:
    scan_paths: list[Path] = []
    for folder in (ls.workspace.folders or {}).values():
        folder_path = uri_to_path(folder.uri)
        if folder_path is not None and (folder_path / "workspace.mdl").exists():
            scan_paths.append(folder_path)
    if not scan_paths and ls._root_uri:
        root_path = uri_to_path(ls._root_uri)
        if root_path is not None and (root_path / "workspace.mdl").exists():
            scan_paths.append(root_path)
    loaded_uris: list[str] = []
    for path in scan_paths:
        index = _get_index_for_root(ls, path)
        loaded_uris.extend(_scan_and_load_path(ls, path, index))
    for uri in loaded_uris:
        _publish_document_diagnostics(ls, uri, ls.index_for(uri))


@server.feature(types.WORKSPACE_DID_CHANGE_WATCHED_FILES)
def did_change_watched_files(ls: ModelableLanguageServer, params: types.DidChangeWatchedFilesParams) -> None:
    for change in params.changes:
        uri = change.uri
        index = ls.index_for(uri)
        if change.type == types.FileChangeType.Deleted:
            index.remove_document(uri)
        else:
            path = uri_to_path(uri)
            if path is not None and path.exists():
                with contextlib.suppress(Exception):
                    index.load_background_document(uri, path.read_text(encoding="utf-8"))
        _publish_document_diagnostics(ls, uri, index)


@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
def did_open(ls: ModelableLanguageServer, params: types.DidOpenTextDocumentParams) -> None:
    uri = params.text_document.uri
    path = uri_to_path(uri)
    if path is not None:
        scan_root = find_workspace_root(path) or path.parent
        if scan_root not in ls._scanned_dirs:
            index = _get_index_for_root(ls, scan_root)
            _scan_and_load_path(ls, scan_root, index)
    index = ls.index_for(uri)
    index.upsert_document(uri, params.text_document.text)
    _publish_document_diagnostics(ls, uri, index)


@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
async def did_change(ls: ModelableLanguageServer, params: types.DidChangeTextDocumentParams) -> None:
    document = ls.workspace.get_text_document(params.text_document.uri)
    uri = document.uri
    ls.index_for(uri).upsert_document(uri, document.source)

    existing = ls._debounce_tasks.get(uri)
    if existing is not None and not existing.done():
        existing.cancel()

    async def _delayed_publish() -> None:
        await asyncio.sleep(_DEBOUNCE_DELAY)
        _publish_document_diagnostics(ls, uri, ls.index_for(uri))

    ls._debounce_tasks[uri] = asyncio.ensure_future(_delayed_publish())


@server.feature(types.TEXT_DOCUMENT_DID_CLOSE)
def did_close(ls: ModelableLanguageServer, params: types.DidCloseTextDocumentParams) -> None:
    uri = params.text_document.uri
    existing = ls._debounce_tasks.pop(uri, None)
    if existing is not None and not existing.done():
        existing.cancel()
    ls.index_for(uri).close_document(uri)
    ls.text_document_publish_diagnostics(types.PublishDiagnosticsParams(uri=uri, diagnostics=[]))


@server.feature(types.TEXT_DOCUMENT_HOVER)
def hover(ls: ModelableLanguageServer, params: types.HoverParams) -> types.Hover | None:
    return build_hover(
        ls.index_for(params.text_document.uri),
        params.text_document.uri,
        params.position.line,
        params.position.character,
    )


@server.feature(types.TEXT_DOCUMENT_DEFINITION)
def definition(
    ls: ModelableLanguageServer, params: types.DefinitionParams
) -> types.Location | list[types.Location] | None:
    return build_definition(
        ls.index_for(params.text_document.uri),
        params.text_document.uri,
        params.position.line,
        params.position.character,
    )


@server.feature(types.TEXT_DOCUMENT_REFERENCES)
def references(ls: ModelableLanguageServer, params: types.ReferenceParams) -> list[types.Location] | None:
    return build_references(
        ls.index_for(params.text_document.uri),
        params.text_document.uri,
        params.position.line,
        params.position.character,
        params.context.include_declaration,
    )


@server.feature(types.TEXT_DOCUMENT_COMPLETION)
def completion(ls: ModelableLanguageServer, params: types.CompletionParams) -> types.CompletionList:
    return build_completion(
        ls.index_for(params.text_document.uri),
        params.text_document.uri,
        params.position.line,
        params.position.character,
    )


@server.feature(types.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
def document_symbol(
    ls: ModelableLanguageServer, params: types.DocumentSymbolParams
) -> list[types.DocumentSymbol] | None:
    return build_document_symbols(ls.index_for(params.text_document.uri), params.text_document.uri)


@server.feature(types.WORKSPACE_SYMBOL)
def workspace_symbol(
    ls: ModelableLanguageServer, params: types.WorkspaceSymbolParams
) -> list[types.WorkspaceSymbol] | None:
    results: list[types.WorkspaceSymbol] = []
    seen_roots: set[int] = set()
    for index in [ls.index, *ls._indexes.values()]:
        if id(index) not in seen_roots:
            seen_roots.add(id(index))
            found = build_workspace_symbols(index, params.query)
            if found:
                results.extend(found)
    return results or None


@server.feature(types.TEXT_DOCUMENT_FORMATTING)
def document_formatting(
    ls: ModelableLanguageServer, params: types.DocumentFormattingParams
) -> list[types.TextEdit] | None:
    return build_document_formatting(
        ls.index_for(params.text_document.uri),
        params.text_document.uri,
        params.options.tab_size,
        params.options.insert_spaces,
    )


@server.feature(types.TEXT_DOCUMENT_CODE_ACTION)
def code_action(ls: ModelableLanguageServer, params: types.CodeActionParams) -> list[types.CodeAction] | None:
    return build_code_actions(
        ls.index_for(params.text_document.uri),
        params.text_document.uri,
        params.range.start.line,
        params.range.start.character,
        list(params.context.diagnostics),
    )


@server.feature(types.TEXT_DOCUMENT_SEMANTIC_TOKENS_FULL)
def semantic_tokens_full(
    ls: ModelableLanguageServer, params: types.SemanticTokensParams
) -> types.SemanticTokens | None:
    source = ls.index_for(params.text_document.uri).documents.get(params.text_document.uri)
    if source is None:
        return types.SemanticTokens(data=[])
    return build_semantic_tokens(source.text)


@server.feature(types.TEXT_DOCUMENT_PREPARE_RENAME)
def prepare_rename(ls: ModelableLanguageServer, params: types.PrepareRenameParams) -> types.Range | None:
    return build_prepare_rename(
        ls.index_for(params.text_document.uri),
        params.text_document.uri,
        params.position.line,
        params.position.character,
    )


@server.feature(types.TEXT_DOCUMENT_RENAME)
def rename(ls: ModelableLanguageServer, params: types.RenameParams) -> types.WorkspaceEdit | None:
    return build_rename(
        ls.index_for(params.text_document.uri),
        params.text_document.uri,
        params.position.line,
        params.position.character,
        params.new_name,
    )


@server.feature(types.TEXT_DOCUMENT_DOCUMENT_HIGHLIGHT)
def document_highlight(
    ls: ModelableLanguageServer, params: types.DocumentHighlightParams
) -> list[types.DocumentHighlight] | None:
    return build_document_highlight(
        ls.index_for(params.text_document.uri),
        params.text_document.uri,
        params.position.line,
        params.position.character,
    )


@server.feature(types.TEXT_DOCUMENT_FOLDING_RANGE)
def folding_range(ls: ModelableLanguageServer, params: types.FoldingRangeParams) -> list[types.FoldingRange] | None:
    return build_folding_ranges(ls.index_for(params.text_document.uri), params.text_document.uri)


@server.feature(types.TEXT_DOCUMENT_INLAY_HINT)
def inlay_hint(ls: ModelableLanguageServer, params: types.InlayHintParams) -> list[types.InlayHint] | None:
    return build_inlay_hints(ls.index_for(params.text_document.uri), params.text_document.uri, params.range)


def _get_index_for_root(ls: ModelableLanguageServer, root: Path) -> LspWorkspaceIndex:
    if root not in ls._indexes:
        ls._indexes[root] = LspWorkspaceIndex()
    return ls._indexes[root]


def _scan_and_load_path(ls: ModelableLanguageServer, folder_path: Path, index: LspWorkspaceIndex) -> list[str]:
    ls._scanned_dirs.add(folder_path)
    loaded: list[str] = []
    for mdl_file in sorted(folder_path.rglob("*.mdl")):
        file_uri = mdl_file.as_uri()
        ls._scanned_dirs.add(mdl_file.parent)
        try:
            index.load_background_document(file_uri, mdl_file.read_text(encoding="utf-8"))
            loaded.append(file_uri)
        except Exception:
            pass
    return loaded


def _publish_document_diagnostics(ls: ModelableLanguageServer, uri: str, index: LspWorkspaceIndex) -> None:
    workspace = index.workspace
    if workspace is None:
        ls.text_document_publish_diagnostics(types.PublishDiagnosticsParams(uri=uri, diagnostics=[]))
        return
    diagnostics = []
    for diagnostic in workspace.errors:
        if diagnostic.path == uri or diagnostic.path == "<workspace>":
            diagnostics.append(diagnostic)
    diagnostics.extend(build_import_diagnostics(index, uri))
    ls.text_document_publish_diagnostics(
        types.PublishDiagnosticsParams(uri=uri, diagnostics=to_lsp_diagnostics(diagnostics))
    )


def main() -> None:
    server.start_io()
