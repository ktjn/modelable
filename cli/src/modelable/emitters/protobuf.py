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
    FixedBinaryType,
    IndexDecl,
    MapType,
    MdlFile,
    ModelVersion,
    NamedType,
    PrimitiveType,
    ProjectionField,
    ProjectionVersion,
    ProtobufReservations,
    SemanticTypeDecl,
)
from modelable.registry.resolver import resolve_model_ref
from modelable.registry.signature import compute_version_signature


@dataclass(frozen=True)
class _SemanticProtoType:
    ref: str
    declaring_domain: str
    proto_type: str
    underlying_type: str
    fixed_length: int | None
    registry_id: int | None


@dataclass(frozen=True)
class _SemanticIndex:
    by_name: dict[str, tuple[_SemanticProtoType, ...]]
    by_domain: dict[str, tuple[_SemanticProtoType, ...]]

    def resolve(self, name: str) -> _SemanticProtoType | None:
        candidates = self.by_name.get(name, ())
        if not candidates:
            return None
        if len(candidates) > 1:
            refs = ", ".join(candidate.ref for candidate in candidates)
            raise ValueError(f"ambiguous semantic type '{name}'; candidates: {refs}")
        return candidates[0]


@dataclass(frozen=True)
class _ProtoField:
    source_name: str
    proto_name: str
    number: int
    type_name: str
    enum: _ProtoEnum | None
    key: bool
    fixed_length: int | None = None
    semantic: _SemanticProtoType | None = None
    map: _ProtoMap | None = None


@dataclass(frozen=True)
class _ProtoEnum:
    name: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class _ProtoMap:
    key_type: str
    value_type: str
    value_fixed_length: int | None = None
    value_semantic: _SemanticProtoType | None = None


def emit_protobuf(
    workspace: Workspace,
    out_dir: Path,
    *,
    registry_ids: dict[str, int] | None = None,
) -> list[EmittedArtifact]:
    """Emit Protocol Buffers schema artifacts for semantic types, models, and projections."""
    semantic_index = _build_semantic_index(workspace.mdl, registry_ids)
    artifacts = _emit_semantic_bundles(semantic_index, out_dir)
    for domain in workspace.mdl.domains:
        for model_name, model_versions in domain.models.items():
            for model_version in model_versions:
                proto, manifest = _emit_model_version(
                    domain,
                    model_name,
                    model_version,
                    out_dir,
                    semantic_index,
                )
                artifacts.extend([proto, manifest])
        for projection_name, projection_versions in domain.projections.items():
            for projection_version in projection_versions:
                proto, manifest = _emit_projection_version(
                    domain,
                    projection_name,
                    projection_version,
                    out_dir,
                    workspace.mdl,
                    semantic_index,
                )
                artifacts.extend([proto, manifest])
    return artifacts


def _emit_model_version(
    domain: DomainDef,
    model_name: str,
    version: ModelVersion,
    out_dir: Path,
    semantic_index: _SemanticIndex,
) -> tuple[EmittedArtifact, EmittedArtifact]:
    artifact_id = _artifact_id(domain.name, model_name, version.version)
    proto_fields = [
        _field_to_proto(
            field,
            message_name=model_name,
            field_number=index,
            semantic_index=semantic_index,
        )
        for index, field in enumerate(version.fields, start=1)
    ]
    _validate_reservations(
        proto_fields,
        version.protobuf_reservations,
        ref=f"{domain.name}.{model_name}@{version.version}",
    )
    proto_content = _render_proto(
        package=_package_name(domain.name, version.version),
        message_name=model_name,
        fields=proto_fields,
        reservations=version.protobuf_reservations,
    )
    indexes = _manifest_indexes(_index_decl_for(domain, model_name, version.version))
    manifest_content = _manifest_json(
        domain=domain.name,
        name=model_name,
        kind=version.model_kind.value,
        version=version,
        ref=f"{domain.name}.{model_name}@{version.version}",
        fields=proto_fields,
        indexes=indexes,
        reservations=version.protobuf_reservations,
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
    domain: DomainDef,
    projection_name: str,
    version: ProjectionVersion,
    out_dir: Path,
    mdl: MdlFile,
    semantic_index: _SemanticIndex,
) -> tuple[EmittedArtifact, EmittedArtifact]:
    artifact_id = _artifact_id(domain.name, projection_name, version.version)
    proto_fields = [
        _projection_field_to_proto(
            field,
            version,
            mdl,
            message_name=projection_name,
            field_number=index,
            semantic_index=semantic_index,
        )
        for index, field in enumerate(version.fields, start=1)
    ]
    _validate_reservations(
        proto_fields,
        version.protobuf_reservations,
        ref=f"{domain.name}.{projection_name}@{version.version}",
    )
    proto_content = _render_proto(
        package=_package_name(domain.name, version.version),
        message_name=projection_name,
        fields=proto_fields,
        reservations=version.protobuf_reservations,
    )
    manifest_content = _manifest_json(
        domain=domain.name,
        name=projection_name,
        kind="projection",
        version=version,
        ref=f"{domain.name}.{projection_name}@{version.version}",
        fields=proto_fields,
        reservations=version.protobuf_reservations,
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


def _field_to_proto(
    field: FieldDef,
    *,
    message_name: str,
    field_number: int,
    semantic_index: _SemanticIndex,
) -> _ProtoField:
    type_name, enum, fixed_length, semantic, proto_map = _type_to_proto(
        field.type,
        message_name=message_name,
        field_name=field.name,
        semantic_index=semantic_index,
    )
    if field.optional and not type_name.startswith("repeated ") and proto_map is None:
        type_name = f"optional {type_name}"
    return _ProtoField(
        source_name=field.name,
        proto_name=_snake_case(field.name),
        number=field_number,
        type_name=type_name,
        enum=enum,
        key=any(isinstance(annotation, AnnKey) for annotation in field.annotations),
        fixed_length=fixed_length,
        semantic=semantic,
        map=proto_map,
    )


def _projection_field_to_proto(
    field: ProjectionField,
    projection: ProjectionVersion,
    mdl: MdlFile,
    *,
    message_name: str,
    field_number: int,
    semantic_index: _SemanticIndex,
) -> _ProtoField:
    field_type = _resolve_projection_field_type(field, projection, mdl)
    type_name, enum, fixed_length, semantic, proto_map = _type_to_proto(
        field_type,
        message_name=message_name,
        field_name=field.name,
        semantic_index=semantic_index,
    )
    return _ProtoField(
        source_name=field.name,
        proto_name=_snake_case(field.name),
        number=field_number,
        type_name=type_name,
        enum=enum,
        key=False,
        fixed_length=fixed_length,
        semantic=semantic,
        map=proto_map,
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


def _type_to_proto(
    field_type: FieldType,
    *,
    message_name: str,
    field_name: str,
    semantic_index: _SemanticIndex,
) -> tuple[str, _ProtoEnum | None, int | None, _SemanticProtoType | None, _ProtoMap | None]:
    if isinstance(field_type, PrimitiveType):
        type_name, fixed_length = _primitive_to_proto(field_type.kind)
        return type_name, None, fixed_length, None, None
    if isinstance(field_type, DecimalType):
        return "string", None, None, None, None
    if isinstance(field_type, FixedBinaryType):
        return "bytes", None, field_type.length, None, None
    if isinstance(field_type, NamedType):
        semantic = semantic_index.resolve(field_type.name)
        if semantic is not None:
            return semantic.proto_type, None, None, semantic, None
        return "bytes", None, None, None, None
    if isinstance(field_type, MapType):
        key_type = _map_key_to_proto(field_type.key, message_name=message_name, field_name=field_name)
        value_type, value_fixed_length, value_semantic, value_enum = _map_value_to_proto(
            field_type.value,
            message_name=message_name,
            field_name=field_name,
            semantic_index=semantic_index,
        )
        proto_map = _ProtoMap(
            key_type=key_type,
            value_type=value_type,
            value_fixed_length=value_fixed_length,
            value_semantic=value_semantic,
        )
        return f"map<{key_type}, {value_type}>", value_enum, None, None, proto_map
    if isinstance(field_type, ArrayType):
        inner, _, _, semantic, item_map = _type_to_proto(
            field_type.item,
            message_name=message_name,
            field_name=field_name,
            semantic_index=semantic_index,
        )
        if item_map is not None:
            raise ValueError(f"protobuf field '{field_name}' cannot use a map inside an array")
        return f"repeated {inner.removeprefix('optional ')}", None, None, semantic, None
    if isinstance(field_type, EnumType):
        enum = _ProtoEnum(name=f"{message_name}{_pascal_case(field_name)}", values=tuple(field_type.values))
        return enum.name, enum, None, None, None
    return "bytes", None, None, None, None


def _map_key_to_proto(field_type: FieldType, *, message_name: str, field_name: str) -> str:
    if not isinstance(field_type, PrimitiveType):
        raise ValueError(
            f"{message_name}.{field_name}: protobuf map key type {_type_display(field_type)} is not supported"
        )

    if field_type.kind not in {"string", "int", "bool", "u8", "u16", "u32", "u64", "i8", "i16", "i32", "i64"}:
        raise ValueError(f"{message_name}.{field_name}: protobuf map key type {field_type.kind} is not supported")
    type_name, fixed_length = _primitive_to_proto(field_type.kind)
    if fixed_length is not None or type_name not in {
        "string",
        "int32",
        "int64",
        "uint32",
        "uint64",
        "bool",
    }:
        raise ValueError(f"{message_name}.{field_name}: protobuf map key type {field_type.kind} is not supported")
    return type_name


def _map_value_to_proto(
    field_type: FieldType,
    *,
    message_name: str,
    field_name: str,
    semantic_index: _SemanticIndex,
) -> tuple[str, int | None, _SemanticProtoType | None, _ProtoEnum | None]:
    if isinstance(field_type, NamedType) and semantic_index.resolve(field_type.name) is None:
        raise ValueError(
            f"{message_name}.{field_name}: protobuf map value named type {field_type.name} is not supported"
        )

    type_name, enum, fixed_length, semantic, proto_map = _type_to_proto(
        field_type,
        message_name=message_name,
        field_name=field_name,
        semantic_index=semantic_index,
    )
    if proto_map is not None:
        raise ValueError(
            f"{message_name}.{field_name}: protobuf map value type {_type_display(field_type)} is not supported"
        )
    if type_name.startswith("repeated "):
        raise ValueError(
            f"{message_name}.{field_name}: protobuf map value type {_type_display(field_type)} is not supported"
        )
    return type_name.removeprefix("optional "), fixed_length, semantic, enum


def _type_display(field_type: FieldType) -> str:
    if isinstance(field_type, PrimitiveType):
        return _primitive_to_proto(field_type.kind)[0]
    if isinstance(field_type, DecimalType):
        return "decimal"
    if isinstance(field_type, FixedBinaryType):
        return f"binary({field_type.length})"
    if isinstance(field_type, NamedType):
        return field_type.name
    if isinstance(field_type, MapType):
        return f"map<{_type_display(field_type.key)}, {_type_display(field_type.value)}>"
    if isinstance(field_type, ArrayType):
        return f"array<{_type_display(field_type.item)}>"
    if isinstance(field_type, EnumType):
        return "enum"
    return type(field_type).__name__


def _primitive_to_proto(kind: str) -> tuple[str, int | None]:
    if kind in ("u128", "i128"):
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
        "u8": "uint32",
        "u16": "uint32",
        "u32": "uint32",
        "u64": "uint64",
        "i8": "int32",
        "i16": "int32",
        "i32": "int32",
        "i64": "int64",
    }.get(kind, "string"), None


def _validate_registry_id(ref: str, value: int) -> int:
    maximum = 2**32 - 1
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"registry id for {ref} must be between 1 and {maximum}")
    return value


def _semantic_declarations(
    mdl: MdlFile,
) -> dict[str, tuple[tuple[str, SemanticTypeDecl], ...]]:
    grouped: dict[str, list[tuple[str, SemanticTypeDecl]]] = {}
    for domain in mdl.domains:
        for decl in domain.semantic_types:
            grouped.setdefault(decl.name, []).append((domain.name, decl))
    return {name: tuple(sorted(candidates, key=lambda candidate: candidate[0])) for name, candidates in grouped.items()}


def _unique_semantic_decl(
    name: str,
    declarations: dict[str, tuple[tuple[str, SemanticTypeDecl], ...]],
) -> tuple[str, SemanticTypeDecl]:
    candidates = declarations.get(name, ())
    if not candidates:
        raise ValueError(f"semantic type '{name}' is not declared")
    if len(candidates) > 1:
        refs = ", ".join(f"{domain}.{decl.name}" for domain, decl in candidates)
        raise ValueError(f"ambiguous semantic type '{name}'; candidates: {refs}")
    return candidates[0]


def _semantic_terminal_type(
    decl: SemanticTypeDecl,
    declarations: dict[str, tuple[tuple[str, SemanticTypeDecl], ...]],
) -> FieldType:
    current = decl.underlying
    visited = {decl.name}
    while isinstance(current, NamedType):
        if current.name in visited:
            raise ValueError(f"semantic type cycle encountered at '{current.name}'")
        visited.add(current.name)
        _, next_decl = _unique_semantic_decl(current.name, declarations)
        current = next_decl.underlying
    return current


def _semantic_terminal_proto(field_type: FieldType) -> tuple[str, int | None]:
    if isinstance(field_type, PrimitiveType):
        return _primitive_to_proto(field_type.kind)
    if isinstance(field_type, DecimalType):
        return "string", None
    if isinstance(field_type, FixedBinaryType):
        return "bytes", field_type.length
    raise ValueError(f"unsupported semantic terminal type: {type(field_type).__name__}")


def _semantic_package(domain: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z_]+", "_", domain).strip("_").lower()
    return f"modelable.{normalized}.semantic"


def _build_semantic_index(
    mdl: MdlFile,
    registry_ids: dict[str, int] | None,
) -> _SemanticIndex:
    declarations = _semantic_declarations(mdl)
    by_name: dict[str, list[_SemanticProtoType]] = {}
    by_domain: dict[str, list[_SemanticProtoType]] = {}
    for domain in sorted(mdl.domains, key=lambda item: item.name):
        for decl in sorted(domain.semantic_types, key=lambda item: item.name):
            ref = f"{domain.name}.{decl.name}"
            terminal, fixed_length = _semantic_terminal_proto(_semantic_terminal_type(decl, declarations))
            allocated = (registry_ids or {}).get(ref) if decl.registry else None
            if allocated is not None:
                allocated = _validate_registry_id(ref, allocated)
            semantic = _SemanticProtoType(
                ref=ref,
                declaring_domain=domain.name,
                proto_type=f".{_semantic_package(domain.name)}.{decl.name}",
                underlying_type=terminal,
                fixed_length=fixed_length,
                registry_id=allocated,
            )
            by_name.setdefault(decl.name, []).append(semantic)
            by_domain.setdefault(domain.name, []).append(semantic)
    return _SemanticIndex(
        by_name={name: tuple(values) for name, values in by_name.items()},
        by_domain={domain: tuple(values) for domain, values in by_domain.items()},
    )


def _render_semantic_bundle(domain: str, definitions: tuple[_SemanticProtoType, ...]) -> str:
    lines = ['syntax = "proto3";', "", f"package {_semantic_package(domain)};", ""]
    if any(definition.underlying_type == "google.protobuf.Timestamp" for definition in definitions):
        lines.extend(['import "google/protobuf/timestamp.proto";', ""])
    for index, definition in enumerate(definitions):
        if index:
            lines.append("")
        message_name = definition.proto_type.rsplit(".", 1)[1]
        lines.extend(
            [
                f"message {message_name} {{",
                f"  {definition.underlying_type} value = 1;",
                "}",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def _emit_semantic_bundles(index: _SemanticIndex, out_dir: Path) -> list[EmittedArtifact]:
    artifacts: list[EmittedArtifact] = []
    for domain, definitions in sorted(index.by_domain.items()):
        content = _render_semantic_bundle(domain, definitions)
        ref = f"{domain}.semantic-types"
        artifacts.append(
            EmittedArtifact(
                target="protobuf",
                ref=ref,
                artifact_id=ref,
                path=out_dir / domain / "semantic-types.proto",
                content=content,
                content_hash=compute_content_hash(content),
            )
        )
    return artifacts


def _validate_reservations(
    fields: list[_ProtoField],
    reservations: ProtobufReservations | None,
    *,
    ref: str,
) -> None:
    if reservations is None:
        return
    reserved_numbers = set(reservations.numbers)
    reserved_names = set(reservations.names)
    for field in fields:
        if field.number in reserved_numbers:
            raise ValueError(f"{ref}: field {field.source_name} uses reserved protobuf field number {field.number}")
        if field.source_name in reserved_names or field.proto_name in reserved_names:
            raise ValueError(f"{ref}: field {field.source_name} uses reserved protobuf field name {field.proto_name}")


def _reservation_lines(reservations: ProtobufReservations | None) -> list[str]:
    if reservations is None:
        return []
    lines: list[str] = []
    if reservations.numbers:
        lines.append(f"  reserved {', '.join(str(number) for number in reservations.numbers)};")
    if reservations.names:
        names = ", ".join(json.dumps(name) for name in reservations.names)
        lines.append(f"  reserved {names};")
    if lines:
        lines.append("")
    return lines


def _render_proto(
    *,
    package: str,
    message_name: str,
    fields: list[_ProtoField],
    reservations: ProtobufReservations | None = None,
) -> str:
    lines = ['syntax = "proto3";', "", f"package {package};", ""]
    imports: set[str] = set()
    if any("google.protobuf.Timestamp" in field.type_name for field in fields):
        imports.add("google/protobuf/timestamp.proto")
    imports.update(f"{semantic.declaring_domain}/semantic-types.proto" for semantic in _referenced_semantics(fields))
    for import_path in sorted(imports):
        lines.append(f'import "{import_path}";')
    if imports:
        lines.append("")

    lines.append(f"message {message_name} {{")
    lines.extend(_reservation_lines(reservations))
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


def _manifest_json(
    *,
    domain: str,
    name: str,
    kind: str,
    version: ModelVersion | ProjectionVersion,
    ref: str,
    fields: list[_ProtoField],
    indexes: dict[str, object] | None = None,
    reservations: ProtobufReservations | None = None,
) -> str:
    semantics = _referenced_semantics(fields)
    schema_entry: dict[str, object] = {
        "ref": ref,
        "kind": kind,
        "schema_id": f"modelable://{domain}/{name}/v{version.version}/protobuf",
        "modelable_signature": compute_version_signature(domain, name, version),
        "schema_fingerprint": _schema_fingerprint(fields, semantics, indexes, reservations),
        "semantic_types": [_manifest_semantic(semantic, include_registry_id=True) for semantic in semantics],
        "fields": [_manifest_field(field) for field in fields],
    }
    if indexes is not None:
        schema_entry["indexes"] = indexes
    if reservations is not None:
        schema_entry["reservations"] = _manifest_reservations(reservations)
    schema = {
        "target": "protobuf",
        "schemas": [schema_entry],
    }
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def _index_decl_for(domain: DomainDef, name: str, version: int) -> IndexDecl | None:
    return next(
        (decl for decl in domain.index_decls if decl.model == name and decl.version == version),
        None,
    )


def _manifest_indexes(index_decl: IndexDecl | None) -> dict[str, object] | None:
    if index_decl is None:
        return None
    return {
        "primary": {
            "index_name": "primary",
            "index_version": index_decl.version,
            "key_fields": list(index_decl.primary),
            "sort_fields": [],
            "unique": True,
        },
        "secondary": [
            {
                "index_name": secondary.name,
                "index_version": index_decl.version,
                "key_fields": list(secondary.key),
                "sort_fields": [
                    {"field": sort_field.field, "direction": sort_field.direction} for sort_field in secondary.sort
                ],
                "unique": secondary.unique,
            }
            for secondary in index_decl.secondary
        ],
    }


def _manifest_field(field: _ProtoField) -> dict[str, object]:
    entry: dict[str, object] = {
        "name": field.source_name,
        "proto_name": field.proto_name,
        "number": field.number,
        "type": field.type_name,
        "key": field.key,
    }
    if field.fixed_length is not None:
        entry["fixed_length"] = field.fixed_length
    if field.semantic is not None:
        entry["semantic_type"] = field.semantic.ref
    if field.enum is not None:
        entry["enum_values"] = list(field.enum.values)
    if field.map is not None:
        map_entry: dict[str, object] = {
            "key_type": field.map.key_type,
            "value_type": field.map.value_type,
        }
        if field.map.value_fixed_length is not None:
            map_entry["value_fixed_length"] = field.map.value_fixed_length
        if field.map.value_semantic is not None:
            map_entry["value_semantic_type"] = field.map.value_semantic.ref
        entry["map"] = map_entry
    return entry


def _manifest_reservations(reservations: ProtobufReservations) -> dict[str, object]:
    return {
        "numbers": list(reservations.numbers),
        "names": list(reservations.names),
    }


def _manifest_semantic(semantic: _SemanticProtoType, *, include_registry_id: bool) -> dict[str, object]:
    entry: dict[str, object] = {
        "ref": semantic.ref,
        "proto_type": semantic.proto_type,
        "underlying_type": semantic.underlying_type,
    }
    if semantic.fixed_length is not None:
        entry["fixed_length"] = semantic.fixed_length
    if include_registry_id and semantic.registry_id is not None:
        entry["registry_id"] = semantic.registry_id
    return entry


def _referenced_semantics(fields: list[_ProtoField]) -> list[_SemanticProtoType]:
    by_ref = {field.semantic.ref: field.semantic for field in fields if field.semantic is not None}
    by_ref.update(
        {
            field.map.value_semantic.ref: field.map.value_semantic
            for field in fields
            if field.map is not None and field.map.value_semantic is not None
        }
    )
    return [by_ref[ref] for ref in sorted(by_ref)]


def _schema_fingerprint(
    fields: list[_ProtoField],
    semantics: list[_SemanticProtoType],
    indexes: dict[str, object] | None = None,
    reservations: ProtobufReservations | None = None,
) -> str:
    normalized: dict[str, object] = {
        "fields": [_manifest_field(field) for field in fields],
        "semantic_types": [_manifest_semantic(semantic, include_registry_id=False) for semantic in semantics],
    }
    if indexes is not None:
        normalized["indexes"] = indexes
    if reservations is not None:
        normalized["reservations"] = _manifest_reservations(reservations)
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
