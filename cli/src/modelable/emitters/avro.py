from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any

from modelable.compiler.workspace import Workspace
from modelable.emitters._schema_mapping import _resolve_projection_source_field
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.diagnostics import emit_warning, enum_member_collision, type_loss
from modelable.emitters.naming import find_identifier_collisions
from modelable.parser.ir import (
    ArrayType,
    DecimalType,
    EnumType,
    FieldDef,
    FieldType,
    FixedBinaryType,
    MapType,
    ModelVersion,
    NamedType,
    ObjectType,
    PrimitiveType,
    ProjectionVersion,
    RefType,
    UnionType,
    VersionMin,
)
from modelable.registry.resolver import resolve_model_ref, resolve_ref_type, resolve_semantic_type_ref


@dataclass
class _AvroContext:
    workspace: Any
    namespace: str
    warnings: list[str] = field(default_factory=list)
    named: set[str] = field(default_factory=set)


def emit_avro(workspace: Workspace, out_dir: PurePath) -> list[EmittedArtifact]:
    """Emit deterministic Avro record schemas for models and event projections."""
    artifacts: list[EmittedArtifact] = []
    for domain in sorted(workspace.mdl.domains, key=lambda item: item.name):
        for name in sorted(domain.models):
            for model_version in sorted(domain.models[name], key=lambda item: item.version):
                ref = f"{domain.name}.{name}@{model_version.version}"
                artifacts.append(_emit_record(domain.name, name, model_version, ref, workspace, out_dir))
        for name in sorted(domain.projections):
            if not name.endswith("Event"):
                continue
            for projection_version in sorted(domain.projections[name], key=lambda item: item.version):
                ref = f"{domain.name}.{name}@{projection_version.version}"
                artifacts.append(_emit_projection(domain.name, name, projection_version, ref, workspace, out_dir))
    return artifacts


def _emit_record(
    domain_name: str,
    name: str,
    version: ModelVersion,
    ref: str,
    workspace: Workspace,
    out_dir: PurePath,
) -> EmittedArtifact:
    context = _AvroContext(workspace.mdl, domain_name)
    schema = _record_schema(name, version.fields, version.version, "model", ref, context)
    return _artifact(ref, domain_name, name, version.version, schema, context.warnings, out_dir)


def _emit_projection(
    domain_name: str,
    name: str,
    version: ProjectionVersion,
    ref: str,
    workspace: Workspace,
    out_dir: PurePath,
) -> EmittedArtifact:
    context = _AvroContext(workspace.mdl, domain_name)
    fields: list[FieldDef] = []
    for projection_field in version.fields:
        source = _resolve_projection_source_field(projection_field, version, workspace.mdl)
        if source is None:
            context.warnings.append(type_loss(f"Avro computed field {projection_field.name}"))
            fields.append(FieldDef(name=projection_field.name, type=PrimitiveType(kind="string")))
        else:
            fields.append(source.model_copy(update={"name": projection_field.name}))
    schema = _record_schema(name, fields, version.version, "event", ref, context)
    return _artifact(ref, domain_name, name, version.version, schema, context.warnings, out_dir)


def _record_schema(
    name: str,
    fields: Sequence[FieldDef],
    version: int,
    kind: str,
    ref: str,
    context: _AvroContext,
) -> dict[str, Any]:
    avro_fields: list[dict[str, Any]] = []
    for model_field in fields:
        field_schema = _field_schema(model_field, model_field.type, context, [name, model_field.name])
        entry: dict[str, Any] = {"name": _avro_name(model_field.name), "type": field_schema}
        if getattr(model_field, "default", None) is not None:
            entry["default"] = _parse_default(model_field.default, field_schema)
        elif model_field.optional or model_field.nullable:
            entry["default"] = None
        avro_fields.append(entry)
    return {
        "type": "record",
        "name": _avro_name(f"{name}V{version}"),
        "namespace": context.namespace,
        "fields": avro_fields,
        "x-modelable": {"ref": ref, "kind": kind, "version": version},
    }


def _field_schema(field: FieldDef, field_type: FieldType, context: _AvroContext, path: list[str]) -> Any:
    schema = _type_schema(field_type, context, path)
    if field.nullable or field.optional:
        return ["null", schema]
    return schema


def _type_schema(field_type: FieldType, context: _AvroContext, path: list[str]) -> Any:
    if isinstance(field_type, PrimitiveType):
        return _primitive_schema(field_type)
    if isinstance(field_type, DecimalType):
        return {"type": "bytes", "logicalType": "decimal", "precision": field_type.precision, "scale": field_type.scale}
    if isinstance(field_type, FixedBinaryType):
        return {"type": "fixed", "name": _avro_name("".join(path) + "Fixed"), "size": field_type.length}
    if isinstance(field_type, ArrayType):
        return {"type": "array", "items": _type_schema(field_type.item, context, [*path, "Item"])}
    if isinstance(field_type, MapType):
        if not isinstance(field_type.key, PrimitiveType) or field_type.key.kind != "string":
            context.warnings.append(type_loss(f"Avro map key at {'.'.join(path)}; Avro requires string keys"))
        return {"type": "map", "values": _type_schema(field_type.value, context, [*path, "Value"])}
    if isinstance(field_type, EnumType):
        name = _avro_name("".join(path) + "Enum")
        for identifier, members in find_identifier_collisions(field_type.values, _avro_name).items():
            context.warnings.append(enum_member_collision("avro", ".".join(path), identifier, members))
        return {"type": "enum", "name": name, "symbols": [_avro_name(value) for value in field_type.values]}
    if isinstance(field_type, ObjectType):
        return _object_schema(field_type, context, path)
    if isinstance(field_type, RefType):
        try:
            resolved = resolve_ref_type(field_type, context.workspace)
        except LookupError:
            context.warnings.append(type_loss(f"unresolved Avro reference {field_type.target}"))
            return "string"
        if not isinstance(resolved.version, ModelVersion):
            context.warnings.append(type_loss(f"Avro reference target is not a model {field_type.target}"))
            return "string"
        key = next((item for item in resolved.version.fields if item.is_key), None)
        if key is None:
            context.warnings.append(type_loss(f"Avro reference target without a key {field_type.target}"))
            return "string"
        return _type_schema(key.type, context, [*path, "Ref"])
    if isinstance(field_type, NamedType):
        try:
            semantic = resolve_semantic_type_ref(context.workspace, context.namespace, field_type.name)[1]
        except LookupError, TypeError:
            semantic = None
        if semantic is not None:
            return _type_schema(semantic.underlying, context, [*path, field_type.name])
        model_ref = field_type.name if "." in field_type.name else f"{context.namespace}.{field_type.name}"
        try:
            resolved = resolve_model_ref(context.workspace, model_ref, VersionMin(min_inclusive=1))
        except LookupError:
            context.warnings.append(type_loss(f"unresolved Avro named type {field_type.name}"))
            return "string"
        if isinstance(resolved.version, ModelVersion):
            return _named_record_schema(resolved.version, context, path)
        context.warnings.append(type_loss(f"Avro named type target is not a model {field_type.name}"))
        return "string"
    if isinstance(field_type, UnionType):
        context.warnings.append(
            emit_warning("EMIT002", f"Avro discriminator '{field_type.discriminator}' is not represented in a union")
        )
        return [_type_schema(variant.type, context, [*path, variant.tag]) for variant in field_type.variants]
    return "string"


def _named_record_schema(version: ModelVersion, context: _AvroContext, path: list[str]) -> Any:
    """Render a resolved named type (value or entity) as its own Avro record."""
    name = _avro_name("".join(path))
    if name in context.named:
        return name
    context.named.add(name)
    return {
        "type": "record",
        "name": name,
        "fields": [
            {
                "name": _avro_name(item.name),
                "type": _field_schema(item, item.type, context, [*path, item.name]),
                **({"default": _parse_default(item.default, item.type)} if item.default is not None else {}),
            }
            for item in version.fields
        ],
    }


def _object_schema(field_type: ObjectType, context: _AvroContext, path: list[str]) -> dict[str, Any] | str:
    name = _avro_name("".join(path))
    if name in context.named:
        return name
    context.named.add(name)
    return {
        "type": "record",
        "name": name,
        "fields": [
            {
                "name": _avro_name(field.name),
                "type": _field_schema(field, field.type, context, [*path, field.name]),
                **({"default": _parse_default(field.default, field.type)} if field.default is not None else {}),
            }
            for field in field_type.fields
        ],
    }


def _primitive_schema(field_type: PrimitiveType) -> Any:
    kind = field_type.kind
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
    if kind in {"json", "string"}:
        return "string"
    return "string"


def _parse_default(value: str | None, schema: Any) -> Any:
    if value is None:
        return None
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


def _artifact(
    ref: str,
    domain: str,
    name: str,
    version: int,
    schema: dict[str, Any],
    warnings: list[str],
    out_dir: PurePath,
) -> EmittedArtifact:
    artifact_id = f"{domain}.{name}.v{version}"
    return EmittedArtifact(
        target="avro",
        ref=ref,
        artifact_id=artifact_id,
        path=out_dir / domain / f"{name}.v{version}.avsc",
        content=schema,
        content_hash=compute_content_hash(schema),
        warnings=warnings,
    )


def _avro_name(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if not result or result[0].isdigit():
        result = f"_{result}"
    return result
