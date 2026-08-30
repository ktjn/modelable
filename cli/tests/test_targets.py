from modelable.emitters.targets import CODEGEN_TARGETS, get_codegen_target, list_compat_checkable_targets


def test_protobuf_and_grpc_support_compat_check():
    assert get_codegen_target("protobuf").supports_compat_check is True
    assert get_codegen_target("json-schema").supports_compat_check is True
    assert get_codegen_target("grpc").supports_compat_check is True
    assert get_codegen_target("openapi").supports_compat_check is True
    assert get_codegen_target("avro").supports_compat_check is True


def test_other_targets_do_not_support_compat_check():
    non_compat_targets = [
        target
        for target in CODEGEN_TARGETS
        if target.name not in ("json-schema", "protobuf", "grpc", "openapi", "avro")
    ]
    assert non_compat_targets
    assert all(target.supports_compat_check is False for target in non_compat_targets)


def test_list_compat_checkable_targets_returns_supported_target_evaluators():
    names = {target.name for target in list_compat_checkable_targets()}
    assert names == {"json-schema", "protobuf", "grpc", "openapi", "avro"}


def test_sql_targets_publish_local_overlay_schema_paths():
    assert get_codegen_target("sql-postgres").overlay_schema == (
        "modelable/schemas/overlays/sql-postgres-v1.schema.json"
    )
    assert get_codegen_target("sql-clickhouse").overlay_schema == (
        "modelable/schemas/overlays/sql-clickhouse-v1.schema.json"
    )
    assert all(target.overlay_schema is None for target in CODEGEN_TARGETS if not target.name.startswith("sql-"))


def test_builtin_targets_expose_extension_descriptors():
    descriptor = get_codegen_target("sql-postgres").extension_descriptor()

    assert descriptor.protocol == "modelable.extension/v1"
    assert descriptor.id == "modelable.target.sql-postgres"
    assert descriptor.version
    assert descriptor.accepted_plan_versions == ("modelable.plan/v0",)
    assert descriptor.output_kinds == ("artifact",)
    assert descriptor.configuration_schema == "modelable/schemas/overlays/sql-postgres-v1.schema.json"
