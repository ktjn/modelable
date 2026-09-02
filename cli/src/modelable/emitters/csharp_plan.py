"""Parser-free C# projection rendering for ``modelable.plan/v1``."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from modelable.emitters.base import EmittedArtifact, compute_content_hash, render_nested_definitions
from modelable.emitters.base import artifact_id as _artifact_id
from modelable.emitters.diagnostics import type_loss
from modelable.emitters.naming import pascalize_titlecase as _pascalize
from modelable.planner.protocol import PlanDocument, validate_plan


def emit_csharp_projection_plan(
    plan: PlanDocument,
    out_dir: Path,
    *,
    named_types: dict[str, tuple[str, str]] | None = None,
) -> EmittedArtifact:
    """Emit one C# projection record from validated plan facts."""
    document = validate_plan(plan)
    domain = _string(document, "domain")
    projection = _string(document, "projection")
    version = _integer(document, "version")
    type_name = f"{_pascalize(domain)}{_pascalize(projection)}V{version}"
    definitions: dict[str, list[str]] = {}
    imports: set[str] = set()
    names = named_types or {}
    warnings: list[str] = []
    properties: list[str] = []

    for field in _mappings(document.get("fields")):
        name = _string(field, "name")
        field_type = _source_type(document, field)
        optional = field.get("optional") is True or field.get("nullable") is True
        if field_type is None:
            warnings.append(type_loss(f"{domain}.{projection}.{name}"))
            csharp_type = "object"
            required = True
        else:
            csharp_type = _annotation(
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
            required = not optional
        prefix = "required " if required else ""
        properties.append(f"    public {prefix}{csharp_type} {_pascalize(name)} {{ get; init; }}")

    lines = _header_lines(domain, imports)
    lines.extend([f"public sealed record {type_name}", "{", *properties, "}"])
    lines.extend(render_nested_definitions(definitions))
    content = "\n".join(lines) + "\n"
    return EmittedArtifact(
        target="csharp",
        ref=f"{domain}.{projection}@{version}",
        artifact_id=_artifact_id(domain, projection, version),
        path=out_dir / f"{domain}.{projection}.v{version}.cs",
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
    return f"{base}?" if optional else base


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
        return "decimal"
    if kind == "fixed_binary":
        warnings.append(
            type_loss(
                f"{owner_type}.{'.'.join(path)} (binary({field_type.get('length')}) length is not enforced by the C# type system)"
            )
        )
        return "byte[]"
    if kind in _PRIMITIVE_KINDS or kind == "primitive":
        return _primitive_to_csharp(str(field_type.get("type", kind)))
    if kind == "array":
        return f"List<{_annotation(_mapping(field_type, 'item'), optional=False, owner_type=owner_type, path=[*path, 'Item'], definitions=definitions, imports=imports, warnings=warnings, named_types=named_types, current_domain=current_domain)}>"
    if kind == "map":
        return f"Dictionary<string, {_annotation(_mapping(field_type, 'value'), optional=False, owner_type=owner_type, path=[*path, 'Value'], definitions=definitions, imports=imports, warnings=warnings, named_types=named_types, current_domain=current_domain)}>"
    if kind in {"ref", "enum"}:
        return "string"
    if kind == "enum_ref":
        resolved = named_types.get(_named_key(str(field_type.get("name", "")), field_type.get("version")))
        if resolved is None:
            return "string"
        name, declaring_domain = resolved
        if declaring_domain != current_domain:
            imports.add(f"using Modelable.{_pascalize(declaring_domain)};")
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
            emitted = f"{_pascalize(model_domain)}{_pascalize(model_name)}V{model_version}"
            if model_domain != current_domain:
                imports.add(f"using Modelable.{_pascalize(model_domain)};")
            return emitted
        return _pascalize(str(field_type.get("name", "Named")))
    if kind == "object":
        nested_name = f"{owner_type}{''.join(_pascalize(part) for part in path)}"
        if nested_name not in definitions:
            lines = [f"public sealed record {nested_name}", "{"]
            for field in _mappings(field_type.get("fields")):
                name = _string(field, "name")
                nested_type = field.get("type")
                nested_optional = field.get("optional") is True or field.get("nullable") is True
                annotation = "object"
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
                prefix = "required " if not nested_optional else ""
                lines.append(f"    public {prefix}{annotation} {_pascalize(name)} {{ get; init; }}")
            lines.append("}")
            definitions[nested_name] = lines
        return nested_name
    return "object"


def _header_lines(domain: str, imports: set[str]) -> list[str]:
    return [
        "#nullable enable",
        "using System;",
        "using System.Collections.Generic;",
        *sorted(imports),
        "",
        f"namespace Modelable.{_pascalize(domain)};",
        "",
    ]


def _primitive_to_csharp(kind: str) -> str:
    return {
        "string": "string",
        "bool": "bool",
        "int": "int",
        "float": "double",
        "uuid": "Guid",
        "timestamp": "DateTime",
        "date": "DateOnly",
        "time": "TimeOnly",
        "duration": "TimeSpan",
        "binary": "byte[]",
        "json": "string",
        "u8": "byte",
        "u16": "ushort",
        "u32": "uint",
        "u64": "ulong",
        "u128": "UInt128",
        "i8": "sbyte",
        "i16": "short",
        "i32": "int",
        "i64": "long",
        "i128": "Int128",
    }.get(kind, "string")


def _module_path(domain: str, type_name: str) -> Path:
    return Path(f"{domain}.{type_name}.cs")


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
