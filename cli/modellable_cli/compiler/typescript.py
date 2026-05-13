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


def _field_ts(field_name: str, fdef: dict[str, Any]) -> str:
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

    comment_parts: list[str] = []
    if fdef.get("description"):
        comment_parts.append(fdef["description"])
    if fdef.get("classification"):
        comment_parts.append(f"classification: {fdef['classification']}")
    if fdef.get("deprecated"):
        comment_parts.append("@deprecated")

    lines: list[str] = []
    if comment_parts:
        lines.append(f"  /** {' | '.join(comment_parts)} */")
    lines.append(f"  {field_name}{optional}: {ts_type}{null_union};")
    return "\n".join(lines)


def model_to_typescript(doc: dict[str, Any]) -> str:
    """Convert a Modellable model or projection document to a TypeScript interface."""
    is_projection = "projection" in doc
    domain = doc.get("domain", "unknown")
    name = doc.get("projection") if is_projection else doc.get("model", "Unknown")
    version = doc.get("version", 1)
    kind = doc.get("kind", "Projection" if is_projection else "Model").upper()

    fqn = f"{domain}.{name}.v{version}"
    fields = doc.get("fields") or {}
    field_lines = [_field_ts(fn, fd) for fn, fd in fields.items() if isinstance(fd, dict)]

    header = f"// Modellable {kind}: {fqn}\n// Generated — do not edit by hand"
    interface_name = f"{name}V{version}"
    body = "\n".join(field_lines) if field_lines else "  // No fields defined"
    return f"{header}\nexport interface {interface_name} {{\n{body}\n}}\n"


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
