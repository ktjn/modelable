from __future__ import annotations

import re
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
    MdlFile,
    ModelVersion,
    NamedType,
    ObjectType,
    PrimitiveType,
    ProjectionField,
    ProjectionVersion,
    RefType,
)
from modelable.registry.resolver import ResolvedModelRef, resolve_model_ref

PRODUCER = "https://github.com/ktjn/modelable"
RUN_EVENT_SCHEMA_URL = "https://openlineage.io/spec/1-0-5/OpenLineage.json#/definitions/RunEvent"
SCHEMA_FACET_URL = "https://openlineage.io/spec/facets/1-1-1/SchemaDatasetFacet.json"
COLUMN_LINEAGE_FACET_URL = "https://openlineage.io/spec/facets/1-2-0/ColumnLineageDatasetFacet.json"
EVENT_TIME = "1970-01-01T00:00:00.000Z"


def emit_openlineage(workspace: Workspace, out_dir: Path) -> list[EmittedArtifact]:
    """Emit design-time OpenLineage run events for Modelable models and projections."""
    artifacts: list[EmittedArtifact] = []

    for domain in workspace.mdl.domains:
        for model_name, versions in domain.models.items():
            for version in versions:
                artifacts.append(_emit_model(domain, model_name, version, out_dir))

        for projection_name, versions in domain.projections.items():
            for version in versions:
                artifacts.append(_emit_projection(domain, projection_name, version, workspace.mdl, out_dir))

    return artifacts


def _emit_model(domain: DomainDef, model_name: str, version: ModelVersion, out_dir: Path) -> EmittedArtifact:
    artifact_id = _artifact_id(domain.name, model_name, version.version)
    event = _event(
        domain=domain.name,
        artifact_id=artifact_id,
        outputs=[
            _dataset(
                domain.name,
                artifact_id,
                fields=[_model_schema_field(field) for field in version.fields],
            )
        ],
    )
    return _artifact(f"{domain.name}.{model_name}@{version.version}", artifact_id, out_dir, event)


def _emit_projection(
    domain: DomainDef,
    projection_name: str,
    version: ProjectionVersion,
    mdl: MdlFile,
    out_dir: Path,
) -> EmittedArtifact:
    artifact_id = _artifact_id(domain.name, projection_name, version.version)
    source = _resolve_source(mdl, version)
    source_dataset = _source_dataset(version, source)
    output_dataset = _dataset(
        domain.name,
        artifact_id,
        fields=[_projection_schema_field(field, version, source) for field in version.fields],
    )
    output_dataset["facets"]["columnLineage"] = _column_lineage(version, source_dataset, source)

    event = _event(
        domain=domain.name,
        artifact_id=artifact_id,
        inputs=[source_dataset] if source_dataset is not None else [],
        outputs=[output_dataset],
    )
    return _artifact(f"{domain.name}.{projection_name}@{version.version}", artifact_id, out_dir, event)


def _event(
    *,
    domain: str,
    artifact_id: str,
    outputs: list[dict[str, object]],
    inputs: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "eventType": "COMPLETE",
        "eventTime": EVENT_TIME,
        "run": {
            "runId": f"modelable-{artifact_id.replace('.', '-')}",
            "facets": {},
        },
        "job": {
            "namespace": f"modelable://{domain}",
            "name": f"compile/{artifact_id}",
        },
        "inputs": inputs or [],
        "outputs": outputs,
        "producer": PRODUCER,
        "schemaURL": RUN_EVENT_SCHEMA_URL,
    }


def _dataset(domain: str, name: str, *, fields: list[dict[str, str]]) -> dict[str, object]:
    return {
        "namespace": f"modelable://{domain}",
        "name": name,
        "facets": {
            "schema": {
                "_producer": PRODUCER,
                "_schemaURL": SCHEMA_FACET_URL,
                "fields": fields,
            }
        },
    }


def _source_dataset(projection: ProjectionVersion, source: ResolvedModelRef | None) -> dict[str, object] | None:
    if source is None:
        return None
    return _dataset(
        source.domain_name,
        _artifact_id(source.domain_name, source.model_name, source.version.version),
        fields=[_model_schema_field(field) for field in source.version.fields],
    )


def _model_schema_field(field: FieldDef) -> dict[str, str]:
    return _schema_field(
        name=field.name,
        field_type=field.type,
        pii=field.is_pii,
        classification=field.classification.value if field.classification else None,
        owner=_owner(field),
    )


def _projection_schema_field(
    field: ProjectionField,
    projection: ProjectionVersion,
    source: ResolvedModelRef | None,
) -> dict[str, str]:
    source_field = _source_field(field, source)
    field_type = source_field.type if source_field is not None else PrimitiveType(kind="string")
    pii = field.is_pii or (source_field.is_pii if source_field is not None else False)
    classification = field.classification or (source_field.classification if source_field is not None else None)
    owner = _owner(source_field) if source_field is not None else None
    return _schema_field(
        name=field.name,
        field_type=field_type,
        pii=pii,
        classification=classification.value if classification is not None else None,
        owner=owner,
    )


def _schema_field(
    *,
    name: str,
    field_type: FieldType,
    pii: bool,
    classification: str | None,
    owner: str | None,
) -> dict[str, str]:
    data = {"name": name, "type": _type_name(field_type)}
    description_parts = []
    if classification is not None:
        description_parts.append(f"classification={classification}")
    if pii:
        description_parts.append("pii=true")
    if owner is not None:
        description_parts.append(f"owner={owner}")
    if description_parts:
        data["description"] = "; ".join(description_parts)
    return data


def _column_lineage(
    projection: ProjectionVersion,
    source_dataset: dict[str, object] | None,
    source: ResolvedModelRef | None,
) -> dict[str, object]:
    fields: dict[str, object] = {}
    if source_dataset is None:
        return _lineage_facet(fields)

    for field in projection.fields:
        lineage = _field_lineage(field, projection, source_dataset, source)
        if lineage is not None:
            fields[field.name] = lineage

    return _lineage_facet(fields)


def _lineage_facet(fields: dict[str, object]) -> dict[str, object]:
    return {
        "_producer": PRODUCER,
        "_schemaURL": COLUMN_LINEAGE_FACET_URL,
        "fields": fields,
    }


def _field_lineage(
    field: ProjectionField,
    projection: ProjectionVersion,
    source_dataset: dict[str, object],
    source: ResolvedModelRef | None,
) -> dict[str, object] | None:
    if isinstance(field.mapping, DirectMapping):
        return {
            "inputFields": [
                {
                    "namespace": source_dataset["namespace"],
                    "name": source_dataset["name"],
                    "field": field.mapping.source_field,
                }
            ]
        }
    if isinstance(field.mapping, ComputedMapping):
        input_fields = [
            {"namespace": source_dataset["namespace"], "name": source_dataset["name"], "field": source_field}
            for source_field in _expression_source_fields(field.mapping.expression, projection, source)
        ]
        return {
            "inputFields": input_fields,
            "transformationDescription": field.mapping.expression,
            "transformationType": "TRANSFORMATION",
        }
    return None


def _expression_source_fields(
    expression: str,
    projection: ProjectionVersion,
    source: ResolvedModelRef | None,
) -> list[str]:
    if source is None:
        return []
    candidates = set(re.findall(rf"\b{re.escape(projection.source.alias)}\.([A-Za-z_][A-Za-z0-9_]*)\b", expression))
    known_fields = {field.name for field in source.version.fields}
    return sorted(candidates & known_fields)


def _resolve_source(mdl: MdlFile, projection: ProjectionVersion) -> ResolvedModelRef | None:
    try:
        return resolve_model_ref(mdl, projection.source.model, projection.source.version)
    except LookupError:
        return None


def _source_field(field: ProjectionField, source: ResolvedModelRef | None) -> FieldDef | None:
    if source is None or not isinstance(field.mapping, DirectMapping):
        return None
    return next(
        (source_field for source_field in source.version.fields if source_field.name == field.mapping.source_field),
        None,
    )


def _owner(field: FieldDef | None) -> str | None:
    if field is None:
        return None
    for annotation in field.annotations:
        if isinstance(annotation, AnnOwner):
            return annotation.team
    return None


def _artifact(ref: str, artifact_id: str, out_dir: Path, event: dict[str, object]) -> EmittedArtifact:
    return EmittedArtifact(
        target="openlineage",
        ref=ref,
        artifact_id=artifact_id,
        path=out_dir / f"{artifact_id}.openlineage.json",
        content=event,
        content_hash=compute_content_hash(event),
    )


def _artifact_id(domain: str, name: str, version: int) -> str:
    return f"{domain}.{name}.v{version}"


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
