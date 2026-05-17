from __future__ import annotations

from dataclasses import dataclass, asdict

from modelable.expressions.cel import extract_field_refs, parse_cel
from modelable.parser.ir import (
    AccessBlock,
    AccessGrant,
    ClassificationLevel,
    ComputedMapping,
    DirectMapping,
    FieldDef,
    MdlFile,
    ModelVersion,
    ProjectionField,
    ProjectionVersion,
    RefType,
)
from modelable.registry.resolver import resolve_model_ref


@dataclass(frozen=True)
class GovernanceFinding:
    code: str
    subject: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def build_projection_governance_findings(
    domain_name: str,
    projection_name: str,
    pv: ProjectionVersion,
    mdl: MdlFile,
) -> list[GovernanceFinding]:
    findings: list[GovernanceFinding] = []
    subject = f"{domain_name}.{projection_name}@{pv.version}"

    _check_projection_access(subject, domain_name, pv.access, findings)
    _check_computed_field_access(subject, domain_name, pv, mdl, findings)
    _check_projection_classification(subject, pv, mdl, findings)

    return findings


def _check_projection_access(
    subject: str,
    domain_name: str,
    access: AccessBlock | None,
    findings: list[GovernanceFinding],
) -> None:
    if access is None:
        findings.append(
            GovernanceFinding(
                code="missing_project_grant",
                subject=subject,
                message=f"{subject} has no documented project grant",
            )
        )
        findings.append(
            GovernanceFinding(
                code="missing_read_grant",
                subject=subject,
                message=f"{subject} has no documented read grant",
            )
        )
        return

    if not _has_entity_permission(access, "project"):
        findings.append(
            GovernanceFinding(
                code="missing_project_grant",
                subject=subject,
                message=f"{subject} has no documented project grant for domain '{domain_name}'",
            )
        )

    if not _has_entity_permission(access, "read"):
        findings.append(
            GovernanceFinding(
                code="missing_read_grant",
                subject=subject,
                message=f"{subject} has no documented read grant for domain '{domain_name}'",
            )
        )


def _check_computed_field_access(
    subject: str,
    projection_domain: str,
    pv: ProjectionVersion,
    mdl: MdlFile,
    findings: list[GovernanceFinding],
) -> None:
    resolved_sources = _build_resolved_sources(pv, mdl)

    for proj_field, source_refs in _iter_projection_field_sources(pv, resolved_sources):
        if not isinstance(proj_field.mapping, ComputedMapping):
            continue

        for target_ref, target_version, field_name in source_refs:
            if not _has_property_derivation(target_version.access, field_name, projection_domain):
                findings.append(
                    GovernanceFinding(
                        code="missing_derivation_policy",
                        subject=subject,
                        message=(
                            f"{subject}.{proj_field.name} uses source field "
                            f"{target_ref}.{field_name} without documented derivation policy"
                        ),
                    )
                )


def _check_projection_classification(
    subject: str,
    pv: ProjectionVersion,
    mdl: MdlFile,
    findings: list[GovernanceFinding],
) -> None:
    resolved_sources = _build_resolved_sources(pv, mdl)

    for proj_field, source_refs in _iter_projection_field_sources(pv, resolved_sources):
        for target_ref, target_version, field_name in source_refs:
            source_field = _find_field(target_version, field_name)
            if source_field is None:
                continue

            _check_pii_preservation(subject, proj_field, target_ref, source_field, findings)
            _check_classification_preservation(
                subject, proj_field, target_ref, source_field, findings
            )


def _has_entity_permission(access: AccessBlock, permission: str) -> bool:
    return any(permission in grant.permissions for grant in access.entity)


def _has_property_derivation(
    access: AccessBlock | None,
    field_name: str,
    projection_domain: str,
) -> bool:
    if access is None:
        return False

    grants = access.properties.get(field_name, [])
    for grant in grants:
        if grant.principal != projection_domain:
            continue
        if "read" in grant.permissions and "derive" in grant.permissions:
            return True
    return False


def _iter_projection_field_sources(
    pv: ProjectionVersion,
    resolved_sources: dict[str, tuple[str, ModelVersion]],
) -> list[tuple[ProjectionField, list[tuple[str, ModelVersion, str]]]]:
    result: list[tuple[ProjectionField, list[tuple[str, ModelVersion, str]]]] = []
    for proj_field in pv.fields:
        source_refs: list[tuple[str, ModelVersion, str]] = []
        mapping = proj_field.mapping

        if isinstance(mapping, DirectMapping):
            target = resolved_sources.get(mapping.source_alias)
            if target is not None:
                target_ref, target_version = target
                source_refs.append((target_ref, target_version, mapping.source_field))
        elif isinstance(mapping, ComputedMapping):
            expr_ast, _ = parse_cel(mapping.expression)
            if expr_ast is not None:
                for alias, field_name in extract_field_refs(expr_ast):
                    target = resolved_sources.get(alias)
                    if target is None:
                        continue
                    target_ref, target_version = target
                    source_refs.append((target_ref, target_version, field_name))

        result.append((proj_field, source_refs))

    return result


def _check_pii_preservation(
    subject: str,
    proj_field: ProjectionField,
    source_ref: str,
    source_field: FieldDef,
    findings: list[GovernanceFinding],
) -> None:
    if not source_field.is_pii or proj_field.is_pii:
        return

    findings.append(
        GovernanceFinding(
            code="missing_pii_metadata",
            subject=subject,
            message=(
                f"{subject}.{proj_field.name} projects {source_ref}.{source_field.name} "
                "without preserving @pii metadata"
            ),
        )
    )


def _check_classification_preservation(
    subject: str,
    proj_field: ProjectionField,
    source_ref: str,
    source_field: FieldDef,
    findings: list[GovernanceFinding],
) -> None:
    source_level = source_field.classification
    if source_level is None:
        return

    projected_level = proj_field.classification
    if projected_level is None:
        findings.append(
            GovernanceFinding(
                code="missing_classification_metadata",
                subject=subject,
                message=(
                    f"{subject}.{proj_field.name} projects {source_ref}.{source_field.name} "
                    "without preserving classification metadata"
                ),
            )
        )
        return

    if _classification_rank(projected_level) < _classification_rank(source_level):
        findings.append(
            GovernanceFinding(
                code="lowered_classification",
                subject=subject,
                message=(
                    f"{subject}.{proj_field.name} lowers classification from "
                    f"{source_level.value} to {projected_level.value}"
                ),
            )
        )


def _classification_rank(level: ClassificationLevel) -> int:
    order = {
        ClassificationLevel.open: 0,
        ClassificationLevel.internal: 1,
        ClassificationLevel.confidential: 2,
        ClassificationLevel.restricted: 3,
        ClassificationLevel.secret: 4,
    }
    return order[level]


def _find_field(version: ModelVersion, field_name: str) -> FieldDef | None:
    return next((field for field in version.fields if field.name == field_name), None)


def _build_resolved_sources(
    pv: ProjectionVersion, mdl: MdlFile
) -> dict[str, tuple[str, ModelVersion]]:
    resolved_sources: dict[str, tuple[str, ModelVersion]] = {}
    all_sources = [(pv.source.model, pv.source.version, pv.source.alias)]
    for join in pv.joins:
        all_sources.append((join.model, join.version, join.alias))

    for model_ref, version_spec, alias in all_sources:
        try:
            resolved = resolve_model_ref(mdl, model_ref, version_spec)
            resolved_sources[alias] = (f"{model_ref}@{resolved.version.version}", resolved.version)
        except LookupError:
            pass

    return resolved_sources
