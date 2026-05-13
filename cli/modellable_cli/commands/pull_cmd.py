"""pull command — pull artifacts from external registries."""

from __future__ import annotations

import click
from rich.console import Console

console = Console()


@click.group("pull")
def pull() -> None:
    """Pull artifacts from external registries.

    \b
    Commands:
      apicurio   Pull a schema artifact from Apicurio Registry  [Phase 2]

    \b
    Example:
      modellable pull apicurio customer.Customer.v1
    """


@pull.command("apicurio")
@click.argument("ref")
@click.option("--url", default=None, help="Apicurio Registry base URL.")
@click.option("--group", default="modellable", show_default=True, help="Artifact group ID.")
@click.option(
    "--out", "-o",
    default="./dist/jsonschema",
    show_default=True,
    help="Output directory.",
)
def pull_apicurio(ref: str, url: str | None, group: str, out: str) -> None:
    """Pull a JSON Schema artifact from Apicurio Registry.

    \b
    [Phase 2] Not yet implemented.

    REF format: domain.ModelName.vVersion

    \b
    Example:
      modellable pull apicurio customer.Customer.v1 --url http://localhost:8080
    """
    console.print(
        "[bold yellow]Phase 2:[/bold yellow] Apicurio Registry integration is not yet implemented.\n\n"
        f"This command will pull the artifact for [bold]{ref}[/bold] "
        "from the Apicurio Registry and write it to the output directory."
    )
