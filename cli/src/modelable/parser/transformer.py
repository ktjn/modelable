from __future__ import annotations

from lark import Transformer

from modelable.parser.ir import (
    AiConfig,
    AccessBlock,
    AccessGrant,
    AnnCustom,
    AnnClassification,
    AnnDeprecated,
    AnnLatestBefore,
    AnnLatestOnly,
    AnnKey,
    AnnPitCutoff,
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
    VersionPinned,
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
    AnnPitCutoff,
    AnnLatestBefore,
    AnnLatestOnly,
    AnnCustom,
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
        name = _str(items[0])
        owner = None
        contact = None
        description = None
        models: dict[str, list[ModelVersion]] = {}
        projections: dict[str, list[ProjectionVersion]] = {}
        auto_projections: list[AutoProjectionDecl] = []
        generate_targets: list[GenerateTarget] = []

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
            elif tag == "generate":
                generate_targets = value

        return DomainDef(
            name=name,
            owner=owner,
            contact=contact,
            description=description,
            models=models,
            projections=projections,
            auto_projections=auto_projections,
            generate_targets=generate_targets,
        )

    def domain_name(self, items):
        return _str(items[0])

    def domain_item(self, items):
        return items[0]

    def owner_attr(self, items):
        return ("owner", _str(items[0]))

    def contact_attr(self, items):
        return ("contact", _str(items[0]))

    def desc_attr(self, items):
        return ("description", _str(items[0]))

    def model_decl(self, items):
        name = str(items[1])
        header = items[2] if len(items) > 2 and isinstance(items[2], tuple) and items[2][0] == "model_header" else None
        body_start = 3 if header is not None else 2
        version = header[1] if header is not None else 0
        change_kind = header[2] if header is not None else ChangeKind.additive
        has_change_kind = header[3] if header is not None else False
        access = next((item for item in items[body_start:] if isinstance(item, AccessBlock)), None)
        model_version = ModelVersion(
            model_kind=items[0],
            version=int(version),
            change_kind=change_kind,
            fields=[item for item in items[body_start:] if isinstance(item, FieldDef)],
            access=access,
            has_version_header=header is not None,
            has_change_kind=has_change_kind,
        )
        return ("model", (name, model_version))

    def model_header(self, items):
        if len(items) == 1 and isinstance(items[0], tuple):
            return ("model_header", int(items[0][1]), items[0][2], True)
        if len(items) == 2:
            return ("model_header", int(items[0]), items[1], True)
        return ("model_header", int(items[0]), ChangeKind.additive, False)

    def model_change(self, items):
        return items[0]

    def model_body_item(self, items):
        return items[0]

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
        default = next((item[1] for item in rest if isinstance(item, tuple) and item[0] == "default"), None)
        return FieldDef(
            name=str(rest[0]),
            optional=any(item == "?" for item in rest),
            type=next(item for item in rest if not isinstance(item, str) and not (isinstance(item, tuple) and item[0] == "default")),
            default=default,
            annotations=annotations,
        )

    def optional_marker(self, _items):
        return "?"

    def field_default(self, items):
        return ("default", str(items[0]).strip())

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

    def ann_pit_cutoff(self, items):
        return AnnPitCutoff(expression=str(items[0]).strip())

    def ann_latest_before(self, items):
        return AnnLatestBefore(expression=str(items[0]).strip())

    def ann_latest_only(self, _items):
        return AnnLatestOnly()

    def ann_custom(self, items):
        name = str(items[0])
        expression = str(items[1]).strip() if len(items) > 1 else None
        return AnnCustom(name=name, expression=expression)

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
        projection_version = ProjectionVersion(
            version=int(items[1]),
            source=source,
            joins=joins,
            where=where,
            group_by=group_by,
            fields=[item for item in items[body_start:] if isinstance(item, ProjectionField)],
            access=access,
        )
        return ("projection", (str(items[0]), projection_version))

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
        return SourceRef(model=str(items[0]), version=items[1], alias=str(items[2]), where=where), joins, where, group_by

    def join_clause(self, items):
        prefix = items[0]
        annotations = [item for item in items[1:] if isinstance(item, ANNOTATION_TYPES)]
        cardinality = next((item[1] for item in items[1:] if isinstance(item, tuple) and item[0] == "cardinality"), None)
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
        return BindingDef(
            name=str(items[0]),
            model="",
            model_version=0,
            adapter="",
        )

    def workspace_decl(self, _items):
        label = None
        name = None
        description = None
        generate_targets: list[GenerateTarget] = []
        ai = None

        for item in _items:
            if isinstance(item, str):
                label = _str(item)
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
        )

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
