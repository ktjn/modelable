from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import yaml


def parse_openapi_document(source_text: str) -> dict[str, Any]:
    """Parse and minimally validate an OpenAPI 3 or Swagger document."""
    try:
        document = json.loads(source_text)
    except json.JSONDecodeError:
        document = yaml.safe_load(source_text)
    if not isinstance(document, dict):
        raise ValueError("OpenAPI document must be a JSON or YAML object")
    if not isinstance(document.get("openapi"), str) and not isinstance(document.get("swagger"), str):
        raise ValueError("OpenAPI document must declare 'openapi' or 'swagger'")
    return document


def iter_component_schemas(document: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield every reusable component schema in stable name order."""
    components = document.get("components") or {}
    if not isinstance(components, dict):
        raise ValueError("OpenAPI 'components' must be an object")
    schemas = components.get("schemas") or {}
    if not isinstance(schemas, dict):
        raise ValueError("OpenAPI 'components.schemas' must be an object")
    for name in sorted(schemas):
        schema = schemas[name]
        if not isinstance(schema, dict):
            raise ValueError(f"OpenAPI component schema '{name}' must be an object")
        yield str(name), schema


def openapi_loss_warnings(document: dict[str, Any]) -> list[str]:
    """Describe OpenAPI API metadata not represented by the current import IR."""
    warnings: list[str] = []
    paths = document.get("paths") or {}
    if isinstance(paths, dict) and paths:
        warnings.append("OpenAPI import drops unsupported operation metadata under 'paths'")
        methods = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
        path_item_metadata = {
            "$ref": "path-item references",
            "summary": "path-item summaries",
            "description": "path-item descriptions",
            "servers": "path-item servers",
            "parameters": "path-item parameters",
        }
        operation_metadata = {
            "tags": "operation tags",
            "summary": "operation summaries",
            "description": "operation descriptions",
            "externalDocs": "operation external documentation",
            "operationId": "operation identifiers",
            "callbacks": "operation callbacks",
            "deprecated": "operation deprecation metadata",
            "servers": "operation servers",
            "security": "operation security",
            "parameters": "operation parameters",
            "requestBody": "request body",
            "responses": "response bindings",
        }
        for path, path_item in sorted(paths.items()):
            if not isinstance(path_item, dict):
                continue
            path_location = f"paths.{path}"
            for key, label in path_item_metadata.items():
                if _is_present(path_item.get(key)):
                    warnings.append(f"OpenAPI import drops unsupported {label} at {path_location}")
            for method, operation in sorted(path_item.items()):
                if method.lower() not in methods or not isinstance(operation, dict):
                    continue
                location = f"paths.{path}.{method}"
                for key, label in operation_metadata.items():
                    if _is_present(operation.get(key)):
                        warnings.append(f"OpenAPI import drops unsupported {label} at {location}")
    for key, label in (
        ("security", "root security requirements"),
        ("servers", "root servers"),
        ("tags", "root tags"),
        ("externalDocs", "root external documentation"),
        ("webhooks", "webhooks"),
    ):
        if _is_present(document.get(key)):
            warnings.append(f"OpenAPI import drops unsupported {label}")
    components = document.get("components") or {}
    if not isinstance(components, dict):
        return warnings
    for key in ("parameters", "responses", "requestBodies", "headers", "examples", "links", "callbacks", "pathItems"):
        if _is_present(components.get(key)):
            warnings.append(f"OpenAPI import drops unsupported components.{key}")
    if _is_present(components.get("securitySchemes")):
        warnings.append("OpenAPI import drops unsupported components.securitySchemes")
    return warnings


def _is_present(value: Any) -> bool:
    return value is not None and value != {} and value != []
