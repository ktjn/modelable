from __future__ import annotations

import re
from pathlib import Path

from modelable.compiler.workspace import Workspace
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.diagnostics import type_loss
from modelable.emitters.shapes import TypeShape
from modelable.parser.ir import DirectMapping, DomainDef, ModelVersion, ProjectionVersion
from modelable.registry.resolver import resolve_model_ref


def emit_python(workspace: Workspace, out_dir: Path) -> list[EmittedArtifact]:
    """Emit Python dataclass modules for every published model and projection version."""
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


def _snake_case(value: str) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    text = re.sub(r"[^A-Za-z0-9]+", "_", text)
    text = text.strip("_").lower()
    return text or "generated"


def _stable_type_name(domain: str, name: str, version: int) -> str:
    return f"{_pascalize(domain)}{_pascalize(name)}V{version}"


def _module_filename(type_name: str) -> str:
    return f"{_snake_case(type_name)}.py"


def _emit_model(domain: DomainDef, model_name: str, version: ModelVersion, out_dir: Path) -> EmittedArtifact:
    artifact_id = _artifact_id(domain.name, model_name, version.version)
    type_name = _stable_type_name(domain.name, model_name, version.version)
    nested_definitions: dict[str, list[str]] = {}
    field_specs = _field_specs_from_model_fields(version.fields, owner_type=type_name, path=[], definitions=nested_definitions)

    lines = _header_lines()
    lines.extend(_render_dataclass_definition(type_name, field_specs))
    lines.extend(_render_nested_definitions(nested_definitions))

    text = "\n".join(lines) + "\n"
    return EmittedArtifact(
        target="python",
        ref=f"{domain.name}.{model_name}@{version.version}",
        artifact_id=artifact_id,
        path=out_dir / _module_path(domain.name, type_name),
        content=text,
        content_hash=compute_content_hash(text),
        warnings=[],
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
    nested_definitions: dict[str, list[str]] = {}
    warnings: list[str] = []

    field_specs: list[tuple[int, str, str, bool]] = []
    for index, field in enumerate(version.fields):
        field_shape = _resolve_projection_field_shape(field, version, mdl)
        if field_shape is None:
            warnings.append(type_loss(f"{domain.name}.{projection_name}.{field.name}"))
            field_specs.append((index, field.name, "object", False))
            continue
        annotation = _shape_annotation(field_shape, owner_type=type_name, path=[field.name], definitions=nested_definitions)
        optional = field_shape.optional or field_shape.nullable
        field_specs.append((index, field.name, annotation, optional))

    lines = _header_lines()
    lines.extend(_render_dataclass_definition(type_name, field_specs))
    lines.extend(_render_nested_definitions(nested_definitions))

    text = "\n".join(lines) + "\n"
    return EmittedArtifact(
        target="python",
        ref=f"{domain.name}.{projection_name}@{version.version}",
        artifact_id=artifact_id,
        path=out_dir / _module_path(domain.name, type_name),
        content=text,
        content_hash=compute_content_hash(text),
        warnings=warnings,
    )


def _header_lines() -> list[str]:
    return [
        "from __future__ import annotations",
        "",
        "from dataclasses import dataclass",
        "from datetime import date, datetime, time, timedelta",
        "from decimal import Decimal",
        "from typing import Optional",
        "from uuid import UUID",
        "",
    ]


def _render_nested_definitions(definitions: dict[str, list[str]]) -> list[str]:
    lines: list[str] = []
    for definition in definitions.values():
        lines.append("")
        lines.extend(definition)
    return lines


def _module_path(domain: str, type_name: str) -> Path:
    return Path(*_package_name(domain).split(".")) / _module_filename(type_name)


def _package_name(domain: str) -> str:
    parts = [part.lower() for part in re.split(r"[^A-Za-z0-9]+", domain) if part]
    return ".".join(parts) or "modelable"


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


def _field_specs_from_model_fields(
    fields,
    *,
    owner_type: str,
    path: list[str],
    definitions: dict[str, list[str]],
) -> list[tuple[int, str, str, bool]]:
    specs: list[tuple[int, str, str, bool]] = []
    for index, field in enumerate(fields):
        shape = TypeShape.from_field_type(field.type, optional=field.optional)
        annotation = _shape_annotation(shape, owner_type=owner_type, path=[*path, field.name], definitions=definitions)
        default_none = shape.optional or shape.nullable
        specs.append((index, field.name, annotation, default_none))
    return specs


def _field_specs_from_object_fields(
    fields,
    *,
    owner_type: str,
    path: list[str],
    definitions: dict[str, list[str]],
) -> list[tuple[int, str, str, bool]]:
    specs: list[tuple[int, str, str, bool]] = []
    for index, field in enumerate(fields):
        annotation = _shape_annotation(field.shape, owner_type=owner_type, path=[*path, field.name], definitions=definitions)
        default_none = field.optional or field.shape.optional or field.shape.nullable
        specs.append((index, field.name, annotation, default_none))
    return specs


def _shape_annotation(
    shape: TypeShape,
    *,
    owner_type: str,
    path: list[str],
    definitions: dict[str, list[str]],
) -> str:
    base = _shape_base_annotation(shape, owner_type=owner_type, path=path, definitions=definitions)
    if shape.optional or shape.nullable:
        return f"Optional[{base}]"
    return base


def _shape_base_annotation(
    shape: TypeShape,
    *,
    owner_type: str,
    path: list[str],
    definitions: dict[str, list[str]],
) -> str:
    if shape.kind == "primitive":
        return _primitive_to_python(shape.ref or "string")
    if shape.kind == "decimal":
        return "Decimal"
    if shape.kind == "array":
        element = shape.element or TypeShape(kind="primitive", ref="object")
        element_type = _shape_annotation(element, owner_type=owner_type, path=path + ["Item"], definitions=definitions)
        return f"list[{element_type}]"
    if shape.kind == "map":
        value = shape.value or TypeShape(kind="primitive", ref="object")
        value_type = _shape_annotation(value, owner_type=owner_type, path=path + ["Value"], definitions=definitions)
        return f"dict[str, {value_type}]"
    if shape.kind == "ref":
        return "str"
    if shape.kind == "enum":
        return "str"
    if shape.kind == "named":
        return _pascalize(shape.ref or "Named")
    if shape.kind == "object":
        type_name = _nested_type_name(owner_type, path)
        if type_name not in definitions:
            definitions[type_name] = _render_dataclass_definition(
                type_name,
                _field_specs_from_object_fields(
                    shape.fields,
                    owner_type=owner_type,
                    path=path,
                    definitions=definitions,
                ),
            )
        return type_name
    return "object"


def _primitive_to_python(kind: str) -> str:
    mapping = {
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
    }
    return mapping.get(kind, "str")


def _nested_type_name(owner_type: str, path: list[str]) -> str:
    suffix = "".join(_pascalize(part) for part in path)
    return f"{owner_type}{suffix}" if suffix else owner_type


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
