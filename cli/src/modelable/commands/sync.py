from __future__ import annotations

import os
import sys
from pathlib import Path

import click

from modelable.commands.common import console, load_workspace_or_exit
from modelable.emitters.openlineage import emit_openlineage
from modelable.registry.openlineage import OpenLineageClient, OpenLineageSyncError


def register_sync_commands(cli_group: click.Group) -> None:
    cli_group.add_command(sync)


@click.command()
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--lineage",
    type=click.Choice(["marquez"]),
    default=None,
    help="Lineage backend to synchronize with.",
)
@click.option(
    "--catalog",
    type=click.Choice(["openmetadata"]),
    default=None,
    help="Catalog backend to synchronize with. Reserved for the next live target.",
)
@click.option("--url", required=True, help="Backend base URL or lineage endpoint URL.")
@click.option("--token", default=None, help="Bearer token. Defaults to MODELABLE_OPENLINEAGE_TOKEN.")
@click.option("--dry-run", is_flag=True, help="List generated sync events without publishing.")
def sync(source: Path, lineage: str | None, catalog: str | None, url: str, token: str | None, dry_run: bool) -> None:
    """Synchronize Modelable-derived catalog or lineage metadata with a live backend."""
    if bool(lineage) == bool(catalog):
        console.print("[red]ERROR[/red] choose exactly one of --lineage or --catalog")
        sys.exit(2)

    if catalog is not None:
        console.print("[red]ERROR[/red] live OpenMetadata catalog sync is not implemented yet; use --lineage marquez")
        sys.exit(2)

    workspace = load_workspace_or_exit(source)
    artifacts = emit_openlineage(workspace, Path(".modelable/openlineage-sync"))
    events = [artifact for artifact in artifacts if isinstance(artifact.content, dict)]

    if dry_run:
        console.print(f"[yellow]DRY RUN[/yellow] would sync {len(events)} OpenLineage event(s) to {url}")
        for event in events:
            console.print(f"- {event.artifact_id} ({event.ref})")
        sys.exit(0)

    client = OpenLineageClient(url, token=token or os.getenv("MODELABLE_OPENLINEAGE_TOKEN"))
    try:
        for event in events:
            client.post_event(event.content)
            console.print(f"[green]OK[/green] synced {event.artifact_id} to {url}")
    except OpenLineageSyncError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        sys.exit(1)

    if not events:
        console.print("[yellow]No OpenLineage events generated.[/yellow]")
    sys.exit(0)
