from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from modelable.commands.common import console
from modelable.config import load_config


def register_config_commands(cli_group: click.Group) -> None:
    cli_group.add_command(config)


@click.group()
def config() -> None:
    """Inspect workspace compiler defaults and their provenance."""


@config.command("explain")
@click.argument("ref", required=False)
@click.option("--path", "source", default=".", type=click.Path(exists=True, path_type=Path))
@click.option("--target", default=None, help="Optional target override to include in the explanation.")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def explain(ref: str | None, source: Path, target: str | None, output_format: str) -> None:
    """Explain effective defaults for REF and their source of authority."""
    try:
        payload = load_config(source).explain(target=target)
    except ValueError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        sys.exit(1)
    if ref is not None:
        payload = {"ref": {"value": ref, "provenance": "cli"}, **payload}
    if output_format == "json":
        click.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    for name, item in payload.items():
        if isinstance(item, dict) and "value" in item:
            console.print(f"{name}: {item['value']!r} ({item['provenance']})")
