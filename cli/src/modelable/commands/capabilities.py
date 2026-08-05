from __future__ import annotations

import json
from dataclasses import asdict

import click

from modelable.capabilities import build_capability_manifest
from modelable.commands.common import console


def register_capabilities_commands(cli_group: click.Group) -> None:
    cli_group.add_command(capabilities)


@click.command("capabilities")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format.",
)
def capabilities(output_format: str) -> None:
    """List Modelable's compiler-owned capabilities.

    Covers output targets, SQL dialects, model kinds, annotations, and
    known deferred features.
    """
    manifest = build_capability_manifest()
    entries = manifest.all()

    if output_format == "json":
        payload = [{**asdict(entry), "status": entry.status.value} for entry in entries]
        click.echo(json.dumps(payload, indent=2))
        return

    for entry in entries:
        console.print(f"[bold]{entry.category}[/bold] {entry.name} ({entry.status.value}): {entry.description}")
        if entry.notes:
            console.print(f"  {entry.notes}")
