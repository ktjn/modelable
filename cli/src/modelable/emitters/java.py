from __future__ import annotations

import re
from pathlib import Path

from modelable.compiler.workspace import Workspace
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.diagnostics import type_loss
from modelable.emitters.shapes import TypeShape
from modelable.parser.ir import DirectMapping, DomainDef, ModelVersion, ProjectionVersion
from modelable.registry.resolver import resolve_model_ref


def emit_java(workspace: Workspace, out_dir: Path) -> list[EmittedArtifact]:
    """Emit Java source files for every model and projection version."""
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


def _package_name(domain: str) -> str:
    parts = [part.lower() for part in re.split(r"[^A-Za-z0-9]+", domain) if part]
    return ".".join(parts) or "modelable"


def _pascalize(value: str) -> str:
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", value) if part]
    return "".join(part[:1].upper() + part[1:] for part in parts) or "Generated"


def _type_name(name: str, version: int) -> str:
    return f"{_pascalize(name)}V{version}"


def _emit_model(domain: DomainDef, model_name: str, version: ModelVersion, out_dir: Path) -> EmittedArtifact:
    artifact_id = _artifact_id(domain.name, model_name, version.version)
    type_name = _type_name(model_name, version.version)
    lines = _header_lines(_package_name(domain.name))
    nested_definitions: dict[str, list[str]] = {}
    warnings: list[str] = []

    params: list[str] = []
    for field in version.fields:
        shape = TypeShape.from_field_type(field.type, optional=field.optional)
        java_type = _shape_to_java(shape, owner_type=type_name, path=[field.name], definitions=nested_definitions)
        params.append(f"    {java_type} {_field_name(field.name)}")
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
    mdl,
) -> EmittedArtifact:
    artifact_id = _artifact_id(domain.name, projection_name, version.version)
    type_name = _type_name(projection_name, version.version)
    lines = _header_lines(_package_name(domain.name))
    nested_definitions: dict[str, list[str]] = {}
    warnings: list[str] = []

    params: list[str] = []
    for field in version.fields:
        field_shape = _resolve_projection_field_shape(field, version, mdl)
        if field_shape is None:
            warnings.append(type_loss(f"{domain.name}.{projection_name}.{field.name}"))
            java_type = "Object"
        else:
            java_type = _shape_to_java(field_shape, owner_type=type_name, path=[field.name], definitions=nested_definitions)
        params.append(f"    {java_type} {_field_name(field.name)}")
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


def _header_lines(package_name: str) -> list[str]:
    return [
        f"package {package_name};",
        "",
        "import java.math.BigDecimal;",
        "import java.time.Duration;",
        "import java.time.Instant;",
        "import java.time.LocalDate;",
        "import java.time.LocalTime;",
        "import java.util.List;",
        "import java.util.Map;",
        "import java.util.Optional;",
        "import java.util.UUID;",
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
) -> str:
    base = _shape_base_to_java(shape, owner_type=owner_type, path=path, definitions=definitions)
    if shape.optional or shape.nullable:
        return f"Optional<{base}>"
    return base


def _shape_base_to_java(
    shape: TypeShape,
    *,
    owner_type: str,
    path: list[str],
    definitions: dict[str, list[str]],
) -> str:
    if shape.kind == "primitive":
        return _primitive_to_java(shape.ref or "string")
    if shape.kind == "decimal":
        return "BigDecimal"
    if shape.kind == "array":
        element = shape.element or TypeShape(kind="primitive", ref="object")
        return f"List<{_shape_to_java(element, owner_type=owner_type, path=[*path, 'Item'], definitions=definitions)}>"
    if shape.kind == "map":
        value = shape.value or TypeShape(kind="primitive", ref="object")
        return f"Map<String, {_shape_to_java(value, owner_type=owner_type, path=[*path, 'Value'], definitions=definitions)}>"
    if shape.kind == "ref":
        return "String"
    if shape.kind == "enum":
        return "String"
    if shape.kind == "named":
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
            )
        return type_name
    return "Object"


def _primitive_to_java(kind: str) -> str:
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
        )
        params.append(f"        {child_type} {_field_name(field.name)}")
    lines.append(",\n".join(params))
    lines.append("    ) {}")
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


def _java_path(domain: str, type_name: str) -> Path:
    return Path(*_package_name(domain).split(".")) / f"{type_name}.java"
