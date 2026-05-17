from __future__ import annotations

from dataclasses import dataclass, field

from modelable.compat.diff import FieldChange, compare_model_versions
from modelable.parser.ir import ChangeKind, MdlFile, ModelVersion


@dataclass(frozen=True)
class CompatibilityReport:
    domain_name: str
    model_name: str
    from_version: int
    to_version: int
    status: str
    findings: list[str] = field(default_factory=list)
    changes: list[FieldChange] = field(default_factory=list)


def check_model_version_compatibility(
    mdl: MdlFile,
    domain_name: str,
    model_name: str,
    from_version: int,
    to_version: int,
) -> CompatibilityReport:
    """Compare two published versions and classify the change set."""
    old_version = _find_version(mdl, domain_name, model_name, from_version)
    new_version = _find_version(mdl, domain_name, model_name, to_version)
    changes = compare_model_versions(old_version, new_version)
    findings = [_format_finding(change) for change in changes]
    status = "breaking" if _has_breaking_change(changes, new_version) else "compatible"
    return CompatibilityReport(
        domain_name=domain_name,
        model_name=model_name,
        from_version=from_version,
        to_version=to_version,
        status=status,
        findings=findings,
        changes=changes,
    )


def _find_version(
    mdl: MdlFile,
    domain_name: str,
    model_name: str,
    version: int,
) -> ModelVersion:
    for domain in mdl.domains:
        if domain.name != domain_name:
            continue
        versions = domain.models.get(model_name, [])
        for candidate in versions:
            if candidate.version == version:
                return candidate
        break
    raise LookupError(f"unknown model version {domain_name}.{model_name}@{version}")


def _format_finding(change: FieldChange) -> str:
    if change.kind == "renamed_field":
        return f"renamed_field {change.field_name} -> {change.replacement}"
    if change.kind == "nullability_changed":
        return (
            f"nullability_changed {change.field_name}: "
            f"{_bool_word(change.from_optional)} -> {_bool_word(change.to_optional)}"
        )
    if change.kind == "identity_changed":
        return f"identity_changed {change.field_name}"
    if change.kind == "enum_changed":
        return f"enum_changed {change.field_name}"
    if change.kind == "type_changed":
        return f"type_changed {change.field_name}"
    if change.kind == "removed_field":
        return f"removed_field {change.field_name}"
    if change.kind == "added_field":
        return f"added_field {change.field_name}"
    return f"{change.kind} {change.field_name}"


def _bool_word(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "optional" if value else "required"


def _has_breaking_change(changes: list[FieldChange], new_version: ModelVersion) -> bool:
    for change in changes:
        if change.kind in {"removed_field", "renamed_field", "type_changed", "enum_changed", "identity_changed"}:
            return True
        if change.kind == "added_field" and change.to_optional is False:
            return True
    return new_version.change_kind == ChangeKind.breaking
