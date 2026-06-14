from __future__ import annotations

import re
from dataclasses import dataclass

from lsprotocol import types

_TOKEN_TYPES = [
    types.SemanticTokenTypes.Namespace.value,
    types.SemanticTokenTypes.Class.value,
    types.SemanticTokenTypes.Property.value,
    types.SemanticTokenTypes.Parameter.value,
    types.SemanticTokenTypes.Variable.value,
    types.SemanticTokenTypes.Type.value,
    types.SemanticTokenTypes.Keyword.value,
    types.SemanticTokenTypes.Decorator.value,
    types.SemanticTokenTypes.Comment.value,
    types.SemanticTokenTypes.String.value,
    types.SemanticTokenTypes.Number.value,
    types.SemanticTokenTypes.Operator.value,
]

_KEYWORDS = {
    "access",
    "additive",
    "aggregate",
    "ai",
    "as",
    "asyncapi",
    "binding",
    "by",
    "cardinality",
    "clickhouse",
    "contact",
    "consumer",
    "description",
    "derive",
    "docs",
    "domain",
    "entity",
    "event",
    "exclude",
    "from",
    "generate",
    "group",
    "internal",
    "join",
    "left",
    "materialisation",
    "mysql",
    "on",
    "openapi",
    "owner",
    "peers",
    "pii",
    "postgres",
    "project",
    "projection",
    "property",
    "protobuf",
    "read",
    "redact",
    "registry",
    "restricted",
    "sql",
    "sqlite",
    "string",
    "subscribe",
    "subscription",
    "transfer",
    "typescript",
    "value",
    "where",
    "workspace",
    "write",
    "jsonschema",
}
_TYPE_WORDS = {
    "array",
    "binary",
    "bool",
    "date",
    "decimal",
    "duration",
    "enum",
    "float",
    "int",
    "map",
    "object",
    "ref",
    "time",
    "timestamp",
    "uuid",
}

_ANNOTATION_PATTERN = re.compile(r"@[A-Za-z_][A-Za-z0-9_-]*")
_WORD_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
_NUMBER_PATTERN = re.compile(r"\d+")
_DOMAIN_DECL_PATTERN = re.compile(r"^\s*domain\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)")
_DECL_PATTERN = re.compile(
    r"^\s*(?P<kind>entity|aggregate|event|value|projection)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*@\s*(?P<version>\d+)"
)
_FIELD_PATTERN = re.compile(
    r"^\s*(?:@[A-Za-z_][A-Za-z0-9_-]*(?:\([^)]*\))?\s+)*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\??\s*:"
)
_PROJECTION_FIELD_PATTERN = re.compile(
    r"^\s*(?:@[A-Za-z_][A-Za-z0-9_-]*(?:\([^)]*\))?\s+)*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?P<op><-|=)"
)
_SOURCE_PATTERN = re.compile(
    r"^\s*(?P<join_prefix>left\s+)?(?P<kind>from|join)\s+"
    r"(?P<domain>[A-Za-z_][A-Za-z0-9_.-]*)\.(?P<model>[A-Za-z_][A-Za-z0-9_.-]*)\s*@\s*"
    r"(?P<version>\d+)\s+as\s+(?P<alias>[A-Za-z_][A-Za-z0-9_]*)"
)
_IMPORT_PINNED_PATTERN = re.compile(
    r"^\s*import\s+domain\s+(?P<import_domain>[A-Za-z_][A-Za-z0-9_.-]*)\s+"
    r"from\s+registry\s+\"[^\"]*\"\s+at\s+"
    r"(?P<domain>[A-Za-z_][A-Za-z0-9_.-]*)\.(?P<model>[A-Za-z_][A-Za-z0-9_.-]*)\s*@\s*"
    r"(?P<version>\d+)"
)
_IMPORT_DOMAIN_PATTERN = re.compile(
    r"^\s*import\s+domain\s+(?P<import_domain>[A-Za-z_][A-Za-z0-9_.-]*)"
)
_ALIASED_REFERENCE_PATTERN = re.compile(
    r"(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\.(?P<field>[A-Za-z_][A-Za-z0-9_]*)"
)


@dataclass(frozen=True)
class _Token:
    line: int
    start: int
    length: int
    token_type: str
    token_modifiers: int = 0


def semantic_tokens_legend() -> types.SemanticTokensLegend:
    return types.SemanticTokensLegend(token_types=_TOKEN_TYPES, token_modifiers=[])


def build_semantic_tokens(text: str) -> types.SemanticTokens:
    tokens: list[_Token] = []
    for line_no, line in enumerate(text.splitlines()):
        spans = _lex_line_spans(line)
        _add_line_tokens(tokens, line_no, line, spans)
        _add_span_tokens(tokens, line_no, spans)
    return types.SemanticTokens(data=_encode_tokens(_dedupe_tokens(tokens)))


def _add_line_tokens(tokens: list[_Token], line_no: int, line: str, spans: list[tuple[int, int, str]]) -> None:
    _add_match_token(tokens, line_no, line, _DOMAIN_DECL_PATTERN, "name", types.SemanticTokenTypes.Namespace.value)
    _add_match_token(tokens, line_no, line, _DECL_PATTERN, "kind", types.SemanticTokenTypes.Keyword.value)
    _add_match_token(tokens, line_no, line, _DECL_PATTERN, "name", types.SemanticTokenTypes.Class.value)
    _add_match_token(tokens, line_no, line, _DECL_PATTERN, "version", types.SemanticTokenTypes.Number.value)
    _add_match_token(tokens, line_no, line, _FIELD_PATTERN, "name", types.SemanticTokenTypes.Property.value)
    _add_match_token(
        tokens,
        line_no,
        line,
        _PROJECTION_FIELD_PATTERN,
        "name",
        types.SemanticTokenTypes.Property.value,
    )
    _add_match_token(
        tokens,
        line_no,
        line,
        _PROJECTION_FIELD_PATTERN,
        "op",
        types.SemanticTokenTypes.Operator.value,
    )
    _add_match_token(tokens, line_no, line, _SOURCE_PATTERN, "kind", types.SemanticTokenTypes.Keyword.value)
    _add_match_token(tokens, line_no, line, _SOURCE_PATTERN, "version", types.SemanticTokenTypes.Number.value)
    _add_match_token(tokens, line_no, line, _SOURCE_PATTERN, "alias", types.SemanticTokenTypes.Parameter.value)
    _add_dotted_reference_token(tokens, line_no, line, _SOURCE_PATTERN, "domain", types.SemanticTokenTypes.Namespace.value)
    _add_dotted_reference_token(tokens, line_no, line, _SOURCE_PATTERN, "model", types.SemanticTokenTypes.Class.value)
    _add_match_token(
        tokens,
        line_no,
        line,
        _IMPORT_DOMAIN_PATTERN,
        "import_domain",
        types.SemanticTokenTypes.Namespace.value,
    )
    _add_dotted_reference_token(
        tokens,
        line_no,
        line,
        _IMPORT_PINNED_PATTERN,
        "domain",
        types.SemanticTokenTypes.Namespace.value,
    )
    _add_dotted_reference_token(
        tokens,
        line_no,
        line,
        _IMPORT_PINNED_PATTERN,
        "model",
        types.SemanticTokenTypes.Class.value,
    )
    _add_match_token(tokens, line_no, line, _IMPORT_PINNED_PATTERN, "version", types.SemanticTokenTypes.Number.value)

    if "<-" in line or "=" in line:
        for match in _ALIASED_REFERENCE_PATTERN.finditer(line):
            if _overlaps_any(match.start(), match.end(), spans):
                continue
            tokens.append(
                _Token(
                    line=line_no,
                    start=match.start("alias"),
                    length=match.end("alias") - match.start("alias"),
                    token_type=types.SemanticTokenTypes.Variable.value,
                )
            )
            tokens.append(
                _Token(
                    line=line_no,
                    start=match.start("field"),
                    length=match.end("field") - match.start("field"),
                    token_type=types.SemanticTokenTypes.Property.value,
                )
            )

    for annotation in _ANNOTATION_PATTERN.finditer(line):
        if _overlaps_any(annotation.start(), annotation.end(), spans):
            continue
        tokens.append(
            _Token(
                line=line_no,
                start=annotation.start(),
                length=annotation.end() - annotation.start(),
                token_type=types.SemanticTokenTypes.Decorator.value,
            )
        )

    for match in _WORD_PATTERN.finditer(line):
        if _overlaps_any(match.start(), match.end(), spans):
            continue
        if _covered_by_existing_token(tokens, line_no, match.start(), match.end()):
            continue
        token_type = _classify_word(match.group(0))
        if token_type is None:
            continue
        tokens.append(
            _Token(
                line=line_no,
                start=match.start(),
                length=match.end() - match.start(),
                token_type=token_type,
            )
        )

    for match in _NUMBER_PATTERN.finditer(line):
        if _overlaps_any(match.start(), match.end(), spans):
            continue
        if _covered_by_existing_token(tokens, line_no, match.start(), match.end()):
            continue
        tokens.append(
            _Token(
                line=line_no,
                start=match.start(),
                length=match.end() - match.start(),
                token_type=types.SemanticTokenTypes.Number.value,
            )
        )

    _add_operator_tokens(tokens, line_no, line, spans)


def _add_span_tokens(tokens: list[_Token], line_no: int, spans: list[tuple[int, int, str]]) -> None:
    for start, end, kind in spans:
        token_type = types.SemanticTokenTypes.Comment.value if kind == "comment" else types.SemanticTokenTypes.String.value
        tokens.append(
            _Token(
                line=line_no,
                start=start,
                length=end - start,
                token_type=token_type,
            )
        )


def _classify_word(word: str) -> str | None:
    lowered = word.lower()
    if lowered in _TYPE_WORDS:
        return types.SemanticTokenTypes.Type.value
    if lowered in _KEYWORDS:
        return types.SemanticTokenTypes.Keyword.value
    return None


def _lex_line_spans(line: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    i = 0
    while i < len(line):
        if line.startswith("//", i):
            spans.append((i, len(line), "comment"))
            break
        if line[i] == '"':
            start = i
            i += 1
            while i < len(line):
                if line[i] == "\\":
                    i += 2
                    continue
                if line[i] == '"':
                    i += 1
                    break
                i += 1
            spans.append((start, i, "string"))
            continue
        i += 1
    return spans


def _add_operator_tokens(tokens: list[_Token], line_no: int, line: str, spans: list[tuple[int, int, str]]) -> None:
    i = 0
    while i < len(line):
        if _overlaps_any(i, i + 1, spans):
            i += 1
            continue
        if line.startswith("<-", i):
            tokens.append(_Token(line=line_no, start=i, length=2, token_type=types.SemanticTokenTypes.Operator.value))
            i += 2
            continue
        if line[i] in "{}()[]:,.<>#=":
            tokens.append(_Token(line=line_no, start=i, length=1, token_type=types.SemanticTokenTypes.Operator.value))
        i += 1


def _add_match_token(
    tokens: list[_Token],
    line_no: int,
    line: str,
    pattern: re.Pattern[str],
    group_name: str,
    token_type: str,
) -> None:
    match = pattern.match(line)
    if match is None:
        return
    start = match.start(group_name)
    end = match.end(group_name)
    if start < 0 or end <= start:
        return
    tokens.append(_Token(line=line_no, start=start, length=end - start, token_type=token_type))


def _add_dotted_reference_token(
    tokens: list[_Token],
    line_no: int,
    line: str,
    pattern: re.Pattern[str],
    group_name: str,
    token_type: str,
) -> None:
    match = pattern.match(line)
    if match is None:
        return
    value = match.group(group_name)
    start = match.start(group_name)
    parts = value.split(".")
    offset = 0
    for index, part in enumerate(parts):
        part_type = token_type if index == len(parts) - 1 else types.SemanticTokenTypes.Namespace.value
        tokens.append(
            _Token(
                line=line_no,
                start=start + offset,
                length=len(part),
                token_type=part_type,
            )
        )
        offset += len(part) + 1


def _overlaps_any(start: int, end: int, spans: list[tuple[int, int, str]]) -> bool:
    return any(start < span_end and end > span_start for span_start, span_end, _kind in spans)


def _covered_by_existing_token(tokens: list[_Token], line_no: int, start: int, end: int) -> bool:
    return any(token.line == line_no and start < token.start + token.length and end > token.start for token in tokens)


def _dedupe_tokens(tokens: list[_Token]) -> list[_Token]:
    seen: set[tuple[int, int, int, str, int]] = set()
    deduped: list[_Token] = []
    for token in tokens:
        key = (token.line, token.start, token.length, token.token_type, token.token_modifiers)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(token)
    return deduped


def _encode_tokens(tokens: list[_Token]) -> list[int]:
    ordered = sorted(tokens, key=lambda token: (token.line, token.start, token.length))
    data: list[int] = []
    previous_line = 0
    previous_start = 0
    type_index = {token_type: index for index, token_type in enumerate(_TOKEN_TYPES)}

    for token in ordered:
        delta_line = token.line - previous_line
        delta_start = token.start - previous_start if delta_line == 0 else token.start
        data.extend([delta_line, delta_start, token.length, type_index[token.token_type], token.token_modifiers])
        previous_line = token.line
        previous_start = token.start

    return data
