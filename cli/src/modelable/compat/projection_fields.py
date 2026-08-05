from __future__ import annotations

from modelable.dependency_graph import resolve_projection_aliases
from modelable.parser.ir import ComputedMapping, FieldType, MdlFile, ModelVersion, ProjectionField, ProjectionVersion


def resolve_projection_field_type_and_optionality(
    field: ProjectionField,
    projection: ProjectionVersion,
    mdl: MdlFile,
) -> tuple[FieldType | None, bool | None]:
    """Resolve a projection field's effective type and optionality from its source.

    Computed-mapping fields have no traceable source field, so both values
    are None for them. Direct-mapping fields resolve through the same
    canonical alias walk `dependency_graph.resolve_projection_aliases` uses,
    so this always agrees with how the rest of the compiler resolves "what
    does alias X refer to" for a projection. Handles projections sourced
    from other projections by recursing through the nested projection's own
    mapping.
    """
    if isinstance(field.mapping, ComputedMapping):
        return None, None

    aliases = resolve_projection_aliases(projection, mdl)
    resolved = aliases.get(field.mapping.source_alias)
    if resolved is None:
        return None, None

    return _resolve_field_from_version(resolved.version, field.mapping.source_field, mdl)


def _resolve_field_from_version(
    version: ModelVersion | ProjectionVersion,
    field_name: str,
    mdl: MdlFile,
) -> tuple[FieldType | None, bool | None]:
    if isinstance(version, ModelVersion):
        for source_field in version.fields:
            if source_field.name == field_name:
                return source_field.type, source_field.optional
        return None, None

    nested_field = next((f for f in version.fields if f.name == field_name), None)
    if nested_field is None:
        return None, None
    return resolve_projection_field_type_and_optionality(nested_field, version, mdl)
