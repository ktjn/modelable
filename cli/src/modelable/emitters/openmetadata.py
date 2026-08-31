from __future__ import annotations

from pathlib import Path

from modelable.compiler.workspace import Workspace
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.openmetadata_plan import emit_openmetadata_projection_plan
from modelable.parser.ir import (
    AnnOwner,
    ArrayType,
    DecimalType,
    DomainDef,
    EnumRefType,
    EnumType,
    FieldDef,
    FieldType,
    MapType,
    ModelVersion,
    NamedType,
    ObjectType,
    PrimitiveType,
    RefType,
)
from modelable.planner.plans import build_plan_documents
from modelable.planner.protocol import PLAN_V1_SCHEMA


def emit_openmetadata(workspace: Workspace, out_dir: Path) -> list[EmittedArtifact]:
    """Emit OpenMetadata-oriented catalog assets with ownership, governance, and lineage."""
    artifacts: list[EmittedArtifact] = []
    plans = {
        (plan["domain"], plan["projection"], plan["version"]): plan
        for plan in build_plan_documents(workspace, schema=PLAN_V1_SCHEMA)
    }

    for domain in sorted(workspace.mdl.domains, key=lambda item: item.name):
        artifact_id = f"{domain.name}.openmetadata"
        assets: list[dict[str, object]] = []
        lineage: list[dict[str, str]] = []
        om_data: dict[str, object] = {
            "name": domain.name,
            "description": domain.description,
            "owner": domain.owner,
            "assets": assets,
            "lineage": lineage,
        }

        for model_name, model_versions in sorted(domain.models.items()):
            for version in sorted(model_versions, key=lambda item: item.version):
                assets.append(_model_asset(domain, model_name, version))

        for projection_name, projection_versions in sorted(domain.projections.items()):
            for projection_version in sorted(projection_versions, key=lambda item: item.version):
                plan = plans[(domain.name, projection_name, projection_version.version)]
                projection_asset, projection_lineage = emit_openmetadata_projection_plan(plan)
                assets.append(projection_asset)
                lineage.extend(projection_lineage)

        path = out_dir / f"{artifact_id}.json"
        artifacts.append(
            EmittedArtifact(
                target="openmetadata",
                ref=domain.name,
                artifact_id=artifact_id,
                path=path,
                content=om_data,
                content_hash=compute_content_hash(om_data),
                warnings=[],
            )
        )

    return artifacts


def _model_asset(domain: DomainDef, model_name: str, version: ModelVersion) -> dict[str, object]:
    return {
        "name": model_name,
        "kind": version.model_kind.value,
        "version": version.version,
        "changeKind": version.change_kind.value,
        "fullyQualifiedName": _asset_fqn(domain.name, model_name, version.version),
        "fields": [_model_field(field) for field in version.fields],
    }


def _model_field(field: FieldDef) -> dict[str, object]:
    return {
        "name": field.name,
        "type": _type_name(field.type),
        "required": not field.optional,
        "key": field.is_key,
        "pii": field.is_pii,
        "classification": field.classification.value if field.classification is not None else None,
        "owner": _owner(field),
    }


def _asset_fqn(domain: str, name: str, version: int) -> str:
    return f"modelable.{domain}.{name}.v{version}"


def _owner(field: FieldDef) -> str | None:
    for annotation in field.annotations:
        if isinstance(annotation, AnnOwner):
            return annotation.team
    return None


def _type_name(field_type: FieldType) -> str:
    if isinstance(field_type, PrimitiveType):
        return field_type.kind
    if isinstance(field_type, DecimalType):
        return f"decimal({field_type.precision},{field_type.scale})"
    if isinstance(field_type, ArrayType):
        return f"array<{_type_name(field_type.item)}>"
    if isinstance(field_type, MapType):
        return f"map<{_type_name(field_type.key)},{_type_name(field_type.value)}>"
    if isinstance(field_type, RefType):
        return f"ref<{field_type.target}>"
    if isinstance(field_type, EnumType):
        return "enum(" + ",".join(field_type.values) + ")"
    if isinstance(field_type, EnumRefType):
        return f"enumRef<{field_type.name}@{field_type.version}>"
    if isinstance(field_type, NamedType):
        return field_type.name
    if isinstance(field_type, ObjectType):
        return "object"
    return "unknown"
