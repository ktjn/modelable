from __future__ import annotations

from lsprotocol import types

from modelable.language.definition import definition as language_definition
from modelable.language.dto import LanguageLocation, LanguagePosition, LanguageRange
from modelable.lsp.workspace import LspWorkspaceIndex


def build_definition(
    index: LspWorkspaceIndex,
    uri: str,
    line: int,
    character: int,
) -> types.Location | list[types.Location] | None:
    result = language_definition(
        index.language,
        uri,
        LanguagePosition(line, character),
    )
    if result is None:
        return None
    return to_lsp_location(result)


def definition_location_for_ref(workspace, ref: str) -> types.Location | None:
    from modelable.language.definition import _definition_for_qualified_ref

    location = _definition_for_qualified_ref(workspace, ref)
    if location is None:
        return None
    return to_lsp_location(location)


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
