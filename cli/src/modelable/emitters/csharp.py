from __future__ import annotations

from pathlib import Path
from typing import Any

from modelable.compiler.workspace import Workspace
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.diagnostics import type_loss
from modelable.emitters.named_types import resolve_named_ref, resolve_named_types
from modelable.emitters.naming import pascalize_titlecase as _pascalize
from modelable.emitters.shapes import TypeShape
from modelable.parser.ir import (
    DirectMapping,
    DomainDef,
    EnumType,
    MdlFile,
    ModelVersion,
    ProjectionVersion,
    SemanticTypeDecl,
    latest_semantic_types,
)
from modelable.registry.resolver import resolve_model_ref


def emit_csharp(workspace: Workspace, out_dir: Path) -> list[EmittedArtifact]:
    """Emit C# source files for every model and projection version."""
    artifacts: list[EmittedArtifact] = []
    for domain in workspace.mdl.domains:
        named_names, named_shapes = resolve_named_types(
            workspace.mdl,
            current_domain=domain.name,
            model_name=_stable_type_name,
            emit_nominal_enums=True,
        )
        for decl in latest_semantic_types(domain):
            if isinstance(decl.underlying, EnumType):
                artifacts.append(_emit_enum_type(domain, decl, out_dir))
        for model_name, model_versions in domain.models.items():
            for model_version in model_versions:
                artifacts.append(
                    _emit_model(domain, model_name, model_version, out_dir, named_names, named_shapes, workspace.mdl)
                )
        for projection_name, projection_versions in domain.projections.items():
            for projection_version in projection_versions:
                artifacts.append(
                    _emit_projection(
                        domain, projection_name, projection_version, out_dir, workspace.mdl, named_names, named_shapes
                    )
                )
    return artifacts


def _artifact_id(domain: str, name: str, version: int) -> str:
    return f"{domain}.{name}.v{version}"


def _namespace_name(domain: str) -> str:
    return f"Modelable.{_pascalize(domain)}"


def _stable_type_name(domain: str, name: str, version: int) -> str:
    return f"{_pascalize(domain)}{_pascalize(name)}V{version}"


def _emit_model(
    domain: DomainDef,
    model_name: str,
    version: ModelVersion,
    out_dir: Path,
    named_names: dict[str, str],
    named_shapes: dict[str, TypeShape],
    mdl: MdlFile,
) -> EmittedArtifact:
    artifact_id = _artifact_id(domain.name, model_name, version.version)
    type_name = _stable_type_name(domain.name, model_name, version.version)
    imports: set[str] = set()
    nested_definitions: dict[str, list[str]] = {}
    warnings: list[str] = []

    params: list[str] = []
    for field in version.fields:
        shape = TypeShape.from_field_type(field.type, optional=field.optional)
        csharp_type = _shape_to_csharp(
            shape,
            owner_type=type_name,
            path=[field.name],
            definitions=nested_definitions,
            imports=imports,
            warnings=warnings,
            named_names=named_names,
            named_shapes=named_shapes,
            mdl=mdl,
            current_domain=domain.name,
        )
        prefix = "required " if not (shape.optional or shape.nullable) else ""
        params.append(f"    public {prefix}{csharp_type} {_property_name(field.name)} {{ get; init; }}")

    lines = _header_lines(_namespace_name(domain.name), imports)
    lines.append(f"public sealed record {type_name}")
    lines.append("{")
    lines.extend(params)
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
    mdl: MdlFile,
    named_names: dict[str, str],
    named_shapes: dict[str, TypeShape],
) -> EmittedArtifact:
    artifact_id = _artifact_id(domain.name, projection_name, version.version)
    type_name = _stable_type_name(domain.name, projection_name, version.version)
    imports: set[str] = set()
    nested_definitions: dict[str, list[str]] = {}
    warnings: list[str] = []

    params: list[str] = []
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
                imports=imports,
                warnings=warnings,
                named_names=named_names,
                named_shapes=named_shapes,
                mdl=mdl,
                current_domain=domain.name,
            )
            prefix = "required " if not (field_shape.optional or field_shape.nullable) else ""
        params.append(f"    public {prefix}{csharp_type} {_property_name(field.name)} {{ get; init; }}")

    lines = _header_lines(_namespace_name(domain.name), imports)
    lines.append(f"public sealed record {type_name}")
    lines.append("{")
    lines.extend(params)
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


def _header_lines(namespace: str, imports: set[str]) -> list[str]:
    return [
        "#nullable enable",
        "using System;",
        "using System.Collections.Generic;",
        *sorted(imports),
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
    imports: set[str],
    warnings: list[str],
    named_names: dict[str, str],
    named_shapes: dict[str, TypeShape],
    mdl: MdlFile,
    current_domain: str,
) -> str:
    base = _shape_base_to_csharp(
        shape,
        owner_type=owner_type,
        path=path,
        definitions=definitions,
        imports=imports,
        warnings=warnings,
        named_names=named_names,
        named_shapes=named_shapes,
        mdl=mdl,
        current_domain=current_domain,
    )
    if shape.optional or shape.nullable:
        return f"{base}?"
    return base


def _shape_base_to_csharp(
    shape: TypeShape,
    *,
    owner_type: str,
    path: list[str],
    definitions: dict[str, list[str]],
    imports: set[str],
    warnings: list[str],
    named_names: dict[str, str],
    named_shapes: dict[str, TypeShape],
    mdl: MdlFile,
    current_domain: str,
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
            element,
            owner_type=owner_type,
            path=[*path, "Item"],
            definitions=definitions,
            imports=imports,
            warnings=warnings,
            named_names=named_names,
            named_shapes=named_shapes,
            mdl=mdl,
            current_domain=current_domain,
        )
        return f"List<{inner}>"
    if shape.kind == "map":
        value = shape.value or TypeShape(kind="primitive", ref="object")
        inner = _shape_to_csharp(
            value,
            owner_type=owner_type,
            path=[*path, "Value"],
            definitions=definitions,
            imports=imports,
            warnings=warnings,
            named_names=named_names,
            named_shapes=named_shapes,
            mdl=mdl,
            current_domain=current_domain,
        )
        return f"Dictionary<string, {inner}>"
    if shape.kind == "ref":
        return "string"
    if shape.kind == "enum":
        return "string"
    if shape.kind == "named":
        declaring_domain, named_name, inline_shape = resolve_named_ref(
            mdl,
            current_domain=current_domain,
            ref=shape.ref or "",
            names=named_names,
            shapes=named_shapes,
            emit_nominal_enums=True,
        )
        if named_name is not None:
            if declaring_domain is not None and declaring_domain != current_domain:
                imports.add(f"using {_namespace_name(declaring_domain)};")
            return named_name
        if inline_shape is not None:
            return _shape_base_to_csharp(
                inline_shape,
                owner_type=owner_type,
                path=path,
                definitions=definitions,
                imports=imports,
                warnings=warnings,
                named_names=named_names,
                named_shapes=named_shapes,
                mdl=mdl,
                current_domain=current_domain,
            )
        return _pascalize(shape.ref or "Named")
    if shape.kind == "object":
        type_name = _nested_type_name(owner_type, path)
        if type_name not in definitions:
            definitions[type_name] = _build_record_definition(
                type_name,
                shape,
                owner_type=owner_type,
                path=path,
                definitions=definitions,
                imports=imports,
                warnings=warnings,
                named_names=named_names,
                named_shapes=named_shapes,
                mdl=mdl,
                current_domain=current_domain,
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
    imports: set[str],
    warnings: list[str],
    named_names: dict[str, str],
    named_shapes: dict[str, TypeShape],
    mdl: MdlFile,
    current_domain: str,
) -> list[str]:
    lines = [f"public sealed record {type_name}", "{"]
    for field in shape.fields:
        child_shape = field.shape
        child_type = _shape_to_csharp(
            child_shape,
            owner_type=owner_type,
            path=[*path, field.name],
            definitions=definitions,
            imports=imports,
            warnings=warnings,
            named_names=named_names,
            named_shapes=named_shapes,
            mdl=mdl,
            current_domain=current_domain,
        )
        prefix = "required " if not (child_shape.optional or child_shape.nullable) else ""
        lines.append(f"    public {prefix}{child_type} {_property_name(field.name)} {{ get; init; }}")
    lines.append("}")
    return lines


def _enum_member_name(value: str) -> str:
    return _pascalize(value)


def _emit_enum_type(domain: DomainDef, decl: SemanticTypeDecl, out_dir: Path) -> EmittedArtifact:
    """Emit one reusable C# ``enum`` for an enum-backed semantic declaration
    (evolution plan E8), imported everywhere it's referenced instead of
    degrading to a bare ``string``.

    C# enum members can't carry per-value data the way a Java or Rust enum
    can, so the wire mapping lives on companion extension methods
    (``ToWireValue()``/``ToXyz(string)``) instead of relying on
    ``Enum.ToString()``, which would emit the PascalCase member name rather
    than the canonical wire value.
    """
    assert isinstance(decl.underlying, EnumType)
    artifact_id = f"{domain.name}.{decl.name}"
    type_name = decl.name
    members = [(_enum_member_name(value), value) for value in decl.underlying.values]

    lines = [
        "#nullable enable",
        "using System;",
        "",
        f"namespace {_namespace_name(domain.name)};",
        "",
        f"public enum {type_name}",
        "{",
        *(f"    {member}," for member, _ in members),
        "}",
        "",
        f"public static class {type_name}Extensions",
        "{",
        f"    public static string ToWireValue(this {type_name} value) => value switch",
        "    {",
        *(f'        {type_name}.{member} => "{value}",' for member, value in members),
        f'        _ => throw new ArgumentOutOfRangeException(nameof(value), value, "Unknown {type_name}"),',
        "    };",
        "",
        f"    public static {type_name} To{type_name}(this string value) => value switch",
        "    {",
        *(f'        "{value}" => {type_name}.{member},' for member, value in members),
        f'        _ => throw new ArgumentException($"Unknown {type_name} wire value: {{value}}", nameof(value)),',
        "    };",
        "}",
    ]
    text = "\n".join(lines) + "\n"
    return EmittedArtifact(
        target="csharp",
        ref=artifact_id,
        artifact_id=artifact_id,
        path=out_dir / f"{artifact_id}.cs",
        content=text,
        content_hash=compute_content_hash(text),
        warnings=[],
    )


def _resolve_projection_field_shape(field: Any, projection: ProjectionVersion, mdl: MdlFile) -> TypeShape | None:
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
        if src_field.name == field.mapping.source_field and hasattr(src_field, "type"):
            return TypeShape.from_field_type(src_field.type, optional=getattr(src_field, "optional", False))
    return None
