from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from modelable.compat.diff import FieldChange, ProjectionChange, describe_field_change, is_field_change_breaking
from modelable.emitters.base import EmittedArtifact

PASSING_STATUSES = {"wire_compatible", "read_compatible"}

# The common target-compatibility axis/severity IR (Slice C3). Every
# comparator in this module — the pre-existing protobuf/gRPC wire guards and
# the source/storage/projection-rebuild/governance additions below — returns
# TargetCompatibilityReport/TargetCompatibilityFinding through this one
# vocabulary, so a consumer (CLI, LSP, a future policy layer) never has to
# special-case which target produced a report.
AXES = (
    "source_compatibility",
    "wire_compatibility",
    "storage_migration",
    "projection_rebuild",
    "governance_review",
)

SEVERITIES = ("compatible", "review_required", "migration_required", "breaking")
_SEVERITY_RANK = {name: rank for rank, name in enumerate(SEVERITIES)}

# Legacy protobuf/gRPC status vocabulary preserved for CLI/output backward
# compatibility (see ROADMAP.md Slice C3 "Preserve
# existing CLI behaviour during migration"), mapped onto the four generic
# severities so reports from every axis can be ranked and merged uniformly.
_STATUS_TO_SEVERITY = {
    "wire_compatible": "compatible",
    "read_compatible": "compatible",
    "requires_read_rebuild": "migration_required",
    "breaking": "breaking",
    "compatible": "compatible",
    "review_required": "review_required",
    "migration_required": "migration_required",
}


@dataclass(frozen=True)
class TargetCompatibilityFinding:
    code: str
    status: str
    ref: str
    message: str
    axis: str = "wire_compatibility"
    severity: str = "breaking"
    field: str | None = None
    index: str | None = None


@dataclass(frozen=True)
class TargetCompatibilityReport:
    target: str
    status: str
    severity: str
    findings: list[TargetCompatibilityFinding]


def compare_protobuf_manifests(
    old_artifacts: list[EmittedArtifact],
    new_artifacts: list[EmittedArtifact],
) -> TargetCompatibilityReport:
    """Compare emitted protobuf schema manifests for wire compatibility."""
    findings: list[TargetCompatibilityFinding] = []
    old_schemas = _schema_entries(old_artifacts)
    new_schemas = _schema_entries(new_artifacts)

    for ref in sorted(set(old_schemas) | set(new_schemas)):
        old_schema = old_schemas.get(ref)
        new_schema = new_schemas.get(ref)
        if old_schema is None:
            continue
        if new_schema is None:
            findings.append(
                _finding(
                    "schema_removed",
                    "breaking",
                    ref,
                    "schema was removed from the protobuf manifest",
                )
            )
            continue
        findings.extend(_compare_schema(ref, old_schema, new_schema))

    status, severity = _worst(findings, default_status="wire_compatible")
    return TargetCompatibilityReport(target="protobuf", status=status, severity=severity, findings=findings)


def compare_grpc_artifacts(
    old_artifacts: list[EmittedArtifact],
    new_artifacts: list[EmittedArtifact],
) -> TargetCompatibilityReport:
    """Compare emitted gRPC service manifests for read-model compatibility."""
    findings: list[TargetCompatibilityFinding] = []
    old_services = _service_entries(old_artifacts)
    new_services = _service_entries(new_artifacts)

    for ref in sorted(set(old_services) | set(new_services)):
        old_service = old_services.get(ref)
        new_service = new_services.get(ref)
        if old_service is None:
            continue
        if new_service is None:
            findings.append(
                _finding(
                    "service_removed",
                    "breaking",
                    ref,
                    "gRPC service manifest was removed",
                )
            )
            continue
        findings.extend(_compare_service(ref, old_service, new_service))

    status, severity = _worst(findings, default_status="read_compatible")
    return TargetCompatibilityReport(target="grpc", status=status, severity=severity, findings=findings)


def compare_source_representation(
    domain_name: str,
    model_name: str,
    changes: list[FieldChange],
    *,
    target: str = "source",
) -> TargetCompatibilityReport:
    """Fold general model-version field changes into the common IR.

    This is also the JSON Schema representation-compatibility axis: JSON
    Schema emission adds no wire-format constraints (field numbers, enum
    ordinals) beyond the shared model contract, so a JSON-representation
    check is exactly a source_compatibility check — there is no separate
    JSON-specific diff to write.
    """
    findings = [
        _finding(
            change.kind,
            "breaking" if is_field_change_breaking(change) else "compatible",
            f"{domain_name}.{model_name}",
            describe_field_change(change),
            axis="source_compatibility",
            field=change.field_name,
        )
        for change in changes
    ]
    status, severity = _worst(findings, default_status="compatible")
    return TargetCompatibilityReport(target=target, status=status, severity=severity, findings=findings)


def compare_storage_migration(
    domain_name: str,
    model_name: str,
    index_changes: list[FieldChange],
) -> TargetCompatibilityReport:
    """Fold index-declaration changes (compat/diff.py::compare_index_decls) into
    the common IR. A changed index always needs a storage migration (rebuilding
    the index), independent of whether the surrounding model version is
    otherwise source-compatible.
    """
    findings = [
        _finding(
            "index_changed",
            "migration_required",
            f"{domain_name}.{model_name}",
            f"index '{change.field_name}' changed and requires a storage migration",
            axis="storage_migration",
            field=change.field_name,
        )
        for change in index_changes
    ]
    status, severity = _worst(findings, default_status="compatible")
    return TargetCompatibilityReport(target="sql", status=status, severity=severity, findings=findings)


def compare_projection_rebuild(
    domain_name: str,
    projection_name: str,
    changes: list[ProjectionChange],
) -> TargetCompatibilityReport:
    """Surface projection changes that require rebuilding a materialized or
    stored copy, independent of whether they break the projection's contract.

    Draws from compare_projection_versions()'s storage dimension (where/
    group_by/join changes, already breaking) and lineage dimension (remapped
    sources, changed computed expressions, currently non-breaking) — reused
    rather than re-derived. An expression-only change is exactly the case
    that is compatible today (breaking=False on the lineage dimension) but
    still needs a rebuild, which is what this axis makes visible.
    """
    findings = []
    for change in changes:
        if change.dimension not in {"storage", "lineage"}:
            continue
        status = "breaking" if change.breaking else "migration_required"
        findings.append(
            _finding(
                change.kind,
                status,
                f"{domain_name}.{projection_name}",
                change.message,
                axis="projection_rebuild",
                field=change.field_name,
            )
        )
    status, severity = _worst(findings, default_status="compatible")
    return TargetCompatibilityReport(target="projection-rebuild", status=status, severity=severity, findings=findings)


def compare_governance_review(
    domain_name: str,
    projection_name: str,
    changes: list[ProjectionChange],
) -> TargetCompatibilityReport:
    """Surface projection governance changes (access grants, PII, classification)
    as review-worthy findings, reusing compare_projection_versions()'s governance
    dimension rather than re-deriving access/classification diffs. A governance
    change that isn't outright breaking (e.g. a grant added, classification
    loosened) still warrants human review, which is what `review_required`
    (as opposed to `compatible`) makes visible.
    """
    findings = []
    for change in changes:
        if change.dimension != "governance":
            continue
        status = "breaking" if change.breaking else "review_required"
        findings.append(
            _finding(
                change.kind,
                status,
                f"{domain_name}.{projection_name}",
                change.message,
                axis="governance_review",
                field=change.field_name,
            )
        )
    status, severity = _worst(findings, default_status="compatible")
    return TargetCompatibilityReport(target="governance-review", status=status, severity=severity, findings=findings)


def _schema_entries(artifacts: list[EmittedArtifact]) -> dict[str, dict[str, Any]]:
    schemas: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        if artifact.path.name != "schema-manifest.json" or not isinstance(artifact.content, str):
            continue
        manifest = json.loads(artifact.content)
        for schema in manifest.get("schemas", []):
            if isinstance(schema, dict) and isinstance(schema.get("ref"), str):
                schemas[str(schema["ref"])] = schema
    return schemas


def _service_entries(artifacts: list[EmittedArtifact]) -> dict[str, dict[str, Any]]:
    services: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        if artifact.path.name != "service-manifest.json" or not isinstance(artifact.content, str):
            continue
        manifest = json.loads(artifact.content)
        ref = manifest.get("ref")
        if isinstance(ref, str):
            services[ref] = manifest
    return services


def _compare_schema(
    ref: str, old_schema: dict[str, Any], new_schema: dict[str, Any]
) -> list[TargetCompatibilityFinding]:
    findings: list[TargetCompatibilityFinding] = []
    old_fields = _fields_by_number(old_schema)
    new_fields = _fields_by_number(new_schema)
    new_field_names = _fields_by_proto_name(new_schema)
    reserved_numbers, reserved_names = _reservations(new_schema)

    for number in sorted(set(old_fields) | set(new_fields)):
        old_field = old_fields.get(number)
        new_field = new_fields.get(number)
        if old_field is None or new_field is None:
            continue
        findings.extend(_compare_field(ref, number, old_field, new_field))

    for number, old_field in sorted(old_fields.items()):
        if number in new_fields:
            continue
        old_proto_name = _string_value(old_field.get("proto_name"))
        old_source_name = _string_value(old_field.get("name"))
        if number in reserved_numbers and (old_proto_name in reserved_names or old_source_name in reserved_names):
            continue
        findings.append(
            _finding(
                "removed_field_not_reserved",
                "breaking",
                ref,
                f"removed field {old_proto_name or number!s} must reserve protobuf number and name",
                field=old_proto_name,
            )
        )

    for proto_name, old_field in _fields_by_proto_name(old_schema).items():
        new_field = new_field_names.get(proto_name)
        if new_field is None:
            continue
        old_number = _int_value(old_field.get("number"))
        new_number = _int_value(new_field.get("number"))
        if old_number is not None and new_number is not None and old_number != new_number:
            findings.append(
                _finding(
                    "field_number_reused",
                    "breaking",
                    ref,
                    f"field {proto_name} moved from protobuf number {old_number} to {new_number}",
                    field=proto_name,
                )
            )

    return findings


def _compare_field(
    ref: str,
    number: int,
    old_field: dict[str, Any],
    new_field: dict[str, Any],
) -> list[TargetCompatibilityFinding]:
    findings: list[TargetCompatibilityFinding] = []
    old_name = _string_value(old_field.get("proto_name"))
    new_name = _string_value(new_field.get("proto_name"))
    field_name = old_name or new_name
    if old_name != new_name:
        findings.append(
            _finding(
                "field_number_reused",
                "breaking",
                ref,
                f"protobuf number {number} changed from {old_name!s} to {new_name!s}",
                field=field_name,
            )
        )

    old_type = _string_value(old_field.get("type"))
    new_type = _string_value(new_field.get("type"))
    if old_type != new_type:
        findings.append(
            _finding(
                "field_type_changed",
                "breaking",
                ref,
                f"field {field_name or number!s} changed protobuf type from {old_type!s} to {new_type!s}",
                field=field_name,
            )
        )

    old_enum_values = _string_list(old_field.get("enum_values"))
    new_enum_values = _string_list(new_field.get("enum_values"))
    if old_enum_values != new_enum_values:
        findings.append(
            _finding(
                "enum_value_reused",
                "breaking",
                ref,
                f"field {field_name or number!s} changed inline enum ordinal assignments",
                field=field_name,
            )
        )

    return findings


def _compare_service(
    ref: str, old_service: dict[str, Any], new_service: dict[str, Any]
) -> list[TargetCompatibilityFinding]:
    findings: list[TargetCompatibilityFinding] = []
    old_indexes = _indexes_by_name(old_service)
    new_indexes = _indexes_by_name(new_service)
    for name in sorted(set(old_indexes) | set(new_indexes)):
        if old_indexes.get(name) == new_indexes.get(name):
            continue
        findings.append(
            _finding(
                "read_index_changed",
                "requires_read_rebuild",
                ref,
                f"read index {name} changed and requires read-model rebuild",
                index=name,
            )
        )
    return findings


def _fields_by_number(schema: dict[str, Any]) -> dict[int, dict[str, Any]]:
    fields: dict[int, dict[str, Any]] = {}
    for field in schema.get("fields", []):
        if not isinstance(field, dict):
            continue
        number = _int_value(field.get("number"))
        if number is not None:
            fields[number] = field
    return fields


def _fields_by_proto_name(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {}
    for field in schema.get("fields", []):
        if not isinstance(field, dict):
            continue
        proto_name = _string_value(field.get("proto_name"))
        if proto_name is not None:
            fields[proto_name] = field
    return fields


def _reservations(schema: dict[str, Any]) -> tuple[set[int], set[str]]:
    reservations = schema.get("reservations")
    if not isinstance(reservations, dict):
        return set(), set()
    return set(_int_list(reservations.get("numbers"))), set(_string_list(reservations.get("names")))


def _indexes_by_name(service: dict[str, Any]) -> dict[str, dict[str, Any]]:
    indexes: dict[str, dict[str, Any]] = {}
    for index in service.get("read_indexes", []):
        if not isinstance(index, dict):
            continue
        name = _string_value(index.get("index_name"))
        if name is not None:
            indexes[name] = index
    return indexes


def _finding(
    code: str,
    status: str,
    ref: str,
    message: str,
    *,
    axis: str = "wire_compatibility",
    field: str | None = None,
    index: str | None = None,
) -> TargetCompatibilityFinding:
    return TargetCompatibilityFinding(
        code=code,
        status=status,
        ref=ref,
        message=message,
        axis=axis,
        severity=_STATUS_TO_SEVERITY[status],
        field=field,
        index=index,
    )


def _worst(findings: list[TargetCompatibilityFinding], *, default_status: str) -> tuple[str, str]:
    """Return the (status, severity) of the worst finding, by severity rank."""
    status = default_status
    severity = _STATUS_TO_SEVERITY[default_status]
    for finding in findings:
        if _SEVERITY_RANK[finding.severity] > _SEVERITY_RANK[severity]:
            status = finding.status
            severity = finding.severity
    return status, severity


def _int_value(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _string_value(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _int_list(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, int) and not isinstance(item, bool)]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
