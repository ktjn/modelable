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
    ModelVersion,
    NamedType,
    ObjectType,
    PrimitiveType,
    ProjectionField,
    ProjectionVersion,
    RefType,
    VersionMin,
)
from modelable.registry.resolver import ResolvedModelRef, resolve_model_ref

FHIR_R4_VERSION = "4.0.1"
FHIR_STRUCTURE_DEFINITION_BASE = "http://hl7.org/fhir/StructureDefinition"
MODELABLE_STRUCTURE_DEFINITION_BASE = "http://modelable.io/fhir/StructureDefinition"
MODELABLE_VALUE_SET_BASE = "http://modelable.io/fhir/ValueSet"
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
    "Basic": frozenset(
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
            "code",
            "subject",
            "created",
            "author",
        }
    ),
}

# Real base FHIR R4 type for each supported base resource element whose type is
# a single complex datatype. When a profile maps a Modelable composite (value
# object / named type) onto one of these elements, the differential must
# constrain the element to its real base type (e.g. `Observation.code` is a
# `CodeableConcept`), not the generic `BackboneElement` fallback — the official
# HL7 validator rejects snapshot generation otherwise. Elements whose real base
# type genuinely is `BackboneElement` (e.g. `Patient.contact`,
# `Observation.component`) are intentionally absent: the fallback is already
# correct for them. Choice elements (`[x]`) and primitive-typed elements are
# also absent — the former have no single specific type, the latter never
# reach the composite fallback.
_BASE_RESOURCE_FIELD_TYPES: dict[str, dict[str, str]] = {
    "Patient": {
        "identifier": "Identifier",
        "name": "HumanName",
        "telecom": "ContactPoint",
        "address": "Address",
        "maritalStatus": "CodeableConcept",
        "photo": "Attachment",
        "generalPractitioner": "Reference",
        "managingOrganization": "Reference",
    },
    "Observation": {
        "identifier": "Identifier",
        "basedOn": "Reference",
        "partOf": "Reference",
        "category": "CodeableConcept",
        "code": "CodeableConcept",
        "subject": "Reference",
        "focus": "Reference",
        "encounter": "Reference",
        "performer": "Reference",
        "dataAbsentReason": "CodeableConcept",
        "interpretation": "CodeableConcept",
        "note": "Annotation",
        "bodySite": "CodeableConcept",
        "method": "CodeableConcept",
        "specimen": "Reference",
        "device": "Reference",
        "hasMember": "Reference",
        "derivedFrom": "Reference",
    },
    "Encounter": {
        "class": "Coding",
        "type": "CodeableConcept",
        "serviceType": "CodeableConcept",
        "priority": "CodeableConcept",
        "subject": "Reference",
        "episodeOfCare": "Reference",
        "basedOn": "Reference",
        "appointment": "Reference",
        "period": "Period",
        "length": "Duration",
        "reasonCode": "CodeableConcept",
        "reasonReference": "Reference",
        "account": "Reference",
        "serviceProvider": "Reference",
        "partOf": "Reference",
    },
}


def emit_fhir_profile(workspace: Workspace, out_dir: Path) -> list[EmittedArtifact]:
    """Emit FHIR R4 StructureDefinition profiles and companion Extension SDs."""
    artifacts: list[EmittedArtifact] = []
    annotation_extensions = _annotation_extension_artifacts(workspace, out_dir)
    artifacts.extend(annotation_extensions)
    for domain in workspace.mdl.domains:
        for projection_name, versions in domain.projections.items():
            for version in versions:
                result = _emit_projection(domain, projection_name, version, workspace.mdl, out_dir)
                artifacts.append(result["profile"])
                artifacts.extend(result["extensions"])
    return artifacts


def _annotation_extension_artifacts(workspace: Workspace, out_dir: Path) -> list[EmittedArtifact]:
    artifacts: list[EmittedArtifact] = []
    annotations: tuple[tuple[str, type[AnnPii] | type[AnnClassification], str], ...] = (
        ("pii", AnnPii, "boolean"),
        ("classification", AnnClassification, "code"),
    )
    for name, annotation_type, value_code in annotations:
        if any(
            isinstance(annotation, annotation_type)
            for domain in workspace.mdl.domains
            for versions in domain.models.values()
            for version in versions
            for field in version.fields
            for annotation in field.annotations
        ) or any(
            isinstance(annotation, annotation_type)
            for domain in workspace.mdl.domains
            for versions in domain.projections.values()
            for version in versions
            for field in version.fields
            for annotation in field.annotations
        ):
            artifacts.append(_emit_annotation_extension_sd(name, value_code, out_dir))
    return artifacts


def _emit_annotation_extension_sd(name: str, value_code: str, out_dir: Path) -> EmittedArtifact:
    url = f"{MODELABLE_STRUCTURE_DEFINITION_BASE}/{name}"
    elements = [
        {
            "id": "Extension",
            "path": "Extension",
            "min": 0,
            "max": "1",
            "definition": f"Modelable {name} annotation extension.",
        },
        {
            "id": "Extension.url",
            "path": "Extension.url",
            "min": 1,
            "max": "1",
            "fixedUri": url,
            "type": [{"code": "uri"}],
            "definition": " identifies the extension.",
        },
        {
            "id": "Extension.value[x]",
            "path": "Extension.value[x]",
            "min": 1,
            "max": "1",
            "type": [{"code": value_code}],
            "definition": f"Value of the Modelable {name} annotation.",
        },
    ]
    _add_extension_bases(elements)
    struct_def: dict[str, object] = {
        "resourceType": "StructureDefinition",
        "url": url,
        "version": "1",
        "name": f"Modelable{name.title()}",
        "title": f"Modelable {name} annotation",
        "status": "draft",
        "fhirVersion": FHIR_R4_VERSION,
        "kind": "complex-type",
        "abstract": False,
        "context": [{"type": "element", "expression": "Element"}],
        "type": "Extension",
        "baseDefinition": f"{FHIR_STRUCTURE_DEFINITION_BASE}/Extension",
        "derivation": "constraint",
        "snapshot": {"element": elements},
        "differential": {"element": elements},
    }
    content = json.dumps(struct_def, indent=2, ensure_ascii=False) + "\n"
    return EmittedArtifact(
        target="fhir-extension",
        ref=f"workspace.extension.{name}",
        artifact_id=name,
        path=out_dir / f"{name}.fhir.json",
        content=content,
        content_hash=compute_content_hash(content),
        warnings=[],
    )


def _emit_projection(
    domain: DomainDef,
    projection_name: str,
    version: ProjectionVersion,
    mdl: MdlFile,
    out_dir: Path,
) -> dict[str, object]:
    artifact_id = _artifact_id(domain.name, projection_name, version.version)
    source = _resolve_source(mdl, version)
    base_resource, warnings = _base_resource(source)

    ext_fields = [f for f in version.fields if _is_extension_field(base_resource, f)]
    direct_fields = [f for f in version.fields if not _is_extension_field(base_resource, f)]
    elements = _elements(domain, projection_name, version, source, base_resource, ext_fields, direct_fields, mdl)

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
    profile = EmittedArtifact(
        target="fhir-profile",
        ref=f"{domain.name}.{projection_name}@{version.version}",
        artifact_id=artifact_id,
        path=out_dir / f"{artifact_id}.fhir.json",
        content=content,
        content_hash=compute_content_hash(content),
        warnings=warnings,
    )

    extension_artifacts = [
        _emit_extension_sd(domain, projection_name, version.version, field, source, out_dir, mdl)
        for field in ext_fields
    ]

    return {"profile": profile, "extensions": extension_artifacts}


def _is_extension_field(base_resource: str, field: ProjectionField) -> bool:
    elements = _BASE_RESOURCE_ELEMENTS.get(base_resource)
    if elements is None:
        return True
    return field.name not in elements


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
    ext_fields: list[ProjectionField],
    direct_fields: list[ProjectionField],
    mdl: MdlFile,
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
    elements: list[dict[str, object]] = [root]
    # `Extension`/`modifierExtension` precede every resource-specific field
    # (identifier, name, contact, ...) in every base FHIR resource's own
    # structural element order. A differential must list its elements in
    # that same base-structural order for the official snapshot generator
    # to match each differential element against the base it constrains -
    # out of order, it reports "No match found ... check that the path and
    # definitions are legal in the differential (including order)" and
    # aborts snapshot generation for every element after the mismatch.
    if ext_fields:
        elements.append(_extension_slicing_element(base_resource))
        for field in ext_fields:
            source_field = _source_field(field, source)
            field_type = source_field.type if source_field is not None else PrimitiveType(kind="string")
            elements.append(
                _extension_slice_element(domain, projection_name, projection, field, source, base_resource, field_type)
            )
            if not isinstance(field_type, ObjectType):
                elements.append(
                    _extension_value_element(
                        domain.name,
                        projection_name,
                        field,
                        field_type,
                        base_resource,
                        mdl,
                        source_field=source_field,
                    )
                )
    for field in direct_fields:
        elements.append(_field_element(domain, projection_name, projection, field, source, base_resource, mdl))
    return elements


def _field_element(
    domain: DomainDef,
    projection_name: str,
    projection: ProjectionVersion,
    field: ProjectionField,
    source: ResolvedModelRef | None,
    base_resource: str,
    mdl: MdlFile,
) -> dict[str, object]:
    source_field = _source_field(field, source)
    field_type = source_field.type if source_field is not None else PrimitiveType(kind="string")
    path = f"{base_resource}.{field.name}"
    max_occurs = _max_occurs(field_type)
    element: dict[str, object] = {
        "id": path,
        "path": path,
        "min": 0 if source_field is not None and source_field.optional else 1,
        "max": max_occurs,
        "base": {"path": path, "min": 0, "max": max_occurs},
        "definition": f"Modelable field {field.name}.",
        "type": _fhir_type(
            field_type,
            source_field=source_field,
            mdl=mdl,
            current_domain=domain.name,
            allow_backbone=True,
            base_element=(base_resource, field.name),
        ),
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
    candidate = next(
        (source_field for source_field in source.version.fields if source_field.name == field.mapping.source_field),
        None,
    )
    return candidate if isinstance(candidate, FieldDef) else None


def _fhir_type(
    field_type: FieldType,
    *,
    source_field: FieldDef | None = None,
    mdl: MdlFile | None = None,
    current_domain: str | None = None,
    allow_backbone: bool = False,
    base_element: tuple[str, str] | None = None,
) -> list[dict[str, object]]:
    # `allow_backbone` must stay False for every call site that ultimately
    # feeds an Extension's own `value[x]` (including nested sub-extension
    # `value[x]`) - the base FHIR `Extension.value[x]` element's own type
    # binding excludes `BackboneElement`, so assigning it there is invalid
    # generated output, not just a stylistic choice. It is only valid for a
    # genuine base-resource field element (e.g. `Patient.contact`), whose
    # own base type in core FHIR already is `BackboneElement`.
    if source_field is not None:
        wire_type = _wire_fhir_type_override(source_field)
        if wire_type is not None:
            return [{"code": wire_type}]
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
        return _fhir_type(
            field_type.item,
            mdl=mdl,
            current_domain=current_domain,
            allow_backbone=allow_backbone,
            base_element=base_element,
        )
    if isinstance(field_type, NamedType) and mdl is not None and current_domain is not None:
        model_ref = field_type.name if "." in field_type.name else f"{current_domain}.{field_type.name}"
        try:
            resolved = resolve_model_ref(mdl, model_ref, VersionMin(min_inclusive=1))
        except LookupError:
            return _composite_fallback(allow_backbone, base_element)
        if isinstance(resolved.version, ModelVersion) and resolved.version.model_kind.value == "value":
            value_field = resolved.version.fields[0] if len(resolved.version.fields) == 1 else None
            if value_field is not None:
                return _fhir_type(
                    value_field.type,
                    source_field=value_field,
                    mdl=mdl,
                    current_domain=resolved.domain_name,
                    allow_backbone=allow_backbone,
                    base_element=base_element,
                )
        return _composite_fallback(allow_backbone, base_element)
    if isinstance(field_type, (NamedType, ObjectType)):
        return _composite_fallback(allow_backbone, base_element)
    return [{"code": "string"}]


def _composite_fallback(allow_backbone: bool, base_element: tuple[str, str] | None) -> list[dict[str, object]]:
    specific = _specific_base_element_type(base_element)
    if specific is not None:
        return [{"code": specific}]
    return [{"code": "BackboneElement"}] if allow_backbone else [{"code": "string"}]


def _specific_base_element_type(base_element: tuple[str, str] | None) -> str | None:
    """Return the real FHIR base type for a known base-resource element, if any."""
    if base_element is None:
        return None
    resource, name = base_element
    return _BASE_RESOURCE_FIELD_TYPES.get(resource, {}).get(name)


def _wire_fhir_type_override(field: FieldDef) -> str | None:
    wire = field.wire_targets().get("fhir")
    if wire is not None:
        if getattr(wire, "type", None) is not None:
            return wire.type
        encoding = getattr(wire, "encoding", None)
        if encoding is not None:
            _encoding_map = {
                "string": "string",
                "integer": "integer",
                "boolean": "boolean",
                "decimal": "decimal",
                "dateTime": "dateTime",
                "uri": "uri",
                "code": "code",
            }
            return _encoding_map.get(encoding)
    return None


def _max_occurs(field_type: FieldType) -> str:
    if isinstance(field_type, ArrayType):
        return "*"
    return "1"


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
        "u8": "integer",
        "u16": "integer",
        # u32's range (0..4294967295) exceeds FHIR integer's 32-bit signed range
        # (max 2147483647), so it maps to string like the wider unsigned kinds.
        "u32": "string",
        "u64": "string",
        "u128": "string",
        "i8": "integer",
        "i16": "integer",
        "i32": "integer",
        "i64": "string",
        "i128": "string",
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


def _extension_artifact_id(domain_name: str, projection_name: str, version: int, field_name: str) -> str:
    return f"{domain_name}.{projection_name}.v{version}.ext.{field_name}"


def _extension_slicing_element(base_resource: str) -> dict[str, object]:
    return {
        "id": f"{base_resource}.extension",
        "path": f"{base_resource}.extension",
        "min": 0,
        "max": "*",
        "base": {"path": f"{base_resource}.extension", "min": 0, "max": "*"},
        "definition": "Optional Extensions Element - found in all resources.",
        "type": [{"code": "Extension"}],
        "slicing": {
            "discriminator": [{"type": "value", "path": "url"}],
            "ordered": False,
            "rules": "open",
        },
    }


def _extension_slice_element(
    domain: DomainDef,
    projection_name: str,
    projection: ProjectionVersion,
    field: ProjectionField,
    source: ResolvedModelRef | None,
    base_resource: str,
    field_type: FieldType,
) -> dict[str, object]:
    source_field = _source_field(field, source)
    ext_id = _extension_artifact_id(domain.name, projection_name, projection.version, field.name)
    max_occurs = _max_occurs(field_type)
    element: dict[str, object] = {
        "id": f"{base_resource}.extension:{field.name}",
        "path": f"{base_resource}.extension",
        "sliceName": field.name,
        "min": 0 if source_field is not None and source_field.optional else 1,
        "max": max_occurs,
        "base": {"path": f"{base_resource}.extension", "min": 0, "max": "*"},
        "type": [
            {
                "code": "Extension",
                "profile": [f"{MODELABLE_STRUCTURE_DEFINITION_BASE}/{ext_id}"],
            }
        ],
        "definition": f"Modelable field {field.name} (extension).",
    }

    extensions = _extensions(field, source_field)
    if extensions:
        element["extension"] = extensions

    lineage = _lineage_mapping(field, projection, source)
    if lineage is not None:
        element["mapping"] = [{"identity": "modelable", "map": lineage}]

    return element


def _extension_value_element(
    domain_name: str,
    projection_name: str,
    field: ProjectionField,
    field_type: FieldType,
    base_resource: str,
    mdl: MdlFile,
    *,
    source_field: FieldDef | None = None,
) -> dict[str, object]:
    # A repeating field is expressed by letting the *slice*
    # (`Extension.extension:{field.name}`, built in `_extension_slice_element`)
    # repeat - each individual Extension occurrence still carries exactly one
    # value, matching the base `Extension.value[x]` element's own fixed 0..1
    # cardinality in core FHIR. Reusing the field's own (possibly `*`) max
    # here as well would double-apply the array-ness and violate that base
    # cardinality once `base` is present for the validator to check against.
    element: dict[str, object] = {
        "id": f"{base_resource}.extension:{field.name}.value[x]",
        "path": f"{base_resource}.extension.value[x]",
        "min": 1,
        "max": "1",
        "base": {"path": "Extension.value[x]", "min": 0, "max": "1"},
        "type": _fhir_type(field_type, source_field=source_field, mdl=mdl, current_domain=domain_name),
    }

    element["definition"] = f"Modelable field {field.name} extension value."

    binding = _binding(domain_name, projection_name, field.name, field_type)
    if binding is not None:
        element["binding"] = binding

    return element


def _extension_sd_value_element(
    domain_name: str,
    projection_name: str,
    field: ProjectionField,
    field_type: FieldType,
    mdl: MdlFile,
    *,
    source_field: FieldDef | None = None,
) -> dict[str, object]:
    # See the matching comment in `_extension_value_element`: an extension
    # definition describes a single occurrence, so `value[x]` is always 0..1
    # regardless of the source field's own cardinality - repetition is a
    # property of the *slice* that references this definition, not of the
    # definition itself.
    element: dict[str, object] = {
        "id": "Extension.value[x]",
        "path": "Extension.value[x]",
        "min": 1,
        "max": "1",
        "type": _fhir_type(field_type, source_field=source_field, mdl=mdl, current_domain=domain_name),
    }

    element["definition"] = f"Modelable field {field.name} extension value."

    binding = _binding(domain_name, projection_name, field.name, field_type)
    if binding is not None:
        element["binding"] = binding

    return element


def _extension_sd_sub_extension_elements(
    domain_name: str,
    projection_name: str,
    field: ProjectionField,
    source_field: FieldDef | None,
    ext_id: str,
    parent_ext_url: str,
    mdl: MdlFile,
) -> list[dict[str, object]]:
    if source_field is None or not isinstance(source_field.type, ObjectType):
        field_type = source_field.type if source_field is not None else PrimitiveType(kind="string")
        return [
            _extension_sd_value_element(domain_name, projection_name, field, field_type, mdl, source_field=source_field)
        ]

    obj_type = source_field.type
    sub_elements: list[dict[str, object]] = [
        {
            "id": "Extension.extension",
            "path": "Extension.extension",
            "min": 0,
            "max": "*",
            "slicing": {
                "discriminator": [{"type": "value", "path": "url"}],
                "ordered": False,
                "rules": "open",
            },
        },
    ]
    for sub_field in obj_type.fields:
        sub_url = f"{parent_ext_url}#{sub_field.name}"
        sub_fhir_type = _fhir_type(sub_field.type, source_field=sub_field, mdl=mdl, current_domain=domain_name)
        sub_max = _max_occurs(sub_field.type)
        slice_id = f"Extension.extension:{sub_field.name}"
        sub_elements.append(
            {
                "id": slice_id,
                "path": "Extension.extension",
                "sliceName": sub_field.name,
                "min": 0 if sub_field.optional else 1,
                "max": sub_max,
                "type": [{"code": "Extension"}],
                "definition": f"Modelable sub-field {field.name}.{sub_field.name}.",
            }
        )
        sub_elements.append(
            {
                "id": f"{slice_id}.url",
                "path": "Extension.extension.url",
                "min": 1,
                "max": "1",
                "fixedUri": sub_url,
                "type": [{"code": "uri"}],
            }
        )
        sub_elements.append(
            {
                "id": f"{slice_id}.value[x]",
                "path": "Extension.extension.value[x]",
                "min": 1,
                # Same reasoning as `_extension_sd_value_element`/
                # `_extension_value_element`: the outer slice above already
                # carries `sub_max`'s repetition; a single sub-extension
                # occurrence's own value is always 0..1 per base FHIR.
                "max": "1",
                "type": sub_fhir_type,
                "definition": f"Modelable sub-field {field.name}.{sub_field.name} value.",
            }
        )
    return sub_elements


def _emit_extension_sd(
    domain: DomainDef,
    projection_name: str,
    version_num: int,
    field: ProjectionField,
    source: ResolvedModelRef | None,
    out_dir: Path,
    mdl: MdlFile,
) -> EmittedArtifact:
    source_field = _source_field(field, source)
    ext_id = _extension_artifact_id(domain.name, projection_name, version_num, field.name)
    ext_url = f"{MODELABLE_STRUCTURE_DEFINITION_BASE}/{ext_id}"
    sd_name = f"{projection_name}{field.name[0].upper() + field.name[1:] if field.name else field.name}"

    elements: list[dict[str, object]] = [
        {
            "id": "Extension",
            "path": "Extension",
            "definition": f"Modelable extension for {domain.name}.{projection_name}.{field.name}.",
        },
        {
            "id": "Extension.url",
            "path": "Extension.url",
            "min": 1,
            "max": "1",
            "fixedUri": ext_url,
            "type": [{"code": "uri"}],
            "definition": "Source of the definition for the extension code - a logical name or a URL.",
        },
    ]
    elements.extend(
        _extension_sd_sub_extension_elements(domain.name, projection_name, field, source_field, ext_id, ext_url, mdl)
    )
    _add_extension_bases(elements)

    struct_def: dict[str, object] = {
        "resourceType": "StructureDefinition",
        "url": ext_url,
        "version": str(version_num),
        "name": sd_name,
        "title": f"{projection_name} {field.name}",
        "status": "draft",
        "fhirVersion": FHIR_R4_VERSION,
        "kind": "complex-type",
        "abstract": False,
        "context": [{"type": "element", "expression": "Element"}],
        "type": "Extension",
        "baseDefinition": f"{FHIR_STRUCTURE_DEFINITION_BASE}/Extension",
        "derivation": "constraint",
        "snapshot": {"element": elements},
        "differential": {"element": elements},
    }
    _add_domain_metadata(struct_def, domain)

    content = json.dumps(struct_def, indent=2, ensure_ascii=False) + "\n"
    return EmittedArtifact(
        target="fhir-extension",
        ref=f"{domain.name}.{projection_name}@{version_num}.{field.name}",
        artifact_id=ext_id,
        path=out_dir / f"{ext_id}.fhir.json",
        content=content,
        content_hash=compute_content_hash(content),
        warnings=[],
    )


def _add_extension_bases(elements: list[dict[str, object]]) -> None:
    for element in elements:
        path = str(element["path"])
        element.setdefault("min", 0)
        element.setdefault("max", "*")
        element.setdefault(
            "base",
            {
                "path": path,
                "min": element["min"],
                "max": element["max"],
            },
        )


def _version_label(projection: ProjectionVersion) -> str:
    version = projection.source.version
    if hasattr(version, "version"):
        return str(version.version)
    return str(version)
