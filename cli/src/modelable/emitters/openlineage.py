from __future__ import annotations

from pathlib import Path

from modelable.compiler.workspace import Workspace
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.openlineage_plan import emit_openlineage_plan
from modelable.parser.ir import (
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
from modelable.registry.resolver import annotation_owner

PRODUCER = "https://github.com/ktjn/modelable"
RUN_EVENT_SCHEMA_URL = "https://openlineage.io/spec/1-0-5/OpenLineage.json#/definitions/RunEvent"
SCHEMA_FACET_URL = "https://openlineage.io/spec/facets/1-1-1/SchemaDatasetFacet.json"
EVENT_TIME = "1970-01-01T00:00:00.000Z"


def emit_openlineage(workspace: Workspace, out_dir: Path) -> list[EmittedArtifact]:
    """Emit design-time OpenLineage run events for Modelable models and projections."""
    artifacts: list[EmittedArtifact] = []
    projection_artifacts = {
        f"{plan['domain']}.{plan['projection']}@{plan['version']}": emit_openlineage_plan(plan, out_dir)
        for plan in build_plan_documents(workspace, schema=PLAN_V1_SCHEMA)
    }

    for domain in workspace.mdl.domains:
        for model_name, model_versions in domain.models.items():
            for version in model_versions:
                artifacts.append(_emit_model(domain, model_name, version, out_dir))

        for projection_name, projection_versions in domain.projections.items():
            for projection_version in projection_versions:
                ref = f"{domain.name}.{projection_name}@{projection_version.version}"
                artifacts.append(projection_artifacts[ref])

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


def _model_schema_field(field: FieldDef) -> dict[str, str]:
    return _schema_field(
        name=field.name,
        field_type=field.type,
        pii=field.is_pii,
        classification=field.classification.value if field.classification else None,
        owner=_owner(field),
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


def _owner(field: FieldDef | None) -> str | None:
    if field is None:
        return None
    return annotation_owner(field.annotations)


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
    if isinstance(field_type, EnumRefType):
        return f"enumRef<{field_type.name}@{field_type.version}>"
    if isinstance(field_type, NamedType):
        return field_type.name
    if isinstance(field_type, ObjectType):
        return "object"
    return "unknown"
