from __future__ import annotations

import re
from dataclasses import dataclass

from modelable.compiler.workspace import Workspace
from modelable.language.dto import LanguageHover, LanguagePosition, LanguageRange
from modelable.language.positions import codepoint_to_utf16, utf16_to_codepoint
from modelable.language.workspace import LanguageWorkspace
from modelable.llm.context import (
    build_model_summary,
    build_projection_summary,
    parse_model_ref,
    parse_model_ref_version_spec,
)
from modelable.parser.ir import (
    FieldDef,
    ModelVersion,
    ProjectionField,
    ProjectionVersion,
    VersionSpec,
)
from modelable.registry.resolver import resolve_model_ref

_QUALIFIED_REF_PATTERN = re.compile(
    r"(?P<domain>[A-Za-z_][A-Za-z0-9_]*)\.(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*@\s*(?P<version>\d+)"
)
_REF_TYPE_PATTERN = re.compile(r"ref\s*<\s*(?P<domain>[A-Za-z_][A-Za-z0-9_]*)\.(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*>")
_FIELD_REF_PATTERN = re.compile(r"(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\.(?P<field>[A-Za-z_][A-Za-z0-9_]*)")
_SOURCE_ALIAS_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])(?:from|(?:left\s+)?join)\s+"
    r"(?P<domain>[A-Za-z_][A-Za-z0-9_-]*)\s*\.\s*"
    r"(?P<model>[A-Za-z_][A-Za-z0-9_-]*(?:\s*\.\s*[A-Za-z_][A-Za-z0-9_-]*)*)"
    r"\s*@\s*(?P<version>\d+(?:\s*#\s*[0-9a-fA-F]+)?|>=\s*\d+(?:\s*<\s*\d+)?)"
    r"\s+as\s+(?P<alias>[A-Za-z_][A-Za-z0-9_]*)(?![A-Za-z0-9_-])"
)
_DECL_PATTERN = re.compile(
    r"^\s*(?P<kind>entity|aggregate|event|value|projection)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*@\s*(?P<version>\d+)"
)
_DOMAIN_PATTERN = re.compile(r'^\s*domain\s+(?:"(?P<quoted>[^"]+)"|(?P<name>[A-Za-z_][A-Za-z0-9_]*))')
_WORD_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True)
class _HoverInfo:
    markdown: str
    line: int
    start: int
    end: int


def hover(
    workspace: LanguageWorkspace,
    uri: str,
    position: LanguagePosition,
) -> LanguageHover | None:
    document = workspace.current_document(uri)
    semantic = workspace.semantic_workspace()
    if document is None or semantic is None:
        return None

    lines = document.text.splitlines()
    if position.line < 0 or position.line >= len(lines) or position.character < 0:
        return None
    text_line = lines[position.line]
    try:
        character = utf16_to_codepoint(text_line, position.character)
    except ValueError:
        return None

    for match in _QUALIFIED_REF_PATTERN.finditer(text_line):
        if _contains(match.start(), match.end(), character):
            ref = f"{match.group('domain')}.{match.group('name')}@{match.group('version')}"
            return _make_ref_hover(
                semantic,
                ref,
                text_line,
                position.line,
                match.start(),
                match.end(),
            )

    for match in _REF_TYPE_PATTERN.finditer(text_line):
        if _contains(match.start(), match.end(), character):
            result = _make_unversioned_ref_hover(
                semantic,
                match.group("domain"),
                match.group("name"),
                text_line,
                position.line,
                match.start(),
                match.end(),
            )
            if result is not None:
                return result

    for match in _FIELD_REF_PATTERN.finditer(text_line):
        if _contains(match.start(), match.end(), character):
            info = _hover_for_field_reference(
                semantic,
                document.text,
                position.line,
                match.group("alias"),
                match.group("field"),
                match.start(),
                match.end(),
            )
            if info is not None:
                return _language_hover(info, text_line)

    word = _word_at(text_line, character)
    if word is None:
        return None

    summary = _hover_for_bare_word(
        semantic,
        document.text,
        position.line,
        word,
    )
    if summary is None:
        return None
    start, end = _word_span(text_line, character)
    return _language_hover(
        _HoverInfo(
            markdown=_markdown_block(summary),
            line=position.line,
            start=start,
            end=end,
        ),
        text_line,
    )


def _make_ref_hover(
    workspace: Workspace,
    ref: str,
    text_line: str,
    line: int,
    start: int,
    end: int,
) -> LanguageHover | None:
    model_ref = parse_model_ref(ref)
    domain = next(
        (domain for domain in workspace.mdl.domains if domain.name == model_ref.domain),
        None,
    )
    if domain is None:
        return None

    if model_ref.name in domain.models:
        summary = build_model_summary(workspace, ref)
    elif model_ref.name in domain.projections:
        summary = build_projection_summary(workspace, ref)
    else:
        return None

    return _language_hover(
        _HoverInfo(
            markdown=_markdown_block(summary),
            line=line,
            start=start,
            end=end,
        ),
        text_line,
    )


def _make_unversioned_ref_hover(
    workspace: Workspace,
    domain_name: str,
    name: str,
    text_line: str,
    line: int,
    start: int,
    end: int,
) -> LanguageHover | None:
    domain = next(
        (domain for domain in workspace.mdl.domains if domain.name == domain_name),
        None,
    )
    if domain is None:
        return None
    if name in domain.models:
        latest = max(domain.models[name], key=lambda version: version.version)
        ref = f"{domain_name}.{name}@{latest.version}"
        return _make_ref_hover(workspace, ref, text_line, line, start, end)
    if name in domain.projections:
        latest_projection = max(domain.projections[name], key=lambda version: version.version)
        ref = f"{domain_name}.{name}@{latest_projection.version}"
        return _make_ref_hover(workspace, ref, text_line, line, start, end)
    return None


def _hover_for_bare_word(
    workspace: Workspace,
    text: str,
    line: int,
    word: str,
) -> str | None:
    scope = _current_scope(text, line)
    if scope is None:
        return None
    domain_name, kind, name, version, _scope_line = scope
    domain = next(
        (domain for domain in workspace.mdl.domains if domain.name == domain_name),
        None,
    )
    if domain is None:
        return None

    if kind == "model":
        versions = domain.models.get(name)
        if not versions:
            return None
        model_version = next(
            (item for item in versions if item.version == version),
            None,
        )
        if model_version is None:
            return None
        if word == name:
            return build_model_summary(
                workspace,
                f"{domain_name}.{name}@{version}",
            )
        field = next(
            (item for item in model_version.fields if item.name == word),
            None,
        )
        if field is None:
            return None
        return _model_field_summary(
            domain_name,
            name,
            version,
            field,
        )

    projection_versions = domain.projections.get(name)
    if not projection_versions:
        return None
    projection_version = next(
        (item for item in projection_versions if item.version == version),
        None,
    )
    if projection_version is None:
        return None
    if word == name:
        return build_projection_summary(
            workspace,
            f"{domain_name}.{name}@{version}",
        )
    projection_field = next(
        (item for item in projection_version.fields if item.name == word),
        None,
    )
    if projection_field is None:
        return None
    return f"{domain_name}.{name}@{version}.{projection_field.name}\nmapping: {_mapping_text(projection_field)}"


def _hover_for_field_reference(
    workspace: Workspace,
    text: str,
    line: int,
    alias: str,
    field_name: str,
    start: int,
    end: int,
) -> _HoverInfo | None:
    scope = _current_scope(text, line)
    if scope is None:
        return None
    domain_name, kind, name, version, scope_line = scope
    domain = next(
        (domain for domain in workspace.mdl.domains if domain.name == domain_name),
        None,
    )
    if domain is None:
        return None
    if kind == "model":
        versions = domain.models.get(name)
        if not versions:
            return None
        model_version = next(
            (item for item in versions if item.version == version),
            None,
        )
        if model_version is None:
            return None
        field = next(
            (item for item in model_version.fields if item.name == field_name),
            None,
        )
        if field is None:
            return None
        return _HoverInfo(
            markdown=_markdown_block(
                _model_field_summary(
                    domain_name,
                    name,
                    version,
                    field,
                )
            ),
            line=line,
            start=start,
            end=end,
        )

    projection_versions = domain.projections.get(name)
    if not projection_versions:
        return None
    projection_version = next(
        (item for item in projection_versions if item.version == version),
        None,
    )
    if projection_version is None:
        return None
    current_reference = _projection_reference_for_alias(
        text,
        scope_line,
        line,
        alias,
    )
    if current_reference is None:
        return None
    model_ref, version_spec = current_reference
    try:
        resolved = resolve_model_ref(
            workspace.mdl,
            model_ref,
            version_spec,
        )
    except LookupError:
        return None
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


def _hover_for_source_field(
    workspace: Workspace,
    domain_name: str,
    model_name: str,
    version: int,
    field_name: str,
    line: int,
    start: int,
    end: int,
) -> _HoverInfo | None:
    source_version = _source_version(
        workspace,
        domain_name,
        model_name,
        version,
    )
    if source_version is None:
        return None

    if isinstance(source_version, ProjectionVersion):
        source_field = next(
            (item for item in source_version.fields if item.name == field_name),
            None,
        )
        if source_field is None:
            return None
        return _HoverInfo(
            markdown=_markdown_block(
                f"{domain_name}.{model_name}@{version}.{source_field.name}\nmapping: {_mapping_text(source_field)}"
            ),
            line=line,
            start=start,
            end=end,
        )

    source_model_field = next(
        (item for item in source_version.fields if item.name == field_name),
        None,
    )
    if source_model_field is None:
        return None
    return _HoverInfo(
        markdown=_markdown_block(
            _model_field_summary(
                domain_name,
                model_name,
                version,
                source_model_field,
            )
        ),
        line=line,
        start=start,
        end=end,
    )


def _source_version(
    workspace: Workspace,
    domain_name: str,
    model_name: str,
    version: int,
) -> ModelVersion | ProjectionVersion | None:
    domain = next(
        (domain for domain in workspace.mdl.domains if domain.name == domain_name),
        None,
    )
    if domain is None:
        return None
    versions = domain.models.get(model_name, [])
    source_version = next(
        (item for item in versions if item.version == version),
        None,
    )
    if source_version is not None:
        return source_version
    projection_versions = domain.projections.get(model_name, [])
    return next(
        (item for item in projection_versions if item.version == version),
        None,
    )


def _model_field_summary(
    domain_name: str,
    model_name: str,
    version: int,
    field: FieldDef,
) -> str:
    flags = []
    if field.is_key:
        flags.append("key")
    if field.is_pii:
        flags.append("pii")
    if field.classification:
        flags.append(f"classification={field.classification.value}")
    for annotation in field.annotations:
        if annotation.kind == "deprecated":
            flags.append(f"deprecated replacedBy={annotation.replaced_by}")
    suffix = f" [{', '.join(flags)}]" if flags else ""
    return (
        f"{domain_name}.{model_name}@{version}.{field.name}\n"
        f"type: {field.type.kind}\n"
        f"optional: {'yes' if field.optional else 'no'}{suffix}"
    )


def _language_hover(info: _HoverInfo, text_line: str) -> LanguageHover:
    return LanguageHover(
        markdown=info.markdown,
        range=LanguageRange.at(
            info.line,
            codepoint_to_utf16(text_line, info.start),
            info.line,
            codepoint_to_utf16(text_line, info.end),
        ),
    )


def _projection_reference_for_alias(
    text: str,
    scope_line: int,
    line: int,
    alias: str,
) -> tuple[str, VersionSpec | int] | None:
    lines = text.splitlines()
    end_line = min(line, len(lines) - 1)
    active_projection = "\n".join(lines[scope_line : end_line + 1])
    masked_projection = _mask_ignored_regions(active_projection)
    for match in _SOURCE_ALIAS_PATTERN.finditer(masked_projection):
        if _matched_text(active_projection, match, "alias") != alias:
            continue
        domain_text = _matched_text(active_projection, match, "domain")
        model_text = _matched_text(active_projection, match, "model")
        version_text = _matched_text(active_projection, match, "version")
        model_text = re.sub(r"\s*\.\s*", ".", model_text)
        version_text = re.sub(r"\s+", "", version_text)
        domain, model, version = parse_model_ref_version_spec(f"{domain_text}.{model_text}@{version_text}")
        return f"{domain}.{model}", version
    return None


def _matched_text(
    source: str,
    match: re.Match[str],
    group: str,
) -> str:
    start, end = match.span(group)
    return source[start:end]


def _mask_ignored_regions(text: str) -> str:
    masked = list(text)
    index = 0
    while index < len(text):
        if text.startswith("//", index):
            while index < len(text) and text[index] not in "\r\n":
                masked[index] = " "
                index += 1
            continue

        if text[index] != '"':
            index += 1
            continue

        masked[index] = " "
        index += 1
        while index < len(text):
            if text[index] == "\\":
                masked[index] = " "
                index += 1
                if index < len(text):
                    if text[index] not in "\r\n":
                        masked[index] = " "
                    index += 1
                continue
            if text[index] == '"':
                masked[index] = " "
                index += 1
                break
            if text[index] not in "\r\n":
                masked[index] = " "
            index += 1
    return "".join(masked)


def _current_scope(
    text: str,
    line: int,
) -> tuple[str, str, str, int, int] | None:
    lines = text.splitlines()
    current_domain: str | None = None
    current_kind: str | None = None
    current_name: str | None = None
    current_version: int | None = None
    current_line: int | None = None
    for index, item in enumerate(lines[: line + 1]):
        domain_match = _DOMAIN_PATTERN.match(item)
        if domain_match:
            current_domain = domain_match.group("quoted") or domain_match.group("name")
            current_kind = None
            current_name = None
            current_version = None
            current_line = None
            continue
        declaration_match = _DECL_PATTERN.match(item)
        if declaration_match and current_domain is not None:
            current_kind = "model" if declaration_match.group("kind") != "projection" else "projection"
            current_name = declaration_match.group("name")
            current_version = int(declaration_match.group("version"))
            current_line = index
    if current_domain and current_kind and current_name and current_version is not None and current_line is not None:
        return current_domain, current_kind, current_name, current_version, current_line
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


def _safe_markdown(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("](", r"]\(")


def _markdown_block(text: str) -> str:
    return f"```text\n{_safe_markdown(text)}\n```"


def _mapping_text(field: ProjectionField) -> str:
    mapping = getattr(field, "mapping", None)
    if mapping is None:
        return "unknown"
    kind = getattr(mapping, "kind", None)
    if kind == "direct":
        return f"direct {mapping.source_alias}.{mapping.source_field}"
    if kind == "computed":
        return f"computed {mapping.expression}"
    return "unknown"
