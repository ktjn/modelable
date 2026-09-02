"""Parser-free Go projection rendering for ``modelable.plan/v1``."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from modelable.emitters.base import EmittedArtifact, compute_content_hash, render_nested_definitions
from modelable.emitters.base import artifact_id as _artifact_id
from modelable.emitters.diagnostics import type_loss
from modelable.emitters.naming import package_name
from modelable.emitters.naming import pascalize_plain as _pascalize
from modelable.emitters.naming import snake_case as _snake_case
from modelable.planner.protocol import PlanDocument, validate_plan


def emit_go_projection_plan(
    plan: PlanDocument,
    out_dir: Path,
    *,
    module_name: str = "modelable/generated",
    named_types: dict[str, tuple[str, str]] | None = None,
) -> EmittedArtifact:
    """Emit one Go projection source file from validated plan facts."""
    document = validate_plan(plan)
    domain = _string(document, "domain")
    projection = _string(document, "projection")
    version = _integer(document, "version")
    type_name = f"{_pascalize(domain)}{_pascalize(projection)}V{version}"
    definitions: dict[str, list[str]] = {}
    imports: set[str] = set()
    names = named_types or {}
    warnings: list[str] = []
    field_specs: list[tuple[int, str, str, bool]] = []

    for index, field in enumerate(_mappings(document.get("fields"))):
        name = _string(field, "name")
        field_type = _source_type(document, field)
        optional = field.get("optional") is True or field.get("nullable") is True
        if field_type is None:
            warnings.append(type_loss(f"{domain}.{projection}.{name}"))
            field_specs.append((index, name, "any", False))
            continue
        annotation = _annotation(
            field_type,
            optional=optional,
            owner_type=type_name,
            path=[name],
            definitions=definitions,
            imports=imports,
            warnings=warnings,
            named_types=names,
            current_domain=domain,
            module_name=module_name,
        )
        field_specs.append((index, name, annotation, optional))

    lines = _header_lines(package_name(domain, separator="_"), imports)
    lines.extend(_render_struct_definition(type_name, field_specs))
    lines.extend(render_nested_definitions(definitions))
    content = "\n".join(lines) + "\n"
    return EmittedArtifact(
        target="go",
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
    module_name: str,
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
        module_name=module_name,
    )
    return f"*{base}" if optional else base


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
    module_name: str,
) -> str:
    kind = field_type.get("kind")
    if kind == "decimal":
        return "string"
    if kind == "fixed_binary":
        return f"[{field_type.get('length')}]byte"
    if kind in _PRIMITIVE_KINDS or kind == "primitive":
        field_ref = f"{owner_type}.{'.'.join(path)}"
        return _primitive_to_go(str(field_type.get("type", kind)), imports, warnings, field_ref)
    if kind == "array":
        item = _mapping(field_type, "item")
        return f"[]{_annotation(item, optional=False, owner_type=owner_type, path=[*path, 'Item'], definitions=definitions, imports=imports, warnings=warnings, named_types=named_types, current_domain=current_domain, module_name=module_name)}"
    if kind == "map":
        value = _mapping(field_type, "value")
        return f"map[string]{_annotation(value, optional=False, owner_type=owner_type, path=[*path, 'Value'], definitions=definitions, imports=imports, warnings=warnings, named_types=named_types, current_domain=current_domain, module_name=module_name)}"
    if kind in {"ref", "enum"}:
        return "string"
    if kind == "enum_ref":
        resolved = named_types.get(_named_key(str(field_type.get("name", "")), field_type.get("version")))
        return _named_reference(resolved, imports, current_domain, module_name) if resolved else "string"
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
                module_name=module_name,
            )
        resolved_model = field_type.get("resolved_model")
        if isinstance(resolved_model, dict):
            model_domain = _string(resolved_model, "domain")
            model_name = _string(resolved_model, "name")
            model_version = _integer(resolved_model, "version")
            emitted = f"{_pascalize(model_domain)}{_pascalize(model_name)}V{model_version}"
            return _named_reference((emitted, model_domain), imports, current_domain, module_name)
        return _pascalize(str(field_type.get("name", "Named")))
    if kind == "object":
        nested_name = _nested_type_name(owner_type, path)
        if nested_name not in definitions:
            specs: list[tuple[int, str, str, bool]] = []
            for index, field in enumerate(_mappings(field_type.get("fields"))):
                name = _string(field, "name")
                nested_type = field.get("type")
                nested_optional = field.get("optional") is True or field.get("nullable") is True
                annotation = "any"
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
                        module_name=module_name,
                    )
                specs.append((index, name, annotation, nested_optional))
            definitions[nested_name] = _render_struct_definition(nested_name, specs)
        return nested_name
    return "any"


def _named_reference(resolved: tuple[str, str], imports: set[str], current_domain: str, module_name: str) -> str:
    emitted, domain = resolved
    if domain != current_domain:
        imports.add(f"{module_name}/{package_name(domain, separator='_')}")
        return f"{package_name(domain, separator='_')}.{emitted}"
    return emitted


def _primitive_to_go(kind: str, imports: set[str], warnings: list[str], field_ref: str) -> str:
    if kind in {"u128", "i128"}:
        warnings.append(type_loss(field_ref))
        return "[16]byte"
    result = {
        "string": "string",
        "bool": "bool",
        "int": "int64",
        "float": "float64",
        "uuid": "string",
        "timestamp": "time.Time",
        "date": "time.Time",
        "time": "time.Time",
        "duration": "time.Duration",
        "binary": "[]byte",
        "json": "string",
        "u8": "uint8",
        "u16": "uint16",
        "u32": "uint32",
        "u64": "uint64",
        "i8": "int8",
        "i16": "int16",
        "i32": "int32",
        "i64": "int64",
    }.get(kind, "string")
    if result.startswith("time."):
        imports.add("time")
    return result


def _header_lines(package: str, imports: set[str]) -> list[str]:
    lines = ["// Code generated by Modelable; DO NOT EDIT.", f"package {package}"]
    if imports:
        lines.extend(["", "import ("])
        lines.extend(f'    "{item}"' for item in sorted(imports))
        lines.append(")")
    lines.append("")
    return lines


def _render_struct_definition(type_name: str, field_specs: list[tuple[int, str, str, bool]]) -> list[str]:
    lines = [f"type {type_name} struct {{"]
    if not field_specs:
        lines.append("}")
        return lines
    for _, name, annotation, optional in sorted(field_specs, key=lambda item: (item[3], item[0])):
        lines.append(f"    {_pascalize(name, fallback='Field')} {annotation} {_json_tag(name, optional)}")
    lines.append("}")
    return lines


def _json_tag(name: str, optional: bool) -> str:
    return f'`json:"{name}{",omitempty" if optional else ""}"`'


def _module_path(domain: str, type_name: str) -> Path:
    return Path(package_name(domain, separator="_")) / f"{_snake_case(type_name)}.go"


def _nested_type_name(owner_type: str, path: list[str]) -> str:
    return f"{owner_type}{''.join(_pascalize(part) for part in path)}"


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
