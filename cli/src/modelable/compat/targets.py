from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from modelable.emitters.base import EmittedArtifact

PASSING_STATUSES = {"wire_compatible", "read_compatible"}
STATUS_RANK = {
    "wire_compatible": 0,
    "read_compatible": 0,
    "requires_read_rebuild": 1,
    "breaking": 2,
}


@dataclass(frozen=True)
class TargetCompatibilityFinding:
    code: str
    status: str
    ref: str
    message: str
    field: str | None = None
    index: str | None = None


@dataclass(frozen=True)
class TargetCompatibilityReport:
    target: str
    status: str
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

    return TargetCompatibilityReport(
        target="protobuf",
        status=_worst_status(findings, default="wire_compatible"),
        findings=findings,
    )


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

    return TargetCompatibilityReport(
        target="grpc",
        status=_worst_status(findings, default="read_compatible"),
        findings=findings,
    )


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
        if number in reserved_numbers and old_proto_name in reserved_names:
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
    field: str | None = None,
    index: str | None = None,
) -> TargetCompatibilityFinding:
    return TargetCompatibilityFinding(
        code=code,
        status=status,
        ref=ref,
        message=message,
        field=field,
        index=index,
    )


def _worst_status(findings: list[TargetCompatibilityFinding], *, default: str) -> str:
    status = default
    for finding in findings:
        if STATUS_RANK[finding.status] > STATUS_RANK[status]:
            status = finding.status
    return status


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
