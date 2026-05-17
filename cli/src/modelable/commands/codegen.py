from __future__ import annotations

import click
from rich.console import Console

console = Console()

CODEGEN_FORMATS: list[dict[str, object]] = [
    {
        "name": "json-schema",
        "description": "JSON Schema 2020-12 artifacts with x-modelable extensions",
        "status": "implemented",
    },
    {
        "name": "markdown",
        "description": "Markdown documentation with field and lineage tables",
        "status": "implemented",
    },
    {
        "name": "typescript",
        "description": "Native TypeScript interfaces emitted from the normalized graph",
        "status": "implemented",
    },
]

_FORMAT_LOOKUP = {entry["name"]: entry for entry in CODEGEN_FORMATS}


def register_codegen_commands(cli_group: click.Group) -> None:
    cli_group.add_command(codegen)


@click.group()
def codegen() -> None:
    """Explore supported code generation formats and type mappings."""


@codegen.command(name="formats")
def formats() -> None:
    """List supported compilation targets."""
    console.print("Supported code generation formats:")
    for entry in CODEGEN_FORMATS:
        console.print(
            f"- {entry['name']}: {entry['description']} [{entry['status']}]"
        )


@codegen.command(name="types")
@click.option(
    "--format",
    "format_name",
    type=click.Choice([entry["name"] for entry in CODEGEN_FORMATS]),
    default="typescript",
    show_default=True,
    help="Target format to describe.",
)
def types(format_name: str) -> None:
    """Show the field-type mapping for a target format."""
    entry = _FORMAT_LOOKUP[format_name]
    console.print(f"{format_name} type mappings")
    console.print(f"{entry['description']}")
    console.print("")

    for source_type, target_type, note in _type_mappings_for(format_name):
        line = f"- {source_type} -> {target_type}"
        if note:
            line += f" ({note})"
        console.print(line)


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
