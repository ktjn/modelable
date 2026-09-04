from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from modelable.expressions.cel import extract_field_refs, parse_cel
from modelable.parser.ir import ComputedMapping, DirectMapping, MdlFile, ProjectionVersion
from modelable.registry.resolver import ResolvedDeclaration, resolve_model_ref

UsageKind = Literal["direct", "computed", "join", "filter", "group"]


@dataclass(frozen=True)
class PropertyDependency:
    consumer_ref: str
    target_property: str | None
    usage_kind: UsageKind
    source_ref: str
    source_property: str


def resolve_projection_aliases(pv: ProjectionVersion, mdl: MdlFile) -> dict[str, ResolvedDeclaration]:
    """Resolve every source/join alias on a projection version to its concrete source.

    This is the one canonical alias-resolution walk; every subsystem that needs
    "what does alias X refer to" for a projection should call this instead of
    re-walking `pv.source`/`pv.joins` itself.
    """
    aliases: dict[str, ResolvedDeclaration] = {}
    sources = [(pv.source.model, pv.source.version, pv.source.alias)]
    sources.extend((join.model, join.version, join.alias) for join in pv.joins)

    for model_ref, version_spec, alias in sources:
        try:
            aliases[alias] = resolve_model_ref(mdl, model_ref, version_spec)
        except LookupError:
            continue

    return aliases


def build_projection_dependencies(
    mdl: MdlFile,
    domain_name: str,
    projection_name: str,
    pv: ProjectionVersion,
) -> list[PropertyDependency]:
    """Build the full set of source-property dependencies for one projection version.

    Covers direct mappings, computed expressions, join predicates, `where`
    filters, and `group by` keys — the complete set of positions a projection
    can reference a source property from.
    """
    consumer_ref = f"{domain_name}.{projection_name}@{pv.version}"
    aliases = resolve_projection_aliases(pv, mdl)
    dependencies: list[PropertyDependency] = []

    for field in pv.fields:
        mapping = field.mapping
        if isinstance(mapping, DirectMapping):
            resolved = aliases.get(mapping.source_alias)
            if resolved is not None:
                dependencies.append(
                    PropertyDependency(
                        consumer_ref=consumer_ref,
                        target_property=field.name,
                        usage_kind="direct",
                        source_ref=_source_ref(resolved),
                        source_property=mapping.source_field,
                    )
                )
        elif isinstance(mapping, ComputedMapping):
            dependencies.extend(
                _refs_from_expression(mapping.expression, aliases, consumer_ref, field.name, "computed")
            )

    for join in pv.joins:
        dependencies.extend(_refs_from_expression(join.on, aliases, consumer_ref, None, "join"))

    if pv.where:
        dependencies.extend(_refs_from_expression(pv.where, aliases, consumer_ref, None, "filter"))

    for group_expr in pv.group_by:
        dependencies.extend(_refs_from_expression(group_expr, aliases, consumer_ref, None, "group"))

    return dependencies


def _refs_from_expression(
    expression: str,
    aliases: dict[str, ResolvedDeclaration],
    consumer_ref: str,
    target_property: str | None,
    usage_kind: UsageKind,
) -> list[PropertyDependency]:
    expr_ast, _errors = parse_cel(expression)
    if expr_ast is None:
        return []

    dependencies: list[PropertyDependency] = []
    for alias, field_name in extract_field_refs(expr_ast):
        resolved = aliases.get(alias)
        if resolved is None:
            continue
        dependencies.append(
            PropertyDependency(
                consumer_ref=consumer_ref,
                target_property=target_property,
                usage_kind=usage_kind,
                source_ref=_source_ref(resolved),
                source_property=field_name,
            )
        )
    return dependencies


def _source_ref(resolved: ResolvedDeclaration) -> str:
    return resolved.identity
