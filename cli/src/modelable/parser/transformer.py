from __future__ import annotations

from typing import Any, Literal, cast

from lark import Transformer

from modelable.parser.ir import (
    AccessBlock,
    AccessGrant,
    AiConfig,
    AnnClassification,
    AnnCustom,
    AnnDeprecated,
    AnnKey,
    AnnLatestBefore,
    AnnLatestOnly,
    Annotation,
    AnnOwner,
    AnnPii,
    AnnPitCutoff,
    AnnServer,
    AnnWire,
    ApiDecl,
    ApiOperation,
    ApiResponse,
    ArrayType,
    AutoProjectionDecl,
    AutoProjectionTarget,
    BindingDef,
    ChangeKind,
    ComputedMapping,
    DecimalType,
    DirectMapping,
    DomainDef,
    EnumType,
    FieldDef,
    FieldMapping,
    FieldType,
    FixedBinaryType,
    GenerateTarget,
    IndexDecl,
    JoinRef,
    MapType,
    MdlFile,
    ModelKind,
    ModelVersion,
    NamedType,
    ObjectType,
    PackageConfig,
    PrimitiveType,
    ProjectionField,
    ProjectionVersion,
    ProtobufReservations,
    RefType,
    SecondaryIndexDecl,
    SelectionClause,
    SemanticTypeDecl,
    SortField,
    SourceRef,
    UnionType,
    UnionVariant,
    ValueConstraint,
    VersionExact,
    VersionMin,
    VersionPinned,
    VersionRange,
    WireTargetHint,
    WorkspaceDef,
)

ANNOTATION_TYPES = (
    AnnKey,
    AnnPii,
    AnnClassification,
    AnnDeprecated,
    AnnOwner,
    AnnServer,
    AnnWire,
    AnnPitCutoff,
    AnnLatestBefore,
    AnnLatestOnly,
    AnnCustom,
)


def _str(value: object) -> str:
    text = str(value)
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1]
    return text


def _build_selection_clause(mode: Literal["pick", "omit"], items: list[object]) -> SelectionClause:
    field_names: list[str] = []
    qualified_fields: list[tuple[str, str]] = []
    annotations: list[Annotation] = []
    for item in items:
        if isinstance(item, ANNOTATION_TYPES):
            annotations.append(item)
        elif isinstance(item, str) and "." in item:
            alias, field_name = item.split(".", 1)
            qualified_fields.append((alias, field_name))
        else:
            field_names.append(str(item))
    return SelectionClause(
        mode=mode,
        field_names=field_names,
        qualified_fields=qualified_fields,
        annotations=annotations,
    )


class MdlTransformer(Transformer[list[object], Any]):
    def start(self, items: list[object]) -> MdlFile:
        domains: list[DomainDef] = []
        bindings: list[BindingDef] = []
        workspace: WorkspaceDef | None = None
        for item in items:
            if isinstance(item, DomainDef):
                domains.append(item)
            elif isinstance(item, BindingDef):
                bindings.append(item)
            elif isinstance(item, WorkspaceDef):
                workspace = item
        return MdlFile(domains=domains, bindings=bindings, workspace=workspace)

    def statement(self, items: list[object]) -> object:
        return items[0]

    def domain_decl(self, items: list[object]) -> DomainDef:
        name = _str(items[0])
        owner = None
        contact = None
        description = None
        models: dict[str, list[ModelVersion]] = {}
        projections: dict[str, list[ProjectionVersion]] = {}
        auto_projections: list[AutoProjectionDecl] = []
        apis: list[ApiDecl] = []
        generate_targets: list[GenerateTarget] = []
        semantic_types: list[SemanticTypeDecl] = []
        index_decls: list[IndexDecl] = []

        for tag, value in [item for item in items[1:] if isinstance(item, tuple)]:
            if tag == "owner":
                owner = value
            elif tag == "contact":
                contact = value
            elif tag == "description":
                description = value
            elif tag == "model":
                model_name, model_version = value
                models.setdefault(model_name, []).append(model_version)
            elif tag == "projection":
                projection_name, projection_version = value
                projections.setdefault(projection_name, []).append(projection_version)
            elif tag == "auto_projection":
                auto_projections.append(value)
            elif tag == "api":
                apis.append(value)
            elif tag == "generate":
                generate_targets = value
            elif tag == "semantic":
                semantic_types.append(value)
            elif tag == "index":
                index_decls.append(value)

        return DomainDef(
            name=name,
            owner=owner,
            contact=contact,
            description=description,
            models=models,
            projections=projections,
            auto_projections=auto_projections,
            apis=apis,
            generate_targets=generate_targets,
            semantic_types=semantic_types,
            index_decls=index_decls,
        )

    def domain_name(self, items: list[object]) -> str:
        return _str(items[0])

    def domain_item(self, items: list[object]) -> object:
        return items[0]

    def owner_attr(self, items: list[object]) -> tuple[str, str]:
        return ("owner", _str(items[0]))

    def contact_attr(self, items: list[object]) -> tuple[str, str]:
        return ("contact", _str(items[0]))

    def desc_attr(self, items: list[object]) -> tuple[str, str]:
        return ("description", _str(items[0]))

    def model_decl(self, items: list[object]) -> tuple[str, tuple[str, ModelVersion]]:
        annotations = [item for item in items if isinstance(item, ANNOTATION_TYPES)]
        items = [item for item in items if not isinstance(item, ANNOTATION_TYPES)]
        name = str(items[1])
        header = items[2] if len(items) > 2 and isinstance(items[2], tuple) and items[2][0] == "model_header" else None
        body_start = 3 if header is not None else 2
        version = header[1] if header is not None else 0
        change_kind = header[2] if header is not None else ChangeKind.additive
        has_change_kind = header[3] if header is not None else False
        access = next((item for item in items[body_start:] if isinstance(item, AccessBlock)), None)
        reservation = next((item for item in items[body_start:] if isinstance(item, ProtobufReservations)), None)
        model_kind = items[0] if isinstance(items[0], ModelKind) else ModelKind.entity
        model_version = ModelVersion(
            model_kind=model_kind,
            version=int(version) if isinstance(version, (int, str)) else 0,
            change_kind=change_kind if isinstance(change_kind, ChangeKind) else ChangeKind.additive,
            fields=[item for item in items[body_start:] if isinstance(item, FieldDef)],
            access=access,
            has_version_header=header is not None,
            has_change_kind=has_change_kind,
            annotations=annotations,
            protobuf_reservations=reservation,
        )
        return ("model", (name, model_version))

    def model_header(self, items: list[object]) -> tuple[str, int, ChangeKind, bool]:
        if len(items) == 1 and isinstance(items[0], tuple):
            h = items[0]
            return (
                "model_header",
                int(h[1]) if len(h) > 1 else 0,
                h[2] if len(h) > 2 and isinstance(h[2], ChangeKind) else ChangeKind.additive,
                True,
            )
        if len(items) == 2:
            v = int(items[0]) if isinstance(items[0], (int, str)) else 0
            ck = items[1] if isinstance(items[1], ChangeKind) else ChangeKind.additive
            return ("model_header", v, ck, True)
        return ("model_header", 0, ChangeKind.additive, False)

    def model_change(self, items: list[object]) -> object:
        return items[0]

    def model_body_item(self, items: list[object]) -> object:
        return items[0]

    def mk_entity(self, _items: list[object]) -> ModelKind:
        return ModelKind.entity

    def mk_aggregate(self, _items: list[object]) -> ModelKind:
        return ModelKind.aggregate

    def mk_event(self, _items: list[object]) -> ModelKind:
        return ModelKind.event

    def mk_value(self, _items: list[object]) -> ModelKind:
        return ModelKind.value

    def ck_additive(self, _items: list[object]) -> ChangeKind:
        return ChangeKind.additive

    def ck_breaking(self, _items: list[object]) -> ChangeKind:
        return ChangeKind.breaking

    def bl_true(self, _items: list[object]) -> bool:
        return True

    def bl_false(self, _items: list[object]) -> bool:
        return False

    def bool_literal(self, items: list[object]) -> bool:
        return items[0]  # type: ignore[return-value]

    def semantic_item(self, items: list[object]) -> tuple[str, bool]:
        return ("registry", items[0])  # type: ignore[return-value]

    def semantic_body(self, items: list[object]) -> dict[str, bool]:
        return dict(items)  # type: ignore[arg-type]

    def semantic_decl(self, items: list[object]) -> tuple[str, SemanticTypeDecl]:
        name = str(items[0])
        header = cast(
            tuple[str, int, ChangeKind, bool] | None,
            items[1] if len(items) > 1 and isinstance(items[1], tuple) else None,
        )
        underlying = items[2] if header is not None else items[1]
        body_index = 3 if header is not None else 2
        body = cast(
            dict[str, bool],
            items[body_index] if len(items) > body_index and isinstance(items[body_index], dict) else {},
        )
        version = header[1] if header is not None else 0
        change_kind = header[2] if header is not None else ChangeKind.additive
        has_change_kind = header[3] if header is not None else False
        return (
            "semantic",
            SemanticTypeDecl(
                name=name,
                underlying=underlying,  # type: ignore[arg-type]
                version=int(version),
                change_kind=change_kind.value if isinstance(change_kind, ChangeKind) else "additive",
                has_version_header=header is not None,
                has_change_kind=has_change_kind,
                registry=body.get("registry", False),
            ),
        )

    def semantic_header(self, items: list[object]) -> tuple[str, int, ChangeKind, bool]:
        if not items:
            return ("semantic_header", 0, ChangeKind.additive, False)
        version = int(cast(int | str, items[0]))
        change_kind = items[1] if len(items) > 1 and isinstance(items[1], ChangeKind) else ChangeKind.additive
        return ("semantic_header", version, change_kind, len(items) > 1)

    def semantic_change(self, items: list[object]) -> ChangeKind:
        return items[0]  # type: ignore[return-value]

    def sd_asc(self, _items: list[object]) -> str:
        return "asc"

    def sd_desc(self, _items: list[object]) -> str:
        return "desc"

    def sort_dir(self, items: list[object]) -> str:
        return items[0]  # type: ignore[return-value]

    def sort_field(self, items: list[object]) -> SortField:
        direction = items[1] if len(items) > 1 else "asc"
        return SortField(field=str(items[0]), direction=direction)  # type: ignore[arg-type]

    def key_item(self, items: list[object]) -> tuple[str, list[str]]:
        return ("key", [str(item) for item in items])

    def sort_item(self, items: list[object]) -> tuple[str, list[SortField]]:
        return ("sort", list(items))  # type: ignore[arg-type]

    def unique_item(self, items: list[object]) -> tuple[str, bool]:
        return ("unique", items[0])  # type: ignore[return-value]

    def secondary_index_item(self, items: list[object]) -> tuple[str, object]:
        return items[0]  # type: ignore[return-value]

    def secondary_index(self, items: list[object]) -> SecondaryIndexDecl:
        name = str(items[0])
        parts: dict[str, object] = dict(item for item in items[1:] if isinstance(item, tuple))
        return SecondaryIndexDecl(
            name=name,
            key=parts.get("key", []),  # type: ignore[arg-type]
            sort=parts.get("sort", []),  # type: ignore[arg-type]
            unique=parts.get("unique", False),  # type: ignore[arg-type]
        )

    def primary_index(self, items: list[object]) -> tuple[str, list[str]]:
        return ("primary", [str(item) for item in items])

    def index_item(self, items: list[object]) -> object:
        return items[0]

    def index_decl(self, items: list[object]) -> tuple[str, IndexDecl]:
        model = str(items[0])
        version = int(items[1])
        primary: list[str] = []
        secondary: list[SecondaryIndexDecl] = []
        for item in items[2:]:
            if isinstance(item, tuple) and item[0] == "primary":
                primary = item[1]
            elif isinstance(item, SecondaryIndexDecl):
                secondary.append(item)
        return (
            "index",
            IndexDecl(model=model, version=version, primary=primary, secondary=secondary),
        )

    def field_decl(self, items: list[object]) -> FieldDef:
        annotations = [item for item in items if isinstance(item, ANNOTATION_TYPES)]
        rest = [item for item in items if not isinstance(item, ANNOTATION_TYPES)]
        default = next((item[1] for item in rest if isinstance(item, tuple) and item[0] == "default"), None)
        constraints = [
            ValueConstraint(kind=key, value=value)
            for item in rest
            if isinstance(item, tuple) and item[0] == "constraints"
            for key, value in item[1].items()
        ]
        type_item = next(
            (
                item
                for item in rest
                if not isinstance(item, str) and not (isinstance(item, tuple) and item[0] == "default")
            ),
            None,
        )
        return FieldDef(
            name=str(rest[0]),
            optional=any(item == "?" for item in rest),
            nullable=sum(item == "?" for item in rest) > 1
            or any(isinstance(item, str) and item == "nullable" for item in rest),
            type=type_item
            if isinstance(
                type_item,
                (
                    PrimitiveType,
                    DecimalType,
                    FixedBinaryType,
                    ArrayType,
                    MapType,
                    RefType,
                    EnumType,
                    ObjectType,
                    NamedType,
                    UnionType,
                ),
            )
            else PrimitiveType(kind="string"),
            default=default,
            annotations=annotations,
            constraints=constraints,
        )

    def constraint_clause(self, items: list[object]) -> tuple[str, dict[str, object]]:
        values = {str(item[0]): item[1] for item in items if isinstance(item, tuple) and len(item) == 2}
        return ("constraints", values)

    def constraint_item(self, items: list[object]) -> tuple[str, object]:
        return str(items[0]), items[1]

    def constraint_string(self, items: list[object]) -> str:
        return _str(items[0])

    def constraint_number(self, items: list[object]) -> int | float:
        value = str(items[0])
        return float(value) if "." in value else int(value)

    def constraint_true(self, _items: list[object]) -> bool:
        return True

    def constraint_false(self, _items: list[object]) -> bool:
        return False

    def optional_marker(self, _items: list[object]) -> str:
        return "?"

    def nullable_marker(self, _items: list[object]) -> str:
        return "nullable"

    def field_default(self, items: list[object]) -> tuple[str, str]:
        return ("default", str(items[0]).strip())

    def reserved_numbers(self, items: list[object]) -> tuple[str, list[int]]:
        return ("numbers", [int(str(item)) for item in items])

    def reserved_names(self, items: list[object]) -> tuple[str, list[str]]:
        return ("names", [_str(item) for item in items])

    def reservation_item(self, items: list[object]) -> object:
        return items[0]

    def reservation_block(self, items: list[object]) -> ProtobufReservations:
        parts: dict[str, object] = {}
        for item in items:
            if isinstance(item, tuple):
                parts[item[0]] = item[1]
        return ProtobufReservations(
            numbers=parts.get("numbers", []),  # type: ignore[arg-type]
            names=parts.get("names", []),  # type: ignore[arg-type]
        )

    def ann_key(self, _items: list[object]) -> AnnKey:
        return AnnKey()

    def ann_pii(self, _items: list[object]) -> AnnPii:
        return AnnPii()

    def ann_classification(self, items: list[object]) -> AnnClassification:
        return AnnClassification(level=_str(items[0]))

    def ann_deprecated(self, items: list[object]) -> AnnDeprecated:
        return AnnDeprecated(replaced_by=_str(items[0]))

    def ann_owner(self, items: list[object]) -> AnnOwner:
        return AnnOwner(team=_str(items[0]))

    def ann_server(self, _items: list[object]) -> AnnServer:
        return AnnServer()

    def ann_wire(self, items: list[object]) -> AnnWire:
        targets: dict[str, WireTargetHint] = {}
        for target, modifier, value in items:
            hint = targets.get(target, WireTargetHint())
            if modifier is None:
                if hint.encoding is not None and hint.encoding != value:
                    raise ValueError(
                        f"conflicting wire encodings for target '{target}': {hint.encoding!r} vs {value!r}"
                    )
                hint.encoding = value
            elif modifier == "type":
                if hint.type is not None and hint.type != value:
                    raise ValueError(f"conflicting wire types for target '{target}': {hint.type!r} vs {value!r}")
                hint.type = value
            elif modifier == "case":
                if hint.case is not None and hint.case != value:
                    raise ValueError(f"conflicting wire cases for target '{target}': {hint.case!r} vs {value!r}")
                hint.case = value
            elif modifier == "overrides":
                overlap = sorted(set(hint.overrides) & set(value))
                for key in overlap:
                    if hint.overrides[key] != value[key]:
                        raise ValueError(
                            f"conflicting wire override for target '{target}' member '{key}': "
                            f"{hint.overrides[key]!r} vs {value[key]!r}"
                        )
                hint.overrides.update(value)
            elif modifier == "fieldCase":
                if hint.field_case is not None and hint.field_case != value:
                    raise ValueError(
                        f"conflicting wire field cases for target '{target}': {hint.field_case!r} vs {value!r}"
                    )
                hint.field_case = value
            else:
                raise ValueError(f"unsupported wire modifier: {modifier}")
            targets[target] = hint
        return AnnWire(targets=targets)

    def ann_pit_cutoff(self, items: list[object]) -> AnnPitCutoff:
        return AnnPitCutoff(expression=str(items[0]).strip())

    def ann_latest_before(self, items: list[object]) -> AnnLatestBefore:
        return AnnLatestBefore(expression=str(items[0]).strip())

    def ann_latest_only(self, _items: list[object]) -> AnnLatestOnly:
        return AnnLatestOnly()

    def ann_custom(self, items: list[object]) -> AnnCustom:
        name = str(items[0])
        expression = str(items[1]).strip() if len(items) > 1 else None
        return AnnCustom(name=name, expression=expression)

    def annotation(self, items: list[object]) -> object:
        return items[0]

    def wire_option(self, items: list[object]) -> tuple[object, object, object]:
        target, modifier = items[0]
        return target, modifier, items[1]

    def wire_key(self, items: list[object]) -> tuple[str, str | None]:
        if len(items) == 1:
            return str(items[0]), None
        return str(items[0]), str(items[1])

    def wire_string(self, items: list[object]) -> str:
        return _str(items[0])

    def wire_value(self, items: list[object]) -> object:
        return items[0]

    def wire_map(self, items: list[object]) -> dict[str, object]:
        return dict(items)

    def wire_map_item(self, items: list[object]) -> tuple[str, str]:
        return str(items[0]), _str(items[1])

    def type_expr(self, items: list[object]) -> FieldType:
        item = items[0]
        if isinstance(item, str):
            return NamedType(name=item)
        return item  # type: ignore[return-value]

    def pt_string(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="string")

    def pt_int(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="int")

    def pt_float(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="float")

    def pt_bool(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="bool")

    def pt_date(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="date")

    def pt_time(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="time")

    def pt_timestamp(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="timestamp")

    def pt_uuid(self, items: list[object]) -> PrimitiveType:
        if not items:
            return PrimitiveType(kind="uuid")
        version = int(items[0])
        if version not in (4, 7):
            raise ValueError(f"uuid version must be 4 or 7, got {version}")
        return PrimitiveType(kind="uuid", version=version)

    def pt_duration(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="duration")

    def pt_binary(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="binary")

    def pt_json(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="json")

    def pt_u8(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="u8")

    def pt_u16(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="u16")

    def pt_u32(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="u32")

    def pt_u64(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="u64")

    def pt_u128(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="u128")

    def pt_i8(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="i8")

    def pt_i16(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="i16")

    def pt_i32(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="i32")

    def pt_i64(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="i64")

    def pt_i128(self, _items: list[object]) -> PrimitiveType:
        return PrimitiveType(kind="i128")

    def primitive_type(self, items: list[object]) -> object:
        return items[0]

    def decimal_type(self, items: list[object]) -> DecimalType:
        return DecimalType(precision=int(items[0]), scale=int(items[1]))

    def fixed_binary_type(self, items: list[object]) -> FixedBinaryType:
        return FixedBinaryType(length=int(items[0]))

    def enum_member(self, items: list[object]) -> str:
        return str(items[0])

    def enum_type(self, items: list[object]) -> EnumType:
        return EnumType(values=[str(item) for item in items])

    def array_type(self, items: list[object]) -> ArrayType:
        return ArrayType(item=items[0])

    def map_type(self, items: list[object]) -> MapType:
        return MapType(key=items[0], value=items[1])

    def ref_type(self, items: list[object]) -> RefType:
        version = items[1] if len(items) > 1 else None
        return RefType(target=str(items[0]), version=version)

    def object_type(self, items: list[object]) -> ObjectType:
        return ObjectType(fields=[item for item in items if isinstance(item, FieldDef)])

    def union_variant(self, items: list[object]) -> UnionVariant:
        return UnionVariant(tag=str(items[0]), type=items[1])

    def union_type(self, items: list[object]) -> UnionType:
        return UnionType(
            discriminator=str(items[0]), variants=[item for item in items[1:] if isinstance(item, UnionVariant)]
        )

    def dotted_ref(self, items: list[object]) -> str:
        return ".".join(str(item) for item in items)

    def IDENT(self, token: object) -> str:  # noqa: N802
        return str(token)

    def projection_decl(self, items: list[object]) -> tuple[str, tuple[str, ProjectionVersion]]:
        annotations = [item for item in items if isinstance(item, ANNOTATION_TYPES)]
        items = [item for item in items if not isinstance(item, ANNOTATION_TYPES)]
        source_index = next(
            (
                i
                for i, item in enumerate(items[2:], start=2)
                if isinstance(item, tuple) and len(item) == 4 and isinstance(item[0], SourceRef)
            ),
            None,
        )
        if source_index is None:
            source = SourceRef(model="", version=VersionExact(version=0), alias="", where=None)
            joins: list[JoinRef] = []
            where = None
            group_by: list[str] = []
            body_start = 2
        else:
            source, joins, where, group_by = items[source_index]
            body_start = source_index + 1
        access = next((item for item in items[body_start:] if isinstance(item, AccessBlock)), None)
        reservation = next((item for item in items[body_start:] if isinstance(item, ProtobufReservations)), None)
        selection = next((item for item in items[body_start:] if isinstance(item, SelectionClause)), None)
        projection_version = ProjectionVersion(
            version=int(items[1]),
            source=source,
            joins=joins,
            where=where,
            group_by=group_by,
            fields=[item for item in items[body_start:] if isinstance(item, ProjectionField)],
            access=access,
            annotations=annotations,
            protobuf_reservations=reservation,
            selection=selection,
        )
        return ("projection", (str(items[0]), projection_version))

    def selection_clause(self, items):
        return items[0]

    def pick_clause(self, items):
        return _build_selection_clause("pick", items)

    def omit_clause(self, items):
        return _build_selection_clause("omit", items)

    def selector(self, items):
        return items[0]

    def join_prefix(self, items):
        if len(items) == 5:
            return ("join", "left", str(items[1]), items[2], str(items[3]), str(items[4]).strip())
        return ("join", "inner", str(items[0]), items[1], str(items[2]), str(items[3]).strip())

    def projection_body_item(self, items):
        return items[0]

    def projection_source_block(self, items):
        return items[0]

    def source_clause(self, items):
        joins = [item for item in items[3:] if isinstance(item, JoinRef)]
        where = next((item for item in items[3:] if isinstance(item, str)), None)
        group_by = next((item for item in items[3:] if isinstance(item, list)), [])
        return (
            SourceRef(model=str(items[0]), version=items[1], alias=str(items[2]), where=where),
            joins,
            where,
            group_by,
        )

    def join_clause(self, items):
        prefix = items[0]
        annotations = [item for item in items[1:] if isinstance(item, ANNOTATION_TYPES)]
        cardinality = next(
            (item[1] for item in items[1:] if isinstance(item, tuple) and item[0] == "cardinality"), None
        )
        return JoinRef(
            model=str(prefix[2]),
            version=prefix[3],
            alias=str(prefix[4]),
            on=prefix[5],
            join_kind=prefix[1],
            cardinality=cardinality,
            annotations=annotations,
        )

    def where_clause(self, items):
        return str(items[0]).strip()

    def join_modifier(self, _items):
        return "left"

    def cardinality_attr(self, items):
        return ("cardinality", str(items[0]))

    def group_clause(self, items):
        return [str(item) for item in items]

    def group_item(self, items):
        return str(items[0]).strip()

    def api_decl(self, items: list[Any]) -> tuple[str, ApiDecl]:
        operations = [item for item in items[2:] if isinstance(item, ApiOperation)]
        return ("api", ApiDecl(model=str(items[0]), version=int(items[1]), operations=operations))

    def api_operation(self, items: list[Any]) -> ApiOperation:
        method = next((item[1] for item in items[1:] if isinstance(item, tuple) and item[0] == "method"), None)
        path = next((item[1] for item in items[1:] if isinstance(item, tuple) and item[0] == "path"), None)
        request = next((item[1] for item in items[1:] if isinstance(item, tuple) and item[0] == "request"), None)
        responses: list[ApiResponse] = next(
            (item[1] for item in items[1:] if isinstance(item, tuple) and item[0] == "responses"), []
        )
        if method is None or path is None:
            raise ValueError("API operation requires method and path")
        return ApiOperation(name=_str(items[0]), method=method, path=path, request=request, responses=responses)

    def api_operation_item(self, items: list[Any]) -> Any:
        return items[0]

    def method_clause(self, items: list[Any]) -> tuple[str, Any]:
        return ("method", items[0])

    def path_clause(self, items: list[Any]) -> tuple[str, str]:
        return ("path", _str(items[0]))

    def request_clause(self, items: list[Any]) -> tuple[str, tuple[str, int]]:
        return ("request", (str(items[0]), int(items[1])))

    def responses_block(self, items: list[Any]) -> tuple[str, list[ApiResponse]]:
        return ("responses", list(items))

    def response_decl(self, items: list[Any]) -> ApiResponse:
        return ApiResponse(status_code=int(items[0]), projection=str(items[1]), version=int(items[2]))

    def http_get(self, _items: list[Any]) -> str:
        return "GET"

    def http_post(self, _items: list[Any]) -> str:
        return "POST"

    def http_put(self, _items: list[Any]) -> str:
        return "PUT"

    def http_patch(self, _items: list[Any]) -> str:
        return "PATCH"

    def http_delete(self, _items: list[Any]) -> str:
        return "DELETE"

    def version_spec(self, items):
        return items[0]

    def version_exact(self, items):
        return VersionExact(version=int(items[0]))

    def version_pinned(self, items):
        return VersionPinned(version=int(items[0]), content_hash=str(items[1]))

    def version_range(self, items):
        return VersionRange(min_inclusive=int(items[0]), max_exclusive=int(items[1]))

    def version_min(self, items):
        return VersionMin(min_inclusive=int(items[0]))

    def qualified_field(self, items):
        return f"{items[0]}.{items[1]}"

    def direct_field(self, items):
        annotations = [item for item in items if isinstance(item, ANNOTATION_TYPES)]
        rest = [item for item in items if not isinstance(item, ANNOTATION_TYPES)]
        source_alias, source_field = str(rest[1]).split(".", 1)
        return ProjectionField(
            name=str(rest[0]),
            mapping=DirectMapping(source_alias=source_alias, source_field=source_field),
            annotations=annotations,
        )

    def computed_field(self, items):
        annotations = [item for item in items if isinstance(item, ANNOTATION_TYPES)]
        rest = [item for item in items if not isinstance(item, ANNOTATION_TYPES)]
        return ProjectionField(
            name=str(rest[0]),
            mapping=ComputedMapping(expression=str(rest[1]).strip()),
            annotations=annotations,
        )

    def proj_field(self, items):
        return items[0]

    def auto_projections_decl(self, items):
        return (
            "auto_projection",
            AutoProjectionDecl(
                model=str(items[0]),
                version=int(items[1]),
                targets=[item for item in items[2:] if isinstance(item, AutoProjectionTarget)],
            ),
        )

    def access_block(self, items):
        entity = []
        properties: dict[str, list[AccessGrant]] = {}
        for item in items:
            if not isinstance(item, tuple):
                continue
            if item[0] == "entity":
                entity.append(item[1])
            elif item[0] == "property":
                field_name, grant = item[1]
                properties.setdefault(field_name, []).append(grant)
        return AccessBlock(entity=entity, properties=properties)

    def entity_grant(self, items):
        return ("entity", AccessGrant(principal=str(items[0]), permissions=list(items[1])))

    def property_grant(self, items):
        field_name = str(items[0])
        return (
            "property",
            (
                field_name,
                AccessGrant(principal=str(items[1]), permissions=list(items[2])),
            ),
        )

    def access_item(self, items):
        return items[0]

    def principal(self, items):
        return str(items[0])

    def permission_list(self, items):
        return [str(item) for item in items]

    def p_read(self, _items):
        return "read"

    def p_project(self, _items):
        return "project"

    def p_subscribe(self, _items):
        return "subscribe"

    def p_write(self, _items):
        return "write"

    def p_transfer(self, _items):
        return "transfer"

    def p_manage_access(self, _items):
        return "manage_access"

    def p_derive(self, _items):
        return "derive"

    def p_redact(self, _items):
        return "redact"

    def auto_projection_item(self, items):
        kind = items[0]
        excluded_fields = []
        excluded_annotations = []
        operations = []
        for option in items[1:]:
            if option is None:
                continue
            opt_kind, opt_values = option
            if opt_kind == "exclude":
                for val in opt_values:
                    if isinstance(val, str):
                        excluded_fields.append(val)
                    else:
                        excluded_annotations.append(val)
            elif opt_kind == "on":
                operations.extend(opt_values)
        return AutoProjectionTarget(
            kind=kind,
            excluded_fields=excluded_fields,
            excluded_annotations=excluded_annotations,
            operations=operations,
        )

    def auto_projection_kind(self, items):
        return items[0]

    def apk_db(self, _items):
        return "db"

    def apk_request(self, _items):
        return "request"

    def apk_reply(self, _items):
        return "reply"

    def apk_event(self, _items):
        return "event"

    def auto_projection_option(self, items):
        return items[0]

    def exclude_option(self, items):
        return ("exclude", [item for item in items if item is not None])

    def on_option(self, items):
        return ("on", [str(item) for item in items if item is not None])

    def auto_projection_exclusion(self, items):
        return items[0]

    def generate_block(self, items):
        return ("generate", [item for item in items if isinstance(item, GenerateTarget)])

    def generate_target(self, items):
        target = items[0]
        output_path = _str(items[1]) if len(items) > 1 else None
        if isinstance(target, tuple):
            name, dialect = target
        else:
            name, dialect = target, None
        return GenerateTarget(name=name, dialect=dialect, output_path=output_path)

    def target_name(self, items):
        return items[0]

    def tn_openapi(self, _items):
        return "openapi"

    def tn_typescript(self, _items):
        return "typescript"

    def tn_avro(self, _items):
        return "avro"

    def tn_protobuf(self, _items):
        return "protobuf"

    def tn_sql(self, items):
        return ("sql", str(items[0]))

    def tn_jsonschema(self, _items):
        return "jsonschema"

    def tn_asyncapi(self, _items):
        return "asyncapi"

    def tn_docs(self, _items):
        return "docs"

    def db_dialect(self, items):
        return items[0]

    def dd_postgres(self, _items):
        return "postgres"

    def dd_mysql(self, _items):
        return "mysql"

    def dd_clickhouse(self, _items):
        return "clickhouse"

    def dd_sqlite(self, _items):
        return "sqlite"

    def binding_decl(self, items):
        name = str(items[0])
        model = ""
        model_version = 0
        adapter = ""
        table = None
        for item in items[1:]:
            if not isinstance(item, tuple):
                continue
            tag, *vals = item
            if tag == "adapter":
                adapter = vals[0]
            elif tag == "model":
                model, model_version = vals[0], vals[1]
            elif tag == "table":
                table = vals[0]
        return BindingDef(name=name, model=model, model_version=model_version, adapter=adapter, table=table)

    def binding_item(self, items):
        return items[0]

    def binding_adapter_attr(self, items):
        return ("adapter", str(items[0]))

    def binding_model_attr(self, items):
        model_fqn = str(items[0])
        version = int(items[1])
        return ("model", model_fqn, version)

    def binding_table_attr(self, items):
        return ("table", _str(items[0]))

    def workspace_decl(self, _items):
        label = None
        name = None
        description = None
        generate_targets: list[GenerateTarget] = []
        ai = None
        packages: list[PackageConfig] = []

        for item in _items:
            if isinstance(item, str):
                label = _str(item)
            elif isinstance(item, PackageConfig):
                packages.append(item)
            elif isinstance(item, tuple):
                tag, value = item
                if tag == "name":
                    name = value
                elif tag == "description":
                    description = value
                elif tag == "generate":
                    generate_targets = value
                elif tag == "ai":
                    ai = value

        return WorkspaceDef(
            label=label,
            name=name,
            description=description,
            generate_targets=generate_targets,
            ai=ai,
            packages=packages,
        )

    def package_block(self, items):
        name = _str(items[0])
        include: list[str] = []
        description = None
        for item in items[1:]:
            if not isinstance(item, tuple):
                continue
            tag, value = item
            if tag == "include":
                include = value
            elif tag == "description":
                description = value
        return PackageConfig(name=name, include=include, description=description)

    def package_item(self, items):
        return items[0]

    def package_include_attr(self, items):
        return ("include", [_str(item) for item in items if item is not None])

    def package_description_attr(self, items):
        return ("description", _str(items[0]))

    def workspace_item(self, items):
        return items[0]

    def workspace_label(self, items):
        return _str(items[0])

    def workspace_name_attr(self, items):
        return ("name", _str(items[0]))

    def workspace_description_attr(self, items):
        return ("description", _str(items[0]))

    def ai_block(self, items):
        attrs = dict(items)
        return (
            "ai",
            AiConfig(
                provider=attrs.get("provider"),
                model=attrs.get("model"),
                repair_attempts=attrs.get("repair_attempts"),
            ),
        )

    def ai_provider(self, items):
        return ("provider", _str(items[0]))

    def ai_model(self, items):
        return ("model", _str(items[0]))

    def ai_repair_attempts(self, items):
        return ("repair_attempts", int(items[0]))

    def field_mapping(self, items):
        return FieldMapping(source=str(items[0]), target=str(items[1]))

    def ai_item(self, items):
        return items[0]

    def join_option(self, items: list[object]) -> object:
        return items[0]
