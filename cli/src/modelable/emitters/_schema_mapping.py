from __future__ import annotations

from modelable.parser.ir import (
    AnnClassification,
    AnnDeprecated,
    AnnKey,
    AnnOwner,
    AnnPii,
    AnnServer,
    ArrayType,
    DecimalType,
    DirectMapping,
    EnumType,
    FieldDef,
    FieldType,
    FixedBinaryType,
    MapType,
    MdlFile,
    NamedType,
    ObjectType,
    PrimitiveType,
    ProjectionField,
    ProjectionVersion,
    RefType,
)
from modelable.registry.resolver import resolve_model_ref, resolve_ref_type

_INTEGER_BOUNDS: dict[str, tuple[int, int]] = {
    "u8": (0, 2**8 - 1),
    "u16": (0, 2**16 - 1),
    "u32": (0, 2**32 - 1),
    "u64": (0, 2**64 - 1),
    "u128": (0, 2**128 - 1),
    "i8": (-(2**7), 2**7 - 1),
    "i16": (-(2**15), 2**15 - 1),
    "i32": (-(2**31), 2**31 - 1),
    "i64": (-(2**63), 2**63 - 1),
    "i128": (-(2**127), 2**127 - 1),
}


def _primitive_to_json_schema(kind: str) -> dict:
    if kind in _INTEGER_BOUNDS:
        low, high = _INTEGER_BOUNDS[kind]
        return {"type": "integer", "minimum": low, "maximum": high}
    mapping: dict[str, dict] = {
        "string": {"type": "string"},
        "bool": {"type": "boolean"},
        "int": {"type": "integer", "format": "int64"},
        "float": {"type": "number"},
        "uuid": {"type": "string", "format": "uuid"},
        "timestamp": {"type": "string", "format": "date-time"},
        "date": {"type": "string", "format": "date"},
        "time": {"type": "string", "format": "time"},
        "duration": {"type": "string", "format": "duration"},
        "binary": {"type": "string", "contentEncoding": "base64"},
        "json": {},
    }
    return mapping.get(kind, {"type": "string"})


def _definition_name(path: list[str]) -> str:
    return "".join(_pascalize_part(part) for part in path if part)


def _pascalize_part(value: str) -> str:
    return value[:1].upper() + value[1:] if value else value


def _resolve_projection_field_type(
    field: ProjectionField,
    projection: ProjectionVersion,
    mdl: MdlFile,
) -> FieldType | None:
    source_field = _resolve_projection_source_field(field, projection, mdl)
    return source_field.type if source_field is not None else None


def _resolve_projection_source_field(
    field: ProjectionField,
    projection: ProjectionVersion,
    mdl: MdlFile,
) -> FieldDef | None:
    """Resolve the JSON Schema type for a projection field from its source model."""
    if not isinstance(field.mapping, DirectMapping):
        return None

    # Find the source model version that matches the projection source.
    source_fqn = projection.source.model
    try:
        source_domain, source_model = source_fqn.rsplit(".", 1)
    except ValueError:
        return None

    try:
        resolved = resolve_model_ref(mdl, f"{source_domain}.{source_model}", projection.source.version)
    except LookupError:
        return None
    source_mv = resolved.version

    for src_field in source_mv.fields:
        if isinstance(src_field, FieldDef) and src_field.name == field.mapping.source_field:
            return src_field

    return None


def _field_to_json_schema(
    field: FieldDef | ProjectionField,
    field_type=None,
    defs: dict[str, dict] | None = None,
    path: list[str] | None = None,
    *,
    mdl: MdlFile | None = None,
    ref_base: str = "#/$defs/",
) -> dict:
    prop = (
        _type_to_json_schema(field_type, defs=defs, path=path, mdl=mdl, ref_base=ref_base)
        if field_type is not None
        else {}
    )

    if getattr(field, "nullable", False):
        if isinstance(prop.get("type"), str):
            prop["type"] = [prop["type"], "null"]
        else:
            prop = {"anyOf": [prop, {"type": "null"}]}

    wire_targets = field.wire_targets()
    if wire_targets:
        prop["x-modelable-wire"] = {target: _wire_hint_to_json(hint) for target, hint in sorted(wire_targets.items())}

    for ann in field.annotations:
        if isinstance(ann, AnnKey):
            prop["x-modelable-field"] = {**(prop.get("x-modelable-field") or {}), "key": True}
        elif isinstance(ann, AnnPii):
            prop["x-modelable-field"] = {**(prop.get("x-modelable-field") or {}), "pii": True}
        elif isinstance(ann, AnnClassification):
            prop["x-modelable-classification"] = ann.level
        elif isinstance(ann, AnnDeprecated):
            prop["deprecated"] = True
            prop["x-modelable-field"] = {
                **(prop.get("x-modelable-field") or {}),
                "replacedBy": ann.replaced_by,
            }
        elif isinstance(ann, AnnOwner):
            prop["x-modelable-field"] = {
                **(prop.get("x-modelable-field") or {}),
                "owner": ann.team,
            }
        elif isinstance(ann, AnnServer):
            prop["x-modelable-field"] = {
                **(prop.get("x-modelable-field") or {}),
                "server": True,
            }

    constraint_keys = {
        "min_length": "minLength",
        "max_length": "maxLength",
        "min_items": "minItems",
        "max_items": "maxItems",
        "unique_items": "uniqueItems",
    }
    for constraint in getattr(field, "constraints", []):
        if constraint.kind in {"min", "max"} and isinstance(constraint.value, (int, float)):
            prop["minimum" if constraint.kind == "min" else "maximum"] = constraint.value
        elif constraint.kind in constraint_keys:
            prop[constraint_keys[constraint.kind]] = constraint.value
        elif constraint.kind in {"pattern", "format"}:
            prop[constraint.kind] = constraint.value

    json_hint = wire_targets.get("json")
    if (
        json_hint is not None
        and json_hint.encoding == "string"
        and (
            isinstance(field_type, (DecimalType,))
            or (isinstance(field_type, PrimitiveType) and field_type.kind == "int")
        )
    ):
        prop["type"] = "string"
        prop.pop("format", None)

    return prop


def _type_to_json_schema(
    field_type,
    defs: dict[str, dict] | None = None,
    path: list[str] | None = None,
    *,
    mdl: MdlFile | None = None,
    ref_base: str = "#/$defs/",
) -> dict:
    if isinstance(field_type, PrimitiveType):
        schema = _primitive_to_json_schema(field_type.kind)
        if field_type.kind == "uuid" and field_type.version == 7:
            schema = {**schema, "x-modelable-uuid-version": 7}
        return schema
    if isinstance(field_type, DecimalType):
        return {
            "type": "string",
            "pattern": r"^-?\d+(\.\d+)?$",
            "x-modelable-field": {"decimalPrecision": field_type.precision, "decimalScale": field_type.scale},
        }
    if isinstance(field_type, FixedBinaryType):
        return {
            "type": "string",
            "contentEncoding": "base64",
            "x-modelable-fixed-length": field_type.length,
        }
    if isinstance(field_type, ArrayType):
        return {
            "type": "array",
            "items": _type_to_json_schema(field_type.item, defs=defs, path=path, mdl=mdl, ref_base=ref_base),
        }
    if isinstance(field_type, MapType):
        return {
            "type": "object",
            "additionalProperties": _type_to_json_schema(
                field_type.value, defs=defs, path=path, mdl=mdl, ref_base=ref_base
            ),
        }
    if isinstance(field_type, RefType):
        if mdl is not None:
            resolved = resolve_ref_type(field_type, mdl)
            return {"$ref": f"{ref_base}{resolved.domain_name}.{resolved.model_name}.v{resolved.version.version}"}
        return {
            "type": "string",
            "x-modelable-ref": field_type.target,
        }
    if isinstance(field_type, EnumType):
        return {
            "type": "string",
            "enum": field_type.values,
        }
    if isinstance(field_type, NamedType):
        def_name = _definition_name([field_type.name])
        if defs is not None:
            defs.setdefault(
                def_name,
                {
                    "title": field_type.name,
                    "type": "object",
                    "x-modelable-field": {"namedType": field_type.name},
                },
            )
            return {"$ref": f"{ref_base}{def_name}"}
        return {
            "type": "object",
            "x-modelable-field": {"namedType": field_type.name},
        }
    if isinstance(field_type, ObjectType):
        def_name = _definition_name(path or ["InlineObject"])
        if defs is not None:
            defs.setdefault(
                def_name, _object_type_to_json_schema(field_type, defs=defs, path=path, mdl=mdl, ref_base=ref_base)
            )
            return {"$ref": f"{ref_base}{def_name}"}
        return _object_type_to_json_schema(field_type, defs=defs, path=path, mdl=mdl, ref_base=ref_base)

    return {"type": "object"}


def _object_type_to_json_schema(
    field_type: ObjectType,
    defs: dict[str, dict] | None = None,
    path: list[str] | None = None,
    *,
    mdl: MdlFile | None = None,
    ref_base: str = "#/$defs/",
) -> dict:
    prop: dict = {"title": _definition_name(path or ["InlineObject"]), "type": "object"}
    props: dict[str, dict] = {}
    req: list[str] = []
    for f in field_type.fields:
        child_path = [*(path or []), f.name]
        props[f.name] = _field_to_json_schema(f, f.type, defs=defs, path=child_path, mdl=mdl, ref_base=ref_base)
        if not f.optional:
            req.append(f.name)
    prop["properties"] = props
    if req:
        prop["required"] = req
    return prop


def _wire_hint_to_json(hint) -> dict:
    data: dict[str, object] = {}
    if hint.encoding is not None:
        data["encoding"] = hint.encoding
    if hint.type is not None:
        data["type"] = hint.type
    if hint.case is not None:
        data["case"] = hint.case
    if hint.overrides:
        data["overrides"] = {key: hint.overrides[key] for key in sorted(hint.overrides)}
    return data
