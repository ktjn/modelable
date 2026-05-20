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
        "deferred",
        "deferred",
        "deferred",
        "deferred",
        "deferred",
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


def test_type_shape_preserves_nullability_and_collections():
    shape = TypeShape.from_field("array<uuid>?", optional=True)

    assert shape.kind == "array"
    assert shape.optional is True
    assert shape.nullable is True
    assert shape.element is not None
    assert shape.element.kind == "primitive"
    assert shape.element.ref == "uuid"
