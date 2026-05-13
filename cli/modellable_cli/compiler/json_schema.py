"""JSON Schema 2020-12 generator for Modellable model definitions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_TYPE_MAP: dict[str, dict[str, str]] = {
    "string":    {"type": "string"},
    "boolean":   {"type": "boolean"},
    "integer":   {"type": "integer"},
    "decimal":   {"type": "number"},
    "float":     {"type": "number", "format": "float"},
    "timestamp": {"type": "string", "format": "date-time"},
    "date":      {"type": "string", "format": "date"},
    "time":      {"type": "string", "format": "time"},
    "duration":  {"type": "string", "format": "duration"},
    "uuid":      {"type": "string", "format": "uuid"},
    "binary":    {"type": "string", "contentEncoding": "base64"},
    "enum":      {"type": "string"},
    "array":     {"type": "array"},
    "object":    {"type": "object"},
    "map":       {"type": "object", "additionalProperties": {}},
    "reference": {},
}


def _field_schema(
    domain: str, model_name: str, version: int, field_name: str, fdef: dict[str, Any]
) -> dict[str, Any]:
    ftype = fdef.get("type", "string")
    prop: dict[str, Any] = dict(_TYPE_MAP.get(ftype, {"type": "string"}))

    if fdef.get("format"):
        prop["format"] = fdef["format"]

    if ftype == "enum" and fdef.get("values"):
        prop["enum"] = list(fdef["values"])

    if ftype == "array" and isinstance(fdef.get("items"), dict):
        items_type = fdef["items"].get("type", "string")
        prop["items"] = dict(_TYPE_MAP.get(items_type, {"type": "string"}))

    if ftype == "reference" and fdef.get("model"):
        prop["$ref"] = f"#/$defs/{fdef['model']}"

    if fdef.get("description"):
        prop["description"] = fdef["description"]

    prop["x-modellable-field"] = f"{domain}.{model_name}.v{version}.{field_name}"

    if fdef.get("classification"):
        prop["x-modellable-classification"] = fdef["classification"]

    if fdef.get("deprecated"):
        prop["deprecated"] = True
        if fdef.get("replacedBy"):
            prop["x-modellable-replaced-by"] = fdef["replacedBy"]

    return prop


def model_to_json_schema(doc: dict[str, Any]) -> dict[str, Any]:
    """Convert a Modellable model or projection document to JSON Schema 2020-12."""
    is_projection = "projection" in doc
    domain = doc.get("domain", "unknown")
    name = doc.get("projection") if is_projection else doc.get("model", "Unknown")
    version = doc.get("version", 1)
    kind = doc.get("kind", "Projection" if is_projection else "Model")

    fields = doc.get("fields") or {}
    properties: dict[str, Any] = {}
    required: list[str] = []

    for fname, fdef in fields.items():
        if not isinstance(fdef, dict):
            continue
        properties[fname] = _field_schema(domain, name, version, fname, fdef)
        if fdef.get("required"):
            required.append(fname)

    schema: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"modellable://{domain}/{name}/v{version}",
        "title": f"{domain}.{name}.v{version}",
        "type": "object",
    }

    if doc.get("description"):
        schema["description"] = doc["description"]

    if required:
        schema["required"] = required

    if properties:
        schema["properties"] = properties

    schema["x-modellable"] = {
        "kind": kind,
        "domain": domain,
        "name": name,
        "version": version,
    }

    return schema


def write_json_schema(doc: dict[str, Any], out_dir: Path) -> Path:
    """Generate JSON Schema for doc and write to out_dir. Returns the output path."""
    is_projection = "projection" in doc
    domain = doc.get("domain", "unknown")
    name = doc.get("projection") if is_projection else doc.get("model", "unknown")
    version = doc.get("version", 1)

    schema = model_to_json_schema(doc)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{domain}.{name}.v{version}.schema.json"
    out_path.write_text(json.dumps(schema, indent=2))
    return out_path
