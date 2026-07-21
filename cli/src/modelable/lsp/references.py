from __future__ import annotations

from lsprotocol import types

from modelable.language.dto import LanguageLocation, LanguagePosition, LanguageRange
from modelable.language.references import references as language_references
from modelable.lsp.workspace import LspWorkspaceIndex


def build_references(
    index: LspWorkspaceIndex,
    uri: str,
    line: int,
    character: int,
    include_declaration: bool,
) -> list[types.Location] | None:
    result = language_references(
        index.language,
        uri,
        LanguagePosition(line, character),
        include_declaration,
    )
    if not result:
        return None
    return [to_lsp_location(location) for location in result]


def to_lsp_location(location: LanguageLocation) -> types.Location:
    return types.Location(
        uri=location.uri,
        range=_to_lsp_range(location.range),
    )


def _to_lsp_range(value: LanguageRange) -> types.Range:
    return types.Range(
        start=types.Position(
            line=value.start.line,
            character=value.start.character,
        ),
        end=types.Position(
            line=value.end.line,
            character=value.end.character,
        ),
    )
