from __future__ import annotations

import re

from lsprotocol import types

from modelable.lsp.workspace import LspWorkspaceIndex
from modelable.registry.resolver import resolve_model_ref

_DOMAIN_PATTERN = re.compile(r"^\s*domain\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)")
_DECL_PATTERN = re.compile(
    r"^\s*(?P<kind>entity|aggregate|event|value|projection)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*@\s*(?P<version>\d+)"
)
_SOURCE_PATTERN = re.compile(
    r"^\s*(?:left\s+)?(?:from|join)\s+"
    r"(?P<domain>[A-Za-z_][A-Za-z0-9_.-]*)\.(?P<model>[A-Za-z_][A-Za-z0-9_.-]*)"
    r"\s*@\s*(?P<version>\d+)(?:\s+as\s+(?P<alias>[A-Za-z_][A-Za-z0-9_]*))?"
)
_DIRECT_MAPPING_PATTERN = re.compile(
    r"^\s*(?:@[A-Za-z_][A-Za-z0-9_]*(?:\([^)]*\))?\s+)*"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*<-\s*"
    r"(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\.(?P<field>[A-Za-z_][A-Za-z0-9_]*)"
)


def build_inlay_hints(
    index: LspWorkspaceIndex,
    uri: str,
    range: types.Range,
) -> list[types.InlayHint] | None:
    source = index.documents.get(uri)
    workspace = index.workspace
    if source is None or workspace is None:
        return None

    hints: list[types.InlayHint] = []
    lines = source.text.splitlines()
    current_domain: str | None = None
    in_projection = False
    alias_map: dict[str, tuple[str, str, int]] = {}

    for line_no, line in enumerate(lines):
        domain_match = _DOMAIN_PATTERN.match(line)
        if domain_match:
            current_domain = domain_match.group("name")
            in_projection = False
            alias_map = {}
            continue

        decl_match = _DECL_PATTERN.match(line)
        if decl_match and current_domain is not None:
            in_projection = decl_match.group("kind") == "projection"
            alias_map = {}
            continue

        source_match = _SOURCE_PATTERN.match(line)
        if source_match and in_projection:
            domain_name = source_match.group("domain")
            model_name = source_match.group("model")
            version = int(source_match.group("version"))
            alias = source_match.group("alias")
            if alias:
                try:
                    resolved = resolve_model_ref(workspace.mdl, f"{domain_name}.{model_name}", version)
                    alias_map[alias] = (resolved.domain_name, resolved.model_name, resolved.version.version)
                except LookupError:
                    pass
            if range.start.line <= line_no <= range.end.line:
                kind_label = _resolve_model_kind(workspace, domain_name, model_name, version)
                if kind_label is not None:
                    hints.append(
                        types.InlayHint(
                            position=types.Position(line=line_no, character=source_match.end("version")),
                            label=f" [{kind_label}]",
                            kind=types.InlayHintKind.Type,
                        )
                    )
            continue

        if not in_projection or current_domain is None:
            continue

        if range.start.line <= line_no <= range.end.line:
            direct_match = _DIRECT_MAPPING_PATTERN.match(line)
            if direct_match:
                alias = direct_match.group("alias")
                source_field_name = direct_match.group("field")
                target = alias_map.get(alias)
                if target is not None:
                    field_type = _resolve_field_type(workspace, *target, source_field_name)
                    if field_type is not None:
                        hints.append(
                            types.InlayHint(
                                position=types.Position(line=line_no, character=direct_match.end("name")),
                                label=f": {field_type}",
                                kind=types.InlayHintKind.Type,
                            )
                        )

    return hints


def _resolve_model_kind(workspace, domain_name: str, model_name: str, version: int) -> str | None:
    domain = next((d for d in workspace.mdl.domains if d.name == domain_name), None)
    if domain is None:
        return None
    versions = domain.models.get(model_name, [])
    model_version = next((item for item in versions if item.version == version), None)
    if model_version is not None:
        return model_version.model_kind.value
    versions = domain.projections.get(model_name, [])
    if any(item.version == version for item in versions):
        return "projection"
    return None


def _resolve_field_type(
    workspace,
    domain_name: str,
    model_name: str,
    version: int,
    field_name: str,
) -> str | None:
    domain = next((d for d in workspace.mdl.domains if d.name == domain_name), None)
    if domain is None:
        return None
    versions = domain.models.get(model_name, [])
    model_version = next((item for item in versions if item.version == version), None)
    if model_version is None:
        return None
    field = next((f for f in model_version.fields if f.name == field_name), None)
    if field is None:
        return None
    return field.type.kind
