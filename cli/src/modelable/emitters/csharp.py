from __future__ import annotations

import re
from pathlib import Path

from modelable.compiler.workspace import Workspace
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.diagnostics import type_loss
from modelable.emitters.shapes import TypeShape
from modelable.parser.ir import DirectMapping, DomainDef, ModelVersion, ProjectionVersion
from modelable.registry.resolver import resolve_model_ref


def emit_csharp(workspace: Workspace, out_dir: Path) -> list[EmittedArtifact]:
    """Emit C# source files for every model and projection version."""
    artifacts: list[EmittedArtifact] = []
    for domain in workspace.mdl.domains:
        for model_name, versions in domain.models.items():
            for version in versions:
                artifacts.append(_emit_model(domain, model_name, version, out_dir))
        for projection_name, versions in domain.projections.items():
            for version in versions:
                artifacts.append(_emit_projection(domain, projection_name, version, out_dir, workspace.mdl))
    return artifacts


def _artifact_id(domain: str, name: str, version: int) -> str:
    return f"{domain}.{name}.v{version}"


def _pascalize(value: str) -> str:
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", value) if part]
    return "".join(part[:1].upper() + part[1:] for part in parts) or "Generated"


def _namespace_name(domain: str) -> str:
    return f"Modelable.{_pascalize(domain)}"


def _stable_type_name(domain: str, name: str, version: int) -> str:
    return f"{_pascalize(domain)}{_pascalize(name)}V{version}"


def _emit_model(domain: DomainDef, model_name: str, version: ModelVersion, out_dir: Path) -> EmittedArtifact:
    artifact_id = _artifact_id(domain.name, model_name, version.version)
    type_name = _stable_type_name(domain.name, model_name, version.version)
    lines = _header_lines(_namespace_name(domain.name))
    nested_definitions: dict[str, list[str]] = {}
    warnings: list[str] = []

    lines.append(f"public sealed record {type_name}")
    lines.append("{")
    for field in version.fields:
        shape = TypeShape.from_field_type(field.type, optional=field.optional)
        csharp_type = _shape_to_csharp(
            shape, owner_type=type_name, path=[field.name], definitions=nested_definitions, warnings=warnings
        )
        prefix = "required " if not (shape.optional or shape.nullable) else ""
        lines.append(f"    public {prefix}{csharp_type} {_property_name(field.name)} {{ get; init; }}")
    lines.append("}")
    lines.extend(_render_nested_definitions(nested_definitions))

    text = "\n".join(lines) + "\n"
    return EmittedArtifact(
        target="csharp",
        ref=f"{domain.name}.{model_name}@{version.version}",
        artifact_id=artifact_id,
        path=out_dir / f"{artifact_id}.cs",
        content=text,
        content_hash=compute_content_hash(text),
        warnings=warnings,
    )


def _emit_projection(
    domain: DomainDef,
    projection_name: str,
    version: ProjectionVersion,
    out_dir: Path,
    mdl,
) -> EmittedArtifact:
    artifact_id = _artifact_id(domain.name, projection_name, version.version)
    type_name = _stable_type_name(domain.name, projection_name, version.version)
    lines = _header_lines(_namespace_name(domain.name))
    nested_definitions: dict[str, list[str]] = {}
    warnings: list[str] = []

    lines.append(f"public sealed record {type_name}")
    lines.append("{")
    for field in version.fields:
        field_shape = _resolve_projection_field_shape(field, version, mdl)
        if field_shape is None:
            warnings.append(type_loss(f"{domain.name}.{projection_name}.{field.name}"))
            csharp_type = "object"
            prefix = "required "
        else:
            csharp_type = _shape_to_csharp(
                field_shape,
                owner_type=type_name,
                path=[field.name],
                definitions=nested_definitions,
                warnings=warnings,
            )
            prefix = "required " if not (field_shape.optional or field_shape.nullable) else ""
        lines.append(f"    public {prefix}{csharp_type} {_property_name(field.name)} {{ get; init; }}")
    lines.append("}")
    lines.extend(_render_nested_definitions(nested_definitions))

    text = "\n".join(lines) + "\n"
    return EmittedArtifact(
        target="csharp",
        ref=f"{domain.name}.{projection_name}@{version.version}",
        artifact_id=artifact_id,
        path=out_dir / f"{artifact_id}.cs",
        content=text,
        content_hash=compute_content_hash(text),
        warnings=warnings,
    )


def _header_lines(namespace: str) -> list[str]:
    return [
        "#nullable enable",
        "using System;",
        "using System.Collections.Generic;",
        "",
        f"namespace {namespace};",
        "",
    ]


def _render_nested_definitions(definitions: dict[str, list[str]]) -> list[str]:
    lines: list[str] = []
    for definition in definitions.values():
        lines.append("")
        lines.extend(definition)
    return lines


def _property_name(value: str) -> str:
    return _pascalize(value)


def _shape_to_csharp(
    shape: TypeShape,
    *,
    owner_type: str,
    path: list[str],
    definitions: dict[str, list[str]],
    warnings: list[str],
) -> str:
    base = _shape_base_to_csharp(shape, owner_type=owner_type, path=path, definitions=definitions, warnings=warnings)
    if shape.optional or shape.nullable:
        return f"{base}?"
    return base


def _shape_base_to_csharp(
    shape: TypeShape,
    *,
    owner_type: str,
    path: list[str],
    definitions: dict[str, list[str]],
    warnings: list[str],
) -> str:
    if shape.kind == "primitive":
        return _primitive_to_csharp(shape.ref or "string")
    if shape.kind == "decimal":
        return "decimal"
    if shape.kind == "fixed_binary":
        field_ref = f"{owner_type}.{'.'.join(path)}"
        warnings.append(type_loss(f"{field_ref} (binary({shape.length}) length is not enforced by the C# type system)"))
        return "byte[]"
    if shape.kind == "array":
        element = shape.element or TypeShape(kind="primitive", ref="object")
        inner = _shape_to_csharp(
            element, owner_type=owner_type, path=[*path, "Item"], definitions=definitions, warnings=warnings
        )
        return f"List<{inner}>"
    if shape.kind == "map":
        value = shape.value or TypeShape(kind="primitive", ref="object")
        inner = _shape_to_csharp(
            value, owner_type=owner_type, path=[*path, "Value"], definitions=definitions, warnings=warnings
        )
        return f"Dictionary<string, {inner}>"
    if shape.kind == "ref":
        return "string"
    if shape.kind == "enum":
        return "string"
    if shape.kind == "named":
        return _pascalize(shape.ref or "Named")
    if shape.kind == "object":
        type_name = _nested_type_name(owner_type, path)
        if type_name not in definitions:
            definitions[type_name] = _build_record_definition(
                type_name, shape, owner_type=owner_type, path=path, definitions=definitions, warnings=warnings
            )
        return type_name
    return "object"


def _primitive_to_csharp(kind: str) -> str:
    mapping = {
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
    }
    return mapping.get(kind, "string")


def _nested_type_name(owner_type: str, path: list[str]) -> str:
    suffix = "".join(_pascalize(part) for part in path)
    return f"{owner_type}{suffix}" if suffix else owner_type


def _build_record_definition(
    type_name: str,
    shape: TypeShape,
    *,
    owner_type: str,
    path: list[str],
    definitions: dict[str, list[str]],
    warnings: list[str],
) -> list[str]:
    lines = [f"public sealed record {type_name}", "{"]
    for field in shape.fields:
        child_shape = field.shape
        child_type = _shape_to_csharp(
            child_shape,
            owner_type=owner_type,
            path=[*path, field.name],
            definitions=definitions,
            warnings=warnings,
        )
        prefix = "required " if not (child_shape.optional or child_shape.nullable) else ""
        lines.append(f"    public {prefix}{child_type} {_property_name(field.name)} {{ get; init; }}")
    lines.append("}")
    return lines


def _resolve_projection_field_shape(field, projection: ProjectionVersion, mdl):
    if not isinstance(field.mapping, DirectMapping):
        return None
    try:
        source_domain, source_model = projection.source.model.rsplit(".", 1)
    except ValueError:
        return None
    try:
        resolved = resolve_model_ref(mdl, f"{source_domain}.{source_model}", projection.source.version)
    except LookupError:
        return None
    source_mv = resolved.version
    for src_field in source_mv.fields:
        if src_field.name == field.mapping.source_field:
            return TypeShape.from_field_type(src_field.type, optional=src_field.optional)
    return None
