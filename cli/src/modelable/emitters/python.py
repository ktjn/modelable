from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from modelable.compiler.workspace import Workspace
from modelable.emitters.base import EmittedArtifact, compute_content_hash, render_nested_definitions
from modelable.emitters.base import artifact_id as _artifact_id
from modelable.emitters.named_types import resolve_named_ref, resolve_named_types
from modelable.emitters.naming import find_identifier_collisions, package_name
from modelable.emitters.naming import pascalize_plain as _pascalize
from modelable.emitters.naming import snake_case as _snake_case
from modelable.emitters.projection_shapes import projection_field_shape
from modelable.emitters.python_plan import emit_python_projection_plan
from modelable.emitters.shapes import TypeShape
from modelable.parser.ir import (
    DomainDef,
    EnumProjectionDecl,
    EnumType,
    MdlFile,
    ModelVersion,
    ProjectionVersion,
    SemanticTypeDecl,
)
from modelable.planner.plans import build_plan_documents
from modelable.planner.protocol import PLAN_V1_SCHEMA
from modelable.registry.resolver import latest_semantic_type_declarations


def emit_python(workspace: Workspace, out_dir: Path) -> list[EmittedArtifact]:
    """Emit Python dataclass modules for every published model and projection version."""
    artifacts: list[EmittedArtifact] = []
    plans = {
        (plan["domain"], plan["projection"], plan["version"]): plan
        for plan in build_plan_documents(workspace, schema=PLAN_V1_SCHEMA)
    }
    for domain in workspace.mdl.domains:
        named_names, named_shapes = resolve_named_types(
            workspace.mdl, current_domain=domain.name, model_name=_stable_type_name, emit_nominal_enums=True
        )
        latest_decls = latest_semantic_type_declarations(domain)
        for decl in latest_decls:
            if isinstance(decl.underlying, EnumType):
                artifacts.append(_emit_enum_type(domain, decl, out_dir))
        for decl in domain.semantic_types:
            if isinstance(decl.underlying, EnumType) and decl not in latest_decls:
                artifacts.append(_emit_versioned_enum_type(domain, decl, out_dir))
        for projection in domain.enum_projections:
            artifacts.append(_emit_enum_projection(domain, projection, out_dir))
        for model_name, model_versions in domain.models.items():
            for model_version in model_versions:
                artifacts.append(
                    _emit_model(domain, model_name, model_version, out_dir, named_names, named_shapes, workspace.mdl)
                )
        for projection_name, projection_versions in domain.projections.items():
            for projection_version in projection_versions:
                artifacts.append(
                    _emit_projection(
                        domain,
                        projection_name,
                        projection_version,
                        out_dir,
                        workspace.mdl,
                        named_names,
                        named_shapes,
                        plans[(domain.name, projection_name, projection_version.version)],
                    )
                )
    return artifacts


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
    lines.extend(render_nested_definitions(nested_definitions))

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
    plan: dict[str, object],
) -> EmittedArtifact:
    return emit_python_projection_plan(
        plan,
        out_dir,
        named_types=_named_plan_types(domain.name, version, mdl, named_names, named_shapes),
    )


def _named_plan_types(
    current_domain: str,
    version: ProjectionVersion,
    mdl: MdlFile,
    named_names: dict[str, str],
    named_shapes: dict[str, TypeShape],
) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}

    def visit(shape: TypeShape) -> None:
        if shape.kind == "named":
            declaring_domain, named_name, _ = resolve_named_ref(
                mdl,
                current_domain=current_domain,
                ref=shape.ref or "",
                names=named_names,
                shapes=named_shapes,
                emit_nominal_enums=True,
                emit_nominal_enum_projections=True,
                exact_version=shape.version,
            )
            if declaring_domain is not None and named_name is not None:
                key = f"{shape.ref}|{shape.version if shape.version is not None else '?'}"
                result[key] = (named_name, declaring_domain)
            return
        if shape.kind == "array" and shape.element is not None:
            visit(shape.element)
        elif shape.kind == "map":
            if shape.key is not None:
                visit(shape.key)
            if shape.value is not None:
                visit(shape.value)
        elif shape.kind == "object":
            for field in shape.fields:
                visit(field.shape)

    for field in version.fields:
        shape = projection_field_shape(field, version, mdl)
        if shape is not None:
            visit(shape)
    return result


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


def _module_path(domain: str, type_name: str) -> Path:
    return Path(*_package_name(domain).split(".")) / _module_filename(type_name)


def _package_name(domain: str) -> str:
    return package_name(domain)


def _enum_member_name(value: str) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").upper()
    if text and text[0].isdigit():
        text = f"_{text}"
    return text or "UNKNOWN"


def _validate_enum_members(owner: str, values: list[str]) -> None:
    for identifier, members in find_identifier_collisions(values, _enum_member_name).items():
        joined_members = ", ".join(repr(member) for member in members)
        raise ValueError(f"{owner}: Python enum members {joined_members} all generate identifier {identifier!r}")


def _emit_enum_type(domain: DomainDef, decl: SemanticTypeDecl, out_dir: Path) -> EmittedArtifact:
    """Emit one reusable Python ``StrEnum`` for an enum-backed semantic
    declaration (evolution plan E8), imported everywhere it's referenced
    instead of degrading to a bare ``str`` annotation.
    """
    assert isinstance(decl.underlying, EnumType)
    return _emit_enum_artifact(
        domain,
        type_name=decl.name,
        values=decl.underlying.values,
        ref=f"{domain.name}.{decl.name}",
        artifact_id=f"{domain.name}.{decl.name}",
        out_dir=out_dir,
    )


def _emit_enum_artifact(
    domain: DomainDef,
    *,
    type_name: str,
    values: list[str],
    ref: str,
    artifact_id: str,
    out_dir: Path,
) -> EmittedArtifact:
    _validate_enum_members(ref, values)
    lines = [
        "from __future__ import annotations",
        "",
        "from enum import StrEnum",
        "",
        "",
        f"class {type_name}(StrEnum):",
        *(f"    {_enum_member_name(value)} = {value!r}" for value in values),
    ]
    text = "\n".join(lines) + "\n"
    return EmittedArtifact(
        target="python",
        ref=ref,
        artifact_id=artifact_id,
        path=out_dir / _module_path(domain.name, type_name),
        content=text,
        content_hash=compute_content_hash(text),
        warnings=[],
    )


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
            mdl,
            current_domain=current_domain,
            ref=shape.ref or "",
            names=named_names,
            shapes=named_shapes,
            emit_nominal_enums=True,
            emit_nominal_enum_projections=True,
            exact_version=shape.version,
        )
        if named_name is not None:
            local_name = named_name
            if declaring_domain is not None and named_name != owner_type:
                if declaring_domain != current_domain and not named_name.startswith(_pascalize(declaring_domain)):
                    local_name = f"{_pascalize(declaring_domain)}{named_name}"
                imports.add(
                    f"from {_package_name(declaring_domain)}.{_module_filename(named_name)[:-3]} import "
                    f"{named_name}{f' as {local_name}' if local_name != named_name else ''}"
                )
            return local_name
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


def _emit_enum_projection(domain: DomainDef, projection: EnumProjectionDecl, out_dir: Path) -> EmittedArtifact:
    return _emit_enum_artifact(
        domain,
        type_name=f"{_pascalize(domain.name)}{projection.name}V{projection.version}",
        values=projection.members,
        ref=f"{domain.name}.{projection.name}@{projection.version}",
        artifact_id=f"{domain.name}.{projection.name}.v{projection.version}",
        out_dir=out_dir,
    )


def _emit_versioned_enum_type(domain: DomainDef, decl: SemanticTypeDecl, out_dir: Path) -> EmittedArtifact:
    assert isinstance(decl.underlying, EnumType)
    return _emit_enum_artifact(
        domain,
        type_name=f"{_pascalize(domain.name)}{decl.name}V{decl.version}",
        values=decl.underlying.values,
        ref=f"{domain.name}.{decl.name}@{decl.version}",
        artifact_id=f"{domain.name}.{decl.name}.v{decl.version}",
        out_dir=out_dir,
    )
