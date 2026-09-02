"""Parser-free Java projection rendering for ``modelable.plan/v1``."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from modelable.emitters.base import EmittedArtifact, compute_content_hash, render_nested_definitions
from modelable.emitters.base import artifact_id as _artifact_id
from modelable.emitters.diagnostics import type_loss
from modelable.emitters.naming import package_name
from modelable.emitters.naming import pascalize_plain as _pascalize
from modelable.planner.protocol import PlanDocument, validate_plan


def emit_java_projection_plan(
    plan: PlanDocument,
    out_dir: Path,
    *,
    named_types: dict[str, tuple[str, str]] | None = None,
) -> EmittedArtifact:
    """Emit one Java projection record from validated plan facts."""
    document = validate_plan(plan)
    domain = _string(document, "domain")
    projection = _string(document, "projection")
    version = _integer(document, "version")
    type_name = f"{_pascalize(projection)}V{version}"
    definitions: dict[str, list[str]] = {}
    imports: set[str] = set()
    names = named_types or {}
    warnings: list[str] = []
    params: list[str] = []

    for field in _mappings(document.get("fields")):
        name = _string(field, "name")
        field_type = _source_type(document, field)
        optional = field.get("optional") is True or field.get("nullable") is True
        if field_type is None:
            warnings.append(type_loss(f"{domain}.{projection}.{name}"))
            java_type = "Object"
        else:
            java_type = _annotation(
                field_type,
                optional=optional,
                owner_type=type_name,
                path=[name],
                definitions=definitions,
                imports=imports,
                warnings=warnings,
                named_types=names,
                current_domain=domain,
            )
        params.append(f"    {java_type} {_field_name(name)}")

    lines = _header_lines(package_name(domain), imports)
    lines.extend([f"public record {type_name}(", ",\n".join(params), ") {"])
    lines.extend(render_nested_definitions(definitions))
    lines.append("}")
    content = "\n".join(lines) + "\n"
    return EmittedArtifact(
        target="java",
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
    optional: bool,
    owner_type: str,
    path: list[str],
    definitions: dict[str, list[str]],
    imports: set[str],
    warnings: list[str],
    named_types: dict[str, tuple[str, str]],
    current_domain: str,
) -> str:
    base = _base_annotation(
        field_type,
        owner_type=owner_type,
        path=path,
        definitions=definitions,
        imports=imports,
        warnings=warnings,
        named_types=named_types,
        current_domain=current_domain,
    )
    return f"Optional<{base}>" if optional else base


def _base_annotation(
    field_type: dict[str, Any],
    *,
    owner_type: str,
    path: list[str],
    definitions: dict[str, list[str]],
    imports: set[str],
    warnings: list[str],
    named_types: dict[str, tuple[str, str]],
    current_domain: str,
) -> str:
    kind = field_type.get("kind")
    if kind == "decimal":
        return "BigDecimal"
    if kind == "fixed_binary":
        warnings.append(
            type_loss(
                f"{owner_type}.{'.'.join(path)} (binary({field_type.get('length')}) length is not enforced by the Java type system)"
            )
        )
        return "byte[]"
    if kind in _PRIMITIVE_KINDS or kind == "primitive":
        primitive_kind = str(field_type.get("type", kind))
        if primitive_kind in {"u8", "u16", "u32", "u64"}:
            warnings.append(type_loss(f"{owner_type}.{'.'.join(path)}"))
        return _primitive_to_java(primitive_kind)
    if kind == "array":
        return f"List<{_annotation(_mapping(field_type, 'item'), optional=False, owner_type=owner_type, path=[*path, 'Item'], definitions=definitions, imports=imports, warnings=warnings, named_types=named_types, current_domain=current_domain)}>"
    if kind == "map":
        return f"Map<String, {_annotation(_mapping(field_type, 'value'), optional=False, owner_type=owner_type, path=[*path, 'Value'], definitions=definitions, imports=imports, warnings=warnings, named_types=named_types, current_domain=current_domain)}>"
    if kind in {"ref", "enum"}:
        return "String"
    if kind == "enum_ref":
        resolved = named_types.get(_named_key(str(field_type.get("name", "")), field_type.get("version")))
        if resolved is None:
            return "String"
        name, declaring_domain = resolved
        if declaring_domain != current_domain:
            imports.add(f"import {package_name(declaring_domain)}.{name};")
        return name
    if kind == "named":
        underlying = field_type.get("resolved_underlying_type")
        if isinstance(underlying, dict):
            return _base_annotation(
                underlying,
                owner_type=owner_type,
                path=path,
                definitions=definitions,
                imports=imports,
                warnings=warnings,
                named_types=named_types,
                current_domain=current_domain,
            )
        resolved_model = field_type.get("resolved_model")
        if isinstance(resolved_model, dict):
            model_domain = _string(resolved_model, "domain")
            model_name = _string(resolved_model, "name")
            model_version = _integer(resolved_model, "version")
            emitted = f"{_pascalize(model_name)}V{model_version}"
            if model_domain != current_domain:
                imports.add(f"import {package_name(model_domain)}.{emitted};")
            return emitted
        return _pascalize(str(field_type.get("name", "Named")))
    if kind == "object":
        nested_name = _nested_type_name(path)
        if nested_name not in definitions:
            params: list[str] = []
            for field in _mappings(field_type.get("fields")):
                name = _string(field, "name")
                nested_type = field.get("type")
                nested_optional = field.get("optional") is True or field.get("nullable") is True
                annotation = "Object"
                if isinstance(nested_type, dict):
                    annotation = _annotation(
                        nested_type,
                        optional=nested_optional,
                        owner_type=owner_type,
                        path=[*path, name],
                        definitions=definitions,
                        imports=imports,
                        warnings=warnings,
                        named_types=named_types,
                        current_domain=current_domain,
                    )
                params.append(f"        {annotation} {_field_name(name)}")
            definitions[nested_name] = [f"    public record {nested_name}(", ",\n".join(params), "    ) {}"]
        return nested_name
    return "Object"


def _primitive_to_java(kind: str) -> str:
    return {
        "string": "String",
        "bool": "Boolean",
        "int": "Long",
        "float": "Double",
        "uuid": "UUID",
        "timestamp": "Instant",
        "date": "LocalDate",
        "time": "LocalTime",
        "duration": "Duration",
        "binary": "byte[]",
        "json": "String",
        "u8": "Byte",
        "u16": "Short",
        "u32": "Integer",
        "u64": "Long",
        "u128": "BigInteger",
        "i8": "Byte",
        "i16": "Short",
        "i32": "Integer",
        "i64": "Long",
        "i128": "BigInteger",
    }.get(kind, "String")


def _header_lines(package: str, imports: set[str]) -> list[str]:
    return [
        f"package {package};",
        "",
        "import java.math.BigDecimal;",
        "import java.math.BigInteger;",
        "import java.time.Duration;",
        "import java.time.Instant;",
        "import java.time.LocalDate;",
        "import java.time.LocalTime;",
        "import java.util.List;",
        "import java.util.Map;",
        "import java.util.Optional;",
        "import java.util.UUID;",
        *sorted(imports),
        "",
    ]


def _field_name(value: str) -> str:
    parts = [part for part in value.replace("-", "_").split("_") if part]
    if not parts:
        return "field"
    return parts[0][:1].lower() + parts[0][1:] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def _module_path(domain: str, type_name: str) -> Path:
    return Path(*package_name(domain).split(".")) / f"{type_name}.java"


def _nested_type_name(path: list[str]) -> str:
    return "".join(_pascalize(part) for part in path) or "Nested"


def _mapping(mapping: dict[str, object], key: str) -> dict[str, Any]:
    value = mapping.get(key)
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _mappings(value: object) -> list[dict[str, Any]]:
    return [cast(dict[str, Any], item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _string(mapping: dict[str, object], key: str) -> str:
    return str(mapping.get(key, ""))


def _integer(mapping: dict[str, object], key: str) -> int:
    value = mapping.get(key)
    if not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    return value


def _named_key(name: str, version: object) -> str:
    return f"{name}|{version if isinstance(version, int) else '?'}"


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
