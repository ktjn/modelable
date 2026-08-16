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
        for path, path_item in sorted(paths.items()):
            if not isinstance(path_item, dict):
                continue
            for method, operation in sorted(path_item.items()):
                if method.lower() not in methods or not isinstance(operation, dict):
                    continue
                location = f"paths.{path}.{method}"
                if operation.get("security") is not None:
                    warnings.append(f"OpenAPI import drops unsupported operation security at {location}")
                if operation.get("parameters"):
                    warnings.append(f"OpenAPI import drops unsupported operation parameters at {location}")
                if operation.get("requestBody") is not None:
                    warnings.append(f"OpenAPI import drops unsupported request body at {location}")
                if operation.get("responses"):
                    warnings.append(f"OpenAPI import drops unsupported response bindings at {location}")
    if document.get("security") is not None:
        warnings.append("OpenAPI import drops unsupported root security requirements")
    security_schemes = (document.get("components") or {}).get("securitySchemes")
    if security_schemes:
        warnings.append("OpenAPI import drops unsupported components.securitySchemes")
    return warnings
