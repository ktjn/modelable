from __future__ import annotations

import click
from rich.console import Console

from modelable.emitters.shapes import type_shape_catalog
from modelable.emitters.targets import (
    get_codegen_target,
    list_codegen_targets as _list_codegen_targets,
    list_implemented_codegen_targets,
)

console = Console()


def register_codegen_commands(cli_group: click.Group) -> None:
    cli_group.add_command(codegen)


@click.group()
def codegen() -> None:
    """Explore supported code generation formats and type mappings."""


@codegen.command(name="formats")
def formats() -> None:
    """List supported compilation targets."""
    console.print("Supported code generation formats:")
    for entry in _list_codegen_targets():
        console.print(f"- {entry.name}: {entry.description} [{entry.status}, {entry.kind}]")


@codegen.command(name="types")
@click.option(
    "--format",
    "format_name",
    type=click.Choice([entry.name for entry in list_implemented_codegen_targets()]),
    default="typescript",
    show_default=True,
    help="Target format to describe.",
)
def types(format_name: str) -> None:
    """Show the field-type mapping for a target format."""
    entry = get_codegen_target(format_name)
    console.print("Target inventory:")
    for target in _list_codegen_targets():
        console.print(f"- {target.name}: {target.status} [{target.kind}]")
    console.print("")
    console.print(f"{format_name} type mappings")
    console.print(f"{entry.description}")
    console.print("")
    console.print("Type shape catalog:")
    for label, shape, note in type_shape_catalog():
        line = f"- {label}: {shape.describe()}"
        if note:
            line += f" ({note})"
        console.print(line)
    console.print("")

    for source_type, target_type, note in _type_mappings_for(format_name):
        line = f"- {source_type} -> {target_type}"
        if note:
            line += f" ({note})"
        console.print(line)


def list_codegen_targets() -> list[dict[str, object]]:
    return [
        {
            "name": target.name,
            "description": target.description,
            "status": target.status,
            "kind": target.kind,
            "default_out_dir": str(target.default_out_dir) if target.default_out_dir is not None else None,
        }
        for target in _list_codegen_targets()
    ]


def _type_mappings_for(format_name: str) -> list[tuple[str, str, str | None]]:
    if format_name == "json-schema":
        return [
            ("string", '{"type":"string"}', None),
            ("bool", '{"type":"boolean"}', None),
            ("int", '{"type":"integer","format":"int64"}', None),
            ("float", '{"type":"number"}', None),
            ("uuid", '{"type":"string","format":"uuid"}', None),
            ("timestamp", '{"type":"string","format":"date-time"}', None),
            ("date", '{"type":"string","format":"date"}', None),
            ("time", '{"type":"string","format":"time"}', None),
            ("duration", '{"type":"string","format":"duration"}', None),
            ("binary", '{"type":"string","contentEncoding":"base64"}', None),
            ("decimal(p, s)", '{"type":"string","pattern":"^-?\\d+(\\.\\d+)?$"}', None),
            ("array<T>", '{"type":"array","items":<T>}', None),
            ("map<K, V>", '{"type":"object","additionalProperties":<V>}', None),
            ("ref<T>", '{"type":"string","x-modelable-ref":"T"}', None),
            ("enum(...)", '{"type":"string","enum":[...]}', None),
            ("object { ... }", '{"type":"object","properties":{...}}', None),
            ("named", '{"type":"object","x-modelable-field":{"namedType":"Name"}}', None),
        ]
    if format_name == "csharp":
        return [
            ("string", "string", "optional fields use string?"),
            ("bool", "bool", "optional fields use bool?"),
            ("int", "int", "optional fields use int?"),
            ("float", "double", "optional fields use double?"),
            ("uuid", "Guid", "optional fields use Guid?"),
            ("timestamp", "DateTime", "optional fields use DateTime?"),
            ("date", "DateOnly", "optional fields use DateOnly?"),
            ("time", "TimeOnly", "optional fields use TimeOnly?"),
            ("duration", "TimeSpan", "optional fields use TimeSpan?"),
            ("binary", "byte[]", "optional fields use byte[]?"),
            ("decimal(p, s)", "decimal", "optional fields use decimal?"),
            ("array<T>", "List<T>", None),
            ("map<K, V>", "Dictionary<string, V>", None),
            ("ref<T>", "string", "references compile to reference strings"),
            ("enum(...)", "string", None),
            ("object { ... }", "{ ... }", "inline objects become nested records"),
            ("named", "Name", None),
        ]
    if format_name == "markdown":
        return [
            ("string", "string", "rendered as canonical .mdl text"),
            ("bool", "bool", "rendered as canonical .mdl text"),
            ("int", "int", "rendered as canonical .mdl text"),
            ("float", "float", "rendered as canonical .mdl text"),
            ("uuid", "uuid", "rendered as canonical .mdl text"),
            ("timestamp", "timestamp", "rendered as canonical .mdl text"),
            ("date", "date", "rendered as canonical .mdl text"),
            ("time", "time", "rendered as canonical .mdl text"),
            ("duration", "duration", "rendered as canonical .mdl text"),
            ("binary", "binary", "rendered as canonical .mdl text"),
            ("decimal(p, s)", "decimal(p, s)", "rendered as canonical .mdl text"),
            ("array<T>", "array<T>", "rendered as canonical .mdl text"),
            ("map<K, V>", "map<K, V>", "rendered as canonical .mdl text"),
            ("ref<T>", "ref<T>", "rendered as canonical .mdl text"),
            ("enum(...)", "enum(...)", "rendered as canonical .mdl text"),
            ("object { ... }", "object { ... }", "rendered as canonical .mdl text"),
            ("named", "Name", "rendered as canonical .mdl text"),
        ]
    return [
        ("string", "string", None),
        ("bool", "boolean", None),
        ("int", "number", None),
        ("float", "number", None),
        ("uuid", "string", "preserves uuid format as a string"),
        ("timestamp", "string", "preserves date-time semantics"),
        ("date", "string", "preserves date semantics"),
        ("time", "string", "preserves time semantics"),
        ("duration", "string", "preserves duration semantics"),
        ("binary", "string", "base64-encoded"),
        ("decimal(p, s)", "string", "decimal precision and scale encoded as text"),
        ("array<T>", "T[]", None),
        ("map<K, V>", "Record<string, V>", None),
        ("ref<T>", "string", "reference string"),
        ("enum(...)", "'a' | 'b' | ...", None),
        ("object { ... }", "{ ... }", None),
        ("named", "Name", None),
    ]
