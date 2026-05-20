from click.testing import CliRunner

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
    ]
    assert [target["status"] for target in targets] == [
        "implemented",
        "implemented",
        "implemented",
        "implemented",
        "implemented",
        "implemented",
        "implemented",
        "implemented",
    ]


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


def test_type_shape_preserves_nullability_and_collections():
    shape = TypeShape.from_field("array<uuid>?", optional=True)

    assert shape.kind == "array"
    assert shape.optional is True
    assert shape.nullable is True
    assert shape.element is not None
    assert shape.element.kind == "primitive"
    assert shape.element.ref == "uuid"
