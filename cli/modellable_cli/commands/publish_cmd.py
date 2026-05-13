"""publish command — push generated artifacts to external registries."""

from __future__ import annotations

import click
from rich.console import Console

console = Console()


@click.group("publish")
def publish() -> None:
    """Push generated artifacts to external registries.

    \b
    Commands:
      apicurio       Push JSON Schema artifacts to Apicurio Registry  [Phase 2]
      openmetadata   Push catalog metadata to OpenMetadata             [Phase 3]

    \b
    Examples:
      modellable publish apicurio ./dist/jsonschema
      modellable publish openmetadata ./dist/openmetadata.json
    """


@publish.command("apicurio")
@click.argument("path", type=click.Path())
@click.option("--url", default=None, help="Apicurio Registry base URL.")
@click.option("--group", default="modellable", show_default=True, help="Artifact group ID.")
def publish_apicurio(path: str, url: str | None, group: str) -> None:
    """Push JSON Schema artifacts to Apicurio Registry.

    \b
    [Phase 2] Not yet implemented.

    Artifact IDs follow the convention: domain.Name.vVersion

    \b
    Example:
      modellable compile ./models --target json-schema --out ./dist/jsonschema
      modellable publish apicurio ./dist/jsonschema --url http://localhost:8080
    """
    console.print(
        "[bold yellow]Phase 2:[/bold yellow] Apicurio Registry integration is not yet implemented.\n\n"
        f"This command will publish JSON Schema artifacts from [bold]{path}[/bold] "
        "to the Apicurio Registry.\n\n"
        "[dim]Run Phase 1 commands first to generate the artifacts:\n"
        "  modellable compile ./models --target json-schema --out ./dist/jsonschema[/dim]"
    )


@publish.command("openmetadata")
@click.argument("path", type=click.Path())
@click.option("--url", default=None, help="OpenMetadata server URL.")
def publish_openmetadata(path: str, url: str | None) -> None:
    """Push catalog metadata to OpenMetadata.

    \b
    [Phase 3] Not yet implemented.

    \b
    Example:
      modellable export openmetadata ./models --out ./dist/openmetadata.json
      modellable publish openmetadata ./dist/openmetadata.json
    """
    console.print(
        "[bold yellow]Phase 3:[/bold yellow] OpenMetadata integration is not yet implemented.\n\n"
        f"This command will ingest domain, model, and lineage metadata from [bold]{path}[/bold] "
        "into the OpenMetadata catalog.\n\n"
        "[dim]Generate the export first:\n"
        "  modellable export openmetadata ./models --out ./dist/openmetadata.json[/dim]"
    )
