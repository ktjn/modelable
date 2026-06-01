from __future__ import annotations

import re

from lsprotocol import types

from modelable.lsp.workspace import LspWorkspaceIndex

_DECL_PATTERN = re.compile(
    r"^\s*(?P<kind>entity|aggregate|event|value|projection)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*@\s*(?P<version>\d+)"
)
_MODEL_WITHOUT_VERSION_PATTERN = re.compile(
    r"^\s*(?P<kind>entity|aggregate|event|value)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\{"
)
_FIELD_PATTERN = re.compile(
    r"^\s*(?:@[A-Za-z_][A-Za-z0-9_]*(?:\([^)]*\))?\s+)*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\??\s*:"
)


def build_code_actions(
    index: LspWorkspaceIndex,
    uri: str,
    line: int,
    character: int,
    diagnostics: list[types.Diagnostic],
) -> list[types.CodeAction] | None:
    source = index.documents.get(uri)
    if source is None:
        return None

    if not source.text:
        return None

    if _has_parse_eof_diagnostic(diagnostics):
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

    if _has_missing_key_diagnostic(diagnostics):
        return _missing_key_action(source.text, uri, diagnostics)

    if _has_missing_owner_diagnostic(diagnostics):
        return _missing_owner_action(source.text, uri, diagnostics)

    if _has_missing_version_diagnostic(diagnostics):
        return _missing_version_action(source.text, uri, diagnostics)

    return None


def _has_parse_eof_diagnostic(diagnostics: list[types.Diagnostic]) -> bool:
    for diagnostic in diagnostics:
        if diagnostic.code != "PARSE":
            continue
        if "Unexpected end-of-input" in diagnostic.message:
            return True
    return False


def _has_missing_key_diagnostic(diagnostics: list[types.Diagnostic]) -> bool:
    return any(
        diagnostic.code == "SEM" and "must have exactly one @key field" in diagnostic.message
        for diagnostic in diagnostics
    )


def _has_missing_owner_diagnostic(diagnostics: list[types.Diagnostic]) -> bool:
    return any(
        diagnostic.code == "SEM" and "must have an owner attribute" in diagnostic.message
        for diagnostic in diagnostics
    )


def _has_missing_version_diagnostic(diagnostics: list[types.Diagnostic]) -> bool:
    return any(
        diagnostic.code == "SEM" and "must have a version header" in diagnostic.message
        for diagnostic in diagnostics
    )


def _missing_key_action(
    text: str, uri: str, diagnostics: list[types.Diagnostic]
) -> list[types.CodeAction] | None:
    lines = text.splitlines()
    in_model = False
    for line_no, line in enumerate(lines):
        if _DECL_PATTERN.match(line):
            in_model = True
            continue
        if not in_model:
            continue
        field_match = _FIELD_PATTERN.match(line)
        if field_match is None:
            if line.strip() == "}":
                in_model = False
            continue

        insert_at = field_match.start("name")
        edit = types.WorkspaceEdit(
            changes={
                uri: [
                    types.TextEdit(
                        range=types.Range(
                            start=types.Position(line=line_no, character=insert_at),
                            end=types.Position(line=line_no, character=insert_at),
                        ),
                        new_text="@key ",
                    )
                ]
            }
        )
        return [
            types.CodeAction(
                title="Insert @key annotation",
                kind=types.CodeActionKind.QuickFix,
                diagnostics=diagnostics,
                is_preferred=True,
                edit=edit,
            )
        ]

    return None


def _missing_owner_action(
    text: str, uri: str, diagnostics: list[types.Diagnostic]
) -> list[types.CodeAction] | None:
    lines = text.splitlines()
    for line_no, line in enumerate(lines):
        if "domain" in line and "{" in line:
            # Insert owner right after the opening brace
            indent = "  "
            if line_no + 1 < len(lines):
                next_line = lines[line_no + 1]
                if next_line.strip():
                    indent = next_line[: len(next_line) - len(next_line.lstrip())]

            edit = types.WorkspaceEdit(
                changes={
                    uri: [
                        types.TextEdit(
                            range=types.Range(
                                start=types.Position(line=line_no + 1, character=0),
                                end=types.Position(line=line_no + 1, character=0),
                            ),
                            new_text=f'{indent}owner: "required-team"\n',
                        )
                    ]
                }
            )
            return [
                types.CodeAction(
                    title='Insert owner: "required-team"',
                    kind=types.CodeActionKind.QuickFix,
                    diagnostics=diagnostics,
                    is_preferred=True,
                    edit=edit,
                )
            ]
    return None


def _missing_version_action(
    text: str, uri: str, diagnostics: list[types.Diagnostic]
) -> list[types.CodeAction] | None:
    lines = text.splitlines()
    for line_no, line in enumerate(lines):
        match = _MODEL_WITHOUT_VERSION_PATTERN.match(line)
        if match:
            # Insert @ 1 (additive) before the brace
            opening_brace_at = line.find("{")
            edit = types.WorkspaceEdit(
                changes={
                    uri: [
                        types.TextEdit(
                            range=types.Range(
                                start=types.Position(line=line_no, character=opening_brace_at),
                                end=types.Position(line=line_no, character=opening_brace_at),
                            ),
                            new_text="@ 1 (additive) ",
                        )
                    ]
                }
            )
            return [
                types.CodeAction(
                    title="Insert @ 1 (additive)",
                    kind=types.CodeActionKind.QuickFix,
                    diagnostics=diagnostics,
                    is_preferred=True,
                    edit=edit,
                )
            ]
    return None
