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
