from __future__ import annotations

from pathlib import Path
from typing import cast

import click

from modelable.consequence_protocol import ConsequenceProtocolError, load_consequence_graph, serialize_consequence_graph


def register_consequence_commands(cli_group: click.Group) -> None:
    cli_group.add_command(consequence)


@click.group()
def consequence() -> None:
    """Inspect and validate standalone modelable.consequence documents."""


@consequence.command("validate")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text", show_default=True)
def validate(path: Path, output_format: str) -> None:
    """Validate PATH and optionally print its canonical JSON representation."""
    try:
        document = load_consequence_graph(path)
    except ConsequenceProtocolError as error:
        raise click.ClickException(str(error)) from error

    if output_format == "json":
        click.echo(serialize_consequence_graph(document), nl=False)
        return

    click.echo("valid: true")
    click.echo(f"schema: {document['$schema']}")
    click.echo(f"nodes: {len(cast(list[object], document['nodes']))}")
    click.echo(f"edges: {len(cast(list[object], document['edges']))}")
