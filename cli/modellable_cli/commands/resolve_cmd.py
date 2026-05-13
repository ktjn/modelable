"""resolve command — look up and display a model or projection definition."""

from __future__ import annotations

import click
import yaml
from rich.console import Console
from rich.syntax import Syntax

from ..resolver import ModelRef, find_doc

console = Console()


@click.command("resolve")
@click.argument("ref")
@click.option(
    "--path", "-p",
    default=".",
    show_default=True,
    type=click.Path(exists=True),
    help="Directory to search for YAML definitions.",
)
def resolve(ref: str, path: str) -> None:
    """Look up and display a model or projection definition by reference.

    \b
    REF format: domain.ModelName.vVersion
    Examples:
      modellable resolve customer.Customer.v1
      modellable resolve billing.BillingCustomer.v1
    """
    try:
        model_ref = ModelRef.parse(ref)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    doc = find_doc(model_ref, path)
    if doc is None:
        console.print(
            f"[red]Not found:[/red] No definition for [bold]{ref}[/bold] "
            f"in [dim]{path}[/dim]"
        )
        raise SystemExit(1)

    console.print(f"[bold green]✓[/bold green] [bold]{ref}[/bold]\n")
    yaml_text = yaml.dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True)
    console.print(Syntax(yaml_text, "yaml", theme="monokai"))
