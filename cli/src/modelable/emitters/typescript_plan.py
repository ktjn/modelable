"""Parser-free TypeScript projection rendering for ``modelable.plan/v1``."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.diagnostics import missing_metadata, type_loss
from modelable.emitters.naming import apply_case_style
from modelable.planner.protocol import PlanDocument, validate_plan


def emit_typescript_projection_plan(
    plan: PlanDocument,
    out_dir: Path,
    *,
    metadata_lines: list[str] | None = None,
    import_lines: list[str] | None = None,
    field_case: str | None = None,
    ref_names: dict[str, str] | None = None,
    named_imports: dict[str, str] | None = None,
    named_enum_imports: dict[str, str] | None = None,
    wire_by_field: dict[str, object] | None = None,
) -> EmittedArtifact:
    """Emit a TypeScript projection from plan facts and optional import context."""
    document = validate_plan(plan)
    domain = _string(document, "domain")
    projection = _string(document, "projection")
    version = _integer(document, "version")
    interface_name = f"{_pascal(domain)}{_pascal(projection)}V{version}"
    metadata = metadata_lines or _default_metadata(document)
    imports = import_lines or []
    warnings: list[str] = []
    lines = [*metadata, *([*imports, ""] if imports else []), f"export interface {interface_name} {{"]
    for field in _fields(document):
        name = _string(field, "name")
        field_type = _source_type(document, field)
        if field_type is None:
            warnings.append(type_loss(f"{domain}.{projection}.{name}"))
        elif (
            field_type.get("kind") == "named"
            and field_type.get("name") not in (named_imports or {})
            and field_type.get("resolved_underlying_type") is None
        ):
            warnings.append(missing_metadata(f"{domain}.{projection}.{name}"))
        field_name = apply_case_style(name, field_case) if field_case else name
        type_name = _type_to_ts(
            field_type,
            (wire_by_field or {}).get(name, field.get("annotations", [])),
            ref_names or {},
            named_imports or {},
            named_enum_imports or {},
        )
        optional = field.get("optional") is True
        lines.append(f"  {field_name}{'?' if optional else ''}: {type_name};")
    lines.extend(["}", f"export type {projection} = {interface_name};"])
    content = "\n".join(lines) + "\n"
    return EmittedArtifact(
        target="typescript",
        ref=f"{domain}.{projection}@{version}",
        artifact_id=f"{domain}.{projection}.v{version}",
        path=out_dir / f"{domain}.{projection}.v{version}.ts",
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
        if isinstance(resolved, dict):
            for source in resolved.get("fields", []):
                if isinstance(source, dict) and source.get("name") == source_name:
                    value = source.get("type")
                    return cast(dict[str, Any], value) if isinstance(value, dict) else None
    value = field.get("type")
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def _type_to_ts(
    field_type: dict[str, Any] | None,
    wire: object,
    ref_names: dict[str, str],
    named_imports: dict[str, str],
    named_enum_imports: dict[str, str],
) -> str:
    if field_type is None:
        return "unknown"
    kind = field_type.get("kind")
    if kind in {
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
    }:
        if kind in {"int", "float"} and _hint(wire, "encoding") == "string":
            return "string"
        return {
            "string": "string",
            "int": "number",
            "float": "number",
            "bool": "boolean",
            "date": "string",
            "time": "string",
            "timestamp": "string",
            "uuid": "string",
            "duration": "string",
            "binary": "string",
            "json": "unknown",
            "u8": "number",
            "u16": "number",
            "u32": "number",
            "u64": "bigint",
            "u128": "bigint",
            "i8": "number",
            "i16": "number",
            "i32": "number",
            "i64": "bigint",
            "i128": "bigint",
        }.get(str(kind), "unknown")
    if kind in {"decimal", "fixed_binary"}:
        return "string"
    if kind == "array":
        item = _type_to_ts(_mapping(field_type, "item"), {}, ref_names, named_imports, named_enum_imports)
        return f"({item})[]" if _mapping(field_type, "item").get("kind") == "enum" else f"{item}[]"
    if kind == "map":
        value = _type_to_ts(_mapping(field_type, "value"), {}, ref_names, named_imports, named_enum_imports)
        return f"Record<string, {value}>"
    if kind == "enum":
        values = _enum_values(field_type, wire)
        return " | ".join(repr(value) for value in values) or "string"
    if kind == "enum_ref":
        return named_enum_imports.get(_enum_key(field_type), "string")
    if kind == "ref":
        return ref_names.get(_ref_key(field_type), "string")
    if kind == "named":
        name = str(field_type.get("name", ""))
        if name in named_imports:
            return named_imports[name]
        underlying = field_type.get("resolved_underlying_type")
        return (
            _type_to_ts(underlying, {}, ref_names, named_imports, named_enum_imports)
            if isinstance(underlying, dict)
            else name
        )
    if kind == "object":
        inner = "; ".join(
            f"{_string(item, 'name')}{'?' if item.get('optional') is True else ''}: "
            f"{_type_to_ts(item.get('type'), item.get('annotations', []), ref_names, named_imports, named_enum_imports)}"
            for item in _mappings(field_type.get("fields"))
        )
        return f"{{ {inner} }}"
    return "unknown"


def _enum_values(field_type: dict[str, Any], wire: object) -> list[str]:
    overrides = _hint_map(wire, "overrides")
    case = _hint(wire, "case")
    return [
        str(overrides.get(value, apply_case_style(value, case) if case else value))
        for value in field_type.get("values", [])
    ]


def _default_metadata(plan: PlanDocument) -> list[str]:
    source = _mapping(plan, "source")
    version = _mapping(source, "version")
    source_ref = f"{source.get('model', '')}@{_version_label(version)}"
    entries = [f"@modelable domain: {_string(plan, 'domain')}", f"@modelable name: {_string(plan, 'projection')}"]
    entries.extend(["@modelable kind: projection", f"@modelable version: {_integer(plan, 'version')}"])
    entries.append(f"@modelable source: {source_ref}")
    where = plan.get("where")
    if isinstance(where, str):
        entries.append(f"@modelable where: {where}")
    group_by = plan.get("group_by")
    if isinstance(group_by, list) and group_by:
        entries.append(f"@modelable groupBy: {', '.join(str(value) for value in group_by)}")
    return ["/**", *[f" * {entry}" for entry in entries], " */"]


def _ref_key(field_type: dict[str, Any]) -> str:
    return f"{field_type.get('target')}|{_version_label(_mapping(field_type, 'version'))}"


def _enum_key(field_type: dict[str, Any]) -> str:
    return f"{field_type.get('name')}|{field_type.get('version')}"


def _version_label(version: dict[str, Any]) -> str:
    if version.get("kind") in {"exact", "pinned"}:
        return str(version.get("version"))
    if version.get("kind") == "range":
        minimum = version.get("minInclusive", version.get("min_inclusive"))
        maximum = version.get("maxExclusive", version.get("max_exclusive"))
        return f">={minimum}<{maximum}"
    if version.get("kind") == "min":
        minimum = version.get("minInclusive", version.get("min_inclusive"))
        return f">={minimum}"
    return "?"


def _mapping(mapping: dict[str, object], key: str) -> dict[str, Any]:
    value = mapping.get(key)
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _mappings(value: object) -> list[dict[str, Any]]:
    return [cast(dict[str, Any], item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _fields(plan: dict[str, object]) -> list[dict[str, Any]]:
    return _mappings(plan.get("fields"))


def _string(mapping: dict[str, object], key: str) -> str:
    return str(mapping.get(key, ""))


def _integer(mapping: dict[str, object], key: str) -> int:
    value = mapping.get(key)
    if not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    return value


def _hint(value: object, key: str) -> str | None:
    candidate = value.get(key) if isinstance(value, dict) else getattr(value, key, None)
    return candidate if isinstance(candidate, str) else None


def _hint_map(value: object, key: str) -> dict[str, object]:
    candidate = value.get(key) if isinstance(value, dict) else getattr(value, key, None)
    return cast(dict[str, object], candidate) if isinstance(candidate, dict) else {}


def _pascal(value: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in value.replace("-", "_").split("_"))
