from __future__ import annotations

import re
from pathlib import Path

from modelable.compiler.workspace import Workspace
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.diagnostics import missing_metadata, type_loss
from modelable.parser.ir import (
    ArrayType,
    ComputedMapping,
    DecimalType,
    DirectMapping,
    EnumType,
    FieldDef,
    MapType,
    DomainDef,
    ModelVersion,
    NamedType,
    ObjectType,
    PrimitiveType,
    ProjectionVersion,
    RefType,
    VersionExact,
    VersionMin,
    VersionPinned,
    VersionRange,
)
from modelable.registry.resolver import resolve_model_ref


def emit_typescript(workspace: Workspace, out_dir: Path) -> list[EmittedArtifact]:
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
    return "".join(part[:1].upper() + part[1:] for part in parts)


def _stable_interface_name(domain: str, name: str, version: int) -> str:
    return f"{_pascalize(domain)}{_pascalize(name)}V{version}"


def _emit_model(domain: DomainDef, model_name: str, version: ModelVersion, out_dir: Path) -> EmittedArtifact:
    artifact_id = _artifact_id(domain.name, model_name, version.version)
    interface_name = _stable_interface_name(domain.name, model_name, version.version)
    lines = _metadata_lines(
        _domain_metadata_entries(
            domain,
            model_name,
            version.version,
            version.model_kind.value,
            version.change_kind.value,
        )
    )
    lines.append(f"export interface {interface_name} {{")
    warnings: list[str] = []
    for field in version.fields:
        if isinstance(field.type, NamedType):
            warnings.append(missing_metadata(f"{domain.name}.{model_name}.{field.name}"))
        lines.append(f"  {field.name}{'?' if field.optional else ''}: {_type_to_ts(field.type)};")
    lines.append("}")
    lines.append(f"export type {model_name} = {interface_name};")
    return EmittedArtifact(
        target="typescript",
        ref=f"{domain.name}.{model_name}@{version.version}",
        artifact_id=artifact_id,
        path=out_dir / f"{artifact_id}.ts",
        content="\n".join(lines) + "\n",
        content_hash=compute_content_hash("\n".join(lines) + "\n"),
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
    interface_name = _stable_interface_name(domain.name, projection_name, version.version)
    lines = _metadata_lines(
        _domain_metadata_entries(
            domain,
            projection_name,
            version.version,
            "projection",
            source=f"{version.source.model}@{_version_label(version.source.version)}",
            where=version.where,
            group_by=", ".join(version.group_by) if version.group_by else None,
        )
    )
    lines.append(f"export interface {interface_name} {{")
    warnings: list[str] = []
    for field in version.fields:
        field_type = _resolve_projection_field_type(field, version, mdl)
        if field_type is None:
            warnings.append(type_loss(f"{domain.name}.{projection_name}.{field.name}"))
        elif isinstance(field_type, NamedType):
            warnings.append(missing_metadata(f"{domain.name}.{projection_name}.{field.name}"))
        lines.append(f"  {field.name}: {_type_to_ts(field_type)};")
    lines.append("}")
    lines.append(f"export type {projection_name} = {interface_name};")
    return EmittedArtifact(
        target="typescript",
        ref=f"{domain.name}.{projection_name}@{version.version}",
        artifact_id=artifact_id,
        path=out_dir / f"{artifact_id}.ts",
        content="\n".join(lines) + "\n",
        content_hash=compute_content_hash("\n".join(lines) + "\n"),
        warnings=warnings,
    )


def _version_label(version_spec) -> str:
    if isinstance(version_spec, VersionExact):
        return str(version_spec.version)
    return "?"


def _metadata_lines(entries: list[str]) -> list[str]:
    lines = ["/**"]
    lines.extend(f" * {entry}" for entry in entries)
    lines.append(" */")
    return lines


def _domain_metadata_entries(
    domain: DomainDef,
    name: str,
    version: int,
    kind: str,
    change_kind: str | None = None,
    source: str | None = None,
    where: str | None = None,
    group_by: str | None = None,
) -> list[str]:
    entries = [f"@modelable domain: {domain.name}", f"@modelable name: {name}"]
    if domain.owner is not None:
        entries.append(f"@modelable owner: {domain.owner}")
    if domain.contact is not None:
        entries.append(f"@modelable contact: {domain.contact}")
    if domain.description is not None:
        entries.append(f"@modelable description: {domain.description}")
    if change_kind is not None:
        entries.append(f"@modelable kind: {kind}")
        entries.append(f"@modelable version: {version}")
        entries.append(f"@modelable changeKind: {change_kind}")
    else:
        entries.append(f"@modelable kind: {kind}")
        entries.append(f"@modelable version: {version}")
    if source is not None:
        entries.append(f"@modelable source: {source}")
    if where is not None:
        entries.append(f"@modelable where: {where}")
    if group_by is not None:
        entries.append(f"@modelable groupBy: {group_by}")
    return entries


def _resolve_projection_field_type(
    field: FieldDef,
    projection: ProjectionVersion,
    mdl,
):
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
            return src_field.type
    return None


def _version_label(version_spec) -> str:
    if isinstance(version_spec, VersionExact):
        return str(version_spec.version)
    if isinstance(version_spec, VersionRange):
        return f">={version_spec.min_inclusive}<{version_spec.max_exclusive}"
    if isinstance(version_spec, VersionMin):
        return f">={version_spec.min_inclusive}"
    if isinstance(version_spec, VersionPinned):
        return f"{version_spec.version}#{version_spec.content_hash}"
    return "?"


def _type_to_ts(field_type) -> str:
    if isinstance(field_type, PrimitiveType):
        mapping = {
            "string": "string",
            "int": "number",
            "float": "number",
            "bool": "boolean",
            "date": "string",
            "time": "string",
            "timestamp": "string",
            "uuid": "string",
            "duration": "string",
            "binary": "string",
        }
        return mapping.get(field_type.kind, "unknown")
    if isinstance(field_type, DecimalType):
        return "string"
    if isinstance(field_type, ArrayType):
        return f"{_type_to_ts(field_type.item)}[]"
    if isinstance(field_type, MapType):
        return f"Record<string, {_type_to_ts(field_type.value)}>"
    if isinstance(field_type, RefType):
        return "string"
    if isinstance(field_type, EnumType):
        values = " | ".join(repr(value) for value in field_type.values)
        return values or "string"
    if isinstance(field_type, ObjectType):
        inner = "; ".join(f"{field.name}{'?' if field.optional else ''}: {_type_to_ts(field.type)}" for field in field_type.fields)
        return f"{{ {inner} }}"
    if isinstance(field_type, NamedType):
        return field_type.name
    if field_type is None:
        return "unknown"
    if isinstance(field_type, ComputedMapping):
        return "unknown"
    return "unknown"
