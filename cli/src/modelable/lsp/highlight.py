from __future__ import annotations

from lsprotocol import types

from modelable.lsp.references import build_references
from modelable.lsp.workspace import LspWorkspaceIndex


def build_document_highlight(
    index: LspWorkspaceIndex,
    uri: str,
    line: int,
    character: int,
) -> list[types.DocumentHighlight] | None:
    all_refs = build_references(index, uri, line, character, include_declaration=True)
    if all_refs is None:
        return None

    usage_refs = build_references(index, uri, line, character, include_declaration=False) or []
    usage_keys = {
        (loc.range.start.line, loc.range.start.character)
        for loc in usage_refs
        if loc.uri == uri
    }

    highlights: list[types.DocumentHighlight] = []
    for loc in all_refs:
        if loc.uri != uri:
            continue
        key = (loc.range.start.line, loc.range.start.character)
        kind = types.DocumentHighlightKind.Read if key in usage_keys else types.DocumentHighlightKind.Write
        highlights.append(types.DocumentHighlight(range=loc.range, kind=kind))

    return highlights if highlights else None
