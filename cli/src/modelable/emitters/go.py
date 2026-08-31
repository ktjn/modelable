from __future__ import annotations

from pathlib import Path
from typing import Any

from modelable.compiler.workspace import Workspace
from modelable.emitters.base import EmittedArtifact, compute_content_hash, render_nested_definitions
from modelable.emitters.base import artifact_id as _artifact_id
from modelable.emitters.diagnostics import type_loss
from modelable.emitters.go_plan import emit_go_projection_plan
from modelable.emitters.named_types import resolve_named_ref, resolve_named_types
from modelable.emitters.naming import find_identifier_collisions, package_name
from modelable.emitters.naming import pascalize_plain as _pascalize
from modelable.emitters.naming import snake_case as _snake_case
from modelable.emitters.projection_shapes import projection_field_shape
from modelable.emitters.shapes import TypeShape
from modelable.parser.ir import (
    DomainDef,
    EnumProjectionDecl,
    EnumType,
    MdlFile,
    ModelVersion,
    ProjectionVersion,
    SemanticTypeDecl,
    latest_semantic_types,
)
from modelable.planner.plans import build_plan_documents
from modelable.planner.protocol import PLAN_V1_SCHEMA


def emit_go(workspace: Workspace, out_dir: Path) -> list[EmittedArtifact]:
    """Emit Go source files for every model and projection version."""
    artifacts: list[EmittedArtifact] = []
    plans = {
        (plan["domain"], plan["projection"], plan["version"]): plan
        for plan in build_plan_documents(workspace, schema=PLAN_V1_SCHEMA)
    }
    module_name = _go_module_name(workspace.mdl)
    artifacts.append(_emit_go_mod(workspace.mdl, out_dir))
    for domain in workspace.mdl.domains:
        named_names, named_shapes = resolve_named_types(
            workspace.mdl, current_domain=domain.name, model_name=_stable_type_name, emit_nominal_enums=True
        )
        latest_decls = latest_semantic_types(domain)
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
                    _emit_model(
                        domain,
                        model_name,
                        model_version,
                        out_dir,
                        named_names,
                        named_shapes,
                        workspace.mdl,
                        module_name,
                    )
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
                        module_name,
                        plans[(domain.name, projection_name, projection_version.version)],
                    )
                )
    return artifacts


def _stable_type_name(domain: str, name: str, version: int) -> str:
    return f"{_pascalize(domain)}{_pascalize(name)}V{version}"


def _go_module_name(mdl: MdlFile) -> str:
    if mdl.workspace is not None and mdl.workspace.name:
        return f"modelable/{_snake_case(mdl.workspace.name)}"
    return "modelable/generated"


def _emit_go_mod(mdl: MdlFile, out_dir: Path) -> EmittedArtifact:
    text = f"module {_go_module_name(mdl)}\n\ngo 1.26\n"
    return EmittedArtifact(
        target="go",
        ref="go.mod",
        artifact_id="go.mod",
        path=out_dir / "go.mod",
        content=text,
        content_hash=compute_content_hash(text),
        warnings=[],
    )


def _emit_model(
    domain: DomainDef,
    model_name: str,
    version: ModelVersion,
    out_dir: Path,
    named_names: dict[str, str],
    named_shapes: dict[str, TypeShape],
    mdl: MdlFile,
    module_name: str,
) -> EmittedArtifact:
    artifact_id = _artifact_id(domain.name, model_name, version.version)
    type_name = _stable_type_name(domain.name, model_name, version.version)
    nested_definitions: dict[str, list[str]] = {}
    imports: set[str] = set()
    warnings: list[str] = []
    field_specs = _field_specs_from_model_fields(
        version.fields,
        owner_type=type_name,
        path=[],
        definitions=nested_definitions,
        imports=imports,
        warnings=warnings,
        named_names=named_names,
        named_shapes=named_shapes,
        mdl=mdl,
        current_domain=domain.name,
        module_name=module_name,
    )

    lines = _header_lines(_package_name(domain.name), imports)
    lines.extend(_render_struct_definition(type_name, field_specs))
    lines.extend(render_nested_definitions(nested_definitions))

    text = "\n".join(lines) + "\n"
    return EmittedArtifact(
        target="go",
        ref=f"{domain.name}.{model_name}@{version.version}",
        artifact_id=artifact_id,
        path=out_dir / _module_path(domain.name, type_name),
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
    module_name: str,
    plan: dict[str, object],
) -> EmittedArtifact:
    return emit_go_projection_plan(
        plan,
        out_dir,
        module_name=module_name,
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
                result[f"{shape.ref}|{shape.version if shape.version is not None else '?'}"] = (
                    named_name,
                    declaring_domain,
                )
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


def _header_lines(package: str, imports: set[str]) -> list[str]:
    lines = [
        "// Code generated by Modelable; DO NOT EDIT.",
        f"package {package}",
    ]
    if imports:
        lines.append("")
        lines.append("import (")
        for item in sorted(imports):
            lines.append(f'    "{item}"')
        lines.append(")")
    lines.append("")
    return lines


def _module_path(domain: str, type_name: str) -> Path:
    return Path(_package_name(domain)) / _module_filename(type_name)


def _package_name(domain: str) -> str:
    return package_name(domain, separator="_")


def _module_filename(type_name: str) -> str:
    return f"{_snake_case(type_name)}.go"


def _render_struct_definition(type_name: str, field_specs: list[tuple[int, str, str, bool]]) -> list[str]:
    lines = [f"type {type_name} struct {{"]
    if not field_specs:
        lines.append("}")
        return lines
    for _, name, annotation, default_none in sorted(field_specs, key=lambda item: (item[3], item[0])):
        field_name = _field_name(name)
        tag = _json_tag(name, default_none)
        lines.append(f"    {field_name} {annotation} {tag}")
    lines.append("}")
    return lines


def _field_name(value: str) -> str:
    return _pascalize(value, fallback="Field")


def _json_tag(value: str, optional: bool) -> str:
    suffix = ",omitempty" if optional else ""
    return f'`json:"{value}{suffix}"`'


def _field_specs_from_model_fields(
    fields: Any,
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
    module_name: str,
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
            warnings=warnings,
            named_names=named_names,
            named_shapes=named_shapes,
            mdl=mdl,
            current_domain=current_domain,
            module_name=module_name,
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
    warnings: list[str],
    named_names: dict[str, str],
    named_shapes: dict[str, TypeShape],
    mdl: MdlFile,
    current_domain: str,
    module_name: str,
) -> list[tuple[int, str, str, bool]]:
    specs: list[tuple[int, str, str, bool]] = []
    for index, field in enumerate(fields):
        annotation = _shape_annotation(
            field.shape,
            owner_type=owner_type,
            path=[*path, field.name],
            definitions=definitions,
            imports=imports,
            warnings=warnings,
            named_names=named_names,
            named_shapes=named_shapes,
            mdl=mdl,
            current_domain=current_domain,
            module_name=module_name,
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
    warnings: list[str],
    named_names: dict[str, str],
    named_shapes: dict[str, TypeShape],
    mdl: MdlFile,
    current_domain: str,
    module_name: str,
) -> str:
    base = _shape_base_annotation(
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
        module_name=module_name,
    )
    if shape.optional or shape.nullable:
        return f"*{base}"
    return base


def _shape_base_annotation(
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
    module_name: str,
) -> str:
    if shape.kind == "primitive":
        field_ref = f"{owner_type}.{'.'.join(path)}"
        return _primitive_to_go(shape.ref or "string", imports=imports, warnings=warnings, field_ref=field_ref)
    if shape.kind == "decimal":
        return "string"
    if shape.kind == "fixed_binary":
        return f"[{shape.length}]byte"
    if shape.kind == "array":
        element = shape.element or TypeShape(kind="primitive", ref="object")
        element_type = _shape_annotation(
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
            module_name=module_name,
        )
        return f"[]{element_type}"
    if shape.kind == "map":
        value = shape.value or TypeShape(kind="primitive", ref="object")
        value_type = _shape_annotation(
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
            module_name=module_name,
        )
        return f"map[string]{value_type}"
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
            emit_nominal_enum_projections=True,
            exact_version=shape.version,
        )
        if named_name is not None:
            if declaring_domain is not None and declaring_domain != current_domain:
                imports.add(f"{module_name}/{_package_name(declaring_domain)}")
                return f"{_package_name(declaring_domain)}.{named_name}"
            return named_name
        if inline_shape is not None:
            return _shape_base_annotation(
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
                module_name=module_name,
            )
        return _pascalize(shape.ref or "Named")
    if shape.kind == "object":
        type_name = _nested_type_name(owner_type, path)
        if type_name not in definitions:
            definitions[type_name] = _render_struct_definition(
                type_name,
                _field_specs_from_object_fields(
                    shape.fields,
                    owner_type=owner_type,
                    path=path,
                    definitions=definitions,
                    imports=imports,
                    warnings=warnings,
                    named_names=named_names,
                    named_shapes=named_shapes,
                    mdl=mdl,
                    current_domain=current_domain,
                    module_name=module_name,
                ),
            )
        return type_name
    return "any"


def _primitive_to_go(kind: str, *, imports: set[str], warnings: list[str], field_ref: str) -> str:
    if kind in ("u128", "i128"):
        warnings.append(type_loss(field_ref))
        return "[16]byte"
    mapping = {
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
        "u8": "uint8",
        "u16": "uint16",
        "u32": "uint32",
        "u64": "uint64",
        "i8": "int8",
        "i16": "int16",
        "i32": "int32",
        "i64": "int64",
    }
    result = mapping.get(kind, "string")
    if result.startswith("time."):
        imports.add("time")
    return result


def _nested_type_name(owner_type: str, path: list[str]) -> str:
    suffix = "".join(_pascalize(part) for part in path)
    return f"{owner_type}{suffix}" if suffix else owner_type


def _enum_const_name(type_name: str, value: str) -> str:
    return f"{type_name}{_pascalize(value)}"


def _validate_enum_members(owner: str, values: list[str]) -> None:
    for identifier, members in find_identifier_collisions(values, _pascalize).items():
        joined_members = ", ".join(repr(member) for member in members)
        raise ValueError(f"{owner}: Go enum members {joined_members} all generate identifier {identifier!r}")


def _emit_enum_type(domain: DomainDef, decl: SemanticTypeDecl, out_dir: Path) -> EmittedArtifact:
    """Emit one reusable Go named string type plus constants for an
    enum-backed semantic declaration (evolution plan E8), imported
    everywhere it's referenced instead of degrading to a bare ``string``.

    A ``type X string`` needs no custom ``MarshalJSON``/``UnmarshalJSON``:
    ``encoding/json`` already encodes/decodes any string-kinded type as its
    underlying string value, so the canonical wire value round-trips for
    free. Go has no enum-scoped constant namespace, so each constant is
    prefixed with the type name to avoid colliding with another enum's
    members in the same package.
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
        "// Code generated by Modelable; DO NOT EDIT.",
        f"package {_package_name(domain.name)}",
        "",
        f"type {type_name} string",
        "",
        "const (",
    ]
    for value in values:
        lines.append(f'    {_enum_const_name(type_name, value)} {type_name} = "{value}"')
    lines.append(")")
    text = "\n".join(lines) + "\n"
    return EmittedArtifact(
        target="go",
        ref=ref,
        artifact_id=artifact_id,
        path=out_dir / _module_path(domain.name, type_name),
        content=text,
        content_hash=compute_content_hash(text),
        warnings=[],
    )


def _emit_enum_projection(domain: DomainDef, projection: EnumProjectionDecl, out_dir: Path) -> EmittedArtifact:
    type_name = f"{_pascalize(domain.name)}{projection.name}V{projection.version}"
    return _emit_enum_artifact(
        domain,
        type_name=type_name,
        values=projection.members,
        ref=f"{domain.name}.{projection.name}@{projection.version}",
        artifact_id=f"{domain.name}.{projection.name}.v{projection.version}",
        out_dir=out_dir,
    )


def _emit_versioned_enum_type(domain: DomainDef, decl: SemanticTypeDecl, out_dir: Path) -> EmittedArtifact:
    assert isinstance(decl.underlying, EnumType)
    type_name = f"{_pascalize(domain.name)}{decl.name}V{decl.version}"
    return _emit_enum_artifact(
        domain,
        type_name=type_name,
        values=decl.underlying.values,
        ref=f"{domain.name}.{decl.name}@{decl.version}",
        artifact_id=f"{domain.name}.{decl.name}.v{decl.version}",
        out_dir=out_dir,
    )
