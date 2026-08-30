from __future__ import annotations

import dataclasses
import re
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
from modelable.compat.enums import compare_enum_projections, compare_semantic_enum_versions, describe_enum_change
from modelable.dependency_graph import build_projection_dependencies, resolve_projection_aliases
from modelable.parser.ir import (
    ApiDecl,
    ApiOperation,
    EnumProjectionDecl,
    IndexDecl,
    MdlFile,
    ModelVersion,
    ProjectionVersion,
    SemanticTypeDecl,
)
from modelable.registry.resolver import find_dependents, resolve_enum_type_ref


@dataclass(frozen=True)
class CompatibilityReport:
    domain_name: str
    model_name: str
    from_version: int
    to_version: int
    status: str
    findings: list[str] = field(default_factory=list)
    changes: list[FieldChange] = field(default_factory=list)
    semantic_changes: list[FieldChange] = field(default_factory=list)
    storage_changes: list[FieldChange] = field(default_factory=list)


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


@dataclass(frozen=True)
class ApiChange:
    kind: str
    subject: str
    breaking: bool
    message: str


@dataclass(frozen=True)
class ApiCompatibilityReport:
    domain_name: str
    model_name: str
    from_version: int
    to_version: int
    status: str
    findings: list[str] = field(default_factory=list)
    changes: list[ApiChange] = field(default_factory=list)


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
    semantic_changes = compare_model_versions(old_version, new_version)
    old_index = _find_index_decl(mdl, domain_name, model_name, from_version)
    new_index = _find_index_decl(mdl, domain_name, model_name, to_version)
    storage_changes = compare_index_decls(old_index, new_index)
    semantic_changes = _refine_enum_version_changes(mdl, semantic_changes, from_model_domain=domain_name)
    changes = [*semantic_changes, *storage_changes]
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
        semantic_changes=semantic_changes,
        storage_changes=storage_changes,
    )


def _refine_enum_version_changes(
    mdl: MdlFile,
    changes: list[FieldChange],
    *,
    from_model_domain: str,
) -> list[FieldChange]:
    """Classify enum version bumps through the referenced declaration diff.

    An ``enum_version_changed`` field change is non-breaking when the
    referenced declaration diff only adds members (with an exhaustive-consumer
    note), and breaking with member detail when members were removed. This is
    possible only here, where the workspace is available for exact resolution —
    the structural diff alone cannot see declaration content (evolution plan
    E5, item 4).
    """
    refined: list[FieldChange] = []
    for change in changes:
        if (
            change.kind not in {"enum_version_changed", "enum_reference_changed"}
            or not change.from_type
            or not change.to_type
        ):
            refined.append(change)
            continue

        def _parse_ref(text: str) -> tuple[str, int] | None:
            if " @ " not in text:
                return None
            name, _, version_text = text.rpartition(" @ ")
            try:
                return name, int(version_text)
            except ValueError:
                return None

        old_ref = _parse_ref(change.from_type)
        new_ref = _parse_ref(change.to_type)
        if old_ref is None or new_ref is None:
            refined.append(change)
            continue

        try:
            _old_domain, old_decl = resolve_enum_type_ref(mdl, from_model_domain, old_ref[0], old_ref[1])
            _new_domain, new_decl = resolve_enum_type_ref(mdl, from_model_domain, new_ref[0], new_ref[1])
        except LookupError:
            refined.append(change)
            continue

        if isinstance(old_decl, EnumProjectionDecl) and isinstance(new_decl, EnumProjectionDecl):
            if old_ref[0] != new_ref[0]:
                refined.append(change)
                continue
            enum_changes = compare_enum_projections(_old_domain, old_decl, new_decl)
        elif isinstance(old_decl, SemanticTypeDecl) and isinstance(new_decl, SemanticTypeDecl):
            if old_ref[0] != new_ref[0]:
                refined.append(change)
                continue
            enum_changes = compare_semantic_enum_versions(old_decl, new_decl)
        else:
            refined.append(
                dataclasses.replace(
                    change,
                    breaking_override=True,
                    note="nominal enum declaration changed between a semantic enum and an enum projection",
                )
            )
            continue
        notes = [describe_enum_change(item) for item in enum_changes]
        breaking = any(item.breaking for item in enum_changes)
        note = "; ".join(notes) if notes else "member sets are identical"
        refined.append(dataclasses.replace(change, breaking_override=breaking, note=note))
    return refined


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


def check_api_version_compatibility(
    mdl: MdlFile,
    domain_name: str,
    model_name: str,
    from_version: int,
    to_version: int,
) -> ApiCompatibilityReport:
    """Compare versioned API operations without serializing them to OpenAPI."""
    old_api = _find_api(mdl, domain_name, model_name, from_version)
    new_api = _find_api(mdl, domain_name, model_name, to_version)
    changes = _compare_api_operations(mdl, domain_name, old_api, new_api)
    findings = [change.message for change in changes]
    return ApiCompatibilityReport(
        domain_name=domain_name,
        model_name=model_name,
        from_version=from_version,
        to_version=to_version,
        status="breaking" if any(change.breaking for change in changes) else "compatible",
        findings=findings,
        changes=changes,
    )


def _compare_api_operations(
    mdl: MdlFile,
    domain_name: str,
    old_api: ApiDecl,
    new_api: ApiDecl,
) -> list[ApiChange]:
    changes: list[ApiChange] = []
    old_operations = {operation.name: operation for operation in old_api.operations}
    new_operations = {operation.name: operation for operation in new_api.operations}

    removed = {name: operation for name, operation in old_operations.items() if name not in new_operations}
    added = {name: operation for name, operation in new_operations.items() if name not in old_operations}
    for old_name, old_operation in sorted(removed.items()):
        renamed = next(
            (
                (new_name, new_operation)
                for new_name, new_operation in added.items()
                if _operation_signature(new_operation) == _operation_signature(old_operation)
            ),
            None,
        )
        if renamed is not None:
            new_name, _ = renamed
            del added[new_name]
            changes.append(
                ApiChange(
                    "operation_renamed",
                    old_name,
                    True,
                    f"operation '{old_name}' renamed to '{new_name}'",
                )
            )
        else:
            changes.append(ApiChange("operation_removed", old_name, True, f"operation '{old_name}' removed"))

    for name in sorted(added):
        changes.append(ApiChange("operation_added", name, False, f"operation '{name}' added"))

    for name in sorted(set(old_operations) & set(new_operations)):
        changes.extend(
            _compare_operation(
                mdl,
                domain_name,
                old_api.model,
                old_api.version,
                new_api.version,
                old_operations[name],
                new_operations[name],
            )
        )
    return changes


def _compare_operation(
    mdl: MdlFile,
    domain_name: str,
    model_name: str,
    old_api_version: int,
    new_api_version: int,
    old: ApiOperation,
    new: ApiOperation,
) -> list[ApiChange]:
    changes: list[ApiChange] = []
    if old.method != new.method:
        changes.append(ApiChange("method_changed", old.name, True, f"operation '{old.name}' method changed"))
    if old.path != new.path:
        changes.append(ApiChange("path_changed", old.name, True, f"operation '{old.name}' path changed"))
        if set(_path_parameters(old.path)) != set(_path_parameters(new.path)):
            changes.append(
                ApiChange(
                    "path_key_renamed",
                    old.name,
                    True,
                    f"operation '{old.name}' path key changed",
                )
            )
    changes.extend(
        _compare_path_key_types(
            mdl,
            domain_name,
            model_name,
            old_api_version,
            new_api_version,
            old,
            new,
        )
    )
    changes.extend(_compare_request(mdl, domain_name, old, new))
    changes.extend(_compare_responses(mdl, domain_name, old, new))
    return changes


def _compare_path_key_types(
    mdl: MdlFile,
    domain_name: str,
    model_name: str,
    old_api_version: int,
    new_api_version: int,
    old_operation: ApiOperation,
    new_operation: ApiOperation,
) -> list[ApiChange]:
    if old_operation.path != new_operation.path:
        return []
    try:
        old_model = _find_version(mdl, domain_name, model_name, old_api_version)
        new_model = _find_version(mdl, domain_name, model_name, new_api_version)
    except LookupError:
        return []
    old_fields = {field.name: field for field in old_model.fields if field.is_key}
    new_fields = {field.name: field for field in new_model.fields if field.is_key}
    changes = []
    for name in sorted(set(_path_parameters(old_operation.path)) & set(_path_parameters(new_operation.path))):
        old_field = old_fields.get(name)
        new_field = new_fields.get(name)
        if old_field is not None and new_field is not None and old_field.type != new_field.type:
            changes.append(
                ApiChange(
                    "path_key_type_changed",
                    old_operation.name,
                    True,
                    f"operation '{old_operation.name}' path key '{name}' type changed",
                )
            )
    return changes


def _compare_request(
    mdl: MdlFile,
    domain_name: str,
    old: ApiOperation,
    new: ApiOperation,
) -> list[ApiChange]:
    if old.request == new.request:
        return []
    if old.request is None or new.request is None:
        return [ApiChange("request_changed", old.name, True, f"operation '{old.name}' request projection changed")]
    old_name, old_version = old.request
    new_name, new_version = new.request
    if old_name != new_name:
        return [ApiChange("request_changed", old.name, True, f"operation '{old.name}' request projection changed")]
    report = check_projection_version_compatibility(mdl, domain_name, old_name, old_version, new_version)
    return [
        ApiChange(
            "request_changed",
            old.name,
            report.status == "breaking",
            f"operation '{old.name}' request projection changed ({report.status})",
        )
    ]


def _compare_responses(
    mdl: MdlFile,
    domain_name: str,
    old: ApiOperation,
    new: ApiOperation,
) -> list[ApiChange]:
    old_responses = {response.status_code: response for response in old.responses}
    new_responses = {response.status_code: response for response in new.responses}
    changes: list[ApiChange] = []
    for status_code in sorted(set(old_responses) - set(new_responses)):
        changes.append(
            ApiChange(
                "response_removed",
                old.name,
                True,
                f"operation '{old.name}' response {status_code} removed",
            )
        )
    for status_code in sorted(set(new_responses) - set(old_responses)):
        changes.append(
            ApiChange(
                "response_added",
                old.name,
                False,
                f"operation '{old.name}' response {status_code} added",
            )
        )
    for status_code in sorted(set(old_responses) & set(new_responses)):
        old_response = old_responses[status_code]
        new_response = new_responses[status_code]
        if (old_response.projection, old_response.version) == (new_response.projection, new_response.version):
            continue
        if old_response.projection != new_response.projection:
            status = "breaking"
        else:
            report = check_projection_version_compatibility(
                mdl,
                domain_name,
                old_response.projection,
                old_response.version,
                new_response.version,
            )
            status = report.status
        changes.append(
            ApiChange(
                "response_changed",
                old.name,
                status == "breaking",
                f"operation '{old.name}' response {status_code} changed ({status})",
            )
        )
    return changes


def _operation_signature(operation: ApiOperation) -> tuple[str, str]:
    return operation.method, operation.path


def _path_parameters(path: str) -> tuple[str, ...]:
    return tuple(re.findall(r"\{([^{}]+)\}", path))


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


def _find_api(mdl: MdlFile, domain_name: str, model_name: str, version: int) -> ApiDecl:
    for domain in mdl.domains:
        if domain.name != domain_name:
            continue
        for api in domain.apis:
            if api.model == model_name and api.version == version:
                return api
        break
    raise LookupError(f"unknown API version {domain_name}.{model_name}@{version}")


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
