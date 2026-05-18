from __future__ import annotations

from lsprotocol import types

from modelable.lsp.workspace import LspWorkspaceIndex


def build_document_formatting(
    index: LspWorkspaceIndex,
    uri: str,
    tab_size: int,
    insert_spaces: bool,
) -> list[types.TextEdit] | None:
    source = index.documents.get(uri)
    if source is None:
        return None

    formatted = _format_text(source.text, tab_size=max(tab_size, 1), insert_spaces=insert_spaces)
    if formatted == source.text:
        return []

    source_lines = source.text.splitlines()
    line_count = max(len(source_lines), 1)
    end_line = line_count - 1
    end_character = len(source_lines[-1]) if source_lines else 0
    return [
        types.TextEdit(
            range=types.Range(
                start=types.Position(line=0, character=0),
                end=types.Position(line=end_line, character=end_character),
            ),
            new_text=formatted,
        )
    ]


def _format_text(text: str, tab_size: int, insert_spaces: bool) -> str:
    had_trailing_newline = text.endswith("\n")
    lines = text.splitlines()
    if not lines:
        return text

    indent_unit = " " * tab_size if insert_spaces else "\t"
    depth = 0
    formatted_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            formatted_lines.append("")
            continue

        leading_close = stripped.startswith("}")
        indent_depth = max(depth - 1, 0) if leading_close else depth
        formatted_lines.append(f"{indent_unit * indent_depth}{stripped}")

        open_count = stripped.count("{")
        close_count = stripped.count("}")
        depth = max(depth + open_count - close_count, 0)

    formatted = "\n".join(formatted_lines)
    if had_trailing_newline:
        formatted += "\n"
    return formatted
