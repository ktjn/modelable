from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from modelable.compiler.workspace import Workspace
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.odcs_plan import emit_odcs_projection_plan
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
    MdlFile,
    ModelVersion,
    NamedType,
    ObjectType,
    PrimitiveType,
    RefType,
    SemanticTypeDecl,
)
from modelable.planner.plans import build_plan_documents
from modelable.planner.protocol import PLAN_V1_SCHEMA
from modelable.registry.resolver import resolve_named_declaration

ODCS_VERSION = "v3.1.0"


def emit_odcs(workspace: Workspace, out_dir: Path) -> list[EmittedArtifact]:
    """Emit Open Data Contract Standard YAML documents for each model and projection version."""
    artifacts: list[EmittedArtifact] = []
    plans = {
        (plan["domain"], plan["projection"], plan["version"]): plan
        for plan in build_plan_documents(workspace, schema=PLAN_V1_SCHEMA)
    }

    for domain in workspace.mdl.domains:
        for model_name, versions in domain.models.items():
            for version in versions:
                artifacts.append(_emit_model(domain, model_name, version, out_dir, workspace.mdl))
        for projection_name, projection_versions in domain.projections.items():
            for projection_version in projection_versions:
                plan = plans[(domain.name, projection_name, projection_version.version)]
                artifacts.append(
                    emit_odcs_projection_plan(
                        plan,
                        out_dir,
                        domain_description=domain.description,
                        domain_owner=domain.owner,
                        domain_contact=domain.contact,
                    )
                )

    return artifacts


def _emit_model(
    domain: DomainDef, model_name: str, version: ModelVersion, out_dir: Path, mdl: MdlFile
) -> EmittedArtifact:
    artifact_id = _artifact_id(domain.name, model_name, version.version)
    ref = f"{domain.name}.{model_name}@{version.version}"
    properties = [_model_property(field, mdl, domain.name) for field in version.fields]
    custom_properties = _base_custom_properties(domain, ref, version.model_kind.value)
    custom_properties["modelableChangeKind"] = version.change_kind.value

    doc = _contract_document(
        domain=domain,
        name=model_name,
        version=version.version,
        ref=ref,
        kind=version.model_kind.value,
        schema_custom_properties={"modelableKind": version.model_kind.value},
        properties=properties,
        custom_properties=custom_properties,
    )

    return _artifact("odcs", ref, artifact_id, out_dir / f"{artifact_id}.odcs.yaml", doc)


def _contract_document(
    *,
    domain: DomainDef,
    name: str,
    version: int,
    ref: str,
    kind: str,
    schema_custom_properties: dict[str, Any],
    properties: list[dict[str, Any]],
    custom_properties: dict[str, Any],
) -> dict[str, Any]:
    schema_entry: dict[str, Any] = {
        "name": name,
        "logicalType": "object",
        "physicalName": name,
        "properties": properties,
        "customProperties": _custom_properties(schema_custom_properties),
    }
    return {
        "apiVersion": ODCS_VERSION,
        "kind": "DataContract",
        "id": f"modelable://{domain.name}/{name}/v{version}",
        "name": _artifact_id(domain.name, name, version),
        "version": str(version),
        "domain": domain.name,
        "status": "active",
        "description": {"purpose": domain.description or f"Modelable {kind} contract for {ref}"},
        "schema": [schema_entry],
        "authoritativeDefinitions": [{"url": f"modelable:{ref}", "type": "modelable"}],
        "customProperties": _custom_properties(custom_properties),
    }


def _model_property(field: FieldDef, mdl: MdlFile, current_domain: str) -> dict[str, Any]:
    prop = _field_property(field.name, field.type, mdl, current_domain, required=not field.optional)
    if field.is_key:
        prop["primaryKey"] = True
    _apply_governance(prop, field.is_pii, field.classification.value if field.classification else None, _owner(field))
    return prop


def _field_property(
    name: str, field_type: FieldType, mdl: MdlFile, current_domain: str, *, required: bool
) -> dict[str, Any]:
    type_info = _type_info(field_type, mdl, current_domain)
    prop: dict[str, Any] = {
        "name": name,
        "logicalType": type_info["logicalType"],
        "required": required,
        "customProperties": _custom_properties({"modelableType": type_info["modelable_type"]}),
    }
    if "logicalTypeOptions" in type_info:
        prop["logicalTypeOptions"] = type_info["logicalTypeOptions"]
    if "enum" in type_info:
        prop["customProperties"].append({"property": "modelableEnum", "value": type_info["enum"]})
    if extra := type_info.get("extra"):
        prop["customProperties"].extend(_custom_properties(extra))
    return prop


def _type_info(field_type: FieldType, mdl: MdlFile, current_domain: str) -> dict[str, Any]:
    if isinstance(field_type, PrimitiveType):
        if field_type.kind == "uuid":
            return {
                "logicalType": "string",
                "modelable_type": field_type.kind,
                "logicalTypeOptions": {"format": "uuid"},
            }
        return {"logicalType": field_type.kind, "modelable_type": field_type.kind}
    if isinstance(field_type, DecimalType):
        return {
            "logicalType": "number",
            "modelable_type": f"decimal({field_type.precision},{field_type.scale})",
            "extra": {"modelablePrecision": field_type.precision, "modelableScale": field_type.scale},
        }
    if isinstance(field_type, ArrayType):
        return {
            "logicalType": "array",
            "modelable_type": f"array<{_type_name(field_type.item)}>",
            "extra": {"modelableItemType": _type_name(field_type.item)},
        }
    if isinstance(field_type, MapType):
        return {
            "logicalType": "object",
            "modelable_type": f"map<{_type_name(field_type.key)},{_type_name(field_type.value)}>",
            "extra": {
                "modelableKeyType": _type_name(field_type.key),
                "modelableValueType": _type_name(field_type.value),
            },
        }
    if isinstance(field_type, RefType):
        return {
            "logicalType": "string",
            "modelable_type": f"ref<{field_type.target}>",
            "extra": {"modelableRef": field_type.target},
        }
    if isinstance(field_type, EnumType):
        return {"logicalType": "string", "modelable_type": _type_name(field_type), "enum": field_type.values}
    if isinstance(field_type, EnumRefType):
        try:
            resolved = resolve_named_declaration(
                mdl,
                current_domain,
                field_type.name,
                exact_version=field_type.version,
                include_enum_projections=False,
            )
        except LookupError:
            return {"logicalType": "string", "modelable_type": "unknown"}
        if not isinstance(resolved.declaration, SemanticTypeDecl):
            return {"logicalType": "string", "modelable_type": "unknown"}
        declaring_domain = resolved.domain_name
        decl = resolved.declaration
        if not isinstance(decl.underlying, EnumType):
            return {"logicalType": "string", "modelable_type": "unknown"}
        qualified_name = f"{declaring_domain}.{decl.name}"
        return {
            "logicalType": "string",
            "modelable_type": qualified_name,
            "enum": list(decl.underlying.values),
            "extra": {"modelableEnumType": qualified_name},
        }
    if isinstance(field_type, ObjectType):
        return {"logicalType": "object", "modelable_type": "object"}
    if isinstance(field_type, NamedType):
        return {
            "logicalType": "object",
            "modelable_type": field_type.name,
            "extra": {"modelableNamedType": field_type.name},
        }
    return {"logicalType": "string", "modelable_type": "unknown"}


def _apply_governance(prop: dict[str, Any], pii: bool, classification: str | None, owner: str | None) -> None:
    custom_properties: dict[str, Any] = {}
    if pii:
        custom_properties["modelablePii"] = True
    if classification:
        prop["classification"] = classification
    if owner:
        custom_properties["modelableOwner"] = owner
    prop["customProperties"].extend(_custom_properties(custom_properties))


def _base_custom_properties(domain: DomainDef, ref: str, kind: str) -> dict[str, Any]:
    custom_properties: dict[str, Any] = {
        "modelableRef": ref,
        "modelableKind": kind,
    }
    if domain.owner:
        custom_properties["modelableOwner"] = domain.owner
    if domain.contact:
        custom_properties["modelableContact"] = domain.contact
    return custom_properties


def _custom_properties(properties: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"property": key, "value": value} for key, value in properties.items()]


def _artifact(target: str, ref: str, artifact_id: str, path: Path, doc: dict[str, Any]) -> EmittedArtifact:
    yaml_content = yaml.safe_dump(doc, sort_keys=False, default_flow_style=False)
    content = f"# @generated by Modelable\n{yaml_content}"
    return EmittedArtifact(
        target=target,
        ref=ref,
        artifact_id=artifact_id,
        path=path,
        content=content,
        content_hash=compute_content_hash(content),
    )


def _owner(field: FieldDef) -> str | None:
    for annotation in field.annotations:
        if isinstance(annotation, AnnOwner):
            return annotation.team
    return None


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
        return field_type.name
    if isinstance(field_type, NamedType):
        return field_type.name
    if isinstance(field_type, ObjectType):
        return "object"
    return "unknown"
