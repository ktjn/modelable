from __future__ import annotations

from dataclasses import dataclass

from lsprotocol import types

from modelable.lsp.document_symbols import build_document_symbols
from modelable.lsp.workspace import LspWorkspaceIndex


@dataclass(frozen=True)
class _WorkspaceSymbolEntry:
    name: str
    kind: types.SymbolKind
    uri: str
    start_line: int
    start_character: int
    end_line: int
    end_character: int
    container_name: str | None


def build_workspace_symbols(
    index: LspWorkspaceIndex,
    query: str,
) -> list[types.WorkspaceSymbol] | None:
    workspace = index.workspace
    if workspace is None:
        return None

    entries: list[_WorkspaceSymbolEntry] = []
    lowered_query = query.strip().lower()

    for source in workspace.sources:
        symbols = build_document_symbols(index, source.uri)
        if not symbols:
            continue
        entries.extend(_flatten_symbols(source.uri, symbols))

    filtered = [
        entry
        for entry in entries
        if not lowered_query
        or lowered_query in entry.name.lower()
        or (entry.container_name is not None and lowered_query in entry.container_name.lower())
    ]
    filtered.sort(key=lambda item: (item.name.lower(), item.container_name or "", item.uri))
    return [
        types.WorkspaceSymbol(
            name=entry.name,
            kind=entry.kind,
            location=types.Location(
                uri=entry.uri,
                range=types.Range(
                    start=types.Position(line=entry.start_line, character=entry.start_character),
                    end=types.Position(line=entry.end_line, character=entry.end_character),
                ),
            ),
            container_name=entry.container_name,
        )
        for entry in filtered
    ]


def _flatten_symbols(uri: str, symbols: list[types.DocumentSymbol]) -> list[_WorkspaceSymbolEntry]:
    entries: list[_WorkspaceSymbolEntry] = []
    for symbol in symbols:
        entries.append(
            _WorkspaceSymbolEntry(
                name=symbol.name,
                kind=symbol.kind,
                uri=uri,
                start_line=symbol.selection_range.start.line,
                start_character=symbol.selection_range.start.character,
                end_line=symbol.selection_range.end.line,
                end_character=symbol.selection_range.end.character,
                container_name=None,
            )
        )
        for child in symbol.children or []:
            entries.extend(_flatten_child(uri, symbol.name, child))
    return entries


def _flatten_child(
    uri: str,
    container_name: str,
    symbol: types.DocumentSymbol,
) -> list[_WorkspaceSymbolEntry]:
    entries = [
        _WorkspaceSymbolEntry(
            name=symbol.name,
            kind=symbol.kind,
            uri=uri,
            start_line=symbol.selection_range.start.line,
            start_character=symbol.selection_range.start.character,
            end_line=symbol.selection_range.end.line,
            end_character=symbol.selection_range.end.character,
            container_name=container_name,
        )
    ]
    for child in symbol.children or []:
        entries.extend(_flatten_child(uri, symbol.name, child))
    return entries

