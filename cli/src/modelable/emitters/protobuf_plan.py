"""Parser-free scalar Protobuf projection rendering for ``modelable.plan/v0``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.base import artifact_id as _artifact_id
from modelable.emitters.naming import proto_domain_segment
from modelable.emitters.naming import snake_case as _snake_case
from modelable.planner.protocol import PlanDocument, serialize_plan, validate_plan


def emit_protobuf_projection_plan(
    plan: PlanDocument,
    out_dir: Path,
    *,
    modelable_signature: str | None = None,
) -> tuple[EmittedArtifact, EmittedArtifact]:
    """Emit one scalar projection message and manifest from validated plan facts."""
    document = validate_plan(plan)
    domain = _string(document, "domain")
    projection = _string(document, "projection")
    version = _integer(document, "version")
    fields = [_field(document, field, index) for index, field in enumerate(_mappings(document.get("fields")), start=1)]
    package = f"modelable.{proto_domain_segment(domain)}.v{version}"
    proto_content = _render_proto(package, projection, fields)
    signature = modelable_signature or compute_content_hash(serialize_plan(document))
    manifest_content = _render_manifest(domain, projection, version, signature, fields)
    base_path = out_dir / domain / f"{projection}.v{version}"
    ref = f"{domain}.{projection}@{version}"
    artifact = _artifact_id(domain, projection, version)
    return (
        EmittedArtifact(
            target="protobuf",
            ref=ref,
            artifact_id=artifact,
            path=base_path / f"{projection}.v{version}.proto",
            content=proto_content,
            content_hash=compute_content_hash(proto_content),
        ),
        EmittedArtifact(
            target="protobuf",
            ref=ref,
            artifact_id=artifact,
            path=base_path / "schema-manifest.json",
            content=manifest_content,
            content_hash=compute_content_hash(manifest_content),
        ),
    )


def _field(plan: PlanDocument, field: dict[str, Any], number: int) -> dict[str, Any]:
    field_type = _source_type(plan, field)
    type_name, fixed_length = _type_to_proto(field_type)
    return {
        "name": _string(field, "name"),
        "proto_name": _snake_case(_string(field, "name")),
        "number": number,
        "type": type_name,
        "key": False,
        **({"fixed_length": fixed_length} if fixed_length is not None else {}),
    }


def _source_type(plan: PlanDocument, field: dict[str, Any]) -> dict[str, Any]:
    if field.get("kind") != "direct":
        value = field.get("type")
        return cast(dict[str, Any], value) if isinstance(value, dict) else {"kind": "string"}
    alias = field.get("source_alias")
    source_name = field.get("source_field")
    for relation in [_mapping(plan, "source"), *_mappings(plan.get("joins"))]:
        if relation.get("alias") != alias:
            continue
        resolved = relation.get("resolved")
        for source in _mappings(resolved.get("fields") if isinstance(resolved, dict) else None):
            if source.get("name") == source_name:
                value = source.get("type")
                if isinstance(value, dict):
                    return cast(dict[str, Any], value)
    value = field.get("type")
    return cast(dict[str, Any], value) if isinstance(value, dict) else {"kind": "string"}


def _type_to_proto(field_type: dict[str, Any]) -> tuple[str, int | None]:
    kind = field_type.get("kind")
    if kind == "decimal":
        return "string", None
    if kind == "fixed_binary":
        return "bytes", _integer(field_type, "length")
    if kind in {
        "primitive",
        "string",
        "uuid",
        "date",
        "time",
        "duration",
        "binary",
        "int",
        "float",
        "bool",
        "timestamp",
        "u8",
        "u16",
        "u32",
        "u64",
        "u128",
        "i8",
        "i16",
        "i32",
        "i64",
        "i128",
        "json",
    }:
        return _primitive_to_proto(str(field_type.get("type", kind)))
    return "string", None


def _primitive_to_proto(kind: str) -> tuple[str, int | None]:
    if kind in {"u128", "i128"}:
        return "bytes", 16
    return {
        "string": "string",
        "uuid": "string",
        "date": "string",
        "time": "string",
        "duration": "string",
        "int": "int64",
        "float": "double",
        "bool": "bool",
        "timestamp": "google.protobuf.Timestamp",
        "binary": "bytes",
        "json": "string",
        "u8": "uint32",
        "u16": "uint32",
        "u32": "uint32",
        "u64": "uint64",
        "i8": "int32",
        "i16": "int32",
        "i32": "int32",
        "i64": "int64",
    }.get(kind, "string"), None


def _render_proto(package: str, message: str, fields: list[dict[str, Any]]) -> str:
    lines = ['syntax = "proto3";', "", f"package {package};", ""]
    if any(field["type"] == "google.protobuf.Timestamp" for field in fields):
        lines.extend(['import "google/protobuf/timestamp.proto";', ""])
    lines.append(f"message {message} {{")
    lines.extend(f"  {field['type']} {field['proto_name']} = {field['number']};" for field in fields)
    lines.extend(["}", ""])
    return "\n".join(lines)


def _render_manifest(domain: str, name: str, version: int, signature: str, fields: list[dict[str, Any]]) -> str:
    normalized = {"fields": fields, "semantic_types": []}
    schema_entry = {
        "ref": f"{domain}.{name}@{version}",
        "kind": "projection",
        "schema_id": f"modelable://{domain}/{name}/v{version}/protobuf",
        "modelable_signature": signature,
        "schema_fingerprint": compute_content_hash(json.dumps(normalized, indent=2, ensure_ascii=False)),
        "semantic_types": [],
        "fields": fields,
    }
    return json.dumps({"target": "protobuf", "schemas": [schema_entry]}, indent=2, ensure_ascii=False) + "\n"


def _mapping(mapping: dict[str, object], key: str) -> dict[str, Any]:
    value = mapping.get(key)
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _mappings(value: object) -> list[dict[str, Any]]:
    return [cast(dict[str, Any], item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _string(mapping: dict[str, object], key: str) -> str:
    return str(mapping.get(key, ""))


def _integer(mapping: dict[str, object], key: str) -> int:
    value = mapping.get(key)
    if not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    return value
