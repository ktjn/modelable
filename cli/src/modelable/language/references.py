from __future__ import annotations

import re
from collections.abc import Iterable

from modelable.compiler.workspace import Workspace
from modelable.language.dto import LanguageLocation, LanguagePosition, LanguageRange
from modelable.language.positions import codepoint_to_utf16, document_lines, utf16_to_codepoint
from modelable.language.ref_lookup import projection_aliases as _projection_aliases
from modelable.language.scanning import DOMAIN_PATTERN as _DOMAIN_PATTERN
from modelable.language.scanning import contains as _contains
from modelable.language.scanning import word_at as _word_at
from modelable.language.workspace import LanguageWorkspace
from modelable.llm.context import parse_model_ref
from modelable.parser.ir import JoinRef, ModelVersion, ProjectionVersion, SourceRef
from modelable.registry.resolver import resolve_model_ref

_QUALIFIED_REF_PATTERN = re.compile(
    r"(?P<domain>[A-Za-z_][A-Za-z0-9_]*)\.(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*@\s*(?P<version>\d+)"
)
_FIELD_REF_PATTERN = re.compile(r"(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\.(?P<field>[A-Za-z_][A-Za-z0-9_]*)")
_DECL_PATTERN = re.compile(
    r"^\s*(?P<kind>entity|aggregate|event|value|projection|semantic)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*@\s*(?P<version>\d+)"
    r"(?:.*?\bevolves\s*@\s*(?P<base>\d+))?"
)
_EVOLVES_FIELD_OP_PATTERN = re.compile(r"^\s*(?:remove|rename|replace)\s+(?P<field>[A-Za-z_][A-Za-z0-9_]*)")
_ENUM_PROJECTION_DECL_PATTERN = re.compile(
    r"^\s*enum\s+projection\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*@\s*(?P<version>\d+)"
)
_MODEL_FIELD_PATTERN = re.compile(
    r"^\s*(?:@[A-Za-z_][A-Za-z0-9_]*(?:\([^)]*\))?\s+)*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\??\s*:"
)
_PROJECTION_FIELD_PATTERN = re.compile(
    r"^\s*(?:@[A-Za-z_][A-Za-z0-9_]*(?:\([^)]*\))?\s+)*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:<-|=)"
)
_MODEL_DECL_KINDS = {"entity", "aggregate", "event", "value"}


def references(
    workspace: LanguageWorkspace,
    uri: str,
    position: LanguagePosition,
    include_declaration: bool,
) -> tuple[LanguageLocation, ...]:
    document = workspace.current_document(uri)
    semantic = workspace.semantic_workspace()
    if document is None or semantic is None:
        return ()

    lines = document_lines(document.text)
    if position.line < 0 or position.line >= len(lines) or position.character < 0:
        return ()
    text_line = lines[position.line]
    try:
        character = utf16_to_codepoint(text_line, position.character)
    except ValueError:
        return ()

    raw = _resolve_references(semantic, document.text, lines, position.line, character, include_declaration)
    return _safe_locations(workspace, raw)


def _safe_locations(
    workspace: LanguageWorkspace,
    locations: Iterable[LanguageLocation],
) -> tuple[LanguageLocation, ...]:
    return tuple(sorted({location for location in locations if workspace.is_location_current(location)}))


def _resolve_references(
    semantic: Workspace,
    text: str,
    lines: tuple[str, ...],
    line: int,
    character: int,
    include_declaration: bool,
) -> list[LanguageLocation]:
    text_line = lines[line]

    for match in _QUALIFIED_REF_PATTERN.finditer(text_line):
        if _contains(match.start(), match.end(), character):
            ref = f"{match.group('domain')}.{match.group('name')}@{match.group('version')}"
            return _references_for_qualified_ref(semantic, ref, include_declaration)

    for match in _FIELD_REF_PATTERN.finditer(text_line):
        if _contains(match.start(), match.end(), character):
            return _references_for_field_reference(
                semantic,
                text,
                line,
                match.group("alias"),
                match.group("field"),
                include_declaration,
            )

    word = _word_at(text_line, character)
    if word is None:
        return []

    evolves_op_match = _EVOLVES_FIELD_OP_PATTERN.match(text_line)
    if evolves_op_match is not None and _contains(
        evolves_op_match.start("field"), evolves_op_match.end("field"), character
    ):
        scope = _current_scope(text, line)
        base_version = _evolves_base_at(text, line)
        if scope is not None and base_version is not None and scope[1] == "model":
            return _references_for_evolves_field(
                semantic, scope[0], scope[2], base_version, evolves_op_match.group("field"), include_declaration
            )

    scope = _current_scope(text, line)
    if scope is None:
        return []
    domain_name, kind, name, version = scope

    if word == name:
        return _references_for_decl(semantic, domain_name, kind, name, version, include_declaration)

    if kind == "model":
        return _references_for_source_field(
            semantic,
            domain_name,
            name,
            version,
            word,
            include_declaration,
        )
    return _references_for_projection_field(
        semantic,
        domain_name,
        name,
        version,
        word,
        include_declaration,
    )


def _references_for_qualified_ref(
    workspace: Workspace,
    ref: str,
    include_declaration: bool,
) -> list[LanguageLocation]:
    model_ref = parse_model_ref(ref)
    domain = next((d for d in workspace.mdl.domains if d.name == model_ref.domain), None)
    if domain is None:
        return []

    if model_ref.name in domain.models:
        kind = "model"
    elif model_ref.name in domain.projections:
        kind = "projection"
    elif any(item.name == model_ref.name for item in domain.semantic_types):
        kind = "semantic"
    elif any(item.name == model_ref.name for item in domain.enum_projections):
        kind = "enum_projection"
    else:
        return []

    locations = _reference_locations_for_decl(workspace, model_ref.domain, kind, model_ref.name, model_ref.version)
    if include_declaration:
        decl = _find_decl_location(workspace, model_ref.domain, kind, model_ref.name, model_ref.version)
        if decl is not None:
            locations = [decl, *locations]
    return _dedupe_locations(locations)


def _references_for_field_reference(
    workspace: Workspace,
    text: str,
    line: int,
    alias: str,
    field_name: str,
    include_declaration: bool,
) -> list[LanguageLocation]:
    scope = _current_scope(text, line)
    if scope is None:
        return []

    domain_name, kind, name, version = scope
    if kind == "model":
        return _references_for_source_field(
            workspace,
            domain_name,
            name,
            version,
            field_name,
            include_declaration,
        )

    domain = next((d for d in workspace.mdl.domains if d.name == domain_name), None)
    if domain is None:
        return []
    versions = domain.projections.get(name, [])
    projection_version = next((item for item in versions if item.version == version), None)
    if projection_version is None:
        return []

    all_sources: list[SourceRef | JoinRef] = [projection_version.source, *projection_version.joins]
    for source_ref in all_sources:
        if source_ref.alias != alias:
            continue
        try:
            resolved = resolve_model_ref(
                workspace.mdl,
                source_ref.model,
                source_ref.version,
            )
        except LookupError:
            continue
        return _references_for_source_field(
            workspace,
            resolved.domain_name,
            resolved.model_name,
            resolved.version.version,
            field_name,
            include_declaration,
        )

    if include_declaration:
        location = _find_field_location(
            workspace,
            domain_name,
            "projection",
            name,
            version,
            field_name,
        )
        return [location] if location is not None else []
    return []


def _references_for_decl(
    workspace: Workspace,
    domain_name: str,
    kind: str,
    name: str,
    version: int,
    include_declaration: bool,
) -> list[LanguageLocation]:
    locations = _reference_locations_for_decl(workspace, domain_name, kind, name, version)
    if include_declaration:
        decl = _find_decl_location(workspace, domain_name, kind, name, version)
        if decl is not None:
            locations = [decl, *locations]
    return _dedupe_locations(locations)


def _references_for_source_field(
    workspace: Workspace,
    domain_name: str,
    model_name: str,
    version: int,
    field_name: str,
    include_declaration: bool,
) -> list[LanguageLocation]:
    locations: list[LanguageLocation] = []
    if include_declaration:
        decl = _find_source_field_location(workspace, domain_name, model_name, version, field_name)
        if decl is not None:
            locations.append(decl)

    for source in workspace.sources:
        current_domain: str | None = None
        current_projection: tuple[str, int] | None = None
        alias_map: dict[str, tuple[str, str, int]] = {}
        lines = document_lines(source.text)

        for line_no, line_text in enumerate(lines):
            domain_match = _DOMAIN_PATTERN.match(line_text)
            if domain_match:
                current_domain = domain_match.group("quoted") or domain_match.group("name")
                current_projection = None
                alias_map = {}
                continue

            decl_match = _DECL_PATTERN.match(line_text)
            if decl_match and current_domain is not None:
                if decl_match.group("kind") == "projection":
                    current_projection = (decl_match.group("name"), int(decl_match.group("version")))
                    alias_map = _projection_aliases(workspace, current_domain, *current_projection)
                else:
                    current_projection = None
                    alias_map = {}
                continue

            if current_projection is None:
                continue

            for match in _FIELD_REF_PATTERN.finditer(line_text):
                target = alias_map.get(match.group("alias"))
                if target is None:
                    continue
                if target != (domain_name, model_name, version):
                    continue
                if match.group("field") != field_name:
                    continue
                if not _field_exists(workspace, *target, field_name):
                    continue
                locations.append(
                    LanguageLocation(
                        uri=source.uri,
                        range=LanguageRange.at(
                            line_no,
                            codepoint_to_utf16(line_text, match.start()),
                            line_no,
                            codepoint_to_utf16(line_text, match.end()),
                        ),
                    )
                )

    return _dedupe_locations(locations)


def _references_for_evolves_field(
    workspace: Workspace,
    domain_name: str,
    model_name: str,
    base_version: int,
    field_name: str,
    include_declaration: bool,
) -> list[LanguageLocation]:
    """A field name referenced as the argument of `remove`/`rename`/`replace`
    inside an `evolves` block always names a field that exists on that
    block's base version (the compiler rejects any other case) -- so its
    declaration and alias.field usages are resolved exactly like an ordinary
    reference to that base version, plus every other operation line across
    this model's evolves blocks that mentions the same field name."""
    if not _field_exists(workspace, domain_name, model_name, base_version, field_name):
        return []
    locations = _references_for_source_field(
        workspace, domain_name, model_name, base_version, field_name, include_declaration
    )
    locations.extend(_evolves_operation_field_locations(workspace, domain_name, model_name, field_name))
    return _dedupe_locations(locations)


def _evolves_operation_field_locations(
    workspace: Workspace,
    domain_name: str,
    model_name: str,
    field_name: str,
) -> list[LanguageLocation]:
    locations: list[LanguageLocation] = []
    for source in workspace.sources:
        current_domain: str | None = None
        active = False
        lines = document_lines(source.text)
        for line_no, line_text in enumerate(lines):
            domain_match = _DOMAIN_PATTERN.match(line_text)
            if domain_match:
                current_domain = domain_match.group("quoted") or domain_match.group("name")
                active = False
                continue
            decl_match = _DECL_PATTERN.match(line_text)
            if decl_match:
                active = (
                    current_domain == domain_name
                    and decl_match.group("name") == model_name
                    and decl_match.group("base") is not None
                )
                continue
            if not active:
                continue
            if line_text.strip() == "}":
                active = False
                continue
            match = _EVOLVES_FIELD_OP_PATTERN.match(line_text)
            if match is None or match.group("field") != field_name:
                continue
            locations.append(
                LanguageLocation(
                    uri=source.uri,
                    range=LanguageRange.at(
                        line_no,
                        codepoint_to_utf16(line_text, match.start("field")),
                        line_no,
                        codepoint_to_utf16(line_text, match.end("field")),
                    ),
                )
            )
    return locations


def _evolves_base_at(text: str, line: int) -> int | None:
    current_base: int | None = None
    for item in document_lines(text)[: line + 1]:
        if _DOMAIN_PATTERN.match(item):
            current_base = None
            continue
        decl_match = _DECL_PATTERN.match(item)
        if decl_match:
            base = decl_match.group("base")
            current_base = int(base) if base is not None else None
    return current_base


def _references_for_projection_field(
    workspace: Workspace,
    domain_name: str,
    projection_name: str,
    version: int,
    field_name: str,
    include_declaration: bool,
) -> list[LanguageLocation]:
    return _references_for_source_field(
        workspace,
        domain_name,
        projection_name,
        version,
        field_name,
        include_declaration,
    )


def _reference_locations_for_decl(
    workspace: Workspace,
    domain_name: str,
    kind: str,
    name: str,
    version: int,
) -> list[LanguageLocation]:
    ref = f"{domain_name}.{name}@{version}"
    locations: list[LanguageLocation] = []
    for source in workspace.sources:
        lines = document_lines(source.text)
        for line_no, line_text in enumerate(lines):
            for match in _QUALIFIED_REF_PATTERN.finditer(line_text):
                candidate = f"{match.group('domain')}.{match.group('name')}@{match.group('version')}"
                if candidate != ref:
                    continue
                locations.append(
                    LanguageLocation(
                        uri=source.uri,
                        range=LanguageRange.at(
                            line_no,
                            codepoint_to_utf16(line_text, match.start()),
                            line_no,
                            codepoint_to_utf16(line_text, match.end()),
                        ),
                    )
                )
    return locations


def _field_exists(workspace: Workspace, domain_name: str, model_name: str, version: int, field_name: str) -> bool:
    source_version = _source_version(workspace, domain_name, model_name, version)
    if source_version is None:
        return False
    return any(field.name == field_name for field in getattr(source_version, "fields", []))


def _source_version(
    workspace: Workspace, domain_name: str, model_name: str, version: int
) -> ModelVersion | ProjectionVersion | None:
    domain = next((item for item in workspace.mdl.domains if item.name == domain_name), None)
    if domain is None:
        return None
    model_versions = domain.models.get(model_name, [])
    source_version = next((item for item in model_versions if item.version == version), None)
    if source_version is not None:
        return source_version
    proj_versions = domain.projections.get(model_name, [])
    return next((item for item in proj_versions if item.version == version), None)


def _find_source_field_location(
    workspace: Workspace,
    domain_name: str,
    model_name: str,
    version: int,
    field_name: str,
) -> LanguageLocation | None:
    for kind in ("model", "projection"):
        location = _find_field_location(workspace, domain_name, kind, model_name, version, field_name)
        if location is not None:
            return location
    return None


def _find_decl_location(
    workspace: Workspace,
    domain_name: str,
    kind: str,
    name: str,
    version: int,
) -> LanguageLocation | None:
    for source in workspace.sources:
        current_domain: str | None = None
        lines = document_lines(source.text)
        for line_no, line_text in enumerate(lines):
            domain_match = _DOMAIN_PATTERN.match(line_text)
            if domain_match:
                current_domain = domain_match.group("quoted") or domain_match.group("name")
                continue
            if current_domain != domain_name:
                continue
            if kind == "enum_projection":
                enum_projection_match = _ENUM_PROJECTION_DECL_PATTERN.match(line_text)
                if (
                    enum_projection_match
                    and enum_projection_match.group("name") == name
                    and int(enum_projection_match.group("version")) == version
                ):
                    return LanguageLocation(
                        uri=source.uri,
                        range=LanguageRange.at(
                            line_no,
                            codepoint_to_utf16(line_text, enum_projection_match.start("name")),
                            line_no,
                            codepoint_to_utf16(line_text, enum_projection_match.end("name")),
                        ),
                    )
                continue
            decl_match = _DECL_PATTERN.match(line_text)
            if not decl_match:
                continue
            decl_kind = decl_match.group("kind")
            if kind == "model":
                if decl_kind not in _MODEL_DECL_KINDS:
                    continue
            elif decl_kind != kind:
                continue
            if decl_match.group("name") != name:
                continue
            if int(decl_match.group("version")) != version:
                continue
            return LanguageLocation(
                uri=source.uri,
                range=LanguageRange.at(
                    line_no,
                    codepoint_to_utf16(line_text, decl_match.start("name")),
                    line_no,
                    codepoint_to_utf16(line_text, decl_match.end("name")),
                ),
            )
    return None


def _find_field_location(
    workspace: Workspace,
    domain_name: str,
    kind: str,
    name: str,
    version: int,
    field_name: str,
) -> LanguageLocation | None:
    for source in workspace.sources:
        current_domain: str | None = None
        active = False
        lines = document_lines(source.text)
        pattern = _MODEL_FIELD_PATTERN if kind == "model" else _PROJECTION_FIELD_PATTERN

        for line_no, line_text in enumerate(lines):
            domain_match = _DOMAIN_PATTERN.match(line_text)
            if domain_match:
                current_domain = domain_match.group("quoted") or domain_match.group("name")
                active = False
                continue
            decl_match = _DECL_PATTERN.match(line_text)
            if decl_match and current_domain == domain_name:
                decl_kind = decl_match.group("kind")
                active = (
                    (decl_kind in _MODEL_DECL_KINDS if kind == "model" else decl_kind == kind)
                    and decl_match.group("name") == name
                    and int(decl_match.group("version")) == version
                )
                continue
            if not active:
                continue
            field_match = pattern.match(line_text)
            if field_match and field_match.group("name") == field_name:
                return LanguageLocation(
                    uri=source.uri,
                    range=LanguageRange.at(
                        line_no,
                        codepoint_to_utf16(line_text, field_match.start("name")),
                        line_no,
                        codepoint_to_utf16(line_text, field_match.end("name")),
                    ),
                )
            if line_text.strip() == "}":
                active = False
    return None


def _dedupe_locations(locations: list[LanguageLocation]) -> list[LanguageLocation]:
    seen: set[tuple[str, int, int, int, int]] = set()
    deduped: list[LanguageLocation] = []
    for location in locations:
        key = (
            location.uri,
            location.range.start.line,
            location.range.start.character,
            location.range.end.line,
            location.range.end.character,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(location)
    return deduped


def _current_scope(text: str, line: int) -> tuple[str, str, str, int] | None:
    lines = document_lines(text)
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
        if decl_match and current_domain is not None and decl_match.group("kind") != "semantic":
            current_kind = "model" if decl_match.group("kind") != "projection" else "projection"
            current_name = decl_match.group("name")
            current_version = int(decl_match.group("version"))
    if current_domain and current_kind and current_name and current_version is not None:
        return current_domain, current_kind, current_name, current_version
    return None
