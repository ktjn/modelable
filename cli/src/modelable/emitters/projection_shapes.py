from __future__ import annotations

from typing import Any

from modelable.emitters.shapes import TypeShape
from modelable.parser.ir import DirectMapping, MdlFile, ProjectionVersion
from modelable.registry.resolver import resolve_model_ref


def projection_field_shape(field: Any, projection: ProjectionVersion, mdl: MdlFile) -> TypeShape | None:
    """Resolve a projection field to the shape of the source model field it maps.

    Returns ``None`` when the field is not a direct mapping or the source
    model/field cannot be resolved; callers then degrade the field to their
    target's ``any`` type and record a type-loss warning.
    """
    if not isinstance(field.mapping, DirectMapping):
        return None
    try:
        source_domain, source_model = projection.source.model.rsplit(".", 1)
    except ValueError:
        return None
    try:
        resolved = resolve_model_ref(mdl, f"{source_domain}.{source_model}", projection.source.version)
    except LookupError:
        return None
    for source_field in resolved.version.fields:
        if source_field.name == field.mapping.source_field and hasattr(source_field, "type"):
            return TypeShape.from_field_type(source_field.type, optional=getattr(source_field, "optional", False))
    return None
