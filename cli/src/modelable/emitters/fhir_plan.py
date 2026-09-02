"""Parser-free scalar FHIR profile rendering for ``modelable.plan/v1``."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.planner.protocol import PlanDocument, validate_plan

FHIR_R4_VERSION = "4.0.1"
FHIR_STRUCTURE_DEFINITION_BASE = "http://hl7.org/fhir/StructureDefinition"
MODELABLE_STRUCTURE_DEFINITION_BASE = "http://modelable.io/fhir/StructureDefinition"
SUPPORTED_BASE_RESOURCES = {"Encounter", "Observation", "Patient"}

_BASE_RESOURCE_ELEMENTS: dict[str, frozenset[str]] = {
    "Patient": frozenset(
        {
            "id",
            "meta",
            "implicitRules",
            "language",
            "text",
            "contained",
            "extension",
            "modifierExtension",
            "identifier",
            "active",
            "name",
            "telecom",
            "gender",
            "birthDate",
            "deceased[x]",
            "address",
            "maritalStatus",
            "multipleBirth[x]",
            "photo",
            "contact",
            "communication",
            "generalPractitioner",
            "managingOrganization",
            "link",
        }
    ),
    "Observation": frozenset(
        {
            "id",
            "meta",
            "implicitRules",
            "language",
            "text",
            "contained",
            "extension",
            "modifierExtension",
            "identifier",
            "basedOn",
            "partOf",
            "status",
            "category",
            "code",
            "subject",
            "focus",
            "encounter",
            "effective[x]",
            "issued",
            "performer",
            "value[x]",
            "dataAbsentReason",
            "interpretation",
            "note",
            "bodySite",
            "method",
            "specimen",
            "device",
            "referenceRange",
            "hasMember",
            "derivedFrom",
            "component",
        }
    ),
    "Encounter": frozenset(
        {
            "id",
            "meta",
            "implicitRules",
            "language",
            "text",
            "contained",
            "extension",
            "modifierExtension",
            "identifier",
            "status",
            "statusHistory",
            "class",
            "classHistory",
            "type",
            "serviceType",
            "priority",
            "subject",
            "episodeOfCare",
            "basedOn",
            "participant",
            "appointment",
            "period",
            "length",
            "reasonCode",
            "reasonReference",
            "diagnosis",
            "account",
            "hospitalization",
            "location",
            "serviceProvider",
            "partOf",
        }
    ),
}


def emit_fhir_projection_plan(
    plan: PlanDocument,
    out_dir: Path,
    *,
    domain_metadata: Mapping[str, str | None] | None = None,
) -> EmittedArtifact:
    """Emit one scalar FHIR profile from validated plan facts."""
    document = validate_plan(plan)
    domain = _string(document, "domain")
    projection = _string(document, "projection")
    version = _integer(document, "version")
    source = _mapping(document.get("source"))
    base_resource = _string(source, "model").rsplit(".", 1)[-1]
    fields = [_field(document, field, base_resource) for field in _mappings(document.get("fields"))]
    elements: list[dict[str, Any]] = [
        {
            "id": base_resource,
            "path": base_resource,
            "min": 0,
            "max": "*",
            "base": {"path": base_resource, "min": 0, "max": "*"},
            "definition": (
                f"Modelable projection {domain}.{projection}@{version} constrained from "
                f"{_string(source, 'model')}@{_version_label(_mapping(source.get('version')))}."
            ),
        }
    ]
    elements.extend(fields)
    struct_def: dict[str, Any] = {
        "resourceType": "StructureDefinition",
        "url": f"{MODELABLE_STRUCTURE_DEFINITION_BASE}/{domain}.{projection}.v{version}",
        "version": str(version),
        "name": projection,
        "title": projection,
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
    if domain_metadata:
        owner = domain_metadata.get("owner")
        contact = domain_metadata.get("contact")
        description = domain_metadata.get("description")
        if owner is not None:
            struct_def["publisher"] = owner
        if contact is not None:
            struct_def["contact"] = [{"telecom": [{"system": "email", "value": contact}]}]
        if description is not None:
            struct_def["description"] = description
    content = json.dumps(struct_def, indent=2, ensure_ascii=False) + "\n"
    artifact_id = f"{domain}.{projection}.v{version}"
    return EmittedArtifact(
        target="fhir-profile",
        ref=f"{domain}.{projection}@{version}",
        artifact_id=artifact_id,
        path=out_dir / f"{artifact_id}.fhir.json",
        content=content,
        content_hash=compute_content_hash(content),
        warnings=[],
    )


def _field(plan: PlanDocument, field: dict[str, Any], base_resource: str) -> dict[str, Any]:
    name = _string(field, "name")
    source_field = _source_field(plan, field)
    source_type = _mapping(source_field.get("type")) if source_field else _mapping(field.get("type"))
    return {
        "id": f"{base_resource}.{name}",
        "path": f"{base_resource}.{name}",
        "min": 0 if source_field and source_field.get("optional") is True else 1,
        "max": "1",
        "base": {"path": f"{base_resource}.{name}", "min": 0, "max": "1"},
        "definition": f"Modelable field {name}.",
        "type": [{"code": _fhir_type(_string(source_type, "kind"))}],
        **({"mapping": [{"identity": "modelable", "map": _lineage(field)}]} if _lineage(field) else {}),
    }


def _source_field(plan: PlanDocument, field: dict[str, Any]) -> dict[str, Any] | None:
    source = _mapping(plan.get("source"))
    if field.get("kind") != "direct":
        return None
    if field.get("source_alias") != source.get("alias"):
        return None
    resolved = _mapping(source.get("resolved"))
    return next(
        (
            candidate
            for candidate in _mappings(resolved.get("fields"))
            if candidate.get("name") == field.get("source_field")
        ),
        None,
    )


def _lineage(field: dict[str, Any]) -> str | None:
    values = field.get("lineage")
    if isinstance(values, list) and values and isinstance(values[0], str):
        return values[0]
    return None


def _fhir_type(kind: str) -> str:
    return {
        "binary": "base64Binary",
        "bool": "boolean",
        "date": "date",
        "decimal": "decimal",
        "duration": "Duration",
        "float": "decimal",
        "int": "integer",
        "json": "string",
        "string": "string",
        "time": "time",
        "timestamp": "dateTime",
        "uuid": "string",
        "u8": "integer",
        "u16": "integer",
        "i8": "integer",
        "i16": "integer",
    }.get(kind, "string")


def _version_label(version: dict[str, Any]) -> str:
    kind = _string(version, "kind")
    if kind in {"exact", "pinned"}:
        label = str(_integer(version, "version"))
        if kind == "pinned":
            label += f"#{_string(version, 'contentHash')}"
        return label
    if kind == "range":
        return f">={_integer(version, 'minInclusive')}<{_integer(version, 'maxExclusive')}"
    return f">={_integer(version, 'minInclusive')}"


def _mapping(value: object) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _mappings(value: object) -> list[dict[str, Any]]:
    return [cast(dict[str, Any], item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _string(mapping: dict[str, Any], key: str) -> str:
    return str(mapping.get(key, ""))


def _integer(mapping: dict[str, Any], key: str) -> int:
    value = mapping.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"plan {key} must be an integer")
    return value
