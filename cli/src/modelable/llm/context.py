from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from modelable.compiler.workspace import Workspace
from modelable.parser.ir import (
    ComputedMapping,
    DirectMapping,
    ProjectionField,
    VersionMin,
    VersionPinned,
    VersionRange,
    VersionSpec,
)


@dataclass(frozen=True)
class ModelRef:
    domain: str
    name: str
    version: int


def parse_model_ref(ref: str) -> ModelRef:
    if "@" not in ref or "." not in ref:
        raise ValueError("REF must be in the form domain.Model@version")
    model_ref, version_text = ref.rsplit("@", 1)
    domain, name = model_ref.split(".", 1)
    return ModelRef(domain=domain, name=name, version=int(version_text))


def parse_model_ref_version_spec(ref: str) -> tuple[str, str, VersionSpec | int]:
    if "@" not in ref or "." not in ref:
        raise ValueError("REF must be in the form domain.Model@version")
    model_ref, version_text = ref.rsplit("@", 1)
    domain, name = model_ref.split(".", 1)
    return domain, name, _parse_version_spec(version_text)


def build_workspace_summary(workspace: Workspace, focused_ref: str | None = None) -> str:
    lines: list[str] = []
    # If a focused ref is provided, we use a compact summary for everything else to save tokens.
    is_compact = focused_ref is not None

    for domain in workspace.mdl.domains:
        lines.append(f"domain {domain.name}")
        if domain.owner:
            lines.append(f"  owner: {domain.owner}")
        if domain.description:
            lines.append(f"  description: {domain.description}")

        # If focused_ref is a domain name, we show all fields in that domain.
        is_focused_domain = focused_ref == domain.name

        for model_name, model_versions in domain.models.items():
            for m_version in model_versions:
                ref = f"{domain.name}.{model_name}@{m_version.version}"
                lines.append(
                    f"  {m_version.model_kind.value} {model_name} @ {m_version.version} ({m_version.change_kind.value})"
                )
                if not is_compact or is_focused_domain or ref == focused_ref:
                    for m_field in m_version.fields:
                        lines.append(f"    - {m_field.name}: {_field_type_text(m_field.type)}")
                else:
                    lines.append(f"    - ... ({len(m_version.fields)} fields)")
        for projection_name, projection_versions in domain.projections.items():
            for p_version in projection_versions:
                ref = f"{domain.name}.{projection_name}@{p_version.version}"
                lines.append(f"  projection {projection_name} @ {p_version.version}")
                if not is_compact or is_focused_domain or ref == focused_ref:
                    lines.append(
                        f"    from {p_version.source.model} @ {_version_text(p_version.source.version)} as {p_version.source.alias}"
                    )
                    for p_field in p_version.fields:
                        lines.append(f"    - {p_field.name}")
                else:
                    lines.append(f"    - ... ({len(p_version.fields)} fields)")
    return "\n".join(lines)


def build_model_summary(workspace: Workspace, ref: str) -> str:
    model_ref = parse_model_ref(ref)
    domain = next((d for d in workspace.mdl.domains if d.name == model_ref.domain), None)
    if domain is None:
        return f"Unknown domain: {model_ref.domain}"
    versions = domain.models.get(model_ref.name)
    if not versions:
        return f"Unknown model: {model_ref.domain}.{model_ref.name}"
    version = next((item for item in versions if item.version == model_ref.version), None)
    if version is None:
        return f"Unknown model version: {ref}"

    lines = [f"{model_ref.domain}.{model_ref.name}@{version.version}"]
    lines.append(f"kind: {version.model_kind.value}")
    lines.append(f"change: {version.change_kind.value}")
    if domain.owner:
        lines.append(f"owner: {domain.owner}")
    if domain.description:
        lines.append(f"description: {domain.description}")
    for field in version.fields:
        flags = []
        if field.is_key:
            flags.append("key")
        if field.is_pii:
            flags.append("pii")
        if field.classification:
            flags.append(f"classification={field.classification.value}")
        suffix = f" [{', '.join(flags)}]" if flags else ""
        lines.append(f"- {field.name}: {_field_type_text(field.type)}{suffix}")
    return "\n".join(lines)


def build_projection_summary(workspace: Workspace, ref: str) -> str:
    model_ref = parse_model_ref(ref)
    domain = next((d for d in workspace.mdl.domains if d.name == model_ref.domain), None)
    if domain is None:
        return f"Unknown domain: {model_ref.domain}"
    versions = domain.projections.get(model_ref.name)
    if not versions:
        return f"Unknown projection: {model_ref.domain}.{model_ref.name}"
    version = next((item for item in versions if item.version == model_ref.version), None)
    if version is None:
        return f"Unknown projection version: {ref}"

    lines = [f"{model_ref.domain}.{model_ref.name}@{version.version}"]
    lines.append(f"source: {version.source.model} @ {_version_text(version.source.version)} as {version.source.alias}")
    if version.joins:
        for join in version.joins:
            lines.append(f"join: {join.model} @ {_version_text(join.version)} as {join.alias} on {join.on}")
    if version.group_by:
        lines.append(f"group by: {', '.join(version.group_by)}")
    for field in version.fields:
        lines.append(f"- {field.name}: {_projection_mapping_text(field)}")
    return "\n".join(lines)


def _field_type_text(field_type: Any) -> str:
    kind = getattr(field_type, "kind", None)
    if kind is None:
        return "unknown"
    if kind == "decimal":
        return f"decimal({field_type.precision}, {field_type.scale})"
    if kind == "array":
        return f"array<{_field_type_text(field_type.item)}>"
    if kind == "map":
        return f"map<{_field_type_text(field_type.key)}, {_field_type_text(field_type.value)}>"
    if kind == "ref":
        return f"ref<{field_type.target}>"
    if kind == "enum":
        return f"enum({', '.join(field_type.values)})"
    if kind == "object":
        return "object"
    if kind == "named":
        return str(field_type.name)
    return str(kind)


def _version_text(version_spec: Any) -> str:
    kind = getattr(version_spec, "kind", None)
    if kind == "exact":
        return str(version_spec.version)
    if kind == "range":
        return f">={version_spec.min_inclusive}<{version_spec.max_exclusive}"
    if kind == "min":
        return f">={version_spec.min_inclusive}"
    if isinstance(version_spec, VersionPinned):
        return f"{version_spec.version}#{version_spec.content_hash}"
    return "?"


def _projection_mapping_text(field: ProjectionField) -> str:
    mapping = field.mapping
    if isinstance(mapping, DirectMapping):
        return f"direct {mapping.source_alias}.{mapping.source_field}"
    if isinstance(mapping, ComputedMapping):
        return f"computed {mapping.expression}"
    return "unknown"


_VERSION_RANGE_RE = re.compile(r"^>=\s*(\d+)\s*<\s*(\d+)$")
_VERSION_MIN_RE = re.compile(r"^>=\s*(\d+)$")


def _parse_version_spec(version_text: str) -> VersionSpec | int:
    try:
        return int(version_text)
    except ValueError:
        pass

    pinned_match = re.match(r"^(\d+)\#([0-9a-fA-F]+)$", version_text)
    if pinned_match:
        return VersionPinned(
            version=int(pinned_match.group(1)),
            content_hash=pinned_match.group(2),
        )

    range_match = _VERSION_RANGE_RE.match(version_text)
    if range_match:
        return VersionRange(
            min_inclusive=int(range_match.group(1)),
            max_exclusive=int(range_match.group(2)),
        )

    min_match = _VERSION_MIN_RE.match(version_text)
    if min_match:
        return VersionMin(min_inclusive=int(min_match.group(1)))

    raise ValueError("version must be an integer or version range like >=1<3")
