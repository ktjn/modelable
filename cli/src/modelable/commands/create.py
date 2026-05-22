from __future__ import annotations

from pathlib import Path

import click

from modelable.commands.common import console


def register_create_commands(cli_group: click.Group) -> None:
    cli_group.add_command(create)


@click.group()
def create() -> None:
    """Create Modelable definition files interactively."""


@create.command(name="domain")
@click.option("--output-dir", "-d", default=".", type=click.Path(path_type=Path), show_default=True)
def create_domain(output_dir: Path) -> None:
    """Create a domain definition file."""
    name = click.prompt("Domain name")
    out_file = output_dir / f"{name}.mdl"
    if out_file.exists():
        raise click.ClickException(f"{out_file} already exists")
    output_dir.mkdir(parents=True, exist_ok=True)
    out_file.write_text(_domain_text(name), encoding="utf-8")
    console.print(f"[green]Created[/green] {out_file}")


def _domain_text(name: str) -> str:
    return f"domain {name} {{\n}}\n"


_FIELD_TYPES = [
    "string", "int", "float", "bool", "date", "time",
    "timestamp", "uuid", "duration", "binary", "decimal",
]


@create.command(name="model")
@click.option("--output-dir", "-d", default=".", type=click.Path(path_type=Path), show_default=True)
def create_model(output_dir: Path) -> None:
    """Create a model (entity/aggregate/event/value) definition file."""
    domain = click.prompt("Domain name")
    kind = click.prompt("Model kind", type=click.Choice(["entity", "aggregate", "event", "value"]))
    name = click.prompt("Model name")
    version = click.prompt("Version", default=1, type=int)
    change_kind = click.prompt("Change kind", type=click.Choice(["additive", "breaking"]), default="additive")

    fields: list[dict] = []
    while True:
        field_name = click.prompt("Field name (leave blank to finish)", default="", show_default=False)
        if not field_name:
            break
        field_type = click.prompt("Field type", type=click.Choice(_FIELD_TYPES))
        optional = click.confirm("Optional field?", default=False)
        is_key = click.confirm("Add @key annotation?", default=False)
        is_pii = click.confirm("Add @pii annotation?", default=False)
        fields.append({"name": field_name, "type": field_type, "optional": optional, "is_key": is_key, "is_pii": is_pii})

    out_file = output_dir / f"{domain}.mdl"
    if out_file.exists():
        raise click.ClickException(f"{out_file} already exists")
    output_dir.mkdir(parents=True, exist_ok=True)
    out_file.write_text(_model_text(domain, kind, name, version, change_kind, fields), encoding="utf-8")
    console.print(f"[green]Created[/green] {out_file}")


def _model_text(
    domain: str,
    kind: str,
    name: str,
    version: int,
    change_kind: str,
    fields: list[dict],
) -> str:
    lines = [f"domain {domain} {{", f"  {kind} {name} @ {version} ({change_kind}) {{"]
    for field in fields:
        annotations = ""
        if field.get("is_key"):
            annotations += "@key "
        if field.get("is_pii"):
            annotations += "@pii "
        optional_marker = "?" if field.get("optional") else ""
        lines.append(f"    {annotations}{field['name']}{optional_marker}: {field['type']}")
    lines += ["  }", "}"]
    return "\n".join(lines) + "\n"
