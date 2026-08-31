"""Parser-free Python projection rendering for supported plan protocols."""

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


def emit_python_projection_plan(
    plan: PlanDocument,
    out_dir: Path,
    *,
    named_types: dict[str, tuple[str, str]] | None = None,
) -> EmittedArtifact:
    """Emit one Python projection module from validated plan facts."""
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
        if field_type is None:
            warnings.append(type_loss(f"{domain}.{projection}.{name}"))
            field_specs.append((index, name, "object", False))
            continue
        optional = field.get("optional") is True or field.get("nullable") is True
        annotation = _annotation(
            field_type,
            optional=optional,
            owner_type=type_name,
            path=[name],
            definitions=definitions,
            imports=imports,
            named_types=names,
            current_domain=domain,
        )
        field_specs.append((index, name, annotation, optional))

    lines = _header_lines(imports)
    lines.extend(_render_dataclass_definition(type_name, field_specs))
    lines.extend(render_nested_definitions(definitions))
    content = "\n".join(lines) + "\n"
    return EmittedArtifact(
        target="python",
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
    relations = [_mapping(plan, "source"), *_mappings(plan.get("joins"))]
    for relation in relations:
        if relation.get("alias") != alias:
            continue
        resolved = relation.get("resolved")
        if not isinstance(resolved, dict):
            continue
        for source in _mappings(resolved.get("fields")):
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
    named_types: dict[str, tuple[str, str]],
    current_domain: str,
) -> str:
    base = _base_annotation(
        field_type,
        owner_type=owner_type,
        path=path,
        definitions=definitions,
        imports=imports,
        named_types=named_types,
        current_domain=current_domain,
    )
    return f"Optional[{base}]" if optional else base


def _base_annotation(
    field_type: dict[str, Any],
    *,
    owner_type: str,
    path: list[str],
    definitions: dict[str, list[str]],
    imports: set[str],
    named_types: dict[str, tuple[str, str]],
    current_domain: str,
) -> str:
    kind = field_type.get("kind")
    if kind == "primitive" or kind in _PRIMITIVE_KINDS:
        primitive_kind = str(field_type.get("type", kind))
        return _primitive_to_python(primitive_kind)
    if kind == "decimal":
        return "Decimal"
    if kind == "fixed_binary":
        return "bytes"
    if kind == "array":
        item = _mapping(field_type, "item")
        return f"list[{_annotation(item, optional=False, owner_type=owner_type, path=[*path, 'Item'], definitions=definitions, imports=imports, named_types=named_types, current_domain=current_domain)}]"
    if kind == "map":
        value = _mapping(field_type, "value")
        return f"dict[str, {_annotation(value, optional=False, owner_type=owner_type, path=[*path, 'Value'], definitions=definitions, imports=imports, named_types=named_types, current_domain=current_domain)}]"
    if kind == "ref":
        return "str"
    if kind == "enum":
        return "str"
    if kind == "enum_ref":
        key = _named_key(str(field_type.get("name", "")), field_type.get("version"))
        resolved = named_types.get(key)
        if resolved is None:
            return "str"
        return _import_named(resolved, imports, current_domain)
    if kind == "named":
        underlying = field_type.get("resolved_underlying_type")
        if isinstance(underlying, dict):
            return _base_annotation(
                underlying,
                owner_type=owner_type,
                path=path,
                definitions=definitions,
                imports=imports,
                named_types=named_types,
                current_domain=current_domain,
            )
        resolved_model = field_type.get("resolved_model")
        if isinstance(resolved_model, dict):
            model_domain = _string(resolved_model, "domain")
            model_name = _string(resolved_model, "name")
            model_version = _integer(resolved_model, "version")
            emitted = f"{_pascalize(model_domain)}{_pascalize(model_name)}V{model_version}"
            return _import_named((emitted, model_domain), imports, current_domain)
        return _pascalize(str(field_type.get("name", "Named")))
    if kind == "object":
        nested_name = _nested_type_name(owner_type, path)
        if nested_name not in definitions:
            specs: list[tuple[int, str, str, bool]] = []
            for index, field in enumerate(_mappings(field_type.get("fields"))):
                name = _string(field, "name")
                nested_type = field.get("type")
                annotation = "object"
                if isinstance(nested_type, dict):
                    annotation = _annotation(
                        nested_type,
                        optional=field.get("optional") is True or field.get("nullable") is True,
                        owner_type=owner_type,
                        path=[*path, name],
                        definitions=definitions,
                        imports=imports,
                        named_types=named_types,
                        current_domain=current_domain,
                    )
                optional = field.get("optional") is True or field.get("nullable") is True
                specs.append((index, name, annotation, optional))
            definitions[nested_name] = _render_dataclass_definition(nested_name, specs)
        return nested_name
    return "object"


def _import_named(resolved: tuple[str, str], imports: set[str], current_domain: str) -> str:
    emitted, domain = resolved
    if emitted == "":
        return "object"
    local_name = emitted
    if domain != current_domain and not emitted.startswith(_pascalize(domain)):
        local_name = f"{_pascalize(domain)}{emitted}"
    imports.add(
        f"from {package_name(domain)}.{_snake_case(emitted)} import {emitted}"
        f"{f' as {local_name}' if local_name != emitted else ''}"
    )
    return local_name


def _header_lines(imports: set[str]) -> list[str]:
    return [
        "from __future__ import annotations",
        "",
        "from dataclasses import dataclass",
        "from datetime import date, datetime, time, timedelta",
        "from decimal import Decimal",
        "from typing import Optional",
        "from uuid import UUID",
        *sorted(imports),
        "",
    ]


def _render_dataclass_definition(type_name: str, field_specs: list[tuple[int, str, str, bool]]) -> list[str]:
    lines = ["@dataclass(frozen=True, slots=True)", f"class {type_name}:"]
    if not field_specs:
        lines.append("    pass")
        return lines
    for _, name, annotation, default_none in sorted(field_specs, key=lambda item: (item[3], item[0])):
        line = f"    {name}: {annotation}"
        if default_none:
            line += " = None"
        lines.append(line)
    return lines


def _primitive_to_python(kind: str) -> str:
    return {
        "string": "str",
        "bool": "bool",
        "int": "int",
        "float": "float",
        "uuid": "UUID",
        "timestamp": "datetime",
        "date": "date",
        "time": "time",
        "duration": "timedelta",
        "binary": "bytes",
        "u8": "int",
        "u16": "int",
        "u32": "int",
        "u64": "int",
        "u128": "int",
        "i8": "int",
        "i16": "int",
        "i32": "int",
        "i64": "int",
        "i128": "int",
    }.get(kind, "str")


def _nested_type_name(owner_type: str, path: list[str]) -> str:
    return f"{owner_type}{''.join(_pascalize(part) for part in path)}"


def _module_path(domain: str, type_name: str) -> Path:
    return Path(*package_name(domain).split(".")) / f"{_snake_case(type_name)}.py"


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
