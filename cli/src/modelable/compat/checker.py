from __future__ import annotations

from dataclasses import dataclass, field

from modelable.compat.diff import (
    FieldChange,
    ProjectionChange,
    compare_index_decls,
    compare_model_versions,
    compare_projection_versions,
    describe_field_change,
    is_field_change_breaking,
)
from modelable.dependency_graph import build_projection_dependencies, resolve_projection_aliases
from modelable.parser.ir import IndexDecl, MdlFile, ModelVersion, ProjectionVersion
from modelable.registry.resolver import find_dependents


@dataclass(frozen=True)
class CompatibilityReport:
    domain_name: str
    model_name: str
    from_version: int
    to_version: int
    status: str
    findings: list[str] = field(default_factory=list)
    changes: list[FieldChange] = field(default_factory=list)


@dataclass(frozen=True)
class ProjectionImpact:
    domain_name: str
    projection_name: str
    version: int
    status: str  # "broken", "affected", "compatible"
    reason: str | None = None


@dataclass(frozen=True)
class ProjectionCompatibilityReport:
    domain_name: str
    projection_name: str
    from_version: int
    to_version: int
    status: str
    findings: list[str] = field(default_factory=list)
    changes: list[ProjectionChange] = field(default_factory=list)


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
    old_index = _find_index_decl(mdl, domain_name, model_name, from_version)
    new_index = _find_index_decl(mdl, domain_name, model_name, to_version)
    changes.extend(compare_index_decls(old_index, new_index))
    findings = [describe_field_change(change) for change in changes]
    status = "breaking" if _has_breaking_change(changes) else "compatible"
    return CompatibilityReport(
        domain_name=domain_name,
        model_name=model_name,
        from_version=from_version,
        to_version=to_version,
        status=status,
        findings=findings,
        changes=changes,
    )


def check_projection_version_compatibility(
    mdl: MdlFile,
    domain_name: str,
    projection_name: str,
    from_version: int,
    to_version: int,
) -> ProjectionCompatibilityReport:
    """Compare two published versions of the same projection and classify the change set."""
    old_version = _find_projection_version(mdl, domain_name, projection_name, from_version)
    new_version = _find_projection_version(mdl, domain_name, projection_name, to_version)

    _require_all_aliases_resolve(mdl, old_version)
    _require_all_aliases_resolve(mdl, new_version)

    changes = compare_projection_versions(mdl, old_version, new_version)
    changes.extend(_compare_source_version(mdl, old_version, new_version))

    findings = [_format_projection_finding(change) for change in changes]
    status = "breaking" if any(change.breaking for change in changes) else "compatible"
    return ProjectionCompatibilityReport(
        domain_name=domain_name,
        projection_name=projection_name,
        from_version=from_version,
        to_version=to_version,
        status=status,
        findings=findings,
        changes=changes,
    )


def _require_all_aliases_resolve(mdl: MdlFile, projection: ProjectionVersion) -> None:
    resolved = resolve_projection_aliases(projection, mdl)
    declared_aliases = {projection.source.alias, *(join.alias for join in projection.joins)}
    missing = declared_aliases - set(resolved)
    if missing:
        alias = sorted(missing)[0]
        raise LookupError(f"unresolved source reference for alias '{alias}'")


def _compare_source_version(
    mdl: MdlFile,
    old: ProjectionVersion,
    new: ProjectionVersion,
) -> list[ProjectionChange]:
    changes: list[ProjectionChange] = []
    old_aliases = resolve_projection_aliases(old, mdl)
    new_aliases = resolve_projection_aliases(new, mdl)

    for alias in sorted(set(old_aliases) & set(new_aliases)):
        old_resolved = old_aliases[alias]
        new_resolved = new_aliases[alias]
        if old_resolved.model_name != new_resolved.model_name:
            continue  # different source entirely; the shape/lineage dimensions already cover this
        if old_resolved.version.version == new_resolved.version.version:
            continue

        model_report = check_model_version_compatibility(
            mdl,
            old_resolved.domain_name,
            old_resolved.model_name,
            old_resolved.version.version,
            new_resolved.version.version,
        )
        changes.append(
            ProjectionChange(
                dimension="source_version",
                kind="source_version_changed",
                breaking=model_report.status == "breaking",
                field_name=alias,
                message=(
                    f"source '{alias}' moved from {old_resolved.model_name}@{old_resolved.version.version} "
                    f"to {new_resolved.version.version} ({model_report.status})"
                ),
            )
        )

    return changes


def _find_projection_version(
    mdl: MdlFile,
    domain_name: str,
    projection_name: str,
    version: int,
) -> ProjectionVersion:
    for domain in mdl.domains:
        if domain.name != domain_name:
            continue
        versions = domain.projections.get(projection_name, [])
        for candidate in versions:
            if candidate.version == version:
                return candidate
        break
    raise LookupError(f"unknown projection version {domain_name}.{projection_name}@{version}")


def _format_projection_finding(change: ProjectionChange) -> str:
    subject = change.field_name or "-"
    return f"{change.kind} {subject} ({change.dimension}): {change.message}"


def analyze_impact(
    mdl: MdlFile,
    report: CompatibilityReport,
    dependent: tuple[str, str, int],
) -> ProjectionImpact:
    """Analyze the impact of a model change on a specific downstream projection."""
    dep_domain_name, dep_proj_name, dep_version = dependent

    # Find the projection version
    pv = None
    for domain in mdl.domains:
        if domain.name == dep_domain_name:
            pv = next(
                (v for v in domain.projections.get(dep_proj_name, []) if v.version == dep_version),
                None,
            )
            break

    if pv is None:
        return ProjectionImpact(dep_domain_name, dep_proj_name, dep_version, "affected", "unresolved projection")

    source_model_ref = f"{report.domain_name}.{report.model_name}"
    dependencies = build_projection_dependencies(mdl, dep_domain_name, dep_proj_name, pv)
    dependency_source_fields = {
        dependency.source_property
        for dependency in dependencies
        if dependency.source_ref.rsplit("@", 1)[0] == source_model_ref
    }

    # Check if any breaking field change affects a property this projection depends on,
    # through any mapping kind (direct, computed, join predicate, filter, or group key).
    impacted_fields = []
    for change in report.changes:
        is_breaking_field = change.kind in {
            "removed_field",
            "renamed_field",
            "type_changed",
            "enum_changed",
            "identity_changed",
        }
        if change.kind == "added_field" and change.to_optional is False:
            is_breaking_field = True

        if not is_breaking_field:
            continue

        if change.field_name in dependency_source_fields:
            impacted_fields.append(f"field '{change.field_name}' ({change.kind})")

    if impacted_fields:
        return ProjectionImpact(
            dep_domain_name,
            dep_proj_name,
            dep_version,
            "broken",
            f"uses {', '.join(impacted_fields)}",
        )

    if report.status == "breaking":
        return ProjectionImpact(
            dep_domain_name,
            dep_proj_name,
            dep_version,
            "affected",
            f"source {source_model_ref} is marked breaking",
        )

    return ProjectionImpact(dep_domain_name, dep_proj_name, dep_version, "compatible")


def find_projection_dependents(mdl: MdlFile, ref: str) -> list[tuple[str, str, int]]:
    """Return projections that resolve to the exact model version in ``ref``."""
    model_ref, version_text = ref.rsplit("@", 1)
    domain_name, model_name = model_ref.split(".", 1)
    version = int(version_text)
    return sorted(find_dependents(mdl, domain_name, model_name, version))


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


def _find_index_decl(
    mdl: MdlFile,
    domain_name: str,
    model_name: str,
    version: int,
) -> IndexDecl | None:
    for domain in mdl.domains:
        if domain.name != domain_name:
            continue
        return next(
            (decl for decl in domain.index_decls if decl.model == model_name and decl.version == version),
            None,
        )
    return None


def _has_breaking_change(changes: list[FieldChange]) -> bool:
    return any(is_field_change_breaking(change) for change in changes)
