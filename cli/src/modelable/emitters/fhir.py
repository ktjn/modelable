from __future__ import annotations

import json
from pathlib import Path

from modelable.compiler.workspace import Workspace
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.parser.ir import (
    AnnClassification,
    AnnPii,
    ArrayType,
    DecimalType,
    DirectMapping,
    DomainDef,
    EnumType,
    FieldDef,
    FieldType,
    MdlFile,
    NamedType,
    ObjectType,
    PrimitiveType,
    ProjectionField,
    ProjectionVersion,
    RefType,
)
from modelable.registry.resolver import ResolvedModelRef, resolve_model_ref

FHIR_R4_VERSION = "4.0.1"
FHIR_STRUCTURE_DEFINITION_BASE = "http://hl7.org/fhir/StructureDefinition"
MODELABLE_STRUCTURE_DEFINITION_BASE = "http://modelable.io/fhir/StructureDefinition"
MODELABLE_VALUE_SET_BASE = "http://modelable.io/fhir/ValueSet"
SUPPORTED_BASE_RESOURCES = {"Encounter", "Observation", "Patient"}


def emit_fhir_profile(workspace: Workspace, out_dir: Path) -> list[EmittedArtifact]:
    """Emit FHIR R4 StructureDefinition profiles for every projection."""
    artifacts: list[EmittedArtifact] = []
    for domain in workspace.mdl.domains:
        for projection_name, versions in domain.projections.items():
            for version in versions:
                artifacts.append(_emit_projection(domain, projection_name, version, workspace.mdl, out_dir))
    return artifacts


def _emit_projection(
    domain: DomainDef,
    projection_name: str,
    version: ProjectionVersion,
    mdl: MdlFile,
    out_dir: Path,
) -> EmittedArtifact:
    artifact_id = _artifact_id(domain.name, projection_name, version.version)
    source = _resolve_source(mdl, version)
    base_resource, warnings = _base_resource(source)
    elements = _elements(domain, projection_name, version, source, base_resource)

    struct_def: dict[str, object] = {
        "resourceType": "StructureDefinition",
        "url": f"{MODELABLE_STRUCTURE_DEFINITION_BASE}/{artifact_id}",
        "version": str(version.version),
        "name": projection_name,
        "title": projection_name,
        "status": "draft",
        "fhirVersion": FHIR_R4_VERSION,
        "kind": "resource",
        "abstract": False,
        "type": base_resource,
        "baseDefinition": f"{FHIR_STRUCTURE_DEFINITION_BASE}/{base_resource}",
        "derivation": "constraint",
        "mapping": [
            {
                "identity": "modelable",
                "uri": "https://github.com/ktjn/modelable",
                "name": "Modelable",
            }
        ],
        "snapshot": {"element": elements},
        "differential": {"element": elements},
    }
    _add_domain_metadata(struct_def, domain)

    content = json.dumps(struct_def, indent=2, ensure_ascii=False) + "\n"
    return EmittedArtifact(
        target="fhir-profile",
        ref=f"{domain.name}.{projection_name}@{version.version}",
        artifact_id=artifact_id,
        path=out_dir / f"{artifact_id}.fhir.json",
        content=content,
        content_hash=compute_content_hash(content),
        warnings=warnings,
    )


def _artifact_id(domain: str, name: str, version: int) -> str:
    return f"{domain}.{name}.v{version}"


def _add_domain_metadata(struct_def: dict[str, object], domain: DomainDef) -> None:
    if domain.owner is not None:
        struct_def["publisher"] = domain.owner
    if domain.contact is not None:
        struct_def["contact"] = [{"telecom": [{"system": "email", "value": domain.contact}]}]
    if domain.description is not None:
        struct_def["description"] = domain.description


def _resolve_source(mdl: MdlFile, projection: ProjectionVersion) -> ResolvedModelRef | None:
    try:
        return resolve_model_ref(mdl, projection.source.model, projection.source.version)
    except LookupError:
        return None


def _base_resource(source: ResolvedModelRef | None) -> tuple[str, list[str]]:
    if source is None:
        return "Basic", ["FHIR profile source model could not be resolved; using Basic as the base resource"]
    resource = source.model_name
    if resource in SUPPORTED_BASE_RESOURCES:
        return resource, []
    supported = ", ".join(sorted(SUPPORTED_BASE_RESOURCES))
    return "Basic", [f"FHIR profile base resource '{resource}' is not in the supported R4 set: {supported}"]


def _elements(
    domain: DomainDef,
    projection_name: str,
    projection: ProjectionVersion,
    source: ResolvedModelRef | None,
    base_resource: str,
) -> list[dict[str, object]]:
    root = {
        "id": base_resource,
        "path": base_resource,
        "min": 0,
        "max": "*",
        "base": {"path": base_resource, "min": 0, "max": "*"},
        "definition": (
            f"Modelable projection {domain.name}.{projection_name}@{projection.version} constrained from "
            f"{projection.source.model}@{_version_label(projection)}."
        ),
    }
    return [
        root,
        *[
            _field_element(domain, projection_name, projection, field, source, base_resource)
            for field in projection.fields
        ],
    ]


def _field_element(
    domain: DomainDef,
    projection_name: str,
    projection: ProjectionVersion,
    field: ProjectionField,
    source: ResolvedModelRef | None,
    base_resource: str,
) -> dict[str, object]:
    source_field = _source_field(field, source)
    field_type = source_field.type if source_field is not None else PrimitiveType(kind="string")
    path = f"{base_resource}.{field.name}"
    element: dict[str, object] = {
        "id": path,
        "path": path,
        "min": 0 if source_field is not None and source_field.optional else 1,
        "max": "1",
        "base": {"path": path, "min": 0, "max": "1"},
        "definition": f"Modelable field {field.name}.",
        "type": _fhir_type(field_type),
    }

    binding = _binding(domain.name, projection_name, field.name, field_type)
    if binding is not None:
        element["binding"] = binding

    extensions = _extensions(field, source_field)
    if extensions:
        element["extension"] = extensions

    lineage = _lineage_mapping(field, projection, source)
    if lineage is not None:
        element["mapping"] = [{"identity": "modelable", "map": lineage}]

    return element


def _source_field(field: ProjectionField, source: ResolvedModelRef | None) -> FieldDef | None:
    if source is None or not isinstance(field.mapping, DirectMapping):
        return None
    return next(
        (source_field for source_field in source.version.fields if source_field.name == field.mapping.source_field),
        None,
    )


def _fhir_type(field_type: FieldType) -> list[dict[str, object]]:
    if isinstance(field_type, PrimitiveType):
        return [{"code": _primitive_type(field_type.kind)}]
    if isinstance(field_type, DecimalType):
        return [{"code": "decimal"}]
    if isinstance(field_type, EnumType):
        return [{"code": "code"}]
    if isinstance(field_type, RefType):
        target = field_type.target.rsplit(".", 1)[-1]
        return [
            {
                "code": "Reference",
                "targetProfile": [f"{FHIR_STRUCTURE_DEFINITION_BASE}/{target}"],
            }
        ]
    if isinstance(field_type, ArrayType):
        return _fhir_type(field_type.item)
    if isinstance(field_type, (NamedType, ObjectType)):
        return [{"code": "BackboneElement"}]
    return [{"code": "string"}]


def _primitive_type(kind: str) -> str:
    mapping = {
        "binary": "base64Binary",
        "bool": "boolean",
        "date": "date",
        "duration": "Duration",
        "float": "decimal",
        "int": "integer",
        "json": "string",
        "string": "string",
        "time": "time",
        "timestamp": "dateTime",
        "uuid": "string",
    }
    return mapping.get(kind, "string")


def _binding(domain_name: str, projection_name: str, field_name: str, field_type: FieldType) -> dict[str, str] | None:
    if not isinstance(field_type, EnumType):
        return None
    return {
        "strength": "required",
        "valueSet": f"{MODELABLE_VALUE_SET_BASE}/{domain_name}.{projection_name}.{field_name}",
    }


def _extensions(field: ProjectionField, source_field: FieldDef | None) -> list[dict[str, object]]:
    annotations = [*(source_field.annotations if source_field is not None else []), *field.annotations]
    classification_extensions: list[dict[str, object]] = []
    pii_extensions: list[dict[str, object]] = []
    for annotation in annotations:
        if isinstance(annotation, AnnClassification):
            classification_extensions.append(
                {
                    "url": f"{MODELABLE_STRUCTURE_DEFINITION_BASE}/classification",
                    "valueCode": annotation.level,
                }
            )
        elif isinstance(annotation, AnnPii):
            pii_extensions.append(
                {
                    "url": f"{MODELABLE_STRUCTURE_DEFINITION_BASE}/pii",
                    "valueBoolean": True,
                }
            )
    return [*classification_extensions, *pii_extensions]


def _lineage_mapping(
    field: ProjectionField,
    projection: ProjectionVersion,
    source: ResolvedModelRef | None,
) -> str | None:
    if source is None or not isinstance(field.mapping, DirectMapping):
        return None
    return f"{projection.source.model}@{source.version.version}.{field.mapping.source_field}"


def _version_label(projection: ProjectionVersion) -> str:
    version = projection.source.version
    if hasattr(version, "version"):
        return str(version.version)
    return str(version)
