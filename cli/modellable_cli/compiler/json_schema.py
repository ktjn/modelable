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
    domain: str,
    model_name: str,
    version: int,
    field_name: str,
    fdef: dict[str, Any],
    *,
    resolved_origin: str | None = None,
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

    # Fully-qualified identity: where this field lives in the model graph
    prop["x-modellable-field"] = f"{domain}.{model_name}.v{version}.{field_name}"

    # For derived fields: where the value actually comes from
    if resolved_origin:
        prop["x-modellable-origin"] = resolved_origin
    elif "from" in fdef:
        prop["x-modellable-origin"] = fdef["from"]

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

    # Build source alias map for projections so field origins resolve to fully-qualified paths
    source_map: dict[str, dict[str, Any]] = {}
    if is_projection:
        for src in (doc.get("sources") or []):
            key = src.get("alias") or src.get("model", "")
            source_map[key] = src

    for fname, fdef in fields.items():
        if not isinstance(fdef, dict):
            continue

        resolved_origin: str | None = None
        if is_projection and "from" in fdef:
            src_ref: str = fdef["from"]
            alias, _, src_field = src_ref.partition(".")
            src_info = source_map.get(alias)
            if src_info:
                resolved_origin = (
                    f"{src_info.get('domain', '?')}."
                    f"{src_info.get('model', '?')}."
                    f"v{src_info.get('version', '?')}."
                    f"{src_field}"
                )

        properties[fname] = _field_schema(domain, name, version, fname, fdef, resolved_origin=resolved_origin)
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

    x_modellable: dict[str, Any] = {
        "kind": kind,
        "domain": domain,
        "name": name,
        "version": version,
        "fqn": f"{domain}.{name}.v{version}",
    }

    prov = doc.get("provenance")
    if prov:
        x_modellable["provenance"] = {k: v for k, v in prov.items()}

    schema["x-modellable"] = x_modellable

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
