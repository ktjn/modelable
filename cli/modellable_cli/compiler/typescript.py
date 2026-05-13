"""TypeScript interface generator for Modellable model definitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

_TS_TYPE_MAP: dict[str, str] = {
    "string":    "string",
    "boolean":   "boolean",
    "integer":   "number",
    "decimal":   "number",
    "float":     "number",
    "timestamp": "string",
    "date":      "string",
    "time":      "string",
    "duration":  "string",
    "uuid":      "string",
    "binary":    "Uint8Array",
    "enum":      "string",
    "array":     "unknown[]",
    "object":    "Record<string, unknown>",
    "map":       "Record<string, unknown>",
    "reference": "unknown",
}


def _field_ts(
    field_name: str,
    fdef: dict[str, Any],
    *,
    fqn: str | None = None,
    resolved_origin: str | None = None,
) -> str:
    ftype = fdef.get("type", "string")
    ts_type = _TS_TYPE_MAP.get(ftype, "unknown")

    if ftype == "enum" and fdef.get("values"):
        ts_type = " | ".join(f'"{v}"' for v in fdef["values"])
    elif ftype == "array" and isinstance(fdef.get("items"), dict):
        items_type = fdef["items"].get("type", "string")
        ts_type = f"{_TS_TYPE_MAP.get(items_type, 'unknown')}[]"
    elif ftype == "reference" and fdef.get("model"):
        ts_type = fdef["model"]

    required = fdef.get("required", False)
    nullable = fdef.get("nullable", False)
    optional = "" if required else "?"
    null_union = " | null" if nullable else ""

    jsdoc_tags: list[str] = []
    if fdef.get("description"):
        jsdoc_tags.append(fdef["description"])
    if fqn:
        jsdoc_tags.append(f"@field {fqn}")
    if resolved_origin:
        jsdoc_tags.append(f"@origin {resolved_origin}")
    elif "from" in fdef:
        jsdoc_tags.append(f"@origin {fdef['from']}")
    if fdef.get("classification"):
        jsdoc_tags.append(f"@classification {fdef['classification']}")
    if fdef.get("deprecated"):
        jsdoc_tags.append("@deprecated")

    lines: list[str] = []
    if jsdoc_tags:
        if len(jsdoc_tags) == 1 and not any(t.startswith("@") for t in jsdoc_tags):
            lines.append(f"  /** {jsdoc_tags[0]} */")
        else:
            lines.append("  /**")
            for tag in jsdoc_tags:
                lines.append(f"   * {tag}")
            lines.append("   */")
    lines.append(f"  {field_name}{optional}: {ts_type}{null_union};")
    return "\n".join(lines)


def model_to_typescript(doc: dict[str, Any]) -> str:
    """Convert a Modellable model or projection document to a TypeScript interface."""
    is_projection = "projection" in doc
    domain = doc.get("domain", "unknown")
    name = doc.get("projection") if is_projection else doc.get("model", "Unknown")
    version = doc.get("version", 1)
    kind = doc.get("kind", "Projection" if is_projection else "Model")

    fqn = f"{domain}.{name}.v{version}"
    fields = doc.get("fields") or {}

    # Build source alias map for projections
    source_map: dict[str, dict[str, Any]] = {}
    if is_projection:
        for src in (doc.get("sources") or []):
            key = src.get("alias") or src.get("model", "")
            source_map[key] = src

    field_lines: list[str] = []
    for fname, fdef in fields.items():
        if not isinstance(fdef, dict):
            continue
        field_fqn = f"{fqn}.{fname}"
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
        field_lines.append(_field_ts(fname, fdef, fqn=field_fqn, resolved_origin=resolved_origin))

    # Build interface JSDoc header
    jsdoc_lines = [f" * @modellable {kind}"]
    jsdoc_lines.append(f" * @fqn {fqn}")
    if doc.get("description"):
        jsdoc_lines.insert(0, f" * {doc['description']}")
        jsdoc_lines.insert(1, " *")
    prov = doc.get("provenance")
    if prov:
        if prov.get("sourceModel"):
            jsdoc_lines.append(f" * @sourceModel {prov['sourceModel']}")
        if prov.get("sourceSystem"):
            jsdoc_lines.append(f" * @sourceSystem {prov['sourceSystem']}")
        if prov.get("via"):
            jsdoc_lines.append(f" * @via {prov['via']}")
        if prov.get("system"):
            jsdoc_lines.append(f" * @system {prov['system']}")
        if prov.get("ttlSeconds"):
            jsdoc_lines.append(f" * @ttlSeconds {prov['ttlSeconds']}")
        if prov.get("syncStrategy"):
            jsdoc_lines.append(f" * @syncStrategy {prov['syncStrategy']}")

    jsdoc = "/**\n" + "\n".join(jsdoc_lines) + "\n */\n"
    generated_comment = "// Generated — do not edit by hand\n"
    interface_name = f"{name}V{version}"
    body = "\n".join(field_lines) if field_lines else "  // No fields defined"
    return f"{generated_comment}{jsdoc}export interface {interface_name} {{\n{body}\n}}\n"


def write_typescript(doc: dict[str, Any], out_dir: Path) -> Path:
    """Generate TypeScript interface for doc and write to out_dir. Returns the output path."""
    is_projection = "projection" in doc
    domain = doc.get("domain", "unknown")
    name = doc.get("projection") if is_projection else doc.get("model", "unknown")
    version = doc.get("version", 1)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{domain}.{name}.v{version}.d.ts"
    out_path.write_text(model_to_typescript(doc))
    return out_path
