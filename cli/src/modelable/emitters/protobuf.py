from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from modelable.compiler.workspace import Workspace
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.parser.ir import (
    AnnKey,
    ArrayType,
    ComputedMapping,
    DecimalType,
    DirectMapping,
    DomainDef,
    EnumType,
    FieldDef,
    FieldType,
    MdlFile,
    ModelVersion,
    PrimitiveType,
    ProjectionField,
    ProjectionVersion,
)
from modelable.registry.resolver import resolve_model_ref


@dataclass(frozen=True)
class _ProtoField:
    source_name: str
    proto_name: str
    number: int
    type_name: str
    enum: _ProtoEnum | None
    key: bool


@dataclass(frozen=True)
class _ProtoEnum:
    name: str
    values: tuple[str, ...]


def emit_protobuf(workspace: Workspace, out_dir: Path) -> list[EmittedArtifact]:
    """Emit Protocol Buffers schema artifacts for model versions."""
    artifacts: list[EmittedArtifact] = []
    for domain in workspace.mdl.domains:
        for model_name, model_versions in domain.models.items():
            for model_version in model_versions:
                proto, manifest = _emit_model_version(domain, model_name, model_version, out_dir)
                artifacts.extend([proto, manifest])
        for projection_name, projection_versions in domain.projections.items():
            for projection_version in projection_versions:
                proto, manifest = _emit_projection_version(
                    domain, projection_name, projection_version, out_dir, workspace.mdl
                )
                artifacts.extend([proto, manifest])
    return artifacts


def _emit_model_version(
    domain: DomainDef, model_name: str, version: ModelVersion, out_dir: Path
) -> tuple[EmittedArtifact, EmittedArtifact]:
    artifact_id = _artifact_id(domain.name, model_name, version.version)
    proto_fields = [
        _field_to_proto(field, message_name=model_name, field_number=index)
        for index, field in enumerate(version.fields, start=1)
    ]
    proto_content = _render_proto(
        package=_package_name(domain.name, version.version),
        message_name=model_name,
        fields=proto_fields,
    )
    manifest_content = _manifest_json(
        domain=domain.name,
        name=model_name,
        kind=version.model_kind.value,
        version=version.version,
        ref=f"{domain.name}.{model_name}@{version.version}",
        fields=proto_fields,
    )
    base_path = out_dir / domain.name / f"{model_name}.v{version.version}"

    proto_artifact = EmittedArtifact(
        target="protobuf",
        ref=f"{domain.name}.{model_name}@{version.version}",
        artifact_id=artifact_id,
        path=base_path / f"{model_name}.v{version.version}.proto",
        content=proto_content,
        content_hash=compute_content_hash(proto_content),
    )
    manifest_artifact = EmittedArtifact(
        target="protobuf",
        ref=f"{domain.name}.{model_name}@{version.version}",
        artifact_id=artifact_id,
        path=base_path / "schema-manifest.json",
        content=manifest_content,
        content_hash=compute_content_hash(manifest_content),
    )
    return proto_artifact, manifest_artifact


def _emit_projection_version(
    domain: DomainDef, projection_name: str, version: ProjectionVersion, out_dir: Path, mdl: MdlFile
) -> tuple[EmittedArtifact, EmittedArtifact]:
    artifact_id = _artifact_id(domain.name, projection_name, version.version)
    proto_fields = [
        _projection_field_to_proto(field, version, mdl, message_name=projection_name, field_number=index)
        for index, field in enumerate(version.fields, start=1)
    ]
    proto_content = _render_proto(
        package=_package_name(domain.name, version.version),
        message_name=projection_name,
        fields=proto_fields,
    )
    manifest_content = _manifest_json(
        domain=domain.name,
        name=projection_name,
        kind="projection",
        version=version.version,
        ref=f"{domain.name}.{projection_name}@{version.version}",
        fields=proto_fields,
    )
    base_path = out_dir / domain.name / f"{projection_name}.v{version.version}"
    proto_artifact = EmittedArtifact(
        target="protobuf",
        ref=f"{domain.name}.{projection_name}@{version.version}",
        artifact_id=artifact_id,
        path=base_path / f"{projection_name}.v{version.version}.proto",
        content=proto_content,
        content_hash=compute_content_hash(proto_content),
    )
    manifest_artifact = EmittedArtifact(
        target="protobuf",
        ref=f"{domain.name}.{projection_name}@{version.version}",
        artifact_id=artifact_id,
        path=base_path / "schema-manifest.json",
        content=manifest_content,
        content_hash=compute_content_hash(manifest_content),
    )
    return proto_artifact, manifest_artifact


def _field_to_proto(field: FieldDef, *, message_name: str, field_number: int) -> _ProtoField:
    type_name, enum = _type_to_proto(field.type, message_name=message_name, field_name=field.name)
    if field.optional and not type_name.startswith("repeated "):
        type_name = f"optional {type_name}"
    return _ProtoField(
        source_name=field.name,
        proto_name=_snake_case(field.name),
        number=field_number,
        type_name=type_name,
        enum=enum,
        key=any(isinstance(annotation, AnnKey) for annotation in field.annotations),
    )


def _projection_field_to_proto(
    field: ProjectionField, projection: ProjectionVersion, mdl: MdlFile, *, message_name: str, field_number: int
) -> _ProtoField:
    field_type = _resolve_projection_field_type(field, projection, mdl)
    type_name, enum = _type_to_proto(field_type, message_name=message_name, field_name=field.name)
    return _ProtoField(
        source_name=field.name,
        proto_name=_snake_case(field.name),
        number=field_number,
        type_name=type_name,
        enum=enum,
        key=False,
    )


def _resolve_projection_field_type(field: ProjectionField, projection: ProjectionVersion, mdl: MdlFile) -> FieldType:
    mapping = field.mapping
    if isinstance(mapping, ComputedMapping):
        return PrimitiveType(kind="string")
    if not isinstance(mapping, DirectMapping):
        return PrimitiveType(kind="string")

    try:
        source_domain, source_model = projection.source.model.rsplit(".", 1)
    except ValueError:
        return PrimitiveType(kind="string")

    try:
        resolved = resolve_model_ref(mdl, f"{source_domain}.{source_model}", projection.source.version)
    except LookupError:
        return PrimitiveType(kind="string")

    if not isinstance(resolved.version, ModelVersion):
        return PrimitiveType(kind="string")

    for source_field in resolved.version.fields:
        if source_field.name == mapping.source_field:
            return source_field.type
    return PrimitiveType(kind="string")


def _type_to_proto(field_type: FieldType, *, message_name: str, field_name: str) -> tuple[str, _ProtoEnum | None]:
    if isinstance(field_type, PrimitiveType):
        return _primitive_to_proto(field_type.kind), None
    if isinstance(field_type, DecimalType):
        return "string", None
    if isinstance(field_type, ArrayType):
        inner, _ = _type_to_proto(field_type.item, message_name=message_name, field_name=field_name)
        return f"repeated {inner.removeprefix('optional ')}", None
    if isinstance(field_type, EnumType):
        enum = _ProtoEnum(name=f"{message_name}{_pascal_case(field_name)}", values=tuple(field_type.values))
        return enum.name, enum
    return "bytes", None


def _primitive_to_proto(kind: str) -> str:
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
    }.get(kind, "string")


def _render_proto(*, package: str, message_name: str, fields: list[_ProtoField]) -> str:
    lines = ['syntax = "proto3";', "", f"package {package};", ""]
    if any("google.protobuf.Timestamp" in field.type_name for field in fields):
        lines.extend(['import "google/protobuf/timestamp.proto";', ""])

    lines.append(f"message {message_name} {{")
    for field in fields:
        lines.append(f"  {field.type_name} {field.proto_name} = {field.number};")
    lines.append("}")

    enums = [field.enum for field in fields if field.enum is not None]
    for enum in enums:
        lines.extend(["", f"enum {enum.name} {{"])
        prefix = _enum_prefix(enum.name)
        lines.append(f"  {prefix}_UNSPECIFIED = 0;")
        for index, value in enumerate(enum.values, start=1):
            lines.append(f"  {prefix}_{_enum_value(value)} = {index};")
        lines.append("}")
    lines.append("")
    return "\n".join(lines)


def _manifest_json(*, domain: str, name: str, kind: str, version: int, ref: str, fields: list[_ProtoField]) -> str:
    schema = {
        "target": "protobuf",
        "schemas": [
            {
                "ref": ref,
                "kind": kind,
                "schema_id": f"modelable://{domain}/{name}/v{version}/protobuf",
                "schema_fingerprint": _schema_fingerprint(fields),
                "fields": [
                    {
                        "name": field.source_name,
                        "proto_name": field.proto_name,
                        "number": field.number,
                        "type": field.type_name,
                        "key": field.key,
                    }
                    for field in fields
                ],
            }
        ],
    }
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def _schema_fingerprint(fields: list[_ProtoField]) -> str:
    normalized = [
        {
            "name": field.source_name,
            "proto_name": field.proto_name,
            "number": field.number,
            "type": field.type_name,
            "key": field.key,
        }
        for field in fields
    ]
    return compute_content_hash(json.dumps(normalized, indent=2, ensure_ascii=False))


def _artifact_id(domain: str, name: str, version: int) -> str:
    return f"{domain}.{name}.v{version}"


def _package_name(domain: str, version: int) -> str:
    normalized = re.sub(r"[^0-9A-Za-z_]+", "_", domain).strip("_").lower()
    return f"modelable.{normalized}.v{version}"


def _snake_case(value: str) -> str:
    first = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", value)
    second = re.sub("([a-z0-9])([A-Z])", r"\1_\2", first)
    return re.sub(r"[^0-9A-Za-z_]+", "_", second).strip("_").lower()


def _pascal_case(value: str) -> str:
    parts = re.split(r"[^0-9A-Za-z]+|_", _snake_case(value))
    return "".join(part[:1].upper() + part[1:] for part in parts if part)


def _enum_prefix(name: str) -> str:
    return _snake_case(name).upper()


def _enum_value(value: str) -> str:
    return _snake_case(value).upper()
