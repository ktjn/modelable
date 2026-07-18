from __future__ import annotations

import re

from lsprotocol import types

from modelable.compiler.workspace import Workspace
from modelable.llm.context import parse_model_ref
from modelable.lsp.workspace import LspWorkspaceIndex
from modelable.registry.resolver import resolve_model_ref

_QUALIFIED_REF_PATTERN = re.compile(
    r"(?P<domain>[A-Za-z_][A-Za-z0-9_]*)\.(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*@\s*(?P<version>\d+)"
)
_REF_TYPE_PATTERN = re.compile(r"ref\s*<\s*(?P<domain>[A-Za-z_][A-Za-z0-9_]*)\.(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*>")
_FIELD_REF_PATTERN = re.compile(r"(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\.(?P<field>[A-Za-z_][A-Za-z0-9_]*)")
_DECL_PATTERN = re.compile(
    r"^\s*(?P<kind>entity|aggregate|event|value|projection)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*@\s*(?P<version>\d+)"
)
_DOMAIN_PATTERN = re.compile(r'^\s*domain\s+(?:"(?P<quoted>[^"]+)"|(?P<name>[A-Za-z_][A-Za-z0-9_]*))')
_WORD_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_MODEL_FIELD_PATTERN = re.compile(
    r"^\s*(?:@[A-Za-z_][A-Za-z0-9_]*(?:\([^)]*\))?\s+)*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\??\s*:"
)
_PROJECTION_FIELD_PATTERN = re.compile(
    r"^\s*(?:@[A-Za-z_][A-Za-z0-9_]*(?:\([^)]*\))?\s+)*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:<-|=)"
)


_MODEL_DECL_KINDS = {"entity", "aggregate", "event", "value"}


def build_definition(
    index: LspWorkspaceIndex, uri: str, line: int, character: int
) -> types.Location | list[types.Location] | None:
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
            location = _definition_for_qualified_ref(workspace, ref)
            if location is not None:
                return location

    for match in _REF_TYPE_PATTERN.finditer(text_line):
        if _contains(match.start(), match.end(), character):
            location = _definition_for_unversioned_ref(workspace, match.group("domain"), match.group("name"))
            if location is not None:
                return location

    for match in _FIELD_REF_PATTERN.finditer(text_line):
        if _contains(match.start(), match.end(), character):
            location = _definition_for_field_reference(
                workspace,
                source.text,
                line,
                match.group("alias"),
                match.group("field"),
            )
            if location is not None:
                return location

    word = _word_at(text_line, character)
    if word is None:
        return None

    scope = _current_scope(source.text, line)
    if scope is None:
        return None
    domain_name, kind, name, version = scope

    if word == name:
        return _definition_for_decl(workspace, domain_name, kind, name, version)

    if kind == "model":
        return _definition_for_model_field(
            workspace,
            domain_name,
            name,
            version,
            word,
        )
    return _definition_for_projection_field(
        workspace,
        domain_name,
        name,
        version,
        word,
    )


def _definition_for_qualified_ref(workspace, ref: str) -> types.Location | None:
    model_ref = parse_model_ref(ref)
    domain = next((d for d in workspace.mdl.domains if d.name == model_ref.domain), None)
    if domain is None:
        return None
    if model_ref.name in domain.models:
        return _definition_for_decl(workspace, model_ref.domain, "model", model_ref.name, model_ref.version)
    if model_ref.name in domain.projections:
        return _definition_for_decl(workspace, model_ref.domain, "projection", model_ref.name, model_ref.version)
    return None


def definition_location_for_ref(workspace: Workspace, ref: str) -> types.Location | None:
    return _definition_for_qualified_ref(workspace, ref)


def _definition_for_unversioned_ref(workspace, domain_name: str, name: str) -> types.Location | None:
    domain = next((d for d in workspace.mdl.domains if d.name == domain_name), None)
    if domain is None:
        return None
    if name in domain.models:
        latest = max(domain.models[name], key=lambda v: v.version)
        return _definition_for_decl(workspace, domain_name, "model", name, latest.version)
    if name in domain.projections:
        latest = max(domain.projections[name], key=lambda v: v.version)
        return _definition_for_decl(workspace, domain_name, "projection", name, latest.version)
    return None


def _definition_for_field_reference(
    workspace,
    text: str,
    line: int,
    alias: str,
    field_name: str,
) -> types.Location | None:
    scope = _current_scope(text, line)
    if scope is None:
        return None
    domain_name, kind, name, version = scope
    if kind == "model":
        return _definition_for_model_field(workspace, domain_name, name, version, field_name)

    domain = next((d for d in workspace.mdl.domains if d.name == domain_name), None)
    if domain is None:
        return None
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
        return _definition_for_source_field(
            workspace,
            resolved.domain_name,
            resolved.model_name,
            resolved.version.version,
            field_name,
        )

    return _definition_for_projection_field(workspace, domain_name, name, version, field_name)


def _definition_for_decl(
    workspace,
    domain_name: str,
    kind: str,
    name: str,
    version: int,
) -> types.Location | None:
    for source in workspace.sources:
        location = _find_decl_location(source.uri, source.text, domain_name, kind, name, version)
        if location is not None:
            return location
    return None


def _definition_for_model_field(
    workspace,
    domain_name: str,
    model_name: str,
    version: int,
    field_name: str,
) -> types.Location | None:
    return _definition_for_source_field(workspace, domain_name, model_name, version, field_name)


def _definition_for_source_field(
    workspace,
    domain_name: str,
    model_name: str,
    version: int,
    field_name: str,
) -> types.Location | None:
    for source in workspace.sources:
        for kind in ("model", "projection"):
            location = _find_field_location(
                source.uri,
                source.text,
                domain_name,
                kind,
                model_name,
                version,
                field_name,
            )
            if location is not None:
                return location
    return None


def _definition_for_projection_field(
    workspace,
    domain_name: str,
    projection_name: str,
    version: int,
    field_name: str,
) -> types.Location | None:
    return _definition_for_source_field(workspace, domain_name, projection_name, version, field_name)


def _find_decl_location(
    uri: str,
    text: str,
    domain_name: str,
    kind: str,
    name: str,
    version: int,
) -> types.Location | None:
    current_domain: str | None = None
    lines = text.splitlines()
    for line_no, line in enumerate(lines):
        domain_match = _DOMAIN_PATTERN.match(line)
        if domain_match:
            current_domain = domain_match.group("quoted") or domain_match.group("name")
            continue
        decl_match = _DECL_PATTERN.match(line)
        if not decl_match or current_domain != domain_name:
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
        return types.Location(
            uri=uri,
            range=types.Range(
                start=types.Position(line=line_no, character=decl_match.start("name")),
                end=types.Position(line=line_no, character=decl_match.end("name")),
            ),
        )
    return None


def _find_field_location(
    uri: str,
    text: str,
    domain_name: str,
    kind: str,
    name: str,
    version: int,
    field_name: str,
) -> types.Location | None:
    current_domain: str | None = None
    active = False
    lines = text.splitlines()
    pattern = _MODEL_FIELD_PATTERN if kind == "model" else _PROJECTION_FIELD_PATTERN

    for line_no, line in enumerate(lines):
        domain_match = _DOMAIN_PATTERN.match(line)
        if domain_match:
            current_domain = domain_match.group("quoted") or domain_match.group("name")
            active = False
            continue
        decl_match = _DECL_PATTERN.match(line)
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
        field_match = pattern.match(line)
        if field_match and field_match.group("name") == field_name:
            return types.Location(
                uri=uri,
                range=types.Range(
                    start=types.Position(line=line_no, character=field_match.start("name")),
                    end=types.Position(line=line_no, character=field_match.end("name")),
                ),
            )
        if line.strip() == "}":
            active = False
    return None


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


def _contains(start: int, end: int, character: int) -> bool:
    return start <= character <= max(end - 1, start)
