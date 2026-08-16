from __future__ import annotations

from pathlib import PurePath
from typing import Any

from jsonschema import Draft202012Validator

from modelable.compiler.workspace import Workspace
from modelable.emitters._schema_mapping import (
    _field_to_json_schema,
    _resolve_projection_field_type,
)
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.diagnostics import validation_failed
from modelable.governance.por import build_por_reference
from modelable.parser.ir import (
    ApiOperation,
    DomainDef,
    MdlFile,
    ProjectionVersion,
    VersionExact,
    VersionMin,
    VersionPinned,
    VersionRange,
    VersionSpec,
)

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

    for domain in mdl.domains:
        kind_lookup = _projection_kind_lookup(domain)
        for projection_name, versions in domain.projections.items():
            projection_kind = kind_lookup.get(projection_name)
            for version in versions:
                if not _should_emit(version, projection_kind):
                    continue
                schema_id, schema, field_warnings = _projection_to_schema(
                    domain, projection_name, version, projection_kind, mdl, schemas
                )
                schemas[schema_id] = schema
                warnings.extend(field_warnings)

    document: dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {
            "title": getattr(getattr(mdl, "workspace", None), "name", None) or "Modelable API",
            "version": "1.0.0",
        },
        "components": {"schemas": schemas},
        "paths": _emit_paths(mdl, schemas),
    }

    warnings.extend(_validate_schemas(schemas))

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


def _emit_paths(mdl: MdlFile, schemas: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    paths: dict[str, dict[str, Any]] = {}
    for domain in mdl.domains:
        for api in domain.apis:
            model_versions = domain.models.get(api.model, [])
            model = next((item for item in model_versions if item.version == api.version), None)
            key_fields = {field.name: field for field in model.fields if field.is_key} if model else {}
            for operation in api.operations:
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


def _projection_to_schema(
    domain: DomainDef,
    projection_name: str,
    version: ProjectionVersion,
    projection_kind: str | None,
    mdl: MdlFile,
    defs: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any], list[str]]:
    """Build a components.schemas entry for one projection version, reusing
    _field_to_json_schema/_resolve_projection_field_type from
    _schema_mapping.py. Mirrors json_schema.py::_emit_projection_version's
    schema shape (title, x-modelable, x-modelable-por, properties/required),
    with two differences: `x-modelable.kind` is the specific
    request/reply/event kind (falling back to "projection" for
    hand-authored projections) instead of json_schema.py's hardcoded
    "projection", and nested NamedType/ObjectType sub-schemas are written
    into `defs` (a view onto the same `schemas` dict emit_openapi is
    building) so they become sibling components.schemas entries instead of
    a separate $defs block.
    """
    warnings: list[str] = []
    properties: dict[str, Any] = {}
    required: list[str] = []
    for field in version.fields:
        field_type = _resolve_projection_field_type(field, version, mdl)
        properties[field.name] = _field_to_json_schema(
            field, field_type, defs, [field.name], mdl=mdl, ref_base=_REF_BASE
        )
        required.append(field.name)  # projection fields have no `?` syntax yet

    schema = {
        "type": "object",
        "title": projection_name,
        "x-modelable": {
            "domain": domain.name,
            "name": projection_name,
            "kind": projection_kind or "projection",
            "sourceEntity": f"{version.source.model}@{_version_label(version.source.version)}",
            "version": version.version,
        },
        "x-modelable-por": build_por_reference(f"{domain.name}.{projection_name}.v{version.version}"),
        "properties": properties,
        "required": required,
    }
    schema_id = f"{domain.name}.{projection_name}.v{version.version}"
    return schema_id, schema, warnings


def _version_label(version_spec: VersionSpec) -> str:
    if isinstance(version_spec, VersionExact):
        return str(version_spec.version)
    if isinstance(version_spec, VersionRange):
        return f">={version_spec.min_inclusive}<{version_spec.max_exclusive}"
    if isinstance(version_spec, VersionMin):
        return f">={version_spec.min_inclusive}"
    if isinstance(version_spec, VersionPinned):
        return f"{version_spec.version}#{version_spec.content_hash}"
    return "?"


def _validate_schemas(schemas: dict[str, dict[str, Any]]) -> list[str]:
    fragment: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": schemas,
    }
    try:
        Draft202012Validator.check_schema(fragment)
    except Exception as exc:
        return [validation_failed("openapi.json", str(exc))]
    return []
