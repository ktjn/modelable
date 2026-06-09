from __future__ import annotations

from pathlib import Path

from modelable.compiler.workspace import Workspace
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.parser.ir import (
    AnnClassification,
    AnnDeprecated,
    AnnKey,
    AnnOwner,
    AnnPii,
    AnnServer,
    AnnWire,
    ArrayType,
    ComputedMapping,
    DecimalType,
    DirectMapping,
    DomainDef,
    EnumType,
    FieldDef,
    MapType,
    ModelVersion,
    NamedType,
    ObjectType,
    PrimitiveType,
    ProjectionField,
    ProjectionVersion,
    RefType,
    VersionExact,
    VersionMin,
    VersionPinned,
    VersionRange,
)
from modelable.parser.wire import render_wire_annotation


def emit_markdown(workspace: Workspace, out_dir: Path) -> list[EmittedArtifact]:
    """Emit Markdown documentation for every model and projection version."""
    artifacts: list[EmittedArtifact] = []
    for domain in workspace.mdl.domains:
        for model_name, versions in domain.models.items():
            for version in versions:
                artifacts.append(_emit_model(domain, model_name, version, out_dir))
        for projection_name, versions in domain.projections.items():
            for version in versions:
                artifacts.append(_emit_projection(domain, projection_name, version, out_dir))
    return artifacts


def _artifact_id(domain: str, name: str, version: int) -> str:
    return f"{domain}.{name}.v{version}"


def _emit_model(
    domain: DomainDef, model_name: str, version: ModelVersion, out_dir: Path
) -> EmittedArtifact:
    artifact_id = _artifact_id(domain.name, model_name, version.version)
    lines: list[str] = []

    lines.append(f"# {model_name} v{version.version}")
    lines.append("")
    lines.append(f"**Domain:** {domain.name}  ")
    lines.append(f"**Name:** {model_name}  ")
    lines.append(f"**Version:** {version.version}  ")
    lines.append(f"**Artifact ID:** {artifact_id}  ")
    lines.append(f"**Artifact:** {artifact_id}.md  ")
    if domain.owner:
        lines.append(f"**Owner:** {domain.owner}  ")
    if domain.contact:
        lines.append(f"**Contact:** {domain.contact}  ")
    if domain.description:
        lines.append(f"**Description:** {domain.description}  ")
    lines.append(f"**Kind:** {version.model_kind.value}  ")
    lines.append(f"**Change kind:** {version.change_kind.value}  ")
    lines.append("")

    lines.append("## Fields")
    lines.append("")
    lines.append("| Field | Type | Required | Default | Annotations | Classification |")
    lines.append("|---|---|---|---|---|---|")
    for field in version.fields:
        required = "yes" if not field.optional else "no"
        default = field.default if field.default is not None else "—"
        ann_str = _format_annotations(field)
        cls_str = _field_classification(field)
        lines.append(
            f"| {field.name} | {_type_str(field.type)} | {required} | {default} | {ann_str} | {cls_str} |"
        )
    lines.append("")

    text = "\n".join(lines)
    return EmittedArtifact(
        target="markdown",
        ref=f"{domain.name}.{model_name}@{version.version}",
        artifact_id=artifact_id,
        path=out_dir / f"{artifact_id}.md",
        content=text,
        content_hash=compute_content_hash(text),
    )


def _emit_projection(
    domain: DomainDef, projection_name: str, version: ProjectionVersion, out_dir: Path
) -> EmittedArtifact:
    artifact_id = _artifact_id(domain.name, projection_name, version.version)
    lines: list[str] = []

    lines.append(f"# {projection_name} v{version.version}")
    lines.append("")
    lines.append(f"**Domain:** {domain.name}  ")
    lines.append(f"**Name:** {projection_name}  ")
    lines.append(f"**Version:** {version.version}  ")
    lines.append(f"**Artifact ID:** {artifact_id}  ")
    lines.append(f"**Artifact:** {artifact_id}.md  ")
    if domain.owner:
        lines.append(f"**Owner:** {domain.owner}  ")
    if domain.contact:
        lines.append(f"**Contact:** {domain.contact}  ")
    if domain.description:
        lines.append(f"**Description:** {domain.description}  ")
    lines.append(f"**Kind:** projection  ")
    auto_label = "yes" if version.auto_generated else "no"
    lines.append(f"**Auto generated:** {auto_label}  ")
    lines.append(
        f"**Source:** {version.source.model} @ {_version_str(version.source.version)} as {version.source.alias}  "
    )
    if version.where:
        lines.append(f"**Where:** {version.where}  ")
    if version.group_by:
        lines.append(f"**Group by:** {', '.join(version.group_by)}  ")
    lines.append("")

    lines.append("## Sources")
    lines.append("")
    lines.append("| Model | Version | Alias |")
    lines.append("|---|---|---|")
    lines.append(
        f"| {version.source.model} | {_version_str(version.source.version)} | {version.source.alias} |"
    )
    for join in version.joins:
        lines.append(
            f"| {join.model} | {_version_str(join.version)} | {join.alias} (join on `{join.on}`) |"
        )
    lines.append("")

    lines.append("## Fields")
    lines.append("")
    lines.append("| Field | Lineage | Annotations | Classification |")
    lines.append("|---|---|---|---|")
    for field in version.fields:
        lineage_str = _format_lineage(field, version.source.model)
        ann_str = _format_projection_annotations(field)
        cls_str = _projection_field_classification(field)
        lines.append(f"| {field.name} | {lineage_str} | {ann_str} | {cls_str} |")
    lines.append("")

    text = "\n".join(lines)
    return EmittedArtifact(
        target="markdown",
        ref=f"{domain.name}.{projection_name}@{version.version}",
        artifact_id=artifact_id,
        path=out_dir / f"{artifact_id}.md",
        content=text,
        content_hash=compute_content_hash(text),
    )


def _type_str(field_type) -> str:
    if isinstance(field_type, PrimitiveType):
        return field_type.kind
    if isinstance(field_type, DecimalType):
        return f"decimal({field_type.precision},{field_type.scale})"
    if isinstance(field_type, ArrayType):
        return f"array<{_type_str(field_type.item)}>"
    if isinstance(field_type, MapType):
        return f"map<{_type_str(field_type.key)},{_type_str(field_type.value)}>"
    if isinstance(field_type, RefType):
        return f"ref<{field_type.target}>"
    if isinstance(field_type, EnumType):
        return f"enum({', '.join(field_type.values)})"
    if isinstance(field_type, NamedType):
        return field_type.name
    if isinstance(field_type, ObjectType):
        return "object"
    return "unknown"


def _version_str(version_spec) -> str:
    if isinstance(version_spec, VersionExact):
        return str(version_spec.version)
    if isinstance(version_spec, VersionRange):
        return f">={version_spec.min_inclusive}<{version_spec.max_exclusive}"
    if isinstance(version_spec, VersionMin):
        return f">={version_spec.min_inclusive}"
    if isinstance(version_spec, VersionPinned):
        return f"{version_spec.version}#{version_spec.content_hash}"
    return "?"


def _format_annotations(field: FieldDef) -> str:
    parts: list[str] = []
    for ann in field.annotations:
        if isinstance(ann, AnnKey):
            parts.append("@key")
        elif isinstance(ann, AnnPii):
            parts.append("@pii")
        elif isinstance(ann, AnnServer):
            parts.append("@server")
        elif isinstance(ann, AnnDeprecated):
            parts.append(f"@deprecated → {ann.replaced_by}")
        elif isinstance(ann, AnnOwner):
            parts.append(f"@owner({ann.team})")
        elif isinstance(ann, AnnClassification):
            pass  # shown in classification column
        elif isinstance(ann, AnnWire):
            parts.append(render_wire_annotation(ann))
    return ", ".join(parts) if parts else "—"


def _format_projection_annotations(field: ProjectionField) -> str:
    parts: list[str] = []
    for ann in field.annotations:
        if isinstance(ann, AnnPii):
            parts.append("@pii")
        elif isinstance(ann, AnnServer):
            parts.append("@server")
        elif isinstance(ann, AnnDeprecated):
            parts.append(f"@deprecated → {ann.replaced_by}")
        elif isinstance(ann, AnnOwner):
            parts.append(f"@owner({ann.team})")
        elif isinstance(ann, AnnClassification):
            pass
        elif isinstance(ann, AnnWire):
            parts.append(render_wire_annotation(ann))
    return ", ".join(parts) if parts else "—"


def _field_classification(field: FieldDef) -> str:
    for ann in field.annotations:
        if isinstance(ann, AnnClassification):
            return ann.level
    return "—"


def _projection_field_classification(field: ProjectionField) -> str:
    for ann in field.annotations:
        if isinstance(ann, AnnClassification):
            return ann.level
    return "—"


def _format_lineage(field: ProjectionField, source_model: str) -> str:
    mapping = field.mapping
    if isinstance(mapping, DirectMapping):
        return f"direct: {mapping.source_alias}.{mapping.source_field} ({source_model})"
    if isinstance(mapping, ComputedMapping):
        expr = mapping.expression.replace("|", "\\|")
        return f"computed: `{expr}`"
    return "—"
