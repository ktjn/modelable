from __future__ import annotations

from pathlib import Path

from modelable.compiler.workspace import Workspace
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.parser.ir import (
    AnnOwner,
    ArrayType,
    ComputedMapping,
    DecimalType,
    DirectMapping,
    DomainDef,
    EnumType,
    FieldDef,
    FieldType,
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
from modelable.registry.resolver import ResolvedModelRef, resolve_model_ref


def emit_openmetadata(workspace: Workspace, out_dir: Path) -> list[EmittedArtifact]:
    """Emit OpenMetadata-oriented catalog assets with ownership, governance, and lineage."""
    artifacts: list[EmittedArtifact] = []

    for domain in workspace.mdl.domains:
        artifact_id = f"{domain.name}.openmetadata"
        om_data = {
            "name": domain.name,
            "description": domain.description,
            "owner": domain.owner,
            "assets": [],
            "lineage": [],
        }

        for model_name, versions in domain.models.items():
            for version in versions:
                om_data["assets"].append(_model_asset(domain, model_name, version))

        for projection_name, versions in domain.projections.items():
            for version in versions:
                source = _resolve_source(workspace, version)
                om_data["assets"].append(_projection_asset(domain, projection_name, version, source))
                om_data["lineage"].extend(_projection_lineage(domain, projection_name, version, source))

        path = out_dir / f"{artifact_id}.json"
        content_hash = compute_content_hash(om_data)

        artifacts.append(
            EmittedArtifact(
                target="openmetadata",
                ref=f"{domain.name}",
                artifact_id=artifact_id,
                path=path,
                content=om_data,
                content_hash=content_hash,
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


def _projection_asset(
    domain: DomainDef,
    projection_name: str,
    version: ProjectionVersion,
    source: ResolvedModelRef | None,
) -> dict[str, object]:
    asset: dict[str, object] = {
        "name": projection_name,
        "kind": "projection",
        "version": version.version,
        "fullyQualifiedName": _asset_fqn(domain.name, projection_name, version.version),
        "source": {
            "model": version.source.model,
            "version": _version_spec(version.source.version),
            "alias": version.source.alias,
        },
        "fields": [_projection_field(field, version, source) for field in version.fields],
    }
    if version.joins:
        asset["joins"] = [
            {
                "model": join.model,
                "version": _version_spec(join.version),
                "alias": join.alias,
                "on": join.on,
                "kind": join.join_kind,
                "cardinality": join.cardinality,
            }
            for join in version.joins
        ]
    if version.where is not None:
        asset["where"] = version.where
    if version.group_by:
        asset["groupBy"] = version.group_by
    return asset


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


def _projection_field(
    field: ProjectionField,
    projection: ProjectionVersion,
    source: ResolvedModelRef | None,
) -> dict[str, object]:
    source_field = _source_field(field, source)
    pii = field.is_pii or (source_field.is_pii if source_field is not None else False)
    classification = field.classification or (source_field.classification if source_field is not None else None)

    if isinstance(field.mapping, DirectMapping):
        data: dict[str, object] = {
            "name": field.name,
            "mapping": "direct",
            "source": _source_field_ref(projection, field.mapping),
            "pii": pii,
            "classification": classification.value if classification is not None else None,
        }
    elif isinstance(field.mapping, ComputedMapping):
        data = {
            "name": field.name,
            "mapping": "computed",
            "expression": field.mapping.expression,
            "pii": pii,
            "classification": classification.value if classification is not None else None,
        }
    else:
        data = {"name": field.name, "mapping": "unknown", "pii": pii, "classification": None}
    return data


def _projection_lineage(
    domain: DomainDef,
    projection_name: str,
    version: ProjectionVersion,
    source: ResolvedModelRef | None,
) -> list[dict[str, str]]:
    if source is None:
        return []
    lineage: list[dict[str, str]] = []
    for field in version.fields:
        if not isinstance(field.mapping, DirectMapping):
            continue
        source_model = source.model_name
        source_domain = source.domain_name
        lineage.append(
            {
                "from": f"{_asset_fqn(source_domain, source_model, source.version.version)}.{field.mapping.source_field}",
                "to": f"{_asset_fqn(domain.name, projection_name, version.version)}.{field.name}",
                "kind": "direct",
            }
        )
    return lineage


def _resolve_source(workspace: Workspace, projection: ProjectionVersion) -> ResolvedModelRef | None:
    try:
        return resolve_model_ref(workspace.mdl, projection.source.model, projection.source.version)
    except LookupError:
        return None


def _source_field(field: ProjectionField, source: ResolvedModelRef | None) -> FieldDef | None:
    if source is None or not isinstance(field.mapping, DirectMapping):
        return None
    for source_field in source.version.fields:
        if source_field.name == field.mapping.source_field:
            return source_field
    return None


def _source_field_ref(projection: ProjectionVersion, mapping: DirectMapping) -> str:
    version = projection.source.version
    if isinstance(version, VersionExact):
        return f"{projection.source.model}@{version.version}.{mapping.source_field}"
    if isinstance(version, VersionPinned):
        return f"{projection.source.model}@{version.version}#{version.content_hash}.{mapping.source_field}"
    return f"{projection.source.model}@{_version_spec(version)}.{mapping.source_field}"


def _asset_fqn(domain: str, name: str, version: int) -> str:
    return f"modelable.{domain}.{name}.v{version}"


def _version_spec(version) -> dict[str, object]:
    if isinstance(version, VersionExact):
        return {"kind": "exact", "version": version.version}
    if isinstance(version, VersionRange):
        return {
            "kind": "range",
            "minInclusive": version.min_inclusive,
            "maxExclusive": version.max_exclusive,
        }
    if isinstance(version, VersionMin):
        return {"kind": "min", "minInclusive": version.min_inclusive}
    if isinstance(version, VersionPinned):
        return {"kind": "pinned", "version": version.version, "contentHash": version.content_hash}
    return {"kind": "unknown"}


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
    if isinstance(field_type, NamedType):
        return field_type.name
    if isinstance(field_type, ObjectType):
        return "object"
    return "unknown"
