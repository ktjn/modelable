from __future__ import annotations

from modelable.parser.ir import (
    AnnClassification,
    AnnDeprecated,
    AnnKey,
    AnnOwner,
    AnnPii,
    AnnServer,
    AnnWire,
    ArrayType,
    AutoProjectionDecl,
    AutoProjectionTarget,
    BindingDef,
    ComputedMapping,
    DecimalType,
    DirectMapping,
    DomainDef,
    EnumType,
    FieldDef,
    FieldType,
    GenerateTarget,
    MapType,
    MdlFile,
    ModelVersion,
    NamedType,
    ObjectType,
    PrimitiveType,
    ProjectionField,
    ProjectionVersion,
    RefType,
    VersionExact,
    VersionMin,
    VersionRange,
    WorkspaceDef,
)
from modelable.parser.wire import render_wire_annotation


def render_mdl(mdl: MdlFile) -> str:
    lines: list[str] = []
    for domain in mdl.domains:
        lines.extend(_render_domain(domain))
        lines.append("")
    for binding in mdl.bindings:
        lines.extend(_render_binding(binding))
        lines.append("")
    if mdl.workspace is not None:
        lines.extend(_render_workspace(mdl.workspace))
        lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + ("\n" if lines else "")


def render_model_version(
    domain_name: str, model_name: str, version: ModelVersion, owner: str | None = None, description: str | None = None
) -> str:
    return render_mdl(
        MdlFile(
            domains=[
                DomainDef(
                    name=domain_name,
                    owner=owner,
                    description=description,
                    models={model_name: [version]},
                )
            ]
        )
    )


def render_projection_version(
    domain_name: str,
    projection_name: str,
    version: ProjectionVersion,
    owner: str | None = None,
    description: str | None = None,
) -> str:
    return render_mdl(
        MdlFile(
            domains=[
                DomainDef(
                    name=domain_name,
                    owner=owner,
                    description=description,
                    projections={projection_name: [version]},
                )
            ]
        )
    )


def _render_domain(domain: DomainDef) -> list[str]:
    lines = [f"domain {domain.name} {{"]
    if domain.owner:
        lines.append(f'  owner: "{domain.owner}"')
    if domain.description:
        lines.append(f'  description: "{domain.description}"')
    for model_name in sorted(domain.models):
        for mv in domain.models[model_name]:
            lines.extend(_indent(_render_model(model_name, mv), 2))
    for projection_name in sorted(domain.projections):
        for pv in domain.projections[projection_name]:
            lines.extend(_indent(_render_projection(projection_name, pv), 2))
    for decl in domain.auto_projections:
        lines.extend(_indent(_render_auto_projection(decl), 2))
    for target in domain.generate_targets:
        lines.extend(_indent(_render_generate_target(target), 2))
    lines.append("}")
    return lines


def _render_model(model_name: str, version: ModelVersion) -> list[str]:
    lines = [f"{version.model_kind.value} {model_name} @ {version.version} ({version.change_kind.value}) {{"]
    for field in version.fields:
        lines.append(_render_field(field, 2))
    lines.append("}")
    return lines


def _render_field(field: FieldDef, indent: int = 0) -> str:
    prefix = " ".join(_render_annotations(field.annotations))
    suffix = f"{field.name}{'?' if field.optional else ''}: {_render_type(field.type)}"
    return _with_prefix(prefix, suffix, indent)


def _render_projection(projection_name: str, version: ProjectionVersion) -> list[str]:
    lines = [f"projection {projection_name} @ {version.version}"]
    lines.append(
        f"  from {version.source.model} @ {_render_version_spec(version.source.version)} as {version.source.alias}"
    )
    for join in version.joins:
        lines.append(f"  join {join.model} @ {_render_version_spec(join.version)} as {join.alias} on {join.on}")
    if version.group_by:
        lines.append(f"  group by {', '.join(version.group_by)}")
    lines.append("{")
    for field in version.fields:
        lines.append(_render_projection_field(field, 2))
    lines.append("}")
    return lines


def _render_projection_field(field: ProjectionField, indent: int = 0) -> str:
    prefix = " ".join(_render_annotations(field.annotations))
    if isinstance(field.mapping, DirectMapping):
        body = f"{field.name} <- {field.mapping.source_alias}.{field.mapping.source_field}"
    elif isinstance(field.mapping, ComputedMapping):
        body = f"{field.name} = {field.mapping.expression}"
    else:
        body = field.name
    return _with_prefix(prefix, body, indent)


def _render_auto_projection(decl: AutoProjectionDecl) -> list[str]:
    lines = [f"auto projections {decl.model} @ {decl.version} {{"]
    for target in decl.targets:
        lines.append(_render_auto_target(target, 2))
    lines.append("}")
    return lines


def _render_auto_target(target: AutoProjectionTarget, indent: int = 0) -> str:
    parts = [target.kind]
    if target.excluded_fields or target.excluded_annotations:
        exclusions = [
            *target.excluded_fields,
            *(_render_annotation_literal(ann) for ann in target.excluded_annotations),
        ]
        parts.append(f"exclude [{', '.join(exclusions)}]")
    if target.operations:
        parts.append(f"on [{', '.join(target.operations)}]")
    return _join_tokens(parts, indent)


def _render_generate_target(target: GenerateTarget) -> str:
    name = f"{target.name}({target.dialect})" if target.dialect else target.name
    if target.output_path:
        return f'{name} -> "{target.output_path}"'
    return name


def _render_binding(binding: BindingDef) -> list[str]:
    lines = [f"binding {binding.name} {{"]
    lines.append(f"  model: {binding.model} @ {binding.model_version}")
    lines.append(f"  adapter: {binding.adapter}")
    if binding.table:
        lines.append(f'  table: "{binding.table}"')
    for mapping in binding.field_mappings:
        lines.append(f"  {mapping.source} -> {mapping.target}")
    lines.append("}")
    return lines


def _render_workspace(workspace: WorkspaceDef) -> list[str]:
    lines = ["workspace default {"]
    if workspace.ai is not None:
        lines.append("  ai {")
        if workspace.ai.provider:
            lines.append(f'    provider: "{workspace.ai.provider}"')
        if workspace.ai.model:
            lines.append(f'    model: "{workspace.ai.model}"')
        lines.append("  }")
    for target in workspace.generate_targets:
        lines.append(f"  {_render_generate_target(target)}")
    lines.append("}")
    return lines


def _render_type(field_type: FieldType) -> str:
    if isinstance(field_type, PrimitiveType):
        return field_type.kind
    if isinstance(field_type, DecimalType):
        return f"decimal({field_type.precision}, {field_type.scale})"
    if isinstance(field_type, ArrayType):
        return f"array<{_render_type(field_type.item)}>"
    if isinstance(field_type, MapType):
        return f"map<{_render_type(field_type.key)}, {_render_type(field_type.value)}>"
    if isinstance(field_type, RefType):
        return f"ref<{field_type.target}>"
    if isinstance(field_type, EnumType):
        return f"enum({', '.join(field_type.values)})"
    if isinstance(field_type, ObjectType):
        inner = " ".join(_render_field(field, 0) for field in field_type.fields)
        return f"object {{ {inner} }}"
    if isinstance(field_type, NamedType):
        return field_type.name
    return "string"


def _render_annotations(annotations) -> list[str]:
    parts: list[str] = []
    for ann in annotations:
        parts.append(_render_annotation_literal(ann))
    return parts


def _render_annotation_literal(annotation) -> str:
    if isinstance(annotation, AnnKey):
        return "@key"
    if isinstance(annotation, AnnPii):
        return "@pii"
    if isinstance(annotation, AnnClassification):
        return f'@classification("{annotation.level}")'
    if isinstance(annotation, AnnDeprecated):
        return f'@deprecated(replacedBy: "{annotation.replaced_by}")'
    if isinstance(annotation, AnnOwner):
        return f'@owner("{annotation.team}")'
    if isinstance(annotation, AnnServer):
        return "@server"
    if isinstance(annotation, AnnWire):
        return render_wire_annotation(annotation)
    return "@unknown"


def _render_version_spec(version_spec) -> str:
    if isinstance(version_spec, VersionExact):
        return str(version_spec.version)
    if isinstance(version_spec, VersionRange):
        return f">={version_spec.min_inclusive}<{version_spec.max_exclusive}"
    if isinstance(version_spec, VersionMin):
        return f">={version_spec.min_inclusive}"
    return "0"


def _join_tokens(parts: list[str], indent: int = 0) -> str:
    text = " ".join(part for part in parts if part)
    return f"{' ' * indent}{text}"


def _with_prefix(prefix: str, body: str, indent: int = 0) -> str:
    if prefix:
        return f"{' ' * indent}{prefix} {body}"
    return f"{' ' * indent}{body}"


def _indent(lines: list[str], spaces: int) -> list[str]:
    pad = " " * spaces
    return [f"{pad}{line}" if line else line for line in lines]
