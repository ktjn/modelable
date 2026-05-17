from __future__ import annotations

from lark import Transformer

from modelable.parser.ir import (
    AiConfig,
    AnnClassification,
    AnnDeprecated,
    AnnKey,
    AnnOwner,
    AnnPii,
    AnnServer,
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
    GenerateTarget,
    JoinRef,
    MapType,
    MdlFile,
    ModelKind,
    ModelVersion,
    NamedType,
    ObjectType,
    PrimitiveType,
    ProjectionField,
    ProjectionVersion,
    RefType,
    SourceRef,
    VersionExact,
    VersionMin,
    VersionRange,
    WorkspaceDef,
)

ANNOTATION_TYPES = (
    AnnKey,
    AnnPii,
    AnnClassification,
    AnnDeprecated,
    AnnOwner,
    AnnServer,
)


def _str(value) -> str:
    text = str(value)
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1]
    return text


class MdlTransformer(Transformer):
    def start(self, items):
        domains = []
        bindings = []
        workspace = None
        for item in items:
            if isinstance(item, DomainDef):
                domains.append(item)
            elif isinstance(item, BindingDef):
                bindings.append(item)
            elif isinstance(item, WorkspaceDef):
                workspace = item
        return MdlFile(domains=domains, bindings=bindings, workspace=workspace)

    def statement(self, items):
        return items[0]

    def domain_decl(self, items):
        name = str(items[0])
        owner = None
        description = None
        models: dict[str, list[ModelVersion]] = {}
        projections: dict[str, list[ProjectionVersion]] = {}
        auto_projections: list[AutoProjectionDecl] = []
        generate_targets: list[GenerateTarget] = []

        for tag, value in [item for item in items[1:] if isinstance(item, tuple)]:
            if tag == "owner":
                owner = value
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
            elif tag == "generate":
                generate_targets = value

        return DomainDef(
            name=name,
            owner=owner,
            description=description,
            models=models,
            projections=projections,
            auto_projections=auto_projections,
            generate_targets=generate_targets,
        )

    def domain_item(self, items):
        return items[0]

    def owner_attr(self, items):
        return ("owner", _str(items[0]))

    def desc_attr(self, items):
        return ("description", _str(items[0]))

    def model_decl(self, items):
        name = str(items[1])
        model_version = ModelVersion(
            model_kind=items[0],
            version=int(items[2]),
            change_kind=items[3],
            fields=[item for item in items[4:] if isinstance(item, FieldDef)],
        )
        return ("model", (name, model_version))

    def mk_entity(self, _items):
        return ModelKind.entity

    def mk_aggregate(self, _items):
        return ModelKind.aggregate

    def mk_event(self, _items):
        return ModelKind.event

    def mk_value(self, _items):
        return ModelKind.value

    def ck_additive(self, _items):
        return ChangeKind.additive

    def ck_breaking(self, _items):
        return ChangeKind.breaking

    def field_decl(self, items):
        annotations = [item for item in items if isinstance(item, ANNOTATION_TYPES)]
        rest = [item for item in items if not isinstance(item, ANNOTATION_TYPES)]
        return FieldDef(
            name=str(rest[0]),
            optional=any(item == "?" for item in rest),
            type=rest[-1],
            annotations=annotations,
        )

    def optional_marker(self, _items):
        return "?"

    def ann_key(self, _items):
        return AnnKey()

    def ann_pii(self, _items):
        return AnnPii()

    def ann_classification(self, items):
        return AnnClassification(level=_str(items[0]))

    def ann_deprecated(self, items):
        return AnnDeprecated(replaced_by=_str(items[0]))

    def ann_owner(self, items):
        return AnnOwner(team=_str(items[0]))

    def ann_server(self, _items):
        return AnnServer()

    def annotation(self, items):
        return items[0]

    def type_expr(self, items):
        item = items[0]
        if isinstance(item, str):
            return NamedType(name=item)
        return item

    def pt_string(self, _items):
        return PrimitiveType(kind="string")

    def pt_int(self, _items):
        return PrimitiveType(kind="int")

    def pt_float(self, _items):
        return PrimitiveType(kind="float")

    def pt_bool(self, _items):
        return PrimitiveType(kind="bool")

    def pt_date(self, _items):
        return PrimitiveType(kind="date")

    def pt_time(self, _items):
        return PrimitiveType(kind="time")

    def pt_timestamp(self, _items):
        return PrimitiveType(kind="timestamp")

    def pt_uuid(self, _items):
        return PrimitiveType(kind="uuid")

    def pt_duration(self, _items):
        return PrimitiveType(kind="duration")

    def pt_binary(self, _items):
        return PrimitiveType(kind="binary")

    def primitive_type(self, items):
        return items[0]

    def decimal_type(self, items):
        return DecimalType(precision=int(items[0]), scale=int(items[1]))

    def enum_type(self, items):
        return EnumType(values=[str(item) for item in items])

    def array_type(self, items):
        return ArrayType(item=items[0])

    def map_type(self, items):
        return MapType(key=items[0], value=items[1])

    def ref_type(self, items):
        return RefType(target=str(items[0]))

    def object_type(self, items):
        return ObjectType(fields=[item for item in items if isinstance(item, FieldDef)])

    def dotted_ref(self, items):
        return ".".join(str(item) for item in items)

    def IDENT(self, token):
        return str(token)

    def projection_decl(self, items):
        source, joins, group_by = items[2]
        projection_version = ProjectionVersion(
            version=int(items[1]),
            source=source,
            joins=joins,
            group_by=group_by,
            fields=[item for item in items[3:] if isinstance(item, ProjectionField)],
        )
        return ("projection", (str(items[0]), projection_version))

    def source_clause(self, items):
        joins = [item for item in items[3:] if isinstance(item, JoinRef)]
        group_by = next((item for item in items[3:] if isinstance(item, list)), [])
        return SourceRef(model=str(items[0]), version=items[1], alias=str(items[2])), joins, group_by

    def join_clause(self, items):
        return JoinRef(
            model=str(items[0]),
            version=items[1],
            alias=str(items[2]),
            on=str(items[3]).strip(),
        )

    def group_clause(self, items):
        return [str(item) for item in items]

    def version_spec(self, items):
        return items[0]

    def version_exact(self, items):
        return VersionExact(version=int(items[0]))

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

    def dd_sqlite(self, _items):
        return "sqlite"

    def binding_decl(self, items):
        return BindingDef(
            name=str(items[0]),
            model="",
            model_version=0,
            adapter="",
        )

    def workspace_decl(self, _items):
        return WorkspaceDef()

    def ai_block(self, items):
        attrs = dict(items)
        return ("ai", AiConfig(provider=attrs.get("provider"), model=attrs.get("model")))

    def ai_provider(self, items):
        return ("provider", _str(items[0]))

    def ai_model(self, items):
        return ("model", _str(items[0]))

    def field_mapping(self, items):
        return FieldMapping(source=str(items[0]), target=str(items[1]))
