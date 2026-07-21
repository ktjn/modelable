from __future__ import annotations

from lsprotocol import types

from modelable.language.dto import LanguagePosition
from modelable.language.rename import InvalidRenameError
from modelable.language.rename import prepare_rename as language_prepare_rename
from modelable.language.rename import rename as language_rename
from modelable.lsp.workspace import LspWorkspaceIndex


def build_prepare_rename(
    index: LspWorkspaceIndex,
    uri: str,
    line: int,
    character: int,
) -> types.Range | None:
    result = language_prepare_rename(
        index.language,
        uri,
        LanguagePosition(line, character),
    )
    if result is None:
        return None
    return types.Range(
        start=types.Position(line=result.range.start.line, character=result.range.start.character),
        end=types.Position(line=result.range.end.line, character=result.range.end.character),
    )


def build_rename(
    index: LspWorkspaceIndex,
    uri: str,
    line: int,
    character: int,
    new_name: str,
) -> types.WorkspaceEdit | None:
    try:
        result = language_rename(
            index.language,
            uri,
            LanguagePosition(line, character),
            new_name,
        )
    except InvalidRenameError:
        return None

    changes: dict[str, list[types.TextEdit]] = {}
    for edit in result.edits:
        changes.setdefault(edit.uri, []).append(
            types.TextEdit(
                range=types.Range(
                    start=types.Position(line=edit.range.start.line, character=edit.range.start.character),
                    end=types.Position(line=edit.range.end.line, character=edit.range.end.character),
                ),
                new_text=edit.new_text,
            )
        )

    if not changes:
        return None
    return types.WorkspaceEdit(changes=changes)
