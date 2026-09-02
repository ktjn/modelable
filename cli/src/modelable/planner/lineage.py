"""Projection-level lineage: maps each output field to its source field(s)."""

from __future__ import annotations

from dataclasses import dataclass, field

from modelable.expressions.cel import extract_field_refs, parse_cel
from modelable.identity import semantic_path
from modelable.parser.ir import ComputedMapping, DirectMapping, MdlFile, ModelVersion, ProjectionVersion
from modelable.registry.resolver import resolve_model_ref, resolved_version_spec


@dataclass
class FieldLineage:
    field_name: str
    kind: str  # "direct" or "computed"
    lineage: list[str] = field(default_factory=list)
    expression: str | None = None


@dataclass
class ProjectionLineage:
    domain: str
    projection: str
    version: int
    fields: list[FieldLineage] = field(default_factory=list)


def build_projection_lineage(
    domain_name: str,
    projection_name: str,
    pv: ProjectionVersion,
    mdl: MdlFile,
) -> ProjectionLineage:
    """Build field-level lineage for a single projection version."""
    alias_map = _build_alias_map(pv, mdl)
    fields: list[FieldLineage] = []

    for proj_field in pv.fields:
        mapping = proj_field.mapping

        if isinstance(mapping, DirectMapping):
            ref = alias_map.get(mapping.source_alias)
            lineage_refs = _expand_lineage_ref(ref, mapping.source_field, mdl, stack=()) if ref is not None else []
            fields.append(
                FieldLineage(
                    field_name=proj_field.name,
                    kind="direct",
                    lineage=lineage_refs,
                )
            )

        elif isinstance(mapping, ComputedMapping):
            expr_ast, _ = parse_cel(mapping.expression)
            cel_refs = extract_field_refs(expr_ast) if expr_ast is not None else []
            lineage_refs = []
            for alias, field_name in cel_refs:
                model_ref = alias_map.get(alias)
                if model_ref is not None:
                    lineage_refs.extend(_expand_lineage_ref(model_ref, field_name, mdl, stack=()))
            fields.append(
                FieldLineage(
                    field_name=proj_field.name,
                    kind="computed",
                    lineage=lineage_refs,
                    expression=mapping.expression,
                )
            )

    return ProjectionLineage(
        domain=domain_name,
        projection=projection_name,
        version=pv.version,
        fields=fields,
    )


def _build_alias_map(pv: ProjectionVersion, mdl: MdlFile) -> dict[str, str]:
    """Return alias -> 'domain.Model@resolved_version' mapping."""
    alias_map: dict[str, str] = {}

    all_sources = [(pv.source.model, pv.source.version, pv.source.alias)]
    for join in pv.joins:
        all_sources.append((join.model, join.version, join.alias))

    for model_ref, version_spec, alias in all_sources:
        try:
            resolved = resolved_version_spec(mdl, model_ref, version_spec)
            target = resolve_model_ref(mdl, model_ref, resolved.version)
            alias_map[alias] = f"{target.domain_name}.{target.model_name}@{target.version.version}"
        except LookupError:
            pass

    return alias_map


def _canonical_lineage_ref(declaration: str, field_path: str) -> str:
    """Render a source field reference using the canonical semantic-path grammar."""
    return semantic_path(declaration, *field_path.split("."))


def _expand_lineage_ref(
    declaration_ref: str,
    field_path: str,
    mdl: MdlFile,
    *,
    stack: tuple[tuple[str, str], ...],
) -> list[str]:
    """Resolve a source field through projection hops to canonical model lineage."""
    declaration, separator, version_text = declaration_ref.rpartition("@")
    if not separator or not version_text.isdigit():
        return [_canonical_lineage_ref(declaration_ref, field_path)]

    try:
        resolved = resolve_model_ref(mdl, declaration, int(version_text))
    except LookupError:
        return [_canonical_lineage_ref(declaration_ref, field_path)]

    canonical_declaration = f"{resolved.domain_name}.{resolved.model_name}@{resolved.version.version}"
    if isinstance(resolved.version, ModelVersion):
        return [_canonical_lineage_ref(canonical_declaration, field_path)]

    current = (canonical_declaration, field_path)
    if current in stack:
        return [_canonical_lineage_ref(canonical_declaration, field_path)]

    source_aliases = _build_alias_map(resolved.version, mdl)
    source_field = next((field for field in resolved.version.fields if field.name == field_path), None)
    if source_field is None:
        return [_canonical_lineage_ref(canonical_declaration, field_path)]

    mapping = source_field.mapping
    next_stack = (*stack, current)
    if isinstance(mapping, DirectMapping):
        source_ref = source_aliases.get(mapping.source_alias)
        if source_ref is not None:
            return _expand_lineage_ref(source_ref, mapping.source_field, mdl, stack=next_stack)
    elif isinstance(mapping, ComputedMapping):
        expr_ast, _ = parse_cel(mapping.expression)
        refs = extract_field_refs(expr_ast) if expr_ast is not None else []
        expanded: list[str] = []
        for alias, nested_field in refs:
            source_ref = source_aliases.get(alias)
            if source_ref is not None:
                expanded.extend(_expand_lineage_ref(source_ref, nested_field, mdl, stack=next_stack))
        if expanded:
            return expanded

    return [_canonical_lineage_ref(canonical_declaration, field_path)]
