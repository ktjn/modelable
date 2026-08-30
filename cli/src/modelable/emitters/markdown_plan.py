"""Markdown projection emission from validated ``modelable.plan/v0`` documents."""

from __future__ import annotations

from pathlib import Path

from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.planner.protocol import PlanDocument, validate_plan


def emit_markdown_projection_plan(
    plan: PlanDocument,
    out_dir: Path,
    *,
    domain_owner: str | None = None,
    domain_contact: str | None = None,
    domain_description: str | None = None,
) -> EmittedArtifact:
    """Build one Markdown projection document from a validated plan."""
    document = validate_plan(plan)
    domain = _string(document, "domain")
    projection = _string(document, "projection")
    version = _integer(document, "version")
    source = _mapping(document, "source")
    source_model = _string(source, "model")
    source_version = _version_label(_mapping(source, "version"))
    source_alias = _string(source, "alias")

    lines = [
        f"# {projection} v{version}",
        "",
        f"**Domain:** {domain}  ",
        f"**Name:** {projection}  ",
        f"**Version:** {version}  ",
        f"**Artifact ID:** {domain}.{projection}.v{version}  ",
        f"**Artifact:** {domain}.{projection}.v{version}.md  ",
    ]
    if domain_owner:
        lines.append(f"**Owner:** {domain_owner}  ")
    if domain_contact:
        lines.append(f"**Contact:** {domain_contact}  ")
    if domain_description:
        lines.append(f"**Description:** {domain_description}  ")
    lines.extend(
        [
            "**Kind:** projection  ",
            f"**Auto generated:** {'yes' if _bool(document, 'auto_generated') else 'no'}  ",
            f"**Source:** {source_model} @ {source_version} as {source_alias}  ",
        ]
    )
    where = document.get("where")
    if isinstance(where, str) and where:
        lines.append(f"**Where:** {where}  ")
    group_by = _list(document, "group_by")
    if group_by:
        lines.append(f"**Group by:** {', '.join(_string_value(item) for item in group_by)}  ")
    lines.extend(
        [
            "",
            "## Sources",
            "",
            "| Model | Version | Alias |",
            "|---|---|---|",
            f"| {source_model} | {source_version} | {source_alias} |",
        ]
    )
    for join_value in _list(document, "joins"):
        join = _mapping_value(join_value, "join")
        lines.append(
            f"| {_string(join, 'model')} | {_version_label(_mapping(join, 'version'))} | "
            f"{_string(join, 'alias')} (join on `{_string(join, 'on')}`) |"
        )
    lines.extend(["", "## Fields", "", "| Field | Lineage | Annotations | Classification |", "|---|---|---|---|"])
    for field_value in _list(document, "fields"):
        field = _mapping_value(field_value, "field")
        kind = _string(field, "kind")
        if kind == "direct":
            lineage = f"direct: {_string(field, 'source_alias')}.{_string(field, 'source_field')} ({source_model})"
        else:
            expression = _string(field, "expression").replace("|", "\\|")
            lineage = f"computed: `{expression}`"
        annotations = _format_annotations(field.get("annotations"))
        classification = field.get("classification")
        classification_text = classification if isinstance(classification, str) else "—"
        lines.append(f"| {_string(field, 'name')} | {lineage} | {annotations} | {classification_text} |")
    lines.append("")
    text = "\n".join(lines)
    artifact_id = f"{domain}.{projection}.v{version}"
    return EmittedArtifact(
        target="markdown",
        ref=f"{domain}.{projection}@{version}",
        artifact_id=artifact_id,
        path=out_dir / f"{artifact_id}.md",
        content=text,
        content_hash=compute_content_hash(text),
    )


def _format_annotations(value: object) -> str:
    if not isinstance(value, list):
        return "—"
    parts: list[str] = []
    for annotation in value:
        if isinstance(annotation, dict):
            part = _annotation_text(annotation)
            if part is not None:
                parts.append(part)
    return ", ".join(parts) if parts else "—"


def _annotation_text(annotation: dict[str, object]) -> str | None:
    kind = annotation.get("kind")
    if kind == "pii":
        return "@pii"
    if kind == "server":
        return "@server"
    if kind == "deprecated":
        return f"@deprecated → {annotation.get('replaced_by')}"
    if kind == "owner":
        return f"@owner({annotation.get('team')})"
    if kind == "wire":
        targets = annotation.get("targets")
        if not isinstance(targets, dict):
            return None
        options: list[str] = []
        for target in sorted(targets):
            hint = targets[target]
            if not isinstance(hint, dict):
                continue
            if isinstance(hint.get("encoding"), str):
                options.append(f'{target}: "{hint["encoding"]}"')
            if isinstance(hint.get("type"), str):
                options.append(f'{target}.type: "{hint["type"]}"')
            if isinstance(hint.get("case"), str):
                options.append(f'{target}.case: "{hint["case"]}"')
            overrides = hint.get("overrides")
            if isinstance(overrides, dict) and overrides:
                rendered = ", ".join(f'{key}: "{overrides[key]}"' for key in sorted(overrides))
                options.append(f"{target}.overrides: {{ {rendered} }}")
            if isinstance(hint.get("field_case"), str):
                options.append(f'{target}.fieldCase: "{hint["field_case"]}"')
        return f"@wire({', '.join(options)})" if options else None
    return None


def _version_label(version: dict[str, object]) -> str:
    kind = _string(version, "kind")
    if kind in {"exact", "pinned"}:
        label = str(_integer(version, "version"))
        return f"{label}#{_string(version, 'contentHash')}" if kind == "pinned" else label
    if kind == "range":
        return f">={_integer(version, 'minInclusive')}<{_integer(version, 'maxExclusive')}"
    return f">={_integer(version, 'minInclusive')}"


def _mapping(mapping: dict[str, object], name: str) -> dict[str, object]:
    return _mapping_value(mapping.get(name), name)


def _mapping_value(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"plan {name} must be an object")
    return value


def _list(mapping: dict[str, object], name: str) -> list[object]:
    value = mapping.get(name)
    if not isinstance(value, list):
        raise ValueError(f"plan {name} must be an array")
    return value


def _string(mapping: dict[str, object], name: str) -> str:
    value = mapping.get(name)
    if not isinstance(value, str):
        raise ValueError(f"plan {name} must be a string")
    return value


def _string_value(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("plan list must contain strings")
    return value


def _integer(mapping: dict[str, object], name: str) -> int:
    value = mapping.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"plan {name} must be an integer")
    return value


def _bool(mapping: dict[str, object], name: str) -> bool:
    value = mapping.get(name)
    if not isinstance(value, bool):
        raise ValueError(f"plan {name} must be a boolean")
    return value
