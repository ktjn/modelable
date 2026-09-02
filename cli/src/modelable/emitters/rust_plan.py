"""Parser-free Rust projection rendering for ``modelable.plan/v1``."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.base import artifact_id as _artifact_id
from modelable.emitters.diagnostics import enum_member_collision, type_loss
from modelable.emitters.naming import find_identifier_collisions
from modelable.emitters.naming import pascalize_titlecase as _pascalize
from modelable.emitters.naming import snake_case as _snake_case
from modelable.planner.protocol import PlanDocument, validate_plan


def emit_rust_projection_plan(
    plan: PlanDocument,
    out_dir: Path,
    *,
    named_types: dict[str, str] | None = None,
    schema_signature: str | None = None,
) -> EmittedArtifact:
    """Emit one Rust projection module from validated plan facts."""
    document = validate_plan(plan)
    domain = _string(document, "domain")
    projection = _string(document, "projection")
    version = _integer(document, "version")
    type_name = _stable_type_name(domain, projection, version)
    definitions: dict[str, list[str]] = {}
    imports: set[str] = set()
    warnings: list[str] = []
    specs: list[dict[str, Any]] = []

    for index, field in enumerate(_mappings(document.get("fields"))):
        name = _string(field, "name")
        field_type = _source_type(document, field)
        optional = field.get("optional") is True or field.get("nullable") is True
        omittable = field.get("optional") is True
        if field_type is None:
            warnings.append(type_loss(f"{domain}.{projection}.{name}"))
            annotation = "String"
            optional = False
        else:
            annotation = _annotation(
                field_type,
                owner_type=type_name,
                path=[name],
                definitions=definitions,
                imports=imports,
                named_types=named_types or {},
                warnings=warnings,
            )
            _append_collision_warnings(field_type, f"{type_name}.{name}", warnings)
        attrs = []
        rust_name = _field_name(name)
        if rust_name != name:
            attrs.append(f'#[serde(rename = "{name}")]')
        if omittable:
            attrs.insert(0, "#[serde(default)]")
            attrs.insert(1, '#[serde(skip_serializing_if = "Option::is_none")]')
        specs.append(
            {
                "index": index,
                "name": name,
                "annotation": annotation,
                "optional": optional,
                "attrs": attrs,
            }
        )

    needs_uuid = any("uuid::Uuid" in spec["annotation"] for spec in specs)
    needs_chrono = any("chrono::" in spec["annotation"] for spec in specs)
    needs_json = any("serde_json::Value" in spec["annotation"] for spec in specs)
    needs_hashmap = any("HashMap<" in spec["annotation"] for spec in specs)
    lines = _header_lines(
        uuid=needs_uuid,
        chrono=needs_chrono,
        serde_json=needs_json,
        hashmap=needs_hashmap,
        extra_uses=sorted(imports),
    )
    lines.extend(_render_struct(type_name, specs))
    if schema_signature is not None:
        lines.extend(_render_schema_identity(type_name, version, schema_signature))
    lines.extend(_render_nested(definitions))
    lines.extend(_render_from_impl(document, type_name))
    content = "\n".join(lines) + "\n"
    return EmittedArtifact(
        target="rust",
        ref=f"{domain}.{projection}@{version}",
        artifact_id=_artifact_id(domain, projection, version),
        path=out_dir / _module_path(domain, type_name),
        content=content,
        content_hash=compute_content_hash(content),
        warnings=warnings,
    )


def _source_type(plan: PlanDocument, field: dict[str, Any]) -> dict[str, Any] | None:
    if field.get("kind") != "direct":
        value = field.get("type")
        return cast(dict[str, Any], value) if isinstance(value, dict) else None
    alias = field.get("source_alias")
    source_name = field.get("source_field")
    for relation in [_mapping(plan, "source"), *_mappings(plan.get("joins"))]:
        if relation.get("alias") != alias:
            continue
        resolved = relation.get("resolved")
        for source in _mappings(resolved.get("fields") if isinstance(resolved, dict) else None):
            if source.get("name") == source_name:
                value = source.get("type")
                return cast(dict[str, Any], value) if isinstance(value, dict) else None
    value = field.get("type")
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def _annotation(
    field_type: dict[str, Any],
    *,
    owner_type: str,
    path: list[str],
    definitions: dict[str, list[str]],
    imports: set[str],
    named_types: dict[str, str],
    warnings: list[str],
) -> str:
    base = _base_annotation(
        field_type,
        owner_type=owner_type,
        path=path,
        definitions=definitions,
        imports=imports,
        named_types=named_types,
        warnings=warnings,
    )
    return f"Option<{base}>" if field_type.get("optional") or field_type.get("nullable") else base


def _base_annotation(
    field_type: dict[str, Any],
    *,
    owner_type: str,
    path: list[str],
    definitions: dict[str, list[str]],
    imports: set[str],
    named_types: dict[str, str],
    warnings: list[str],
) -> str:
    kind = field_type.get("kind")
    if kind == "decimal":
        return "String"
    if kind == "fixed_binary":
        return f"[u8; {_integer(field_type, 'length')}]"
    if kind in _PRIMITIVE_KINDS or kind == "primitive":
        return _primitive_to_rust(str(field_type.get("type", kind)))
    if kind == "array":
        item = _mapping(field_type, "item")
        return f"Vec<{_annotation(item, owner_type=owner_type, path=[*path, 'Item'], definitions=definitions, imports=imports, named_types=named_types, warnings=warnings)}>"
    if kind == "map":
        value = _mapping(field_type, "value")
        return f"HashMap<String, {_annotation(value, owner_type=owner_type, path=[*path, 'Value'], definitions=definitions, imports=imports, named_types=named_types, warnings=warnings)}>"
    if kind == "ref":
        return "String"
    if kind == "enum":
        enum_name = _nested_type_name(owner_type, path)
        if enum_name not in definitions:
            definitions[enum_name] = _render_enum(enum_name, _strings(field_type.get("values")))
        return enum_name
    if kind == "enum_ref":
        key = _named_key(field_type.get("name"), field_type.get("version"))
        return named_types.get(key, _pascalize(str(field_type.get("name", "Enum"))))
    if kind == "named":
        key = _named_key(field_type.get("name"), field_type.get("version"))
        if key in named_types:
            return named_types[key]
        underlying = field_type.get("resolved_underlying_type")
        if isinstance(underlying, dict):
            return _base_annotation(
                underlying,
                owner_type=owner_type,
                path=path,
                definitions=definitions,
                imports=imports,
                named_types=named_types,
                warnings=warnings,
            )
        resolved_model = field_type.get("resolved_model")
        if isinstance(resolved_model, dict):
            model_domain = _string(resolved_model, "domain")
            model_name = _string(resolved_model, "name")
            model_version = _integer(resolved_model, "version")
            emitted = _stable_type_name(model_domain, model_name, model_version)
            imports.add(f"use super::{_snake_case(emitted)}::{emitted};")
            return emitted
        return _pascalize(str(field_type.get("name", "Named")))
    if kind == "object":
        nested_name = _nested_type_name(owner_type, path)
        if nested_name not in definitions:
            nested_specs: list[dict[str, Any]] = []
            for index, field in enumerate(_mappings(field_type.get("fields"))):
                nested_type = field.get("type")
                optional = field.get("optional") is True or field.get("nullable") is True
                omittable = field.get("optional") is True
                annotation = "String"
                if isinstance(nested_type, dict):
                    annotation = _annotation(
                        nested_type,
                        owner_type=owner_type,
                        path=[*path, _string(field, "name")],
                        definitions=definitions,
                        imports=imports,
                        named_types=named_types,
                        warnings=warnings,
                    )
                name = _string(field, "name")
                attrs = []
                if _field_name(name) != name:
                    attrs.append(f'#[serde(rename = "{name}")]')
                if omittable:
                    attrs.insert(0, "#[serde(default)]")
                nested_specs.append(
                    {"index": index, "name": name, "annotation": annotation, "optional": optional, "attrs": attrs}
                )
            definitions[nested_name] = _render_struct(nested_name, nested_specs)
        return nested_name
    warnings.append(type_loss(f"{owner_type}.{'.'.join(path)}"))
    return "String"


def _header_lines(*, uuid: bool, chrono: bool, serde_json: bool, hashmap: bool, extra_uses: list[str]) -> list[str]:
    lines = ["// @generated by Modelable"]
    if chrono:
        lines.append("// requires: chrono (https://docs.rs/chrono)")
    if serde_json:
        lines.append("// requires: serde_json (https://docs.rs/serde_json)")
    if uuid:
        lines.append("// requires: uuid (https://docs.rs/uuid)")
    if hashmap:
        lines.append("use std::collections::HashMap;")
    lines.extend([*extra_uses, ""])
    return lines


def _render_struct(type_name: str, specs: list[dict[str, Any]]) -> list[str]:
    lines = ["#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]", f"pub struct {type_name} {{"]
    for spec in sorted(specs, key=lambda item: (item["optional"], item["index"])):
        for attr in spec.get("attrs", []):
            lines.append(f"    {attr}")
        annotation = spec["annotation"]
        if spec["optional"] and not annotation.startswith("Option<"):
            annotation = f"Option<{annotation}>"
        lines.append(f"    pub {_field_name(spec['name'])}: {annotation},")
    lines.append("}")
    return lines


def _render_enum(type_name: str, values: list[str]) -> list[str]:
    lines = ["#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]", f"pub enum {type_name} {{"]
    for value in values:
        member = _enum_member_name(value)
        if member != value:
            lines.append(f'    #[serde(rename = "{value}")]')
        lines.append(f"    {member},")
    lines.append("}")
    return lines


def _render_nested(definitions: dict[str, list[str]]) -> list[str]:
    lines: list[str] = []
    for definition in definitions.values():
        lines.extend(["", *definition])
    return lines


def _render_schema_identity(type_name: str, version: int, signature: str) -> list[str]:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", signature):
        raise ValueError("canonical Modelable signature must contain exactly 64 hexadecimal characters")
    lines = [
        "",
        f"impl {type_name} {{",
        f"    pub const SCHEMA_VERSION: u32 = {version};",
        "    pub const SCHEMA_CONTENT_SIGNATURE: [u8; 32] = [",
    ]
    values = bytes.fromhex(signature)
    for offset in range(0, len(values), 8):
        lines.append("        " + ", ".join(f"0x{value:02x}" for value in values[offset : offset + 8]) + ",")
    lines.extend(["    ];", "}"])
    return lines


def _render_from_impl(plan: PlanDocument, projection_type: str) -> list[str]:
    if plan.get("joins"):
        return []
    source = _mapping(plan, "source")
    model_ref = source.get("model")
    resolved_version = source.get("resolved_version")
    if not isinstance(model_ref, str) or not isinstance(resolved_version, int) or "." not in model_ref:
        return []
    source_domain, source_name = model_ref.rsplit(".", 1)
    if source_domain != _string(plan, "domain"):
        return []
    source_type = _stable_type_name(source_domain, source_name, resolved_version)
    source_module = _snake_case(source_type)
    lines = [
        "",
        f"use super::{source_module}::{source_type};",
        "#[allow(clippy::useless_conversion)]",
        f"impl From<{source_type}> for {projection_type} {{",
        f"    fn from(src: {source_type}) -> Self {{",
        "        Self {",
    ]
    for field in _mappings(plan.get("fields")):
        target = _field_name(_string(field, "name"))
        if field.get("kind") == "direct":
            source_field = _field_name(str(field.get("source_field", "")))
            lines.append(f"            {target}: src.{source_field}.into(),")
        else:
            lines.append(f"            {target}: Default::default(), // computed — provide manual impl")
    lines.extend(["        }", "    }", "}"])
    return lines


def _append_collision_warnings(field_type: dict[str, Any], owner: str, warnings: list[str]) -> None:
    if field_type.get("kind") == "enum":
        for identifier, members in find_identifier_collisions(
            _strings(field_type.get("values")), _enum_member_name
        ).items():
            warnings.append(enum_member_collision("rust", owner, identifier, members))
    elif field_type.get("kind") == "array":
        _append_collision_warnings(_mapping(field_type, "item"), f"{owner}[]", warnings)
    elif field_type.get("kind") == "map":
        _append_collision_warnings(_mapping(field_type, "value"), f"{owner}{{}}", warnings)
    elif field_type.get("kind") == "object":
        for field in _mappings(field_type.get("fields")):
            nested = field.get("type")
            if isinstance(nested, dict):
                _append_collision_warnings(nested, f"{owner}.{_string(field, 'name')}", warnings)


def _primitive_to_rust(kind: str) -> str:
    return {
        "string": "String",
        "bool": "bool",
        "int": "i64",
        "float": "f64",
        "uuid": "uuid::Uuid",
        "timestamp": "chrono::DateTime<chrono::Utc>",
        "date": "chrono::NaiveDate",
        "time": "chrono::NaiveTime",
        "duration": "chrono::Duration",
        "binary": "Vec<u8>",
        "json": "serde_json::Value",
        "u8": "u8",
        "u16": "u16",
        "u32": "u32",
        "u64": "u64",
        "u128": "u128",
        "i8": "i8",
        "i16": "i16",
        "i32": "i32",
        "i64": "i64",
        "i128": "i128",
    }.get(kind, "String")


def _stable_type_name(domain: str, name: str, version: int) -> str:
    return f"{_pascalize(domain)}{_pascalize(name)}V{version}"


def _nested_type_name(owner: str, path: list[str]) -> str:
    return owner + "".join(_pascalize(part) for part in path)


def _module_path(domain: str, type_name: str) -> Path:
    return Path(*[part.lower() for part in re.split(r"[^A-Za-z0-9]+", domain) if part]) / f"{_snake_case(type_name)}.rs"


def _field_name(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower() or "field"


def _enum_member_name(value: str) -> str:
    name = _pascalize(value)
    return f"_{name}" if name and name[0].isdigit() else name or "Unknown"


def _named_key(name: object, version: object) -> str:
    return f"{name}|{version if isinstance(version, int) else '?'}"


def _string(mapping: dict[str, object], key: str) -> str:
    return str(mapping.get(key, ""))


def _integer(mapping: dict[str, object], key: str) -> int:
    value = mapping.get(key)
    if not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    return value


def _mapping(mapping: dict[str, object], key: str) -> dict[str, Any]:
    value = mapping.get(key)
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _mappings(value: object) -> list[dict[str, Any]]:
    return [cast(dict[str, Any], item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _strings(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


_PRIMITIVE_KINDS = {
    "string",
    "int",
    "float",
    "bool",
    "date",
    "time",
    "timestamp",
    "uuid",
    "duration",
    "binary",
    "json",
    "u8",
    "u16",
    "u32",
    "u64",
    "u128",
    "i8",
    "i16",
    "i32",
    "i64",
    "i128",
}
