"""OpenMetadata projection emission from validated modelable.plan/v1 data."""

from __future__ import annotations

from typing import cast

from modelable.planner.protocol import PlanDocument, validate_plan


def emit_openmetadata_projection_plan(plan: PlanDocument) -> tuple[dict[str, object], list[dict[str, str]]]:
    """Build one OpenMetadata projection asset from a validated plan document."""
    plan = validate_plan(plan)
    domain = _plan_string(plan, "domain")
    projection = _plan_string(plan, "projection")
    version = _plan_integer(plan, "version")
    source = _plan_mapping(plan, "source")
    source_model = _plan_string(source, "model")
    source_version = _plan_mapping(source, "version")
    source_alias = _plan_string(source, "alias")
    relations = [source, *(_plan_mapping_value(value, "join") for value in _plan_list(plan, "joins"))]

    fields: list[dict[str, object]] = []
    lineage: list[dict[str, str]] = []
    for field_value in _plan_list(plan, "fields"):
        field = _plan_mapping_value(field_value, "field")
        name = _plan_string(field, "name")
        kind = _plan_string(field, "kind")
        source_field_name = field.get("source_field")
        source_relation = source
        if isinstance(source_field_name, str):
            source_relation = next(
                (relation for relation in relations if relation.get("alias") == field.get("source_alias")),
                source,
            )
        relation_version = _plan_mapping(source_relation, "version")
        source_fields = _plan_source_fields(source_relation.get("resolved"))
        source_field = source_fields.get(source_field_name) if isinstance(source_field_name, str) else None
        pii = _plan_bool(field, "pii") or (source_field is not None and _plan_bool(source_field, "pii"))
        classification = field.get("classification") or (
            source_field.get("classification") if source_field is not None else None
        )
        if kind == "direct":
            data = {
                "name": name,
                "mapping": kind,
                "source": _plan_source_field_ref(
                    _plan_string(source_relation, "model"), relation_version, source_field_name
                ),
                "pii": pii,
                "classification": classification,
            }
            resolved_version = source_relation.get("resolved_version")
            if isinstance(resolved_version, int):
                source_domain, source_name = _split_model_ref(_plan_string(source_relation, "model"))
                lineage.append(
                    {
                        "from": f"{_asset_fqn(source_domain, source_name, resolved_version)}.{source_field_name}",
                        "to": f"{_asset_fqn(domain, projection, version)}.{name}",
                        "kind": "direct",
                    }
                )
        elif kind == "computed":
            data = {
                "name": name,
                "mapping": kind,
                "expression": _plan_string(field, "expression"),
                "pii": pii,
                "classification": classification,
            }
        else:
            data = {"name": name, "mapping": kind, "pii": pii, "classification": None}
        fields.append(data)

    asset: dict[str, object] = {
        "name": projection,
        "kind": "projection",
        "version": version,
        "fullyQualifiedName": _asset_fqn(domain, projection, version),
        "source": {"model": source_model, "version": source_version, "alias": source_alias},
        "fields": fields,
    }
    joins = _plan_list(plan, "joins")
    if joins:
        asset["joins"] = [
            {
                "model": _plan_string(join, "model"),
                "version": _plan_mapping(join, "version"),
                "alias": _plan_string(join, "alias"),
                "on": _plan_string(join, "on"),
                "kind": _plan_string(join, "kind"),
                "cardinality": join.get("cardinality"),
            }
            for join in (_plan_mapping_value(value, "join") for value in joins)
        ]
    where = plan.get("where")
    if where is not None:
        asset["where"] = where
    group_by = _plan_list(plan, "group_by")
    if group_by:
        asset["groupBy"] = group_by
    return asset, lineage


def _plan_mapping(mapping: dict[str, object], name: str) -> dict[str, object]:
    value = mapping.get(name)
    if not isinstance(value, dict):
        raise ValueError(f"plan {name} must be an object")
    return cast(dict[str, object], value)


def _plan_mapping_value(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"plan {name} must be an object")
    return cast(dict[str, object], value)


def _plan_list(mapping: dict[str, object], name: str) -> list[object]:
    value = mapping.get(name)
    if not isinstance(value, list):
        raise ValueError(f"plan {name} must be an array")
    return value


def _plan_string(mapping: dict[str, object], name: str) -> str:
    value = mapping.get(name)
    if not isinstance(value, str):
        raise ValueError(f"plan {name} must be a string")
    return value


def _plan_integer(mapping: dict[str, object], name: str) -> int:
    value = mapping.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"plan {name} must be an integer")
    return value


def _plan_bool(mapping: dict[str, object], name: str) -> bool:
    value = mapping.get(name)
    if not isinstance(value, bool):
        raise ValueError(f"plan {name} must be a boolean")
    return value


def _plan_source_fields(value: object) -> dict[str, dict[str, object]]:
    if not isinstance(value, dict):
        return {}
    fields = value.get("fields")
    if not isinstance(fields, list):
        return {}
    return {
        _plan_string(field, "name"): field
        for field in (cast(dict[str, object], item) for item in fields)
        if isinstance(field, dict) and isinstance(field.get("name"), str)
    }


def _plan_source_field_ref(model: str, version: dict[str, object], field: object) -> str:
    field_name = field if isinstance(field, str) else ""
    kind = _plan_string(version, "kind")
    if kind == "exact":
        return f"{model}@{_plan_integer(version, 'version')}.{field_name}"
    if kind == "pinned":
        return f"{model}@{_plan_integer(version, 'version')}#{_plan_string(version, 'contentHash')}.{field_name}"
    if kind == "range":
        return (
            f"{model}@>={_plan_integer(version, 'minInclusive')}<{_plan_integer(version, 'maxExclusive')}.{field_name}"
        )
    return f"{model}@>={_plan_integer(version, 'minInclusive')}.{field_name}"


def _asset_fqn(domain: str, name: str, version: int) -> str:
    return f"modelable.{domain}.{name}.v{version}"


def _split_model_ref(model: str) -> tuple[str, str]:
    if "." not in model:
        return "", model
    domain, name = model.rsplit(".", 1)
    return domain, name
