from __future__ import annotations

from pathlib import PurePath, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator

from modelable.compiler.workspace import Workspace
from modelable.emitters._schema_mapping import (
    _field_to_json_schema,
)
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.diagnostics import type_loss, validation_failed
from modelable.emitters.json_schema_plan import emit_json_schema_plan
from modelable.governance.por import build_por_reference
from modelable.parser.ir import (
    DomainDef,
    FieldDef,
    MdlFile,
    ModelVersion,
    NamedType,
    PrimitiveType,
)
from modelable.planner.plans import build_plan_documents
from modelable.planner.protocol import PLAN_V1_SCHEMA


def emit_json_schema(workspace: Workspace, out_dir: PurePath) -> list[EmittedArtifact]:
    """Emit JSON Schema 2020-12 artifacts for every model and projection version."""
    artifacts: list[EmittedArtifact] = []
    plans = {
        (plan["domain"], plan["projection"], plan["version"]): plan
        for plan in build_plan_documents(workspace, schema=PLAN_V1_SCHEMA)
    }
    for domain in workspace.mdl.domains:
        for model_name, model_versions in domain.models.items():
            for version in model_versions:
                artifact = _emit_model_version(domain, model_name, version, out_dir, workspace.mdl)
                artifacts.append(artifact)

        for projection_name, projection_versions in domain.projections.items():
            for projection_version in projection_versions:
                plan = plans[(domain.name, projection_name, projection_version.version)]
                artifact = emit_json_schema_plan(
                    plan,
                    out_dir,
                    domain_owner=domain.owner,
                    domain_contact=domain.contact,
                    domain_description=domain.description,
                )
                artifacts.append(artifact)
    return artifacts


def emit_json_schema_artifacts(workspace: Workspace) -> list[EmittedArtifact]:
    """Return deterministic JSON Schema artifacts without writing files."""
    return emit_json_schema(workspace, PurePosixPath())


def _artifact_id(domain: str, name: str, version: int) -> str:
    return f"{domain}.{name}.v{version}"


def _emit_model_version(
    domain: DomainDef, model_name: str, version: ModelVersion, out_dir: PurePath, mdl: MdlFile
) -> EmittedArtifact:
    artifact_id = _artifact_id(domain.name, model_name, version.version)
    schema: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": artifact_id,
        "type": "object",
        "title": model_name,
        "x-modelable": {
            "domain": domain.name,
            "name": model_name,
            "kind": version.model_kind.value,
            "version": version.version,
            "changeKind": version.change_kind.value,
        },
        "x-modelable-por": build_por_reference(f"{domain.name}.{model_name}.v{version.version}"),
    }
    _add_domain_metadata(schema["x-modelable"], domain)

    properties: dict[str, dict[str, Any]] = {}
    required: list[str] = []
    warnings: list[str] = []
    defs: dict[str, dict[str, Any]] = {}

    for field in version.fields:
        prop = _field_to_json_schema(field, field.type, defs=defs, path=[field.name], mdl=mdl)
        default_value = _field_default(field)
        if default_value is not None:
            prop["default"] = default_value
        if isinstance(field.type, NamedType):
            warnings.append(type_loss(field.type.name))
        properties[field.name] = prop
        if not field.optional:
            required.append(field.name)

    schema["properties"] = properties
    if required:
        schema["required"] = required
    if defs:
        schema["$defs"] = defs

    path = out_dir / f"{artifact_id}.json"
    artifact = EmittedArtifact(
        target="json-schema",
        ref=f"{domain.name}.{model_name}@{version.version}",
        artifact_id=artifact_id,
        path=path,
        content=schema,
        content_hash=compute_content_hash(schema),
        warnings=warnings,
    )

    _validate_schema(artifact)
    return artifact


def _field_default(field: FieldDef) -> Any:
    if field.default is None:
        return None
    raw = field.default.strip()
    if isinstance(field.type, PrimitiveType):
        if field.type.kind == "bool":
            if raw == "true":
                return True
            if raw == "false":
                return False
        if field.type.kind in {"int"}:
            try:
                return int(raw)
            except ValueError:
                return raw
        if field.type.kind in {"float"}:
            try:
                return float(raw)
            except ValueError:
                return raw
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        return raw[1:-1]
    return raw


def _add_domain_metadata(container: dict[str, Any], domain: DomainDef) -> None:
    if domain.owner is not None:
        container["owner"] = domain.owner
    if domain.contact is not None:
        container["contact"] = domain.contact
    if domain.description is not None:
        container["description"] = domain.description


def _validate_schema(artifact: EmittedArtifact) -> None:
    try:
        Draft202012Validator.check_schema(artifact.content)
    except Exception as exc:
        artifact.warnings.append(validation_failed(str(artifact.path), str(exc)))
