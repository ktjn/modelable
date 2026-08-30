"""OpenAPI component-schema emission from validated ``modelable.plan/v0``."""

from __future__ import annotations

from typing import Any, cast

from modelable.emitters.json_schema_plan import _field_schema, _mapping_or_none
from modelable.governance.por import build_por_reference
from modelable.planner.protocol import PlanDocument, validate_plan


def emit_openapi_projection_plan(
    plan: PlanDocument,
    projection_kind: str | None,
    components: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Build one OpenAPI component schema from a validated projection plan."""
    document = validate_plan(plan)
    domain = _string(document, "domain")
    projection = _string(document, "projection")
    version = _integer(document, "version")
    source = _mapping(document, "source")
    modelable = {
        "domain": domain,
        "name": projection,
        "kind": projection_kind or "projection",
        "sourceEntity": f"{_string(source, 'model')}@{_version_label(_mapping(source, 'version'))}",
        "version": version,
    }
    fields = _list(document, "fields")
    definitions: dict[str, dict[str, object]] = {}
    properties: dict[str, object] = {}
    for value in fields:
        field = _mapping_value(value, "field")
        field_type = _mapping_or_none(field.get("type"))
        if field_type is not None and field_type.get("kind") == "ref":
            resolved_key_type = _mapping_or_none(field_type.get("resolved_key_type"))
            if resolved_key_type is not None:
                field_type = resolved_key_type
        properties[_string(field, "name")] = _field_schema(
            field,
            field_type,
            definitions,
            [_string(field, "name")],
            inherited_constraints=[],
        )
    for name, definition in definitions.items():
        components[name] = cast(dict[str, Any], _rewrite_refs(definition))
    required = [
        _string(_mapping_value(field, "field"), "name")
        for field in fields
        if _mapping_value(field, "field").get("optional") is not True
    ]
    return {
        "type": "object",
        "title": projection,
        "x-modelable": modelable,
        "x-modelable-por": build_por_reference(f"{domain}.{projection}.v{version}"),
        "properties": _rewrite_refs(properties),
        "required": required,
    }


def _rewrite_refs(value: object) -> object:
    if isinstance(value, str):
        return value.replace("#/$defs/", "#/components/schemas/")
    if isinstance(value, list):
        return [_rewrite_refs(item) for item in value]
    if isinstance(value, dict):
        return {key: _rewrite_refs(item) for key, item in value.items()}
    return value


def _version_label(version: dict[str, object]) -> str:
    kind = _string(version, "kind")
    if kind in {"exact", "pinned"}:
        label = str(_integer(version, "version"))
        if kind == "pinned":
            label += f"#{_string(version, 'contentHash')}"
        return label
    if kind == "range":
        return f">={_integer(version, 'minInclusive')}<{_integer(version, 'maxExclusive')}"
    return f">={_integer(version, 'minInclusive')}"


def _mapping(mapping: dict[str, object], name: str) -> dict[str, object]:
    return _mapping_value(mapping.get(name), name)


def _mapping_value(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"plan {name} must be an object")
    return cast(dict[str, object], value)


def _list(mapping: dict[str, object], name: str) -> list[object]:
    value = mapping.get(name)
    if not isinstance(value, list):
        raise ValueError(f"plan {name} must be an array")
    return value


def _string(mapping: dict[str, object], name: str) -> str:
    value = mapping.get(name)
    if not isinstance(value, str):
        raise ValueError(f"plan {name} must be a string")
    return value


def _integer(mapping: dict[str, object], name: str) -> int:
    value = mapping.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"plan {name} must be an integer")
    return value
