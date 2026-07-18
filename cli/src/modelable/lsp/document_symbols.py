from __future__ import annotations

import re

from lsprotocol import types

from modelable.lsp.workspace import LspWorkspaceIndex

_DOMAIN_PATTERN = re.compile(r'^\s*domain\s+(?:"(?P<quoted>[^"]+)"|(?P<name>[A-Za-z_][A-Za-z0-9_]*))')
_DECL_PATTERN = re.compile(
    r"^\s*(?P<kind>entity|aggregate|event|value|projection)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*@\s*(?P<version>\d+)"
)
_FIELD_PATTERN = re.compile(r"^\s*(?:@[A-Za-z_][A-Za-z0-9_]*(?:\([^)]*\))?\s+)*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\??\s*:")
_PROJECTION_FIELD_PATTERN = re.compile(
    r"^\s*(?:@[A-Za-z_][A-Za-z0-9_]*(?:\([^)]*\))?\s+)*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:<-|=)"
)


def build_document_symbols(
    index: LspWorkspaceIndex,
    uri: str,
) -> list[types.DocumentSymbol] | None:
    source = index.documents.get(uri)
    if source is None or index.workspace is None:
        return None

    lines = source.text.splitlines()
    symbols: list[types.DocumentSymbol] = []
    current_domain: types.DocumentSymbol | None = None
    current_decl: types.DocumentSymbol | None = None
    current_domain_name: str | None = None
    current_decl_name: str | None = None
    current_decl_kind: str | None = None
    current_decl_version: int | None = None

    for line_no, line in enumerate(lines):
        domain_match = _DOMAIN_PATTERN.match(line)
        if domain_match:
            current_domain_name = domain_match.group("quoted") or domain_match.group("name")
            current_domain = _make_domain_symbol(
                lines,
                line_no,
                current_domain_name,
            )
            symbols.append(current_domain)
            current_decl = None
            current_decl_name = None
            current_decl_kind = None
            current_decl_version = None
            continue

        decl_match = _DECL_PATTERN.match(line)
        if decl_match and current_domain is not None and current_domain_name is not None:
            current_decl_name = decl_match.group("name")
            current_decl_kind = decl_match.group("kind")
            current_decl_version = int(decl_match.group("version"))
            current_decl = _make_decl_symbol(
                lines,
                line_no,
                current_domain_name,
                current_decl_kind,
                current_decl_name,
                current_decl_version,
            )
            if current_domain.children is None:
                current_domain.children = [current_decl]
            else:
                current_domain.children = [*current_domain.children, current_decl]
            continue

        if current_decl is None:
            continue

        field_match = _FIELD_PATTERN.match(line) or _PROJECTION_FIELD_PATTERN.match(line)
        if field_match:
            field_symbol = _make_field_symbol(
                line_no,
                field_match.start("name"),
                field_match.end("name"),
                field_match.group("name"),
                line,
            )
            if current_decl.children is None:
                current_decl.children = [field_symbol]
            else:
                current_decl.children = [*current_decl.children, field_symbol]

    return symbols


def find_focused_ref(
    index: LspWorkspaceIndex,
    uri: str,
    line: int,
    character: int,
) -> str | None:
    symbols = build_document_symbols(index, uri) or []
    position = types.Position(line=line, character=character)
    for domain in symbols:
        for declaration in domain.children or []:
            if not _position_in_range(position, declaration.range):
                continue
            detail = declaration.detail or ""
            _, separator, version_text = detail.partition("@")
            if not separator or not version_text.strip().isdigit():
                return None
            return f"{domain.name}.{declaration.name}@{int(version_text.strip())}"
    return None


def _position_in_range(position: types.Position, range_: types.Range) -> bool:
    start = (range_.start.line, range_.start.character)
    current = (position.line, position.character)
    end = (range_.end.line, range_.end.character)
    return start <= current <= end


def _make_domain_symbol(
    lines: list[str],
    line_no: int,
    name: str,
) -> types.DocumentSymbol:
    return types.DocumentSymbol(
        name=name,
        kind=types.SymbolKind.Module,
        detail="domain",
        range=types.Range(
            start=types.Position(line=line_no, character=0),
            end=types.Position(
                line=_block_end_line(lines, line_no), character=len(lines[_block_end_line(lines, line_no)])
            ),
        ),
        selection_range=types.Range(
            start=types.Position(line=line_no, character=_domain_name_start(lines[line_no])),
            end=types.Position(line=line_no, character=_domain_name_end(lines[line_no])),
        ),
    )


def _make_decl_symbol(
    lines: list[str],
    line_no: int,
    domain_name: str,
    kind: str,
    name: str,
    version: int,
) -> types.DocumentSymbol:
    detail = f"{kind} @{version}"
    return types.DocumentSymbol(
        name=name,
        kind=types.SymbolKind.Class,
        detail=detail,
        range=types.Range(
            start=types.Position(line=line_no, character=0),
            end=types.Position(
                line=_block_end_line(lines, line_no), character=len(lines[_block_end_line(lines, line_no)])
            ),
        ),
        selection_range=types.Range(
            start=types.Position(line=line_no, character=_decl_name_start(lines[line_no])),
            end=types.Position(line=line_no, character=_decl_name_end(lines[line_no])),
        ),
    )


def _make_field_symbol(
    line_no: int,
    start: int,
    end: int,
    name: str,
    line: str,
) -> types.DocumentSymbol:
    return types.DocumentSymbol(
        name=name,
        kind=types.SymbolKind.Field,
        detail=line.strip(),
        range=types.Range(
            start=types.Position(line=line_no, character=0),
            end=types.Position(line=line_no, character=len(line)),
        ),
        selection_range=types.Range(
            start=types.Position(line=line_no, character=start),
            end=types.Position(line=line_no, character=end),
        ),
    )


def _block_end_line(lines: list[str], start_line: int) -> int:
    depth = 0
    for line_no in range(start_line, len(lines)):
        depth += lines[line_no].count("{")
        depth -= lines[line_no].count("}")
        if line_no > start_line and depth <= 0:
            return line_no
    return max(len(lines) - 1, start_line)


def _domain_name_start(line: str) -> int:
    match = _DOMAIN_PATTERN.match(line)
    if match is None:
        return 0
    return match.start("quoted") if match.group("quoted") is not None else match.start("name")


def _domain_name_end(line: str) -> int:
    match = _DOMAIN_PATTERN.match(line)
    if match is None:
        return 0
    return match.end("quoted") if match.group("quoted") is not None else match.end("name")


def _decl_name_start(line: str) -> int:
    match = _DECL_PATTERN.match(line)
    if match is None:
        return 0
    return match.start("name")


def _decl_name_end(line: str) -> int:
    match = _DECL_PATTERN.match(line)
    if match is None:
        return 0
    return match.end("name")
