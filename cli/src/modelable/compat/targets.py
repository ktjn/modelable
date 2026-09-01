from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import yaml

from modelable.compat.checker import CompatibilityReport
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
    "data_backfill",
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
        findings.extend(_compare_descriptor(ref, old_schema.get("descriptor"), new_schema.get("descriptor")))

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
        findings.extend(_compare_descriptor(ref, old_service.get("descriptor"), new_service.get("descriptor")))

    status, severity = _worst(findings, default_status="read_compatible")
    return TargetCompatibilityReport(target="grpc", status=status, severity=severity, findings=findings)


def compare_event_sink_artifacts(
    old_artifacts: list[EmittedArtifact],
    new_artifacts: list[EmittedArtifact],
) -> TargetCompatibilityReport:
    """Compare event-sink envelopes and payload contracts for compatibility."""
    findings: list[TargetCompatibilityFinding] = []
    old_document = _event_sink_document(old_artifacts)
    new_document = _event_sink_document(new_artifacts)
    old_events = _event_sink_entries(old_document)
    new_events = _event_sink_entries(new_document)
    old_schemas = _openapi_schemas(old_document)
    new_schemas = _openapi_schemas(new_document)

    for ref in sorted(set(old_events) | set(new_events)):
        old_event = old_events.get(ref)
        new_event = new_events.get(ref)
        if old_event is None:
            continue
        if new_event is None:
            findings.append(_finding("event_removed", "breaking", ref, "event contract was removed"))
            continue

        old_operations = _string_list(old_event.get("operations"))
        new_operations = _string_list(new_event.get("operations"))
        for operation in sorted(set(old_operations) - set(new_operations)):
            findings.append(
                _finding(
                    "event_operation_removed",
                    "breaking",
                    ref,
                    f"event operation {operation!r} was removed",
                )
            )

        old_schema = _event_payload_schema(old_event, old_schemas)
        new_schema = _event_payload_schema(new_event, new_schemas)
        if old_schema != new_schema:
            findings.append(
                _finding(
                    "payload_schema_changed",
                    "review_required",
                    ref,
                    "event payload schema changed and requires compatibility review",
                )
            )

    status, severity = _worst(findings, default_status="read_compatible")
    return TargetCompatibilityReport(target="event-sink", status=status, severity=severity, findings=findings)


def compare_registry_artifacts(
    old_artifacts: list[EmittedArtifact],
    new_artifacts: list[EmittedArtifact],
) -> TargetCompatibilityReport:
    """Compare registry inventories for immutable contract and ID changes."""
    findings: list[TargetCompatibilityFinding] = []
    old_contracts = _registry_entries(_registry_document(old_artifacts))
    new_contracts = _registry_entries(_registry_document(new_artifacts))

    for ref in sorted(set(old_contracts) | set(new_contracts)):
        old_contract = old_contracts.get(ref)
        new_contract = new_contracts.get(ref)
        if old_contract is None:
            continue
        if new_contract is None:
            findings.append(_finding("contract_removed", "breaking", ref, "registry contract was removed"))
            continue

        if old_contract.get("kind") != new_contract.get("kind"):
            findings.append(_finding("contract_kind_changed", "breaking", ref, "registry contract kind changed"))
        if old_contract.get("signature") != new_contract.get("signature"):
            findings.append(_finding("contract_changed", "breaking", ref, "registry contract signature changed"))
        if old_contract.get("registry_id") != new_contract.get("registry_id"):
            findings.append(_finding("registry_id_changed", "breaking", ref, "registry contract ID changed"))
        if old_contract.get("schema_version") != new_contract.get("schema_version"):
            findings.append(_finding("schema_version_changed", "breaking", ref, "registry schema version changed"))

    status, severity = _worst(findings, default_status="read_compatible")
    return TargetCompatibilityReport(target="registry", status=status, severity=severity, findings=findings)


def compare_openapi_artifacts(
    old_artifacts: list[EmittedArtifact],
    new_artifacts: list[EmittedArtifact],
) -> TargetCompatibilityReport:
    """Compare OpenAPI schemas and operations for client-visible compatibility."""
    old_document = _artifact_document(old_artifacts, "openapi")
    new_document = _artifact_document(new_artifacts, "openapi")
    old_schemas = _openapi_schemas(old_document)
    new_schemas = _openapi_schemas(new_document)
    old_operations = _openapi_operations(old_document)
    new_operations = _openapi_operations(new_document)
    findings: list[TargetCompatibilityFinding] = []

    for ref in sorted(set(old_schemas) - set(new_schemas)):
        findings.append(
            _finding(
                "schema_removed",
                "breaking",
                ref,
                "OpenAPI component schema was removed",
                axis="source_compatibility",
            )
        )
    for ref in sorted(set(old_schemas) & set(new_schemas)):
        if old_schemas[ref] != new_schemas[ref]:
            findings.append(
                _finding(
                    "schema_changed",
                    "breaking",
                    ref,
                    "OpenAPI component schema changed",
                    axis="source_compatibility",
                )
            )

    for ref in sorted(set(old_operations) - set(new_operations)):
        findings.append(_finding("operation_removed", "breaking", ref, "OpenAPI operation was removed"))
    for ref in sorted(set(old_operations) & set(new_operations)):
        old_operation = old_operations[ref]
        new_operation = new_operations[ref]
        old_parameters = _openapi_path_parameters(old_operation)
        new_parameters = _openapi_path_parameters(new_operation)
        if old_parameters != new_parameters:
            findings.append(
                _finding(
                    "path_parameters_changed",
                    "breaking",
                    ref,
                    "OpenAPI path parameters changed",
                    axis="source_compatibility",
                )
            )
        old_request = _openapi_json_binding(old_operation.get("requestBody"))
        new_request = _openapi_json_binding(new_operation.get("requestBody"))
        if old_request != new_request:
            findings.append(
                _finding(
                    "request_binding_changed",
                    "breaking",
                    ref,
                    "OpenAPI request body binding changed",
                    axis="source_compatibility",
                )
            )
        old_responses = _openapi_responses(old_operation)
        new_responses = _openapi_responses(new_operation)
        for status in sorted(set(old_responses) - set(new_responses)):
            findings.append(
                _finding(
                    "response_removed",
                    "breaking",
                    ref,
                    f"OpenAPI response {status} was removed",
                    axis="source_compatibility",
                )
            )
        for status in sorted(set(old_responses) & set(new_responses)):
            if old_responses[status] != new_responses[status]:
                findings.append(
                    _finding(
                        "response_binding_changed",
                        "breaking",
                        ref,
                        f"OpenAPI response {status} binding changed",
                        axis="source_compatibility",
                    )
                )

    status, severity = _worst(findings, default_status="read_compatible")
    return TargetCompatibilityReport(target="openapi", status=status, severity=severity, findings=findings)


def compare_avro_artifacts(
    old_artifacts: list[EmittedArtifact],
    new_artifacts: list[EmittedArtifact],
) -> TargetCompatibilityReport:
    """Compare Avro record schemas using the shared target finding vocabulary."""
    findings: list[TargetCompatibilityFinding] = []
    old_schemas = _avro_entries(old_artifacts)
    new_schemas = _avro_entries(new_artifacts)

    for ref in sorted(set(old_schemas) | set(new_schemas)):
        old_schema = old_schemas.get(ref)
        new_schema = new_schemas.get(ref)
        if old_schema is None:
            continue
        if new_schema is None:
            findings.append(_finding("schema_removed", "breaking", ref, "Avro schema was removed"))
            continue
        findings.extend(_compare_avro_schema(ref, old_schema, new_schema))

    status, severity = _worst(findings, default_status="read_compatible")
    return TargetCompatibilityReport(target="avro", status=status, severity=severity, findings=findings)


def compare_json_schema_artifacts(
    old_artifacts: list[EmittedArtifact],
    new_artifacts: list[EmittedArtifact],
) -> TargetCompatibilityReport:
    """Compare emitted JSON Schema documents for source compatibility."""
    findings: list[TargetCompatibilityFinding] = []
    old_schemas = _json_schema_entries(old_artifacts)
    new_schemas = _json_schema_entries(new_artifacts)

    for ref in sorted(set(old_schemas) | set(new_schemas)):
        old_schema = old_schemas.get(ref)
        new_schema = new_schemas.get(ref)
        if old_schema is None:
            continue
        if new_schema is None:
            findings.append(
                _finding(
                    "schema_removed", "breaking", ref, "JSON Schema document was removed", axis="source_compatibility"
                )
            )
            continue
        findings.extend(_compare_json_schema(ref, old_schema, new_schema))

    status, severity = _worst(findings, default_status="read_compatible")
    return TargetCompatibilityReport(target="json-schema", status=status, severity=severity, findings=findings)


def compare_sql_artifacts(
    old_artifacts: list[EmittedArtifact],
    new_artifacts: list[EmittedArtifact],
    *,
    target: str = "sql-postgres",
) -> TargetCompatibilityReport:
    """Compare emitted SQL table definitions for storage compatibility."""
    if target not in {"sql-postgres", "sql-clickhouse"}:
        raise ValueError(f"unsupported SQL compatibility target: {target!r}")

    findings: list[TargetCompatibilityFinding] = []
    old_tables = _sql_entries(old_artifacts, target)
    new_tables = _sql_entries(new_artifacts, target)
    for ref in sorted(set(old_tables) | set(new_tables)):
        old_table = old_tables.get(ref)
        new_table = new_tables.get(ref)
        if old_table is None:
            continue
        if new_table is None:
            findings.append(
                _finding(
                    "table_removed",
                    "breaking",
                    ref,
                    f"{target} table definition was removed",
                    axis="storage_migration",
                )
            )
        elif old_table != new_table:
            findings.append(
                _finding(
                    "table_definition_changed",
                    "migration_required",
                    ref,
                    f"{target} table definition changed and requires a storage migration",
                    axis="storage_migration",
                )
            )

    status, severity = _worst(findings, default_status="read_compatible")
    return TargetCompatibilityReport(target=target, status=status, severity=severity, findings=findings)


def compare_fhir_artifacts(
    old_artifacts: list[EmittedArtifact],
    new_artifacts: list[EmittedArtifact],
) -> TargetCompatibilityReport:
    """Compare FHIR StructureDefinitions for profile compatibility."""
    findings: list[TargetCompatibilityFinding] = []
    old_profiles = _fhir_entries(old_artifacts)
    new_profiles = _fhir_entries(new_artifacts)
    for ref in sorted(set(old_profiles) | set(new_profiles)):
        old_profile = old_profiles.get(ref)
        new_profile = new_profiles.get(ref)
        if old_profile is None:
            continue
        if new_profile is None:
            findings.append(_finding("profile_removed", "breaking", ref, "FHIR profile was removed"))
            continue
        findings.extend(_compare_fhir_profile(ref, old_profile, new_profile))

    status, severity = _worst(findings, default_status="read_compatible")
    return TargetCompatibilityReport(target="fhir-profile", status=status, severity=severity, findings=findings)


def compare_odcs_artifacts(
    old_artifacts: list[EmittedArtifact],
    new_artifacts: list[EmittedArtifact],
) -> TargetCompatibilityReport:
    """Compare ODCS DataContract documents for contract compatibility."""
    findings: list[TargetCompatibilityFinding] = []
    old_contracts = _odcs_entries(old_artifacts)
    new_contracts = _odcs_entries(new_artifacts)
    for ref in sorted(set(old_contracts) | set(new_contracts)):
        old_contract = old_contracts.get(ref)
        new_contract = new_contracts.get(ref)
        if old_contract is None:
            for name, property_def in _odcs_properties(new_contract).items():
                if _odcs_required(property_def):
                    findings.append(
                        _finding(
                            "property_required_added",
                            "breaking",
                            ref,
                            f"ODCS required property '{name}' was added",
                            field=name,
                        )
                    )
            continue
        if new_contract is None:
            findings.append(_finding("contract_removed", "breaking", ref, "ODCS contract was removed"))
            continue
        findings.extend(_compare_odcs_contract(ref, old_contract, new_contract))

    status, severity = _worst(findings, default_status="read_compatible")
    return TargetCompatibilityReport(target="odcs", status=status, severity=severity, findings=findings)


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


def compare_semantic_compatibility(
    report: CompatibilityReport,
    *,
    target: str = "source",
) -> TargetCompatibilityReport:
    """Evaluate only target-neutral semantic changes from a model report."""
    return compare_source_representation(
        report.domain_name,
        report.model_name,
        report.semantic_changes,
        target=target,
    )


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


def compare_model_storage_migration(report: CompatibilityReport) -> TargetCompatibilityReport:
    """Evaluate only storage changes from a model compatibility report."""
    return compare_storage_migration(report.domain_name, report.model_name, report.storage_changes)


def compare_data_backfill(report: CompatibilityReport) -> TargetCompatibilityReport:
    """Report deterministic backfills for newly added required fields with defaults."""
    findings = [
        _finding(
            "field_added_with_default",
            "migration_required",
            f"{report.domain_name}.{report.model_name}",
            f"field '{change.field_name}' has a default and requires a data backfill",
            axis="data_backfill",
            field=change.field_name,
        )
        for change in report.semantic_changes
        if change.kind == "added_field" and change.to_optional is False and change.to_default is not None
    ]
    status, severity = _worst(findings, default_status="compatible")
    return TargetCompatibilityReport(target="data-backfill", status=status, severity=severity, findings=findings)


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


def compare_projection_wire_compatibility(
    domain_name: str,
    projection_name: str,
    changes: list[ProjectionChange],
) -> TargetCompatibilityReport:
    """Surface projection wire-hint changes as structured compatibility findings."""
    findings = [
        _finding(
            change.kind,
            "breaking" if change.breaking else "compatible",
            f"{domain_name}.{projection_name}",
            change.message,
            axis="wire_compatibility",
            field=change.field_name,
        )
        for change in changes
        if change.dimension == "wire"
    ]
    status, severity = _worst(findings, default_status="compatible")
    return TargetCompatibilityReport(target="wire", status=status, severity=severity, findings=findings)


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


def _json_schema_entries(artifacts: list[EmittedArtifact]) -> dict[str, dict[str, Any]]:
    return {
        artifact.ref: artifact.content
        for artifact in artifacts
        if artifact.target == "json-schema" and isinstance(artifact.ref, str) and isinstance(artifact.content, dict)
    }


def _sql_entries(artifacts: list[EmittedArtifact], target: str) -> dict[str, str]:
    return {
        artifact.ref: artifact.content
        for artifact in artifacts
        if artifact.target == target and isinstance(artifact.ref, str) and isinstance(artifact.content, str)
    }


def _fhir_entries(artifacts: list[EmittedArtifact]) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        if (
            artifact.target != "fhir-profile"
            or not isinstance(artifact.ref, str)
            or not isinstance(artifact.content, str)
        ):
            continue
        try:
            content = json.loads(artifact.content)
        except json.JSONDecodeError:
            continue
        if isinstance(content, dict):
            entries[artifact.ref] = content
    return entries


def _compare_fhir_profile(
    ref: str, old_profile: dict[str, Any], new_profile: dict[str, Any]
) -> list[TargetCompatibilityFinding]:
    findings: list[TargetCompatibilityFinding] = []
    old_elements = _fhir_elements(old_profile)
    new_elements = _fhir_elements(new_profile)
    for path in sorted(set(old_elements) - set(new_elements)):
        findings.append(
            _finding(
                "element_removed",
                "breaking",
                ref,
                f"FHIR element '{path}' was removed",
                field=path,
            )
        )
    for path in sorted(set(new_elements) - set(old_elements)):
        element = new_elements[path]
        if _fhir_min(element) > 0:
            findings.append(
                _finding(
                    "element_required_added",
                    "breaking",
                    ref,
                    f"FHIR required element '{path}' was added",
                    field=path,
                )
            )
    for path in sorted(set(old_elements) & set(new_elements)):
        old_element = old_elements[path]
        new_element = new_elements[path]
        if _fhir_min(new_element) > _fhir_min(old_element):
            findings.append(
                _finding(
                    "element_min_increased",
                    "breaking",
                    ref,
                    f"FHIR element '{path}' minimum cardinality increased",
                    field=path,
                )
            )
        previous_max = _fhir_max(old_element)
        current_max = _fhir_max(new_element)
        if current_max < previous_max:
            findings.append(
                _finding(
                    "element_max_decreased",
                    "breaking",
                    ref,
                    f"FHIR element '{path}' maximum cardinality decreased",
                    field=path,
                )
            )
        if _fhir_type_signature(old_element) != _fhir_type_signature(new_element):
            findings.append(
                _finding(
                    "element_type_changed",
                    "breaking",
                    ref,
                    f"FHIR element '{path}' type binding changed",
                    field=path,
                )
            )
    return findings


def _fhir_elements(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    snapshot = profile.get("snapshot")
    elements = snapshot.get("element") if isinstance(snapshot, dict) else None
    if not isinstance(elements, list):
        return {}
    return {
        element["path"]: element
        for element in elements
        if isinstance(element, dict) and isinstance(element.get("path"), str)
    }


def _fhir_min(element: dict[str, Any]) -> int:
    value = element.get("min")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _fhir_max(element: dict[str, Any]) -> int:
    value = element.get("max")
    if value == "*":
        return 2**31 - 1
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return value if isinstance(value, int) and not isinstance(value, bool) else 2**31 - 1


def _fhir_type_signature(element: dict[str, Any]) -> str:
    return json.dumps(element.get("type"), sort_keys=True, separators=(",", ":"))


def _odcs_entries(artifacts: list[EmittedArtifact]) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        if artifact.target != "odcs" or not isinstance(artifact.ref, str) or not isinstance(artifact.content, str):
            continue
        try:
            content = yaml.safe_load(artifact.content)
        except yaml.YAMLError:
            continue
        if isinstance(content, dict):
            entries[artifact.ref] = content
    return entries


def _compare_odcs_contract(
    ref: str, old_contract: dict[str, Any], new_contract: dict[str, Any]
) -> list[TargetCompatibilityFinding]:
    findings: list[TargetCompatibilityFinding] = []
    old_properties = _odcs_properties(old_contract)
    new_properties = _odcs_properties(new_contract)
    for name in sorted(set(old_properties) - set(new_properties)):
        findings.append(
            _finding("property_removed", "breaking", ref, f"ODCS property '{name}' was removed", field=name)
        )
    for name in sorted(set(new_properties) - set(old_properties)):
        if _odcs_required(new_properties[name]):
            findings.append(
                _finding(
                    "property_required_added",
                    "breaking",
                    ref,
                    f"ODCS required property '{name}' was added",
                    field=name,
                )
            )
    for name in sorted(set(old_properties) & set(new_properties)):
        old_property = old_properties[name]
        new_property = new_properties[name]
        if not _odcs_required(old_property) and _odcs_required(new_property):
            findings.append(
                _finding(
                    "property_required",
                    "breaking",
                    ref,
                    f"ODCS property '{name}' became required",
                    field=name,
                )
            )
        if _odcs_type_signature(old_property) != _odcs_type_signature(new_property):
            findings.append(
                _finding(
                    "property_type_changed",
                    "breaking",
                    ref,
                    f"ODCS property '{name}' type changed",
                    field=name,
                )
            )
        removed_values = sorted(set(_odcs_enum_values(old_property)) - set(_odcs_enum_values(new_property)))
        if removed_values:
            findings.append(
                _finding(
                    "enum_value_removed",
                    "breaking",
                    ref,
                    f"ODCS property '{name}' removed enum values: {', '.join(removed_values)}",
                    field=name,
                )
            )
    return findings


def _odcs_properties(contract: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if contract is None:
        return {}
    schemas = contract.get("schema")
    if not isinstance(schemas, list):
        return {}
    properties: dict[str, dict[str, Any]] = {}
    for schema in schemas:
        if not isinstance(schema, dict) or not isinstance(schema.get("properties"), list):
            continue
        for property_def in schema["properties"]:
            if isinstance(property_def, dict) and isinstance(property_def.get("name"), str):
                properties[property_def["name"]] = property_def
    return properties


def _odcs_required(property_def: dict[str, Any]) -> bool:
    return property_def.get("required") is True


def _odcs_custom_properties(property_def: dict[str, Any]) -> dict[str, Any]:
    custom_properties = property_def.get("customProperties")
    if not isinstance(custom_properties, list):
        return {}
    return {
        item["property"]: item.get("value")
        for item in custom_properties
        if isinstance(item, dict) and isinstance(item.get("property"), str)
    }


def _odcs_type_signature(property_def: dict[str, Any]) -> str:
    custom = _odcs_custom_properties(property_def)
    modelable_type = "enum" if isinstance(custom.get("modelableEnum"), list) else custom.get("modelableType")
    return json.dumps(
        {
            "logicalType": property_def.get("logicalType"),
            "logicalTypeOptions": property_def.get("logicalTypeOptions"),
            "modelableType": modelable_type,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _odcs_enum_values(property_def: dict[str, Any]) -> list[str]:
    values = _odcs_custom_properties(property_def).get("modelableEnum")
    return [value for value in values if isinstance(value, str)] if isinstance(values, list) else []


def _compare_json_schema(
    ref: str, old_schema: dict[str, Any], new_schema: dict[str, Any]
) -> list[TargetCompatibilityFinding]:
    findings: list[TargetCompatibilityFinding] = []
    old_properties = _json_schema_properties(old_schema)
    new_properties = _json_schema_properties(new_schema)
    old_required = _json_schema_required(old_schema)
    new_required = _json_schema_required(new_schema)

    for field in sorted(set(old_properties) - set(new_properties)):
        findings.append(
            _finding(
                "property_removed",
                "breaking",
                ref,
                f"JSON Schema property '{field}' was removed",
                axis="source_compatibility",
                field=field,
            )
        )
    for field in sorted(new_required - old_required):
        if field in new_properties:
            findings.append(
                _finding(
                    "required_property_added",
                    "breaking",
                    ref,
                    f"JSON Schema required property '{field}' was added",
                    axis="source_compatibility",
                    field=field,
                )
            )
    for field in sorted(set(old_properties) & set(new_properties)):
        if old_properties[field] != new_properties[field]:
            findings.append(
                _finding(
                    "property_type_changed",
                    "breaking",
                    ref,
                    f"JSON Schema property '{field}' changed type or constraints",
                    axis="source_compatibility",
                    field=field,
                )
            )

    return findings


def _json_schema_properties(schema: dict[str, Any]) -> dict[str, object]:
    properties = schema.get("properties")
    return properties if isinstance(properties, dict) else {}


def _json_schema_required(schema: dict[str, Any]) -> set[str]:
    required = schema.get("required")
    return {item for item in required if isinstance(item, str)} if isinstance(required, list) else set()


def _avro_entries(artifacts: list[EmittedArtifact]) -> dict[str, dict[str, Any]]:
    schemas: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        if artifact.target != "avro" or not isinstance(artifact.content, dict):
            continue
        metadata = artifact.content.get("x-modelable")
        ref = metadata.get("ref") if isinstance(metadata, dict) else None
        if isinstance(ref, str):
            schemas[ref] = artifact.content
    return schemas


def _compare_avro_schema(
    ref: str, old_schema: dict[str, Any], new_schema: dict[str, Any]
) -> list[TargetCompatibilityFinding]:
    findings: list[TargetCompatibilityFinding] = []
    if old_schema.get("type") != new_schema.get("type"):
        findings.append(_finding("schema_type_changed", "breaking", ref, "Avro schema type changed"))
        return findings
    if old_schema.get("name") != new_schema.get("name") or old_schema.get("namespace") != new_schema.get("namespace"):
        findings.append(_finding("schema_name_changed", "breaking", ref, "Avro schema name or namespace changed"))

    old_fields = _avro_fields(old_schema)
    new_fields = _avro_fields(new_schema)
    for field in sorted(set(old_fields) - set(new_fields)):
        findings.append(_finding("field_removed", "breaking", ref, f"Avro field '{field}' was removed", field=field))
    for field in sorted(set(new_fields) - set(old_fields)):
        new_field = new_fields[field]
        if "default" not in new_field and not _avro_is_nullable(new_field.get("type")):
            findings.append(
                _finding(
                    "required_field_added",
                    "breaking",
                    ref,
                    f"Avro required field '{field}' was added without a default",
                    field=field,
                )
            )
    for field in sorted(set(old_fields) & set(new_fields)):
        if old_fields[field].get("type") != new_fields[field].get("type"):
            findings.append(
                _finding(
                    "field_type_changed",
                    "breaking",
                    ref,
                    f"Avro field '{field}' type changed",
                    field=field,
                )
            )
    return findings


def _avro_fields(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    fields = schema.get("fields")
    if not isinstance(fields, list):
        return {}
    return {field["name"]: field for field in fields if isinstance(field, dict) and isinstance(field.get("name"), str)}


def _avro_is_nullable(schema: object) -> bool:
    return isinstance(schema, list) and "null" in schema


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


def _event_sink_document(artifacts: list[EmittedArtifact]) -> dict[str, Any]:
    artifact = next(
        (item for item in artifacts if item.path.name == "event-sink.json" and isinstance(item.content, str)), None
    )
    if artifact is None:
        return {}
    content = artifact.content
    if not isinstance(content, str):
        return {}
    document = json.loads(content)
    return document if isinstance(document, dict) else {}


def _event_sink_entries(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    events = document.get("events")
    if not isinstance(events, list):
        return {}
    return {event["ref"]: event for event in events if isinstance(event, dict) and isinstance(event.get("ref"), str)}


def _event_payload_schema(event: dict[str, Any], schemas: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    payload_schema = event.get("payload_schema")
    if not isinstance(payload_schema, dict):
        return None
    schema_ref = payload_schema.get("$ref")
    if not isinstance(schema_ref, str) or not schema_ref.startswith("#/components/schemas/"):
        return payload_schema
    return schemas.get(schema_ref.removeprefix("#/components/schemas/"), payload_schema)


def _registry_document(artifacts: list[EmittedArtifact]) -> dict[str, Any]:
    artifact = next(
        (item for item in artifacts if item.path.name == "registry.json" and isinstance(item.content, str)), None
    )
    if artifact is None:
        return {}
    content = artifact.content
    if not isinstance(content, str):
        return {}
    document = json.loads(content)
    return document if isinstance(document, dict) else {}


def _registry_entries(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    contracts = document.get("contracts")
    if not isinstance(contracts, list):
        return {}
    return {
        contract["ref"]: contract
        for contract in contracts
        if isinstance(contract, dict) and isinstance(contract.get("ref"), str)
    }


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


def _compare_descriptor(ref: str, old_descriptor: object, new_descriptor: object) -> list[TargetCompatibilityFinding]:
    if not isinstance(old_descriptor, dict) or not isinstance(new_descriptor, dict):
        return []
    old_hash = _string_value(old_descriptor.get("content_hash"))
    new_hash = _string_value(new_descriptor.get("content_hash"))
    if old_hash is None or new_hash is None or old_hash == new_hash:
        return []
    return [
        _finding(
            "descriptor_changed",
            "review_required",
            ref,
            "compiled descriptor content changed and requires descriptor compatibility review",
        )
    ]


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


def _artifact_document(artifacts: list[EmittedArtifact], target: str) -> dict[str, Any]:
    artifact = next((item for item in artifacts if item.target == target), None)
    if artifact is None or not isinstance(artifact.content, dict):
        return {}
    return artifact.content


def _openapi_operations(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    paths = document.get("paths")
    if not isinstance(paths, dict):
        return {}
    methods = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
    operations: dict[str, dict[str, Any]] = {}
    for path, path_item in paths.items():
        if not isinstance(path, str) or not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() in methods and isinstance(operation, dict):
                operations[f"{method.lower()} {path}"] = operation
    return operations


def _openapi_schemas(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    components = document.get("components")
    if not isinstance(components, dict):
        return {}
    schemas = components.get("schemas")
    if not isinstance(schemas, dict):
        return {}
    return {str(name): schema for name, schema in schemas.items() if isinstance(name, str) and isinstance(schema, dict)}


def _openapi_path_parameters(operation: dict[str, Any]) -> tuple[tuple[str, str, bool, str], ...]:
    parameters = operation.get("parameters")
    if not isinstance(parameters, list):
        return ()
    result = []
    for parameter in parameters:
        if not isinstance(parameter, dict) or parameter.get("in") != "path":
            continue
        schema = parameter.get("schema")
        result.append(
            (
                str(parameter.get("name", "")),
                "path",
                bool(parameter.get("required")),
                json.dumps(schema, sort_keys=True, separators=(",", ":")),
            )
        )
    return tuple(sorted(result))


def _openapi_json_binding(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    content = value.get("content")
    if not isinstance(content, dict):
        return None
    media = content.get("application/json")
    if not isinstance(media, dict):
        return None
    return json.dumps(media.get("schema"), sort_keys=True, separators=(",", ":"))


def _openapi_responses(operation: dict[str, Any]) -> dict[str, str | None]:
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return {}
    return {
        str(status): _openapi_json_binding(response)
        for status, response in responses.items()
        if isinstance(status, str)
    }


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
