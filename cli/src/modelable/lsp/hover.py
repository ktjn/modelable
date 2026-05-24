from __future__ import annotations

from dataclasses import dataclass
import re

from lsprotocol import types

from modelable.llm.context import build_model_summary, build_projection_summary, parse_model_ref
from modelable.lsp.workspace import LspWorkspaceIndex
from modelable.registry.resolver import resolve_model_ref

_QUALIFIED_REF_PATTERN = re.compile(
    r"(?P<domain>[A-Za-z_][A-Za-z0-9_]*)\.(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*@\s*(?P<version>\d+)"
)
_FIELD_REF_PATTERN = re.compile(r"(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\.(?P<field>[A-Za-z_][A-Za-z0-9_]*)")
_DECL_PATTERN = re.compile(
    r"^\s*(?P<kind>entity|aggregate|event|value|projection)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*@\s*(?P<version>\d+)"
)
_DOMAIN_PATTERN = re.compile(r'^\s*domain\s+(?:"(?P<quoted>[^"]+)"|(?P<name>[A-Za-z_][A-Za-z0-9_]*))')
_WORD_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True)
class HoverInfo:
    markdown: str
    line: int
    start: int
    end: int


def build_hover(index: LspWorkspaceIndex, uri: str, line: int, character: int) -> types.Hover | None:
    source = index.documents.get(uri)
    workspace = index.workspace
    if source is None or workspace is None:
        return None

    lines = source.text.splitlines()
    if line < 0 or line >= len(lines):
        return None
    text_line = lines[line]

    for match in _QUALIFIED_REF_PATTERN.finditer(text_line):
        if _contains(match.start(), match.end(), character):
            ref = f"{match.group('domain')}.{match.group('name')}@{match.group('version')}"
            return _make_ref_hover(workspace, ref, line, match.start(), match.end())

    for match in _FIELD_REF_PATTERN.finditer(text_line):
        if _contains(match.start(), match.end(), character):
            info = _hover_for_field_reference(
                workspace,
                source.text,
                line,
                match.group("alias"),
                match.group("field"),
                match.start(),
                match.end(),
            )
            if info is not None:
                return _hover_from_info(info)

    word = _word_at(text_line, character)
    if word is None:
        return None

    info = _hover_for_bare_word(workspace, source.text, line, word)
    if info is not None:
        start, end = _word_span(text_line, character)
        return _hover_from_info(HoverInfo(markdown=_markdown_block(info), line=line, start=start, end=end))
    return None


def _make_ref_hover(workspace, ref: str, line: int, start: int, end: int) -> types.Hover | None:
    model_ref = parse_model_ref(ref)
    domain = next((d for d in workspace.mdl.domains if d.name == model_ref.domain), None)
    if domain is None:
        return None

    if model_ref.name in domain.models:
        summary = build_model_summary(workspace, ref)
    elif model_ref.name in domain.projections:
        summary = build_projection_summary(workspace, ref)
    else:
        return None

    return _hover_from_info(
        HoverInfo(markdown=_markdown_block(summary), line=line, start=start, end=end)
    )


def _hover_for_bare_word(workspace, text: str, line: int, word: str) -> str | None:
    scope = _current_scope(text, line)
    if scope is None:
        return None
    domain_name, kind, name, version = scope
    domain = next((d for d in workspace.mdl.domains if d.name == domain_name), None)
    if domain is None:
        return None

    if kind == "model":
        versions = domain.models.get(name)
        if not versions:
            return None
        model_version = next((item for item in versions if item.version == version), None)
        if model_version is None:
            return None
        if word == name:
            return build_model_summary(workspace, f"{domain_name}.{name}@{version}")
        field = next((item for item in model_version.fields if item.name == word), None)
        if field is None:
            return None
        flags = []
        if field.is_key:
            flags.append("key")
        if field.is_pii:
            flags.append("pii")
        if field.classification:
            flags.append(f"classification={field.classification.value}")
        suffix = f" [{', '.join(flags)}]" if flags else ""
        return (
            f"{domain_name}.{name}@{version}.{field.name}\n"
            f"type: {field.type.kind}\n"
            f"optional: {'yes' if field.optional else 'no'}{suffix}"
        )

    versions = domain.projections.get(name)
    if not versions:
        return None
    projection_version = next((item for item in versions if item.version == version), None)
    if projection_version is None:
        return None
    if word == name:
        return build_projection_summary(workspace, f"{domain_name}.{name}@{version}")
    field = next((item for item in projection_version.fields if item.name == word), None)
    if field is None:
        return None
    return (
        f"{domain_name}.{name}@{version}.{field.name}\n"
        f"mapping: {_mapping_text(field)}"
    )


def _hover_for_field_reference(
    workspace,
    text: str,
    line: int,
    alias: str,
    field_name: str,
    start: int,
    end: int,
) -> HoverInfo | None:
    scope = _current_scope(text, line)
    if scope is None:
        return None
    domain_name, kind, name, version = scope
    domain = next((d for d in workspace.mdl.domains if d.name == domain_name), None)
    if domain is None:
        return None
    if kind == "model":
        versions = domain.models.get(name)
        if not versions:
            return None
        model_version = next((item for item in versions if item.version == version), None)
        if model_version is None:
            return None
        field = next((item for item in model_version.fields if item.name == field_name), None)
        if field is None:
            return None
        flags = []
        if field.is_key:
            flags.append("key")
        if field.is_pii:
            flags.append("pii")
        if field.classification:
            flags.append(f"classification={field.classification.value}")
        suffix = f" [{', '.join(flags)}]" if flags else ""
        return HoverInfo(
            markdown=_markdown_block(
                f"{domain_name}.{name}@{version}.{field.name}\n"
                f"type: {field.type.kind}\n"
                f"optional: {'yes' if field.optional else 'no'}{suffix}"
            ),
            line=line,
            start=start,
            end=end,
        )
    versions = domain.projections.get(name)
    if not versions:
        return None
    projection_version = next((item for item in versions if item.version == version), None)
    if projection_version is None:
        return None
    for source_ref in [projection_version.source, *projection_version.joins]:
        if source_ref.alias != alias:
            continue
        try:
            resolved = resolve_model_ref(
                workspace.mdl,
                source_ref.model,
                source_ref.version,
            )
        except LookupError:
            break
        return _hover_for_source_field(
            workspace,
            resolved.domain_name,
            resolved.model_name,
            resolved.version.version,
            field_name,
            line,
            start,
            end,
        )
    field = next((item for item in projection_version.fields if item.name == field_name), None)
    if field is None:
        return None
    return HoverInfo(
        markdown=_markdown_block(
            f"{domain_name}.{name}@{version}.{field.name}\n"
            f"mapping: {_mapping_text(field)}"
        ),
        line=line,
        start=start,
        end=end,
    )


def _hover_for_source_field(
    workspace,
    domain_name: str,
    model_name: str,
    version: int,
    field_name: str,
    line: int,
    start: int,
    end: int,
) -> HoverInfo | None:
    source_version = _source_version(workspace, domain_name, model_name, version)
    if source_version is None:
        return None
    source_field = next((item for item in getattr(source_version, "fields", []) if item.name == field_name), None)
    if source_field is None:
        return None

    if getattr(source_field, "mapping", None) is not None:
        return HoverInfo(
            markdown=_markdown_block(
                f"{domain_name}.{model_name}@{version}.{source_field.name}\n"
                f"mapping: {_mapping_text(source_field)}"
            ),
            line=line,
            start=start,
            end=end,
        )

    flags = []
    if source_field.is_key:
        flags.append("key")
    if source_field.is_pii:
        flags.append("pii")
    if source_field.classification:
        flags.append(f"classification={source_field.classification.value}")
    suffix = f" [{', '.join(flags)}]" if flags else ""
    return HoverInfo(
        markdown=_markdown_block(
            f"{domain_name}.{model_name}@{version}.{source_field.name}\n"
            f"type: {source_field.type.kind}\n"
            f"optional: {'yes' if source_field.optional else 'no'}{suffix}"
        ),
        line=line,
        start=start,
        end=end,
    )


def _source_version(workspace, domain_name: str, model_name: str, version: int):
    domain = next((d for d in workspace.mdl.domains if d.name == domain_name), None)
    if domain is None:
        return None
    versions = domain.models.get(model_name, [])
    source_version = next((item for item in versions if item.version == version), None)
    if source_version is not None:
        return source_version
    versions = domain.projections.get(model_name, [])
    return next((item for item in versions if item.version == version), None)


def _hover_from_info(info: HoverInfo) -> types.Hover:
    return types.Hover(
        contents=types.MarkupContent(kind=types.MarkupKind.Markdown, value=info.markdown),
        range=types.Range(
            start=types.Position(line=info.line, character=info.start),
            end=types.Position(line=info.line, character=info.end),
        ),
    )


def _current_scope(text: str, line: int) -> tuple[str, str, str, int] | None:
    lines = text.splitlines()
    current_domain: str | None = None
    current_kind: str | None = None
    current_name: str | None = None
    current_version: int | None = None
    for item in lines[: line + 1]:
        domain_match = _DOMAIN_PATTERN.match(item)
        if domain_match:
            current_domain = domain_match.group("quoted") or domain_match.group("name")
            current_kind = None
            current_name = None
            current_version = None
            continue
        decl_match = _DECL_PATTERN.match(item)
        if decl_match and current_domain is not None:
            current_kind = "model" if decl_match.group("kind") != "projection" else "projection"
            current_name = decl_match.group("name")
            current_version = int(decl_match.group("version"))
    if current_domain and current_kind and current_name and current_version is not None:
        return current_domain, current_kind, current_name, current_version
    return None


def _word_at(text_line: str, character: int) -> str | None:
    for match in _WORD_PATTERN.finditer(text_line):
        if _contains(match.start(), match.end(), character):
            return match.group(0)
    return None


def _word_span(text_line: str, character: int) -> tuple[int, int]:
    for match in _WORD_PATTERN.finditer(text_line):
        if _contains(match.start(), match.end(), character):
            return match.start(), match.end()
    return character, character


def _contains(start: int, end: int, character: int) -> bool:
    return start <= character <= max(end - 1, start)


def _markdown_block(text: str) -> str:
    return f"```text\n{text}\n```"


def _mapping_text(field) -> str:
    mapping = getattr(field, "mapping", None)
    if mapping is None:
        return "unknown"
    kind = getattr(mapping, "kind", None)
    if kind == "direct":
        return f"direct {mapping.source_alias}.{mapping.source_field}"
    if kind == "computed":
        return f"computed {mapping.expression}"
    return "unknown"
