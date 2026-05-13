"""Markdown documentation generator for Modellable model definitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def model_to_markdown(doc: dict[str, Any]) -> str:
    """Convert a Modellable model or projection document to a Markdown data dictionary."""
    is_projection = "projection" in doc
    domain = doc.get("domain", "unknown")
    name = doc.get("projection") if is_projection else doc.get("model", "Unknown")
    version = doc.get("version", 1)
    doc_type = "Projection" if is_projection else "Model"
    fqn = f"{domain}.{name}.v{version}"

    lines: list[str] = [f"# {fqn}", ""]

    meta: list[str] = [f"**Type:** {doc_type}"]
    if doc.get("kind"):
        meta.append(f"**Kind:** {doc['kind']}")
    if doc.get("status"):
        meta.append(f"**Status:** `{doc['status']}`")
    meta.append(f"**Domain:** {domain}")
    lines.extend(meta)

    if doc.get("description"):
        lines.extend(["", doc["description"]])

    # Provenance — present on derived kinds (read_model, cache, replica)
    prov = doc.get("provenance")
    if prov:
        lines.extend(["", "## Provenance", ""])
        lines.append("This model derives its data from an external source. Its values should never be treated as an independent truth.")
        lines.append("")
        if prov.get("sourceModel"):
            lines.append(f"| Property | Value |")
            lines.append(f"|---|---|")
            lines.append(f"| Source Model | `{prov['sourceModel']}` |")
            if prov.get("via"):
                lines.append(f"| Transport | `{prov['via']}` |")
            if prov.get("system"):
                lines.append(f"| Owning System | `{prov['system']}` |")
            if prov.get("syncStrategy"):
                lines.append(f"| Sync Strategy | `{prov['syncStrategy']}` |")
            if prov.get("ttlSeconds"):
                lines.append(f"| TTL (seconds) | `{prov['ttlSeconds']}` |")
            if prov.get("cacheKey"):
                lines.append(f"| Cache Key | `{prov['cacheKey']}` |")
        elif prov.get("sourceSystem"):
            lines.append(f"| Property | Value |")
            lines.append(f"|---|---|")
            lines.append(f"| Source System | `{prov['sourceSystem']}` |")
            if prov.get("via"):
                lines.append(f"| Transport | `{prov['via']}` |")
            if prov.get("system"):
                lines.append(f"| Owning System | `{prov['system']}` |")
            if prov.get("syncStrategy"):
                lines.append(f"| Sync Strategy | `{prov['syncStrategy']}` |")
            if prov.get("syncIntervalMinutes"):
                lines.append(f"| Sync Interval | `{prov['syncIntervalMinutes']} minutes` |")

    # Sources (projections only)
    sources = doc.get("sources") or []
    if sources:
        lines.extend(["", "## Sources", ""])
        for src in sources:
            alias = src.get("alias", "")
            alias_part = f" as `{alias}`" if alias else ""
            lines.append(
                f"- `{src.get('domain', '?')}.{src.get('model', '?')}.v{src.get('version', '?')}`{alias_part}"
            )

    # Fields table
    fields = doc.get("fields") or {}
    if fields:
        lines.extend([
            "",
            "## Fields",
            "",
            "| Field | Type | Required | Classification | Description |",
            "|---|---|:---:|---|---|",
        ])
        for fname, fdef in fields.items():
            if not isinstance(fdef, dict):
                continue
            ftype = fdef.get("type", "—")
            if ftype == "enum" and fdef.get("values"):
                ftype = f"enum ({', '.join(str(v) for v in fdef['values'])})"
            required = "yes" if fdef.get("required") else "—"
            cls = fdef.get("classification", "—")
            desc = fdef.get("description", "—")
            lines.append(f"| `{fname}` | {ftype} | {required} | {cls} | {desc} |")

    # Lineage (projections only)
    if is_projection and fields:
        lines.extend(["", "## Lineage", ""])
        source_map = {
            src.get("alias", src.get("model")): src for src in sources
        }
        has_entry = False
        for fname, fdef in fields.items():
            if not isinstance(fdef, dict):
                continue
            if "from" in fdef:
                src_ref: str = fdef["from"]
                alias, _, src_field = src_ref.partition(".")
                src_info = source_map.get(alias)
                if src_info:
                    full_src = (
                        f"{src_info.get('domain','?')}."
                        f"{src_info.get('model','?')}."
                        f"v{src_info.get('version','?')}."
                        f"{src_field}"
                    )
                else:
                    full_src = src_ref
                lines.append(f"- `{fname}` ← `{full_src}`")
                has_entry = True
            elif "expression" in fdef:
                lines.append(f"- `{fname}` = `{fdef['expression']}` *(computed)*")
                has_entry = True
        if not has_entry:
            lines.append("No lineage declared.")

    return "\n".join(lines) + "\n"


def write_markdown(doc: dict[str, Any], out_dir: Path) -> Path:
    """Generate Markdown docs for doc and write to out_dir. Returns the output path."""
    is_projection = "projection" in doc
    domain = doc.get("domain", "unknown")
    name = doc.get("projection") if is_projection else doc.get("model", "unknown")
    version = doc.get("version", 1)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{domain}.{name}.v{version}.md"
    out_path.write_text(model_to_markdown(doc))
    return out_path
