from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from modelable.compiler.workspace import Workspace
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.diagnostics import type_loss
from modelable.emitters.named_types import resolve_named_ref, resolve_named_types
from modelable.emitters.naming import pascalize_plain as _pascalize
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


def emit_java(workspace: Workspace, out_dir: Path) -> list[EmittedArtifact]:
    """Emit Java source files for every model and projection version."""
    artifacts: list[EmittedArtifact] = []
    for domain in workspace.mdl.domains:
        named_names, named_shapes = resolve_named_types(
            workspace.mdl,
            current_domain=domain.name,
            model_name=lambda _domain, name, version: _type_name(name, version),
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


def _package_name(domain: str) -> str:
    parts = [part.lower() for part in re.split(r"[^A-Za-z0-9]+", domain) if part]
    return ".".join(parts) or "modelable"


def _type_name(name: str, version: int) -> str:
    return f"{_pascalize(name)}V{version}"


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
    type_name = _type_name(model_name, version.version)
    imports: set[str] = set()
    nested_definitions: dict[str, list[str]] = {}
    warnings: list[str] = []

    params: list[str] = []
    for field in version.fields:
        shape = TypeShape.from_field_type(field.type, optional=field.optional)
        java_type = _shape_to_java(
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
        params.append(f"    {java_type} {_field_name(field.name)}")
    lines = _header_lines(_package_name(domain.name), imports)
    lines.append(f"public record {type_name}(")
    lines.append(",\n".join(params))
    lines.append(") {")
    lines.extend(_render_nested_definitions(nested_definitions))
    lines.append("}")

    text = "\n".join(lines) + "\n"
    return EmittedArtifact(
        target="java",
        ref=f"{domain.name}.{model_name}@{version.version}",
        artifact_id=artifact_id,
        path=out_dir / _java_path(domain.name, type_name),
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
    type_name = _type_name(projection_name, version.version)
    imports: set[str] = set()
    nested_definitions: dict[str, list[str]] = {}
    warnings: list[str] = []

    params: list[str] = []
    for field in version.fields:
        field_shape = _resolve_projection_field_shape(field, version, mdl)
        if field_shape is None:
            warnings.append(type_loss(f"{domain.name}.{projection_name}.{field.name}"))
            java_type = "Object"
        else:
            java_type = _shape_to_java(
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
        params.append(f"    {java_type} {_field_name(field.name)}")
    lines = _header_lines(_package_name(domain.name), imports)
    lines.append(f"public record {type_name}(")
    lines.append(",\n".join(params))
    lines.append(") {")
    lines.extend(_render_nested_definitions(nested_definitions))
    lines.append("}")

    text = "\n".join(lines) + "\n"
    return EmittedArtifact(
        target="java",
        ref=f"{domain.name}.{projection_name}@{version.version}",
        artifact_id=artifact_id,
        path=out_dir / _java_path(domain.name, type_name),
        content=text,
        content_hash=compute_content_hash(text),
        warnings=warnings,
    )


def _header_lines(package_name: str, imports: set[str]) -> list[str]:
    return [
        f"package {package_name};",
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


def _render_nested_definitions(definitions: dict[str, list[str]]) -> list[str]:
    lines: list[str] = []
    for definition in definitions.values():
        lines.append("")
        lines.extend(definition)
    return lines


def _field_name(value: str) -> str:
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", value) if part]
    if not parts:
        return "field"
    first = parts[0][:1].lower() + parts[0][1:]
    tail = "".join(part[:1].upper() + part[1:] for part in parts[1:])
    return first + tail


def _shape_to_java(
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
    base = _shape_base_to_java(
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
        return f"Optional<{base}>"
    return base


def _shape_base_to_java(
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
        field_ref = f"{owner_type}.{'.'.join(path)}"
        return _primitive_to_java(shape.ref or "string", warnings=warnings, field_ref=field_ref)
    if shape.kind == "decimal":
        return "BigDecimal"
    if shape.kind == "fixed_binary":
        field_ref = f"{owner_type}.{'.'.join(path)}"
        warnings.append(
            type_loss(f"{field_ref} (binary({shape.length}) length is not enforced by the Java type system)")
        )
        return "byte[]"
    if shape.kind == "array":
        element = shape.element or TypeShape(kind="primitive", ref="object")
        inner = _shape_to_java(
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
        inner = _shape_to_java(
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
        return f"Map<String, {inner}>"
    if shape.kind == "ref":
        return "String"
    if shape.kind == "enum":
        return "String"
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
                imports.add(f"import {_package_name(declaring_domain)}.{named_name};")
            return named_name
        if inline_shape is not None:
            return _shape_base_to_java(
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
        type_name = _nested_type_name(path)
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
    return "Object"


def _primitive_to_java(kind: str, *, warnings: list[str], field_ref: str) -> str:
    if kind in ("u8", "u16", "u32", "u64"):
        warnings.append(type_loss(field_ref))
    mapping = {
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
    }
    return mapping.get(kind, "String")


def _nested_type_name(path: list[str]) -> str:
    return "".join(_pascalize(part) for part in path) or "Nested"


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
    lines = [f"    public record {type_name}("]
    params: list[str] = []
    for field in shape.fields:
        child_shape = field.shape
        child_type = _shape_to_java(
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
        params.append(f"        {child_type} {_field_name(field.name)}")
    lines.append(",\n".join(params))
    lines.append("    ) {}")
    return lines


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


def _java_path(domain: str, type_name: str) -> Path:
    return Path(*_package_name(domain).split(".")) / f"{type_name}.java"


def _enum_member_name(value: str) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").upper()
    if text and text[0].isdigit():
        text = f"_{text}"
    return text or "UNKNOWN"


def _emit_enum_type(domain: DomainDef, decl: SemanticTypeDecl, out_dir: Path) -> EmittedArtifact:
    """Emit one reusable Java ``enum`` for an enum-backed semantic
    declaration (evolution plan E8), imported everywhere it's referenced
    instead of degrading to a bare ``String``.

    Carries its canonical wire value explicitly (``toWireValue``/
    ``fromWireValue``) rather than relying on ``Enum.name()``, since the
    Java-conventional ``UPPER_SNAKE_CASE`` constant name is not the same
    string as the wire value every other target preserves.
    """
    assert isinstance(decl.underlying, EnumType)
    artifact_id = f"{domain.name}.{decl.name}"
    type_name = decl.name
    members = [(_enum_member_name(value), value) for value in decl.underlying.values]

    lines = [f"package {_package_name(domain.name)};", "", f"public enum {type_name} {{"]
    lines.append(",\n".join(f'    {member}("{value}")' for member, value in members) + ";")
    lines.extend(
        [
            "",
            "    private final String wireValue;",
            "",
            f"    {type_name}(String wireValue) {{",
            "        this.wireValue = wireValue;",
            "    }",
            "",
            "    public String toWireValue() {",
            "        return wireValue;",
            "    }",
            "",
            f"    public static {type_name} fromWireValue(String value) {{",
            f"        for ({type_name} item : values()) {{",
            "            if (item.wireValue.equals(value)) {",
            "                return item;",
            "            }",
            "        }",
            f'        throw new IllegalArgumentException("Unknown {type_name} wire value: " + value);',
            "    }",
            "}",
        ]
    )
    text = "\n".join(lines) + "\n"
    return EmittedArtifact(
        target="java",
        ref=artifact_id,
        artifact_id=artifact_id,
        path=out_dir / _java_path(domain.name, type_name),
        content=text,
        content_hash=compute_content_hash(text),
        warnings=[],
    )
