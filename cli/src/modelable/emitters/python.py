from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from modelable.compiler.workspace import Workspace
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.diagnostics import type_loss
from modelable.emitters.named_types import resolve_named_ref, resolve_named_types
from modelable.emitters.naming import pascalize_plain as _pascalize
from modelable.emitters.naming import snake_case as _snake_case
from modelable.emitters.shapes import TypeShape
from modelable.parser.ir import DirectMapping, DomainDef, MdlFile, ModelVersion, ProjectionVersion
from modelable.registry.resolver import resolve_model_ref


def emit_python(workspace: Workspace, out_dir: Path) -> list[EmittedArtifact]:
    """Emit Python dataclass modules for every published model and projection version."""
    artifacts: list[EmittedArtifact] = []
    for domain in workspace.mdl.domains:
        named_names, named_shapes = resolve_named_types(
            workspace.mdl, current_domain=domain.name, model_name=_stable_type_name
        )
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


def _stable_type_name(domain: str, name: str, version: int) -> str:
    return f"{_pascalize(domain)}{_pascalize(name)}V{version}"


def _module_filename(type_name: str) -> str:
    return f"{_snake_case(type_name)}.py"


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
    nested_definitions: dict[str, list[str]] = {}
    imports: set[str] = set()
    field_specs = _field_specs_from_model_fields(
        version.fields,
        owner_type=type_name,
        path=[],
        definitions=nested_definitions,
        imports=imports,
        named_names=named_names,
        named_shapes=named_shapes,
        mdl=mdl,
        current_domain=domain.name,
    )

    lines = _header_lines(imports)
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
    mdl: MdlFile,
    named_names: dict[str, str],
    named_shapes: dict[str, TypeShape],
) -> EmittedArtifact:
    artifact_id = _artifact_id(domain.name, projection_name, version.version)
    type_name = _stable_type_name(domain.name, projection_name, version.version)
    nested_definitions: dict[str, list[str]] = {}
    imports: set[str] = set()
    warnings: list[str] = []

    field_specs: list[tuple[int, str, str, bool]] = []
    for index, field in enumerate(version.fields):
        field_shape = _resolve_projection_field_shape(field, version, mdl)
        if field_shape is None:
            warnings.append(type_loss(f"{domain.name}.{projection_name}.{field.name}"))
            field_specs.append((index, field.name, "object", False))
            continue
        annotation = _shape_annotation(
            field_shape,
            owner_type=type_name,
            path=[field.name],
            definitions=nested_definitions,
            imports=imports,
            named_names=named_names,
            named_shapes=named_shapes,
            mdl=mdl,
            current_domain=domain.name,
        )
        optional = field_shape.optional or field_shape.nullable
        field_specs.append((index, field.name, annotation, optional))

    lines = _header_lines(imports)
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
    fields: Any,
    *,
    owner_type: str,
    path: list[str],
    definitions: dict[str, list[str]],
    imports: set[str],
    named_names: dict[str, str],
    named_shapes: dict[str, TypeShape],
    mdl: MdlFile,
    current_domain: str,
) -> list[tuple[int, str, str, bool]]:
    specs: list[tuple[int, str, str, bool]] = []
    for index, field in enumerate(fields):
        shape = TypeShape.from_field_type(field.type, optional=field.optional)
        annotation = _shape_annotation(
            shape,
            owner_type=owner_type,
            path=[*path, field.name],
            definitions=definitions,
            imports=imports,
            named_names=named_names,
            named_shapes=named_shapes,
            mdl=mdl,
            current_domain=current_domain,
        )
        default_none = shape.optional or shape.nullable
        specs.append((index, field.name, annotation, default_none))
    return specs


def _field_specs_from_object_fields(
    fields: Any,
    *,
    owner_type: str,
    path: list[str],
    definitions: dict[str, list[str]],
    imports: set[str],
    named_names: dict[str, str],
    named_shapes: dict[str, TypeShape],
    mdl: MdlFile,
    current_domain: str,
) -> list[tuple[int, str, str, bool]]:
    specs: list[tuple[int, str, str, bool]] = []
    for index, field in enumerate(fields):
        annotation = _shape_annotation(
            field.shape,
            owner_type=owner_type,
            path=[*path, field.name],
            definitions=definitions,
            imports=imports,
            named_names=named_names,
            named_shapes=named_shapes,
            mdl=mdl,
            current_domain=current_domain,
        )
        default_none = field.optional or field.shape.optional or field.shape.nullable
        specs.append((index, field.name, annotation, default_none))
    return specs


def _shape_annotation(
    shape: TypeShape,
    *,
    owner_type: str,
    path: list[str],
    definitions: dict[str, list[str]],
    imports: set[str],
    named_names: dict[str, str],
    named_shapes: dict[str, TypeShape],
    mdl: MdlFile,
    current_domain: str,
) -> str:
    base = _shape_base_annotation(
        shape,
        owner_type=owner_type,
        path=path,
        definitions=definitions,
        imports=imports,
        named_names=named_names,
        named_shapes=named_shapes,
        mdl=mdl,
        current_domain=current_domain,
    )
    if shape.optional or shape.nullable:
        return f"Optional[{base}]"
    return base


def _shape_base_annotation(
    shape: TypeShape,
    *,
    owner_type: str,
    path: list[str],
    definitions: dict[str, list[str]],
    imports: set[str],
    named_names: dict[str, str],
    named_shapes: dict[str, TypeShape],
    mdl: MdlFile,
    current_domain: str,
) -> str:
    if shape.kind == "primitive":
        return _primitive_to_python(shape.ref or "string")
    if shape.kind == "decimal":
        return "Decimal"
    if shape.kind == "fixed_binary":
        return "bytes"
    if shape.kind == "array":
        element = shape.element or TypeShape(kind="primitive", ref="object")
        element_type = _shape_annotation(
            element,
            owner_type=owner_type,
            path=[*path, "Item"],
            definitions=definitions,
            imports=imports,
            named_names=named_names,
            named_shapes=named_shapes,
            mdl=mdl,
            current_domain=current_domain,
        )
        return f"list[{element_type}]"
    if shape.kind == "map":
        value = shape.value or TypeShape(kind="primitive", ref="object")
        value_type = _shape_annotation(
            value,
            owner_type=owner_type,
            path=[*path, "Value"],
            definitions=definitions,
            imports=imports,
            named_names=named_names,
            named_shapes=named_shapes,
            mdl=mdl,
            current_domain=current_domain,
        )
        return f"dict[str, {value_type}]"
    if shape.kind == "ref":
        return "str"
    if shape.kind == "enum":
        return "str"
    if shape.kind == "named":
        declaring_domain, named_name, inline_shape = resolve_named_ref(
            mdl, current_domain=current_domain, ref=shape.ref or "", names=named_names, shapes=named_shapes
        )
        if named_name is not None:
            if declaring_domain is not None and declaring_domain != current_domain:
                imports.add(
                    f"from {_package_name(declaring_domain)}.{_module_filename(named_name)[:-3]} import {named_name}"
                )
            return named_name
        if inline_shape is not None:
            return _shape_base_annotation(
                inline_shape,
                owner_type=owner_type,
                path=path,
                definitions=definitions,
                imports=imports,
                named_names=named_names,
                named_shapes=named_shapes,
                mdl=mdl,
                current_domain=current_domain,
            )
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
                    imports=imports,
                    named_names=named_names,
                    named_shapes=named_shapes,
                    mdl=mdl,
                    current_domain=current_domain,
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
    }
    return mapping.get(kind, "str")


def _nested_type_name(owner_type: str, path: list[str]) -> str:
    suffix = "".join(_pascalize(part) for part in path)
    return f"{owner_type}{suffix}" if suffix else owner_type


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
