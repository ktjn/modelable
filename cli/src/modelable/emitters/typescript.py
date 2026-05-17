from __future__ import annotations

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


def _emit_model(domain: str, model_name: str, version: ModelVersion, out_dir: Path) -> EmittedArtifact:
    artifact_id = _artifact_id(domain, model_name, version.version)
    lines = [
        f"export interface {model_name} {{",
    ]
    for field in version.fields:
        lines.append(f"  {field.name}{'?' if field.optional else ''}: {_type_to_ts(field.type)};")
    lines.append("}")
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
    lines = [f"export interface {projection_name} {{"]
    for field in version.fields:
        field_type = _resolve_projection_field_type(field, version, model_lookup)
        lines.append(f"  {field.name}: {_type_to_ts(field_type)};")
    lines.append("}")
    return EmittedArtifact(
        target="typescript",
        ref=f"{domain}.{projection_name}@{version.version}",
        artifact_id=artifact_id,
        path=out_dir / f"{artifact_id}.ts",
        content="\n".join(lines) + "\n",
    )


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

