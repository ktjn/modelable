from __future__ import annotations

import json
import re

from modelable.parser.ir import (
    AccessBlock,
    AnnClassification,
    AnnDeprecated,
    AnnKey,
    AnnLatestBefore,
    AnnLatestOnly,
    Annotation,
    AnnOwner,
    AnnPii,
    AnnPitCutoff,
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
    FixedBinaryType,
    GenerateTarget,
    IndexDecl,
    MapType,
    MdlFile,
    ModelVersion,
    NamedType,
    ObjectType,
    PrimitiveType,
    ProjectionField,
    ProjectionVersion,
    ProtobufReservations,
    RefType,
    SemanticTypeDecl,
    VersionExact,
    VersionMin,
    VersionPinned,
    VersionRange,
    VersionSpec,
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


def render_signature_model_version(domain_name: str, model_name: str, version: ModelVersion) -> str:
    """Render the historical normalized text used by canonical signatures."""
    lines = [f"domain {domain_name} {{"]
    lines.extend(_indent(_render_signature_model(model_name, version), 2))
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_signature_projection_version(
    domain_name: str,
    projection_name: str,
    version: ProjectionVersion,
) -> str:
    """Render the historical normalized text used by canonical signatures."""
    lines = [f"domain {domain_name} {{"]
    lines.extend(_indent(_render_signature_projection(projection_name, version), 2))
    lines.append("}")
    return "\n".join(lines) + "\n"


def _render_domain(domain: DomainDef) -> list[str]:
    lines = [f"domain {domain.name} {{"]
    if domain.owner:
        lines.append(f'  owner: "{domain.owner}"')
    if domain.contact:
        lines.append(f'  contact: "{domain.contact}"')
    if domain.description:
        lines.append(f'  description: "{domain.description}"')
    for semantic_decl in domain.semantic_types:
        lines.extend(_indent(_render_semantic_type(semantic_decl), 2))
    for model_name in sorted(domain.models):
        for mv in domain.models[model_name]:
            lines.extend(_indent(_render_model(model_name, mv), 2))
    for projection_name in sorted(domain.projections):
        for pv in domain.projections[projection_name]:
            if not pv.auto_generated:
                lines.extend(_indent(_render_projection(projection_name, pv), 2))
    for index_decl in domain.index_decls:
        lines.extend(_indent(_render_index(index_decl), 2))
    for decl in domain.auto_projections:
        lines.extend(_indent(_render_auto_projection(decl), 2))
    if domain.generate_targets:
        lines.extend(_indent(_render_generate_block(domain.generate_targets), 2))
    lines.append("}")
    return lines


def _render_model(model_name: str, version: ModelVersion) -> list[str]:
    prefix = " ".join(_render_annotations(version.annotations))
    header = f"{version.model_kind.value} {model_name}"
    if version.has_version_header:
        header += f" @ {version.version}"
    if version.has_change_kind:
        header += f" ({version.change_kind.value})"
    lines = [_with_prefix(prefix, f"{header} {{")]
    if version.protobuf_reservations is not None:
        lines.extend(_indent(_render_protobuf_reservations(version.protobuf_reservations), 2))
    if version.access is not None:
        lines.extend(_indent(_render_access(version.access), 2))
    for field in version.fields:
        lines.append(_render_field(field, 2))
    lines.append("}")
    return lines


def _render_field(field: FieldDef, indent: int = 0) -> str:
    prefix = " ".join(_render_annotations(field.annotations))
    suffix = f"{field.name}{'?' if field.optional else ''}: {_render_type(field.type)}"
    if field.default is not None:
        suffix += f" = {field.default}"
    return _with_prefix(prefix, suffix, indent)


def _render_signature_model(model_name: str, version: ModelVersion) -> list[str]:
    lines = [f"{version.model_kind.value} {model_name} @ {version.version} ({version.change_kind.value}) {{"]
    for field in version.fields:
        lines.append(_render_signature_field(field, 2))
    lines.append("}")
    return lines


def _render_signature_field(field: FieldDef, indent: int = 0) -> str:
    prefix = " ".join(_render_annotations(field.annotations))
    suffix = f"{field.name}{'?' if field.optional else ''}: {_render_signature_type(field.type)}"
    return _with_prefix(prefix, suffix, indent)


def _render_projection(projection_name: str, version: ProjectionVersion) -> list[str]:
    prefix = " ".join(_render_annotations(version.annotations))
    lines = [_with_prefix(prefix, f"projection {projection_name} @ {version.version}")]
    lines.append(
        f"  from {version.source.model} @ {_render_version_spec(version.source.version)} as {version.source.alias}"
    )
    for join in version.joins:
        join_prefix = "left join" if join.join_kind == "left" else "join"
        join_line = f"  {join_prefix} {join.model} @ {_render_version_spec(join.version)} as {join.alias} on {join.on}"
        if join.cardinality:
            join_line += f" cardinality: {join.cardinality}"
        annotations = " ".join(_render_annotations(join.annotations))
        if annotations:
            join_line += f" {annotations}"
        lines.append(join_line)
    if version.where:
        lines.append(f"  where {version.where}")
    if version.group_by:
        lines.append(f"  group by {', '.join(version.group_by)}")
    lines.append("{")
    if version.protobuf_reservations is not None:
        lines.extend(_indent(_render_protobuf_reservations(version.protobuf_reservations), 2))
    if version.access is not None:
        lines.extend(_indent(_render_access(version.access), 2))
    for field in version.fields:
        lines.append(_render_projection_field(field, 2))
    lines.append("}")
    return lines


def _render_signature_projection(projection_name: str, version: ProjectionVersion) -> list[str]:
    lines = [f"projection {projection_name} @ {version.version}"]
    lines.append(
        f"  from {version.source.model} @ "
        f"{_render_signature_version_spec(version.source.version)} as {version.source.alias}"
    )
    for join in version.joins:
        lines.append(
            f"  join {join.model} @ {_render_signature_version_spec(join.version)} as {join.alias} on {join.on}"
        )
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
    parts: list[str] = [target.kind]
    if target.excluded_fields or target.excluded_annotations:
        exclusions = [
            *target.excluded_fields,
            *(_render_annotation_literal(ann) for ann in target.excluded_annotations),
        ]
        parts.append(f"exclude [{', '.join(exclusions)}]")
    if target.operations:
        parts.append(f"on [{', '.join(target.operations)}]")
    return _join_tokens(parts, indent)


def _render_semantic_type(declaration: SemanticTypeDecl) -> list[str]:
    header = f"semantic {declaration.name}: {_render_type(declaration.underlying)}"
    if not declaration.registry:
        return [header]
    return [f"{header} {{", "  registry: true", "}"]


def _render_index(declaration: IndexDecl) -> list[str]:
    lines = [f"index {declaration.model} @ {declaration.version} {{"]
    if declaration.primary:
        lines.append(f"  primary {', '.join(declaration.primary)}")
    for secondary in declaration.secondary:
        lines.append(f"  secondary {secondary.name} {{")
        lines.append(f"    key: [{', '.join(secondary.key)}]")
        if secondary.sort:
            rendered_sort = ", ".join(f"{item.field} {item.direction}" for item in secondary.sort)
            lines.append(f"    sort: [{rendered_sort}]")
        lines.append(f"    unique: {'true' if secondary.unique else 'false'}")
        lines.append("  }")
    lines.append("}")
    return lines


def _render_protobuf_reservations(reservations: ProtobufReservations) -> list[str]:
    lines = ["reserved protobuf {"]
    if reservations.numbers:
        lines.append(f"  numbers: [{', '.join(str(number) for number in reservations.numbers)}]")
    if reservations.names:
        names = ", ".join(json.dumps(name) for name in reservations.names)
        lines.append(f"  names: [{names}]")
    lines.append("}")
    return lines


def _render_access(access: AccessBlock) -> list[str]:
    lines = ["access {"]
    for grant in access.entity:
        lines.append(f"  entity {grant.principal} [{', '.join(grant.permissions)}]")
    for field_name, grants in access.properties.items():
        for grant in grants:
            lines.append(f"  property {field_name} {grant.principal} [{', '.join(grant.permissions)}]")
    lines.append("}")
    return lines


def _render_generate_block(targets: list[GenerateTarget]) -> list[str]:
    lines = ["generate {"]
    lines.extend(f"  {_render_generate_target(target)}" for target in targets)
    lines.append("}")
    return lines


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
    label = f" {_render_workspace_label(workspace.label)}" if workspace.label is not None else ""
    lines = [f"workspace{label} {{"]
    if workspace.name:
        lines.append(f"  name: {json.dumps(workspace.name)}")
    if workspace.description:
        lines.append(f"  description: {json.dumps(workspace.description)}")
    if workspace.ai is not None:
        lines.append("  ai {")
        if workspace.ai.provider:
            lines.append(f'    provider: "{workspace.ai.provider}"')
        if workspace.ai.model:
            lines.append(f'    model: "{workspace.ai.model}"')
        if workspace.ai.repair_attempts is not None:
            lines.append(f"    repair_attempts: {workspace.ai.repair_attempts}")
        lines.append("  }")
    if workspace.generate_targets:
        lines.extend(_indent(_render_generate_block(workspace.generate_targets), 2))
    lines.append("}")
    return lines


def _render_workspace_label(label: str) -> str:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", label):
        return label
    return json.dumps(label)


def _render_type(field_type: FieldType) -> str:
    if isinstance(field_type, PrimitiveType):
        if field_type.kind == "uuid" and field_type.version != 4:
            return f"uuid({field_type.version})"
        return field_type.kind
    if isinstance(field_type, DecimalType):
        return f"decimal({field_type.precision}, {field_type.scale})"
    if isinstance(field_type, FixedBinaryType):
        return f"binary({field_type.length})"
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


def _render_signature_type(field_type: FieldType) -> str:
    if isinstance(field_type, PrimitiveType):
        return field_type.kind
    if isinstance(field_type, DecimalType):
        return f"decimal({field_type.precision}, {field_type.scale})"
    if isinstance(field_type, ArrayType):
        return f"array<{_render_signature_type(field_type.item)}>"
    if isinstance(field_type, MapType):
        return f"map<{_render_signature_type(field_type.key)}, {_render_signature_type(field_type.value)}>"
    if isinstance(field_type, RefType):
        return f"ref<{field_type.target}>"
    if isinstance(field_type, EnumType):
        return f"enum({', '.join(field_type.values)})"
    if isinstance(field_type, ObjectType):
        inner = " ".join(_render_signature_field(field, 0) for field in field_type.fields)
        return f"object {{ {inner} }}"
    if isinstance(field_type, NamedType):
        return field_type.name
    return "string"


def _render_annotations(annotations: list[Annotation]) -> list[str]:
    parts: list[str] = []
    for ann in annotations:
        parts.append(_render_annotation_literal(ann))
    return parts


def _render_annotation_literal(annotation: Annotation) -> str:
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
    if isinstance(annotation, AnnPitCutoff):
        return f"@pitCutoff({annotation.expression})"
    if isinstance(annotation, AnnLatestBefore):
        return f"@latestBefore({annotation.expression})"
    if isinstance(annotation, AnnLatestOnly):
        return "@latestOnly"
    if isinstance(annotation, AnnWire):
        return render_wire_annotation(annotation)
    return "@unknown"


def _render_version_spec(version_spec: VersionSpec) -> str:
    if isinstance(version_spec, VersionExact):
        return str(version_spec.version)
    if isinstance(version_spec, VersionRange):
        return f">={version_spec.min_inclusive}<{version_spec.max_exclusive}"
    if isinstance(version_spec, VersionMin):
        return f">={version_spec.min_inclusive}"
    if isinstance(version_spec, VersionPinned):
        return f"{version_spec.version}#{version_spec.content_hash}"
    return "0"


def _render_signature_version_spec(version_spec: VersionSpec) -> str:
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
