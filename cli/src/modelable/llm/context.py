from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from modelable.compiler.workspace import Workspace
from modelable.parser.ir import (
    ComputedMapping,
    DirectMapping,
    MdlFile,
    ProjectionField,
    ProjectionVersion,
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


def build_workspace_summary(workspace: Workspace) -> str:
    lines: list[str] = []
    for domain in workspace.mdl.domains:
        lines.append(f"domain {domain.name}")
        if domain.owner:
            lines.append(f"  owner: {domain.owner}")
        if domain.description:
            lines.append(f"  description: {domain.description}")
        for model_name, versions in domain.models.items():
            for version in versions:
                lines.append(
                    f"  {version.model_kind.value} {model_name} @ {version.version} ({version.change_kind.value})"
                )
                for field in version.fields:
                    lines.append(f"    - {field.name}: {_field_type_text(field.type)}")
        for projection_name, versions in domain.projections.items():
            for version in versions:
                lines.append(f"  projection {projection_name} @ {version.version}")
                lines.append(
                    f"    from {version.source.model} @ {_version_text(version.source.version)} as {version.source.alias}"
                )
                for field in version.fields:
                    lines.append(f"    - {field.name}")
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


def _field_type_text(field_type) -> str:
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
        return field_type.name
    return kind


def _version_text(version_spec) -> str:
    kind = getattr(version_spec, "kind", None)
    if kind == "exact":
        return str(version_spec.version)
    if kind == "range":
        return f">={version_spec.min_inclusive}<{version_spec.max_exclusive}"
    if kind == "min":
        return f">={version_spec.min_inclusive}"
    return "?"


def _projection_mapping_text(field: ProjectionField) -> str:
    mapping = field.mapping
    if isinstance(mapping, DirectMapping):
        return f"direct {mapping.source_alias}.{mapping.source_field}"
    if isinstance(mapping, ComputedMapping):
        return f"computed {mapping.expression}"
    return "unknown"

