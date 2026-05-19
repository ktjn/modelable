from __future__ import annotations

import re
from pathlib import Path

from modelable.compiler.workspace import Workspace
from modelable.emitters.base import EmittedArtifact
from modelable.parser.ir import (
    ArrayType,
    ComputedMapping,
    DecimalType,
    DirectMapping,
    EnumType,
    FieldDef,
    MapType,
    ModelVersion,
    NamedType,
    ObjectType,
    PrimitiveType,
    ProjectionVersion,
    RefType,
    VersionExact,
)


def emit_typescript(workspace: Workspace, out_dir: Path) -> list[EmittedArtifact]:
    model_lookup: dict[tuple[str, str, int], ModelVersion] = {}
    for domain in workspace.mdl.domains:
        for model_name, versions in domain.models.items():
            for version in versions:
                model_lookup[(domain.name, model_name, version.version)] = version

    artifacts: list[EmittedArtifact] = []
    for domain in workspace.mdl.domains:
        for model_name, versions in domain.models.items():
            for version in versions:
                artifacts.append(_emit_model(domain.name, model_name, version, out_dir))
        for projection_name, versions in domain.projections.items():
            for version in versions:
                artifacts.append(_emit_projection(domain.name, projection_name, version, out_dir, model_lookup))
    return artifacts


def _artifact_id(domain: str, name: str, version: int) -> str:
    return f"{domain}.{name}.v{version}"


def _pascalize(value: str) -> str:
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", value) if part]
    return "".join(part[:1].upper() + part[1:] for part in parts)


def _stable_interface_name(domain: str, name: str, version: int) -> str:
    return f"{_pascalize(domain)}{_pascalize(name)}V{version}"


def _emit_model(domain: str, model_name: str, version: ModelVersion, out_dir: Path) -> EmittedArtifact:
    artifact_id = _artifact_id(domain, model_name, version.version)
    interface_name = _stable_interface_name(domain, model_name, version.version)
    lines = _metadata_lines(
        [
            f"@modelable domain: {domain}",
            f"@modelable name: {model_name}",
            f"@modelable kind: {version.model_kind.value}",
            f"@modelable version: {version.version}",
            f"@modelable changeKind: {version.change_kind.value}",
        ]
    )
    lines.append(f"export interface {interface_name} {{")
    for field in version.fields:
        lines.append(f"  {field.name}{'?' if field.optional else ''}: {_type_to_ts(field.type)};")
    lines.append("}")
    lines.append(f"export type {model_name} = {interface_name};")
    return EmittedArtifact(
        target="typescript",
        ref=f"{domain}.{model_name}@{version.version}",
        artifact_id=artifact_id,
        path=out_dir / f"{artifact_id}.ts",
        content="\n".join(lines) + "\n",
    )


def _emit_projection(
    domain: str,
    projection_name: str,
    version: ProjectionVersion,
    out_dir: Path,
    model_lookup: dict[tuple[str, str, int], ModelVersion],
) -> EmittedArtifact:
    artifact_id = _artifact_id(domain, projection_name, version.version)
    interface_name = _stable_interface_name(domain, projection_name, version.version)
    lines = _metadata_lines(
        [
            f"@modelable domain: {domain}",
            f"@modelable name: {projection_name}",
            "@modelable kind: projection",
            f"@modelable version: {version.version}",
            f"@modelable source: {version.source.model}@{_version_label(version.source.version)}",
        ]
    )
    lines.append(f"export interface {interface_name} {{")
    for field in version.fields:
        field_type = _resolve_projection_field_type(field, version, model_lookup)
        lines.append(f"  {field.name}: {_type_to_ts(field_type)};")
    lines.append("}")
    lines.append(f"export type {projection_name} = {interface_name};")
    return EmittedArtifact(
        target="typescript",
        ref=f"{domain}.{projection_name}@{version.version}",
        artifact_id=artifact_id,
        path=out_dir / f"{artifact_id}.ts",
        content="\n".join(lines) + "\n",
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


def _resolve_projection_field_type(
    field: FieldDef,
    projection: ProjectionVersion,
    model_lookup: dict[tuple[str, str, int], ModelVersion],
):
    if not isinstance(field.mapping, DirectMapping):
        return None
    try:
        source_domain, source_model = projection.source.model.rsplit(".", 1)
    except ValueError:
        return None
    if isinstance(projection.source.version, VersionExact):
        source_version = projection.source.version.version
    else:
        source_version = projection.version
    source_mv = model_lookup.get((source_domain, source_model, source_version))
    if source_mv is None:
        return None
    for src_field in source_mv.fields:
        if src_field.name == field.mapping.source_field:
            return src_field.type
    return None


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
