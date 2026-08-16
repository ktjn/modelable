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
