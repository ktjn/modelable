from __future__ import annotations

from lsprotocol import types

from modelable.language.dto import (
    LanguageHover,
    LanguagePosition,
    LanguageRange,
)
from modelable.language.hover import hover as language_hover
from modelable.lsp.workspace import LspWorkspaceIndex


def build_hover(
    index: LspWorkspaceIndex,
    uri: str,
    line: int,
    character: int,
) -> types.Hover | None:
    result = language_hover(
        index.language,
        uri,
        LanguagePosition(line, character),
    )
    if result is None:
        return None
    return to_lsp_hover(result)


def to_lsp_hover(result: LanguageHover) -> types.Hover:
    return types.Hover(
        contents=types.MarkupContent(
            kind=types.MarkupKind.Markdown,
            value=result.markdown,
        ),
        range=_to_lsp_range(result.range) if result.range is not None else None,
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
