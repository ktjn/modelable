from __future__ import annotations

from lsprotocol import types

from modelable.language.dto import LanguagePosition
from modelable.language.references import references as language_references
from modelable.lsp.workspace import LspWorkspaceIndex


def build_document_highlight(
    index: LspWorkspaceIndex,
    uri: str,
    line: int,
    character: int,
) -> list[types.DocumentHighlight] | None:
    position = LanguagePosition(line, character)
    all_refs = language_references(index.language, uri, position, include_declaration=True)
    if not all_refs:
        return None

    usage_refs = language_references(index.language, uri, position, include_declaration=False)
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
        highlights.append(
            types.DocumentHighlight(
                range=types.Range(
                    start=types.Position(
                        line=loc.range.start.line,
                        character=loc.range.start.character,
                    ),
                    end=types.Position(
                        line=loc.range.end.line,
                        character=loc.range.end.character,
                    ),
                ),
                kind=kind,
            )
        )

    return highlights if highlights else None
