"""Parser-free Avro event projection consumer for ``modelable.plan/v0``."""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import PurePath
from typing import Any, cast

from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.diagnostics import emit_warning, enum_member_collision, type_loss
from modelable.emitters.naming import find_identifier_collisions
from modelable.planner.protocol import PlanDocument, validate_plan


@dataclass
class _Context:
    namespace: str
    warnings: list[str] = dataclass_field(default_factory=list)
    named: set[str] = dataclass_field(default_factory=set)


def emit_avro_projection_plan(plan: PlanDocument, out_dir: PurePath) -> EmittedArtifact:
    """Emit one event projection from a validated plan document."""
    document = validate_plan(plan)
    domain = _string(document, "domain")
    name = _string(document, "projection")
    version = _integer(document, "version")
    ref = f"{domain}.{name}@{version}"
    context = _Context(domain)
    source_by_alias = _source_fields(document)
    fields: list[dict[str, Any]] = []
    for field_document in _list_of_mappings(document, "fields"):
        source = None
        if field_document.get("kind") == "direct":
            source = source_by_alias.get(
                (
                    _string(field_document, "source_alias"),
                    _string(field_document, "source_field"),
                )
            )
        if source is None:
            context.warnings.append(type_loss(f"Avro computed field {_string(field_document, 'name')}"))
            fields.append({"name": _string(field_document, "name"), "type": {"kind": "primitive", "type": "string"}})
        else:
            fields.append({"name": _string(field_document, "name"), **source})

    avro_fields: list[dict[str, Any]] = []
    for field_document in fields:
        field_type = field_document.get("type")
        schema = _field_schema(field_document, field_type, context, [name, _string(field_document, "name")])
        entry = {"name": _avro_name(_string(field_document, "name")), "type": schema}
        default = field_document.get("default")
        if isinstance(default, str):
            entry["default"] = _parse_default(default, schema)
        elif field_document.get("optional") or field_document.get("nullable"):
            entry["default"] = None
        avro_fields.append(entry)

    schema = {
        "type": "record",
        "name": _avro_name(f"{name}V{version}"),
        "namespace": domain,
        "fields": avro_fields,
        "x-modelable": {"ref": ref, "kind": "event", "version": version},
    }
    return EmittedArtifact(
        target="avro",
        ref=ref,
        artifact_id=f"{domain}.{name}.v{version}",
        path=out_dir / domain / f"{name}.v{version}.avsc",
        content=schema,
        content_hash=compute_content_hash(schema),
        warnings=context.warnings,
    )


def _source_fields(plan: PlanDocument) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    relations = [_mapping(plan, "source"), *_list_of_mappings(plan, "joins")]
    for relation in relations:
        alias = _string(relation, "alias")
        resolved = relation.get("resolved")
        if not isinstance(resolved, dict):
            continue
        for field_document in resolved.get("fields", []):
            if isinstance(field_document, dict) and isinstance(field_document.get("name"), str):
                result[(alias, field_document["name"])] = cast(dict[str, Any], field_document)
    return result


def _field_schema(field: dict[str, Any], field_type: object, context: _Context, path: list[str]) -> Any:
    schema = _type_schema(field_type, context, path)
    if field.get("nullable") or field.get("optional"):
        return ["null", schema]
    return schema


def _type_schema(field_type: object, context: _Context, path: list[str]) -> Any:
    if not isinstance(field_type, dict):
        return "string"
    kind = field_type.get("kind")
    if kind in {
        "bool",
        "int",
        "i8",
        "i16",
        "i32",
        "u8",
        "u16",
        "u32",
        "i64",
        "u64",
        "i128",
        "u128",
        "float",
        "binary",
        "date",
        "time",
        "timestamp",
        "duration",
        "uuid",
        "json",
        "string",
    }:
        return _primitive_schema(kind)
    if kind == "decimal":
        return {
            "type": "bytes",
            "logicalType": "decimal",
            "precision": field_type.get("precision"),
            "scale": field_type.get("scale"),
        }
    if kind == "fixed_binary":
        return {"type": "fixed", "name": _avro_name("".join(path) + "Fixed"), "size": field_type.get("length")}
    if kind == "array":
        return {"type": "array", "items": _type_schema(field_type.get("item"), context, [*path, "Item"])}
    if kind == "map":
        key = field_type.get("key")
        if not (isinstance(key, dict) and key.get("kind") == "string"):
            context.warnings.append(type_loss(f"Avro map key at {'.'.join(path)}; Avro requires string keys"))
        return {"type": "map", "values": _type_schema(field_type.get("value"), context, [*path, "Value"])}
    if kind == "enum":
        values = [str(value) for value in field_type.get("values", [])]
        name = _avro_name("".join(path) + "Enum")
        for identifier, members in find_identifier_collisions(values, _avro_name).items():
            context.warnings.append(enum_member_collision("avro", ".".join(path), identifier, members))
        return {"type": "enum", "name": name, "symbols": [_avro_name(value) for value in values]}
    if kind == "enum_ref":
        return _enum_ref_schema(field_type, context)
    if kind == "object":
        return _record_type(field_type.get("fields"), context, path)
    if kind == "ref":
        resolved = field_type.get("resolved_key_type")
        if resolved is not None:
            return _type_schema(resolved, context, [*path, "Ref"])
        context.warnings.append(type_loss(f"unresolved Avro reference {field_type.get('target', '')}"))
        return "string"
    if kind == "named":
        underlying = field_type.get("resolved_underlying_type")
        if underlying is not None:
            return _type_schema(underlying, context, [*path, str(field_type.get("name", ""))])
        resolved_model = field_type.get("resolved_model")
        if isinstance(resolved_model, dict):
            return _record_type(resolved_model.get("fields"), context, path)
        context.warnings.append(type_loss(f"unresolved Avro named type {field_type.get('name', '')}"))
        return "string"
    if kind == "union":
        context.warnings.append(emit_warning("EMIT002", "Avro union discriminator is not represented in a union"))
        return [
            _type_schema(item.get("type"), context, [*path, str(item.get("tag", "Variant"))])
            for item in field_type.get("variants", [])
            if isinstance(item, dict)
        ]
    return "string"


def _enum_ref_schema(field_type: dict[str, Any], context: _Context) -> Any:
    values = [str(value) for value in field_type.get("values", [])]
    name = _avro_name(str(field_type.get("name", "Enum")))
    namespace = str(field_type.get("declaring_domain", context.namespace))
    qualified = f"{namespace}.{name}"
    if f"enum:{qualified}" in context.named:
        return qualified
    context.named.add(f"enum:{qualified}")
    for identifier, members in find_identifier_collisions(values, _avro_name).items():
        context.warnings.append(enum_member_collision("avro", qualified, identifier, members))
    return {"type": "enum", "name": name, "namespace": namespace, "symbols": [_avro_name(value) for value in values]}


def _record_type(fields: object, context: _Context, path: list[str]) -> Any:
    name = _avro_name("".join(path))
    if name in context.named:
        return name
    context.named.add(name)
    rendered: list[dict[str, Any]] = []
    for field_document in fields if isinstance(fields, list) else []:
        if not isinstance(field_document, dict):
            continue
        field_name = _string(field_document, "name")
        schema = _field_schema(field_document, field_document.get("type"), context, [*path, field_name])
        entry = {"name": _avro_name(field_name), "type": schema}
        if isinstance(field_document.get("default"), str):
            entry["default"] = _parse_default(field_document["default"], schema)
        rendered.append(entry)
    return {"type": "record", "name": name, "fields": rendered}


def _primitive_schema(kind: object) -> Any:
    kind = str(kind)
    if kind == "bool":
        return "boolean"
    if kind in {"int", "i8", "i16", "i32", "u8", "u16", "u32"}:
        return "int"
    if kind in {"i64", "u64"}:
        return "long"
    if kind in {"i128", "u128"}:
        return {"type": "fixed", "name": f"Modelable{kind.upper()}", "size": 16}
    if kind == "float":
        return "double"
    if kind == "binary":
        return "bytes"
    if kind == "date":
        return {"type": "int", "logicalType": "date"}
    if kind == "time":
        return {"type": "int", "logicalType": "time-millis"}
    if kind == "timestamp":
        return {"type": "long", "logicalType": "timestamp-millis"}
    if kind == "duration":
        return {"type": "fixed", "name": "ModelableDuration", "size": 12, "logicalType": "duration"}
    if kind == "uuid":
        return {"type": "string", "logicalType": "uuid"}
    return "string"


def _parse_default(value: str, schema: Any) -> Any:
    if isinstance(schema, list):
        schema = schema[-1]
    if schema == "boolean":
        return value.lower() == "true"
    if isinstance(schema, str) and schema in {"int", "long", "float", "double"}:
        try:
            return float(value) if schema in {"float", "double"} else int(value)
        except ValueError:
            return value
    return value.strip('"')


def _avro_name(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9_]", "_", value)
    return f"_{result}" if not result or result[0].isdigit() else result


def _mapping(mapping: dict[str, object], key: str) -> dict[str, object]:
    value = mapping.get(key)
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def _list_of_mappings(mapping: dict[str, object], key: str) -> list[dict[str, Any]]:
    value = mapping.get(key)
    return [cast(dict[str, Any], item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _string(mapping: dict[str, object], key: str) -> str:
    return str(mapping.get(key, ""))


def _integer(mapping: dict[str, object], key: str) -> int:
    value = mapping.get(key)
    if not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    return value
