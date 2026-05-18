from __future__ import annotations

from lsprotocol import types

from modelable.lsp.workspace import LspWorkspaceIndex


def build_code_actions(
    index: LspWorkspaceIndex,
    uri: str,
    line: int,
    character: int,
    diagnostics: list[types.Diagnostic],
) -> list[types.CodeAction] | None:
    source = index.documents.get(uri)
    workspace = index.workspace
    if source is None or workspace is None:
        return None

    if not _has_parse_eof_diagnostic(diagnostics):
        return None

    if not source.text:
        return None

    lines = source.text.splitlines()
    if not lines:
        return None

    last_line_index = len(lines) - 1
    last_character = len(lines[-1])
    edit = types.WorkspaceEdit(
        changes={
            uri: [
                types.TextEdit(
                    range=types.Range(
                        start=types.Position(line=last_line_index, character=last_character),
                        end=types.Position(line=last_line_index, character=last_character),
                    ),
                    new_text="\n}",
                )
            ]
        }
    )
    return [
        types.CodeAction(
            title="Insert missing closing brace",
            kind=types.CodeActionKind.QuickFix,
            diagnostics=diagnostics,
            is_preferred=True,
            edit=edit,
        )
    ]


def _has_parse_eof_diagnostic(diagnostics: list[types.Diagnostic]) -> bool:
    for diagnostic in diagnostics:
        if diagnostic.code != "PARSE":
            continue
        if "Unexpected end-of-input" in diagnostic.message:
            return True
    return False
