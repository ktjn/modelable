from __future__ import annotations

from pathlib import PurePath
from typing import Any

from openapi_spec_validator import validate as validate_openapi

from modelable.compiler.workspace import Workspace
from modelable.emitters._schema_mapping import (
    _field_to_json_schema,
)
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.diagnostics import validation_failed
from modelable.emitters.openapi_plan import emit_openapi_projection_plan
from modelable.parser.ir import (
    ApiOperation,
    DomainDef,
    MdlFile,
    ProjectionVersion,
)
from modelable.planner.plans import build_plan_documents

_REF_BASE = "#/components/schemas/"

# Duplicated from planner/planner.py::_generated_projection_name rather than
# imported, because that symbol is private and this emitter needs only the
# five-entry suffix table, not the rest of expansion. Keep in sync if the
# planner's naming convention changes.
_AUTO_PROJECTION_SUFFIXES: dict[str, str] = {
    "db": "Db",
    "request": "Request",
    "reply": "Reply",
    "event": "Event",
}

_EMITTED_AUTO_KINDS = {"request", "reply", "event"}  # "db" excluded by default


def emit_openapi(workspace: Workspace, out_dir: PurePath) -> list[EmittedArtifact]:
    """Emit a single OpenAPI 3.1 document with `components.schemas` for every
    API-facing projection in the workspace."""
    mdl = workspace.mdl
    schemas: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    plans = {(plan["domain"], plan["projection"], plan["version"]): plan for plan in build_plan_documents(workspace)}

    for domain in sorted(mdl.domains, key=lambda item: item.name):
        kind_lookup = _projection_kind_lookup(domain)
        for projection_name in sorted(domain.projections):
            versions = domain.projections[projection_name]
            projection_kind = kind_lookup.get(projection_name)
            for version in sorted(versions, key=lambda item: item.version):
                if not _should_emit(version, projection_kind):
                    continue
                schema_id = f"{domain.name}.{projection_name}.v{version.version}"
                plan = plans[(domain.name, projection_name, version.version)]
                schema = emit_openapi_projection_plan(plan, projection_kind, schemas)
                field_warnings: list[str] = []
                schemas[schema_id] = schema
                warnings.extend(field_warnings)

    document: dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {
            "title": getattr(getattr(mdl, "workspace", None), "name", None) or "Modelable API",
            "version": "1.0.0",
        },
        "components": {"schemas": schemas},
        "paths": _emit_paths(mdl),
    }

    warnings.extend(_validate_document(document))

    artifact = EmittedArtifact(
        target="openapi",
        ref="workspace",
        artifact_id="openapi",
        path=out_dir / "openapi.json",
        content=document,
        content_hash=compute_content_hash(document),
        warnings=warnings,
    )
    return [artifact]


def _emit_paths(mdl: MdlFile) -> dict[str, dict[str, Any]]:
    paths: dict[str, dict[str, Any]] = {}
    for domain in sorted(mdl.domains, key=lambda item: item.name):
        for api in sorted(domain.apis, key=lambda item: (item.model, item.version)):
            model_versions = domain.models.get(api.model, [])
            model = next((item for item in model_versions if item.version == api.version), None)
            key_fields = {field.name: field for field in model.fields if field.is_key} if model else {}
            for operation in sorted(api.operations, key=lambda item: (item.path, item.method, item.name)):
                path_item = paths.setdefault(operation.path, {})
                operation_doc: dict[str, Any] = {
                    "operationId": operation.name,
                    "responses": {},
                    "x-modelable": {
                        "domain": domain.name,
                        "api": api.model,
                        "apiVersion": api.version,
                        "name": operation.name,
                    },
                }
                parameters = []
                for parameter_name in _path_parameters(operation):
                    field = key_fields.get(parameter_name)
                    if field is None:
                        continue
                    parameters.append(
                        {
                            "name": parameter_name,
                            "in": "path",
                            "required": True,
                            "schema": _field_to_json_schema(field, field.type, {}, [parameter_name]),
                        }
                    )
                if parameters:
                    operation_doc["parameters"] = parameters
                if operation.request is not None:
                    projection_name, version = operation.request
                    operation_doc["requestBody"] = {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": f"{_REF_BASE}{domain.name}.{projection_name}.v{version}"}
                            }
                        },
                    }
                for response in sorted(operation.responses, key=lambda item: item.status_code):
                    operation_doc["responses"][str(response.status_code)] = {
                        "description": _response_description(response.status_code),
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": f"{_REF_BASE}{domain.name}.{response.projection}.v{response.version}"
                                }
                            }
                        },
                    }
                path_item[operation.method.lower()] = operation_doc
    return {path: paths[path] for path in sorted(paths)}


def _path_parameters(operation: ApiOperation) -> list[str]:
    parameters: list[str] = []
    start = 0
    while True:
        opening = operation.path.find("{", start)
        if opening < 0:
            return parameters
        closing = operation.path.find("}", opening + 1)
        if closing < 0:
            return parameters
        parameters.append(operation.path[opening + 1 : closing])
        start = closing + 1


def _response_description(status_code: int) -> str:
    if 200 <= status_code < 300:
        return "Successful response"
    if 400 <= status_code < 500:
        return "Client error response"
    if 500 <= status_code < 600:
        return "Server error response"
    return "Response"


def _projection_kind_lookup(domain: DomainDef) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for decl in domain.auto_projections:
        for target in decl.targets:
            name = f"{decl.model}{_AUTO_PROJECTION_SUFFIXES[target.kind]}"
            lookup[name] = target.kind
    return lookup


def _should_emit(version: ProjectionVersion, kind: str | None) -> bool:
    if kind is None:
        return True  # hand-authored: always included by default (design §6.2)
    return kind in _EMITTED_AUTO_KINDS


def _validate_document(document: dict[str, Any]) -> list[str]:
    """Validate the complete emitted document against OpenAPI 3.1."""
    try:
        validate_openapi(document)
    except Exception as exc:
        return [validation_failed("openapi.json", str(exc))]
    return []
