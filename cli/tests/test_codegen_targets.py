import json
from pathlib import Path

from click.testing import CliRunner
from jsonschema import Draft202012Validator

from modelable.cli import cli
from modelable.commands.codegen import list_codegen_targets
from modelable.emitters.shapes import TypeShape


def test_codegen_formats_list_supported_and_deferred_targets():
    result = CliRunner().invoke(cli, ["codegen", "formats"])

    assert result.exit_code == 0, result.output
    assert "json-schema" in result.output
    assert "markdown" in result.output
    assert "typescript" in result.output
    assert "csharp" in result.output
    assert "java" in result.output
    assert "python" in result.output
    assert "rust" in result.output
    assert "go" in result.output

    targets = list_codegen_targets()
    assert [target["name"] for target in targets] == [
        "json-schema",
        "markdown",
        "typescript",
        "csharp",
        "java",
        "python",
        "rust",
        "go",
        "sql-postgres",
        "sql-clickhouse",
        "dbt-yaml",
        "fhir-profile",
        "openmetadata",
        "openlineage",
        "odcs",
        "protobuf",
        "grpc",
        "openapi",
        "avro",
        "registry",
        "event-sink",
    ]
    assert all(target["status"] == "implemented" for target in targets)
    assert all(target["extension"]["protocol"] == "modelable.extension/v1" for target in targets)


def test_codegen_descriptors_reference_valid_local_overlay_schemas():
    root = Path(__file__).parents[1] / "src"
    targets = {target["name"]: target for target in list_codegen_targets()}

    for target_name in ("sql-postgres", "sql-clickhouse"):
        schema_path = root / targets[target_name]["overlay_schema"]
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["properties"]["target"]["const"] == target_name
        assert schema["properties"]["version"]["const"] == 1
        Draft202012Validator(schema).validate(
            {
                "target": target_name,
                "version": 1,
                "models": {"customer.Customer@1": {"table": "customers"}},
                "fields": {"customer.Customer@1#customerId": {"column": "customer_id"}},
            }
        )
        Draft202012Validator(schema).validate(
            {
                "target": target_name,
                "version": 1,
                "models": {"customer.Customer@<3": {"table": "legacy_customers"}},
            }
        )
        Draft202012Validator(schema).validate(
            {
                "target": target_name,
                "version": 1,
                "fields": {"customer.Customer@>=4,<7#address.*": {"column": "address_value"}},
            }
        )
        validator = Draft202012Validator(schema)
        for payload in (
            {
                "target": target_name,
                "version": 1,
                "models": {"customer.Customer@01": {"table": "customers"}},
            },
            {
                "target": target_name,
                "version": 1,
                "fields": {"customer.Customer@1#bad..path": {"column": "customer_id"}},
            },
        ):
            errors = list(validator.iter_errors(payload))
            assert errors


def test_codegen_types_expose_target_inventory_and_shape_catalog():
    result = CliRunner().invoke(cli, ["codegen", "types"])

    assert result.exit_code == 0, result.output
    assert "Target inventory" in result.output
    assert "json-schema" in result.output
    assert "typescript" in result.output
    assert "csharp" in result.output
    assert "java" in result.output
    assert "python" in result.output
    assert "rust" in result.output
    assert "go" in result.output
    assert "Type shape catalog" in result.output
    assert "array<uuid>" in result.output


def test_codegen_types_include_csharp_mappings():
    result = CliRunner().invoke(cli, ["codegen", "types", "--format", "csharp"])

    assert result.exit_code == 0, result.output
    assert "csharp type mappings" in result.output
    assert "Guid" in result.output
    assert "List<T>" in result.output


def test_codegen_types_include_java_mappings():
    result = CliRunner().invoke(cli, ["codegen", "types", "--format", "java"])

    assert result.exit_code == 0, result.output
    assert "java type mappings" in result.output
    assert "Optional<String>" in result.output
    assert "List<T>" in result.output


def test_codegen_types_include_python_mappings():
    result = CliRunner().invoke(cli, ["codegen", "types", "--format", "python"])

    assert result.exit_code == 0, result.output
    assert "python type mappings" in result.output
    assert "string -> str" in result.output
    assert "list[T]" in result.output


def test_codegen_types_include_rust_mappings():
    result = CliRunner().invoke(cli, ["codegen", "types", "--format", "rust"])

    assert result.exit_code == 0, result.output
    assert "rust type mappings" in result.output
    assert "String" in result.output
    assert "Vec<T>" in result.output


def test_codegen_types_include_go_mappings():
    result = CliRunner().invoke(cli, ["codegen", "types", "--format", "go"])

    assert result.exit_code == 0, result.output
    assert "go type mappings" in result.output
    assert "time.Time" in result.output
    assert "map[string]V" in result.output


def test_codegen_types_include_protobuf_mappings():
    result = CliRunner().invoke(cli, ["codegen", "types", "--format", "protobuf"])

    assert result.exit_code == 0, result.output
    assert "protobuf type mappings" in result.output
    assert "google.protobuf.Timestamp" in result.output
    assert "repeated T" in result.output


def test_codegen_types_include_grpc_mappings():
    result = CliRunner().invoke(cli, ["codegen", "types", "--format", "grpc"])

    assert result.exit_code == 0, result.output
    assert "grpc type mappings" in result.output
    assert "CommandEnvelope" in result.output
    assert "EntityReadService" in result.output


def test_type_shape_preserves_nullability_and_collections():
    shape = TypeShape.from_field("array<uuid>?", optional=True)

    assert shape.kind == "array"
    assert shape.optional is True
    assert shape.nullable is True
    assert shape.element is not None
    assert shape.element.kind == "primitive"
    assert shape.element.ref == "uuid"
