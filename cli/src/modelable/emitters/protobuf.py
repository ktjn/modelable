from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from modelable.compiler.workspace import Workspace
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.base import artifact_id as _artifact_id
from modelable.emitters.naming import find_identifier_collisions, proto_domain_segment, proto_package_name
from modelable.emitters.protobuf_plan import emit_protobuf_projection_plan
from modelable.parser.ir import (
    AnnKey,
    ArrayType,
    ComputedMapping,
    DecimalType,
    DirectMapping,
    DomainDef,
    EnumRefType,
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
    latest_semantic_types,
)
from modelable.planner.plans import build_plan_documents
from modelable.planner.protocol import PLAN_V1_SCHEMA, PlanDocument
from modelable.registry.enum_numbers import EnumNumberAllocation
from modelable.registry.resolver import resolve_model_ref, resolve_semantic_type_ref
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
    enum_ref: _ProtoEnumType | None = None


@dataclass(frozen=True)
class _ProtoEnum:
    name: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class _ProtoEnumType:
    """A nominal, domain-owned enum type (evolution plan E6).

    Declared once per declaring domain in that domain's semantic-types.proto
    bundle and referenced by qualified type name everywhere it's used, unlike
    ``_ProtoEnum`` which is rendered fresh, per field, for anonymous
    ``enum(...)`` field types.
    """

    ref: str
    declaring_domain: str
    proto_type: str
    members: tuple[tuple[str, int], ...]
    reservations: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class _EnumIndex:
    by_ref: dict[str, _ProtoEnumType]


@dataclass(frozen=True)
class _ProtoMap:
    key_type: str
    value_type: str
    value_fixed_length: int | None = None
    value_semantic: _SemanticProtoType | None = None
    value_enum_ref: _ProtoEnumType | None = None


def emit_protobuf(
    workspace: Workspace,
    out_dir: Path,
    *,
    registry_ids: dict[str, int] | None = None,
    enum_numbers: dict[str, EnumNumberAllocation] | None = None,
) -> list[EmittedArtifact]:
    """Emit Protocol Buffers schema artifacts for semantic types, models, and projections."""
    semantic_index = _build_semantic_index(workspace.mdl, registry_ids)
    enum_index = _build_enum_index(workspace.mdl, enum_numbers)
    plans: dict[tuple[object, object, object], PlanDocument] = {
        (plan["domain"], plan["projection"], plan["version"]): plan
        for plan in build_plan_documents(workspace, schema=PLAN_V1_SCHEMA)
    }
    artifacts = _emit_semantic_bundles(semantic_index, enum_index, out_dir)
    for domain in workspace.mdl.domains:
        for model_name, model_versions in domain.models.items():
            for model_version in model_versions:
                proto, manifest = _emit_model_version(
                    domain,
                    model_name,
                    model_version,
                    out_dir,
                    workspace.mdl,
                    semantic_index,
                    enum_index,
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
                    enum_index,
                    plan=plans.get((domain.name, projection_name, projection_version.version)),
                )
                artifacts.extend([proto, manifest])
    return artifacts


def _emit_model_version(
    domain: DomainDef,
    model_name: str,
    version: ModelVersion,
    out_dir: Path,
    mdl: MdlFile,
    semantic_index: _SemanticIndex,
    enum_index: _EnumIndex,
) -> tuple[EmittedArtifact, EmittedArtifact]:
    artifact_id = _artifact_id(domain.name, model_name, version.version)
    proto_fields = [
        _field_to_proto(
            field,
            mdl,
            domain_name=domain.name,
            message_name=model_name,
            field_number=index,
            semantic_index=semantic_index,
            enum_index=enum_index,
        )
        for index, field in enumerate(version.fields, start=1)
    ]
    _validate_reservations(
        proto_fields,
        version.protobuf_reservations,
        ref=f"{domain.name}.{model_name}@{version.version}",
    )
    proto_content = _render_proto(
        package=proto_package_name(domain.name, version.version),
        message_name=model_name,
        fields=proto_fields,
        reservations=version.protobuf_reservations,
        enum_imports=_referenced_enum_imports(proto_fields),
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
    enum_index: _EnumIndex,
    plan: PlanDocument | None = None,
) -> tuple[EmittedArtifact, EmittedArtifact]:
    if plan is not None and _can_route_protobuf_projection_plan(plan, version):
        return emit_protobuf_projection_plan(
            plan,
            out_dir,
            modelable_signature=compute_version_signature(domain.name, projection_name, version),
        )
    artifact_id = _artifact_id(domain.name, projection_name, version.version)
    proto_fields = [
        _projection_field_to_proto(
            field,
            version,
            mdl,
            domain_name=domain.name,
            message_name=projection_name,
            field_number=index,
            semantic_index=semantic_index,
            enum_index=enum_index,
        )
        for index, field in enumerate(version.fields, start=1)
    ]
    _validate_reservations(
        proto_fields,
        version.protobuf_reservations,
        ref=f"{domain.name}.{projection_name}@{version.version}",
    )
    proto_content = _render_proto(
        package=proto_package_name(domain.name, version.version),
        message_name=projection_name,
        fields=proto_fields,
        reservations=version.protobuf_reservations,
        enum_imports=_referenced_enum_imports(proto_fields),
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


def _can_route_protobuf_projection_plan(plan: PlanDocument, version: ProjectionVersion) -> bool:
    """Route only scalar projection facts represented by plan/v0 in this slice."""
    if plan.get("joins") or version.protobuf_reservations is not None:
        return False
    fields = plan.get("fields")
    if not isinstance(fields, list):
        return False
    for field in fields:
        if not isinstance(field, dict) or field.get("kind") not in {"direct", "computed"}:
            return False
        field_type = field.get("type")
        if not isinstance(field_type, dict) or field_type.get("kind") not in {
            "string",
            "uuid",
            "date",
            "time",
            "duration",
            "int",
            "float",
            "bool",
            "timestamp",
            "binary",
            "json",
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
            "decimal",
            "fixed_binary",
            "primitive",
        }:
            return False
    return True


def _field_to_proto(
    field: FieldDef,
    mdl: MdlFile,
    *,
    domain_name: str,
    message_name: str,
    field_number: int,
    semantic_index: _SemanticIndex,
    enum_index: _EnumIndex,
) -> _ProtoField:
    type_name, enum, fixed_length, semantic, proto_map, enum_ref = _type_to_proto(
        field.type,
        mdl,
        domain_name=domain_name,
        message_name=message_name,
        field_name=field.name,
        semantic_index=semantic_index,
        enum_index=enum_index,
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
        enum_ref=enum_ref,
    )


def _projection_field_to_proto(
    field: ProjectionField,
    projection: ProjectionVersion,
    mdl: MdlFile,
    *,
    domain_name: str,
    message_name: str,
    field_number: int,
    semantic_index: _SemanticIndex,
    enum_index: _EnumIndex,
) -> _ProtoField:
    field_type = _resolve_projection_field_type(field, projection, mdl)
    type_name, enum, fixed_length, semantic, proto_map, enum_ref = _type_to_proto(
        field_type,
        mdl,
        domain_name=domain_name,
        message_name=message_name,
        field_name=field.name,
        semantic_index=semantic_index,
        enum_index=enum_index,
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
        enum_ref=enum_ref,
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
    mdl: MdlFile,
    *,
    domain_name: str,
    message_name: str,
    field_name: str,
    semantic_index: _SemanticIndex,
    enum_index: _EnumIndex,
) -> tuple[str, _ProtoEnum | None, int | None, _SemanticProtoType | None, _ProtoMap | None, _ProtoEnumType | None]:
    if isinstance(field_type, PrimitiveType):
        type_name, fixed_length = _primitive_to_proto(field_type.kind)
        return type_name, None, fixed_length, None, None, None
    if isinstance(field_type, DecimalType):
        return "string", None, None, None, None, None
    if isinstance(field_type, FixedBinaryType):
        return "bytes", None, field_type.length, None, None, None
    if isinstance(field_type, NamedType):
        semantic = semantic_index.resolve(field_type.name)
        if semantic is not None:
            return semantic.proto_type, None, None, semantic, None, None
        return "bytes", None, None, None, None, None
    if isinstance(field_type, EnumRefType):
        declaring_domain, decl = resolve_semantic_type_ref(mdl, domain_name, field_type.name, field_type.version)
        enum_ref = enum_index.by_ref[f"{declaring_domain}.{decl.name}"]
        return enum_ref.proto_type, None, None, None, None, enum_ref
    if isinstance(field_type, MapType):
        key_type = _map_key_to_proto(field_type.key, message_name=message_name, field_name=field_name)
        value_type, value_fixed_length, value_semantic, value_enum, value_enum_ref = _map_value_to_proto(
            field_type.value,
            mdl,
            domain_name=domain_name,
            message_name=message_name,
            field_name=field_name,
            semantic_index=semantic_index,
            enum_index=enum_index,
        )
        proto_map = _ProtoMap(
            key_type=key_type,
            value_type=value_type,
            value_fixed_length=value_fixed_length,
            value_semantic=value_semantic,
            value_enum_ref=value_enum_ref,
        )
        return f"map<{key_type}, {value_type}>", value_enum, None, None, proto_map, None
    if isinstance(field_type, ArrayType):
        inner, _, _, semantic, item_map, item_enum_ref = _type_to_proto(
            field_type.item,
            mdl,
            domain_name=domain_name,
            message_name=message_name,
            field_name=field_name,
            semantic_index=semantic_index,
            enum_index=enum_index,
        )
        if item_map is not None:
            raise ValueError(f"protobuf field '{field_name}' cannot use a map inside an array")
        return f"repeated {inner.removeprefix('optional ')}", None, None, semantic, None, item_enum_ref
    if isinstance(field_type, EnumType):
        enum = _ProtoEnum(name=f"{message_name}{_pascal_case(field_name)}", values=tuple(field_type.values))
        return enum.name, enum, None, None, None, None
    return "bytes", None, None, None, None, None


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
    mdl: MdlFile,
    *,
    domain_name: str,
    message_name: str,
    field_name: str,
    semantic_index: _SemanticIndex,
    enum_index: _EnumIndex,
) -> tuple[str, int | None, _SemanticProtoType | None, _ProtoEnum | None, _ProtoEnumType | None]:
    if isinstance(field_type, NamedType) and semantic_index.resolve(field_type.name) is None:
        raise ValueError(
            f"{message_name}.{field_name}: protobuf map value named type {field_type.name} is not supported"
        )

    type_name, enum, fixed_length, semantic, proto_map, enum_ref = _type_to_proto(
        field_type,
        mdl,
        domain_name=domain_name,
        message_name=message_name,
        field_name=field_name,
        semantic_index=semantic_index,
        enum_index=enum_index,
    )
    if proto_map is not None:
        raise ValueError(
            f"{message_name}.{field_name}: protobuf map value type {_type_display(field_type)} is not supported"
        )
    if type_name.startswith("repeated "):
        raise ValueError(
            f"{message_name}.{field_name}: protobuf map value type {_type_display(field_type)} is not supported"
        )
    return type_name.removeprefix("optional "), fixed_length, semantic, enum, enum_ref


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
        for decl in latest_semantic_types(domain):
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


class _EnumFamilyTerminalError(Exception):
    """The semantic declaration's terminal type is enum-backed.

    Enum-backed declarations (directly ``enum(...)`` or aliasing another
    enum-backed declaration) are not protobuf scalar wrapper types; the enum
    index (evolution plan E6) handles them separately.
    """


def _semantic_terminal_type(
    decl: SemanticTypeDecl,
    declarations: dict[str, tuple[tuple[str, SemanticTypeDecl], ...]],
) -> FieldType:
    current = decl.underlying
    visited = {decl.name}
    while True:
        if isinstance(current, (EnumType, EnumRefType)):
            raise _EnumFamilyTerminalError()
        if not isinstance(current, NamedType):
            return current
        if current.name in visited:
            raise ValueError(f"semantic type cycle encountered at '{current.name}'")
        visited.add(current.name)
        _, next_decl = _unique_semantic_decl(current.name, declarations)
        current = next_decl.underlying


def _semantic_terminal_proto(field_type: FieldType) -> tuple[str, int | None]:
    if isinstance(field_type, PrimitiveType):
        return _primitive_to_proto(field_type.kind)
    if isinstance(field_type, DecimalType):
        return "string", None
    if isinstance(field_type, FixedBinaryType):
        return "bytes", field_type.length
    raise ValueError(f"unsupported semantic terminal type: {type(field_type).__name__}")


def _semantic_package(domain: str) -> str:
    return f"modelable.{proto_domain_segment(domain)}.semantic"


def _build_semantic_index(
    mdl: MdlFile,
    registry_ids: dict[str, int] | None,
) -> _SemanticIndex:
    declarations = _semantic_declarations(mdl)
    by_name: dict[str, list[_SemanticProtoType]] = {}
    by_domain: dict[str, list[_SemanticProtoType]] = {}
    for domain in sorted(mdl.domains, key=lambda item: item.name):
        for decl in sorted(latest_semantic_types(domain), key=lambda item: item.name):
            ref = f"{domain.name}.{decl.name}"
            try:
                terminal_type = _semantic_terminal_type(decl, declarations)
            except _EnumFamilyTerminalError:
                continue
            terminal, fixed_length = _semantic_terminal_proto(terminal_type)
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


def _build_enum_index(
    mdl: MdlFile,
    enum_numbers: dict[str, EnumNumberAllocation] | None,
) -> _EnumIndex:
    """Build the shared nominal-enum index (evolution plan E6).

    One ``_ProtoEnumType`` per enum-backed semantic declaration, shared by
    every field that references it, keyed by qualified declaration name.
    Numbers come from the persisted allocation ledger when available;
    otherwise they fall back to declaration order, which is not guaranteed
    stable across edits.
    """
    by_ref: dict[str, _ProtoEnumType] = {}
    for domain in sorted(mdl.domains, key=lambda item: item.name):
        for decl in sorted(latest_semantic_types(domain), key=lambda item: item.name):
            if not isinstance(decl.underlying, EnumType):
                continue
            ref = f"{domain.name}.{decl.name}"
            allocation = (enum_numbers or {}).get(ref)
            if allocation is not None:
                members = allocation.members
                reservations = allocation.reservations
            else:
                members = tuple((value, index) for index, value in enumerate(decl.underlying.values, start=1))
                reservations = ()
            by_ref[ref] = _ProtoEnumType(
                ref=ref,
                declaring_domain=domain.name,
                proto_type=f".{_semantic_package(domain.name)}.{decl.name}",
                members=members,
                reservations=reservations,
            )
    return _EnumIndex(by_ref=by_ref)


def _render_enum_block(name: str, enum_type: _ProtoEnumType) -> list[str]:
    prefix = _enum_prefix(name)
    member_values = [member for member, _ in enum_type.members]

    def _proto_identifier(value: str, _prefix: str = prefix) -> str:
        return f"{_prefix}_{_enum_value(value)}"

    for identifier, colliding in find_identifier_collisions(member_values, _proto_identifier).items():
        raise ValueError(
            f"{enum_type.ref}: protobuf enum '{name}' member collision: "
            + ", ".join(f"'{member}'" for member in colliding)
            + f" all generate identifier '{identifier}'"
        )

    lines = [f"enum {name} {{"]
    if enum_type.reservations:
        numbers = ", ".join(str(number) for _, number in enum_type.reservations)
        names = ", ".join(json.dumps(member) for member, _ in enum_type.reservations)
        lines.append(f"  reserved {numbers};")
        lines.append(f"  reserved {names};")
    lines.append(f"  {prefix}_UNSPECIFIED = 0;")
    for member, number in enum_type.members:
        lines.append(f"  {prefix}_{_enum_value(member)} = {number};")
    lines.append("}")
    return lines


def _render_semantic_bundle(
    domain: str,
    definitions: tuple[_SemanticProtoType, ...],
    enum_definitions: tuple[tuple[str, _ProtoEnumType], ...],
) -> str:
    lines = ['syntax = "proto3";', "", f"package {_semantic_package(domain)};", ""]
    if any(definition.underlying_type == "google.protobuf.Timestamp" for definition in definitions):
        lines.extend(['import "google/protobuf/timestamp.proto";', ""])
    first = True
    for definition in definitions:
        if not first:
            lines.append("")
        first = False
        message_name = definition.proto_type.rsplit(".", 1)[1]
        lines.extend(
            [
                f"message {message_name} {{",
                f"  {definition.underlying_type} value = 1;",
                "}",
            ]
        )
    for name, enum_type in enum_definitions:
        if not first:
            lines.append("")
        first = False
        lines.extend(_render_enum_block(name, enum_type))
    lines.append("")
    return "\n".join(lines)


def _emit_semantic_bundles(
    semantic_index: _SemanticIndex,
    enum_index: _EnumIndex,
    out_dir: Path,
) -> list[EmittedArtifact]:
    enum_by_domain: dict[str, list[tuple[str, _ProtoEnumType]]] = {}
    for enum_type in enum_index.by_ref.values():
        name = enum_type.proto_type.rsplit(".", 1)[1]
        enum_by_domain.setdefault(enum_type.declaring_domain, []).append((name, enum_type))

    artifacts: list[EmittedArtifact] = []
    for domain in sorted(set(semantic_index.by_domain) | set(enum_by_domain)):
        definitions = semantic_index.by_domain.get(domain, ())
        enum_definitions = tuple(sorted(enum_by_domain.get(domain, [])))
        content = _render_semantic_bundle(domain, definitions, enum_definitions)
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


def _referenced_enum_imports(fields: list[_ProtoField]) -> set[str]:
    domains = {field.enum_ref.declaring_domain for field in fields if field.enum_ref is not None}
    domains.update(
        field.map.value_enum_ref.declaring_domain
        for field in fields
        if field.map is not None and field.map.value_enum_ref is not None
    )
    return {f"{domain}/semantic-types.proto" for domain in domains}


def _render_proto(
    *,
    package: str,
    message_name: str,
    fields: list[_ProtoField],
    reservations: ProtobufReservations | None = None,
    enum_imports: set[str] | None = None,
) -> str:
    lines = ['syntax = "proto3";', "", f"package {package};", ""]
    imports: set[str] = set()
    if any("google.protobuf.Timestamp" in field.type_name for field in fields):
        imports.add("google/protobuf/timestamp.proto")
    imports.update(f"{semantic.declaring_domain}/semantic-types.proto" for semantic in _referenced_semantics(fields))
    imports.update(enum_imports or ())
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

        def _proto_identifier(value: str, _prefix: str = prefix) -> str:
            return f"{_prefix}_{_enum_value(value)}"

        for identifier, members in find_identifier_collisions(list(enum.values), _proto_identifier).items():
            raise ValueError(
                f"{package}.{message_name}: protobuf enum '{enum.name}' member collision: "
                + ", ".join(f"'{member}'" for member in members)
                + f" all generate identifier '{identifier}'"
            )
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
    if field.enum_ref is not None:
        entry["enum_type"] = field.enum_ref.ref
        entry["enum_numbers"] = dict(field.enum_ref.members)
        if field.enum_ref.reservations:
            entry["enum_reservations"] = dict(field.enum_ref.reservations)
    if field.map is not None:
        map_entry: dict[str, object] = {
            "key_type": field.map.key_type,
            "value_type": field.map.value_type,
        }
        if field.map.value_fixed_length is not None:
            map_entry["value_fixed_length"] = field.map.value_fixed_length
        if field.map.value_semantic is not None:
            map_entry["value_semantic_type"] = field.map.value_semantic.ref
        if field.map.value_enum_ref is not None:
            map_entry["value_enum_type"] = field.map.value_enum_ref.ref
            map_entry["value_enum_numbers"] = dict(field.map.value_enum_ref.members)
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
