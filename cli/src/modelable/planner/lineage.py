"""Projection-level lineage: maps each output field to its source field(s)."""

from __future__ import annotations

from dataclasses import dataclass, field

from modelable.expressions.cel import extract_field_refs, parse_cel
from modelable.parser.ir import ComputedMapping, DirectMapping, MdlFile, ProjectionVersion
from modelable.registry.resolver import resolved_version_spec


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
            ref = alias_map.get(mapping.source_alias, mapping.source_alias)
            lineage_refs = [f"{ref}.{mapping.source_field}"]
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
                model_ref = alias_map.get(alias, alias)
                lineage_refs.append(f"{model_ref}.{field_name}")
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
            alias_map[alias] = f"{model_ref}@{resolved.version}"
        except LookupError:
            pass

    return alias_map
