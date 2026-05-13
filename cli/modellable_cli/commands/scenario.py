"""Commands for listing, inspecting, and loading sample scenarios."""

from __future__ import annotations

import shutil
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table

from ..loader import load_scenario_by_id, load_scenario_index, scenarios_dir

console = Console()

PLATFORM_LABELS = {
    "data-warehouse": "Data Warehouse",
    "high-performance-service": "High-Performance Service",
    "event-driven-microservices": "Event-Driven Microservices",
    "ml-feature-store": "ML Feature Store",
    "api-consumer": "API Consumer",
    "audit-compliance": "Audit & Compliance",
}


@click.group()
def scenario() -> None:
    """Browse and load bundled sample scenarios."""


@scenario.command("list")
def list_scenarios() -> None:
    """List all available sample scenarios."""
    try:
        index = load_scenario_index()
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    table = Table(title="Modellable Sample Scenarios", show_header=True, header_style="bold cyan")
    table.add_column("ID", style="bold", min_width=30)
    table.add_column("Platform", min_width=28)
    table.add_column("Title")

    for meta in index:
        sid = meta.get("scenario", "")
        platform = meta.get("platform", "")
        label = PLATFORM_LABELS.get(platform, platform)
        title = meta.get("title", "")
        table.add_row(sid, label, title)

    console.print(table)
    console.print(
        "\nRun [bold]modellable scenario show <id>[/bold] to inspect a scenario, "
        "or [bold]modellable scenario load <id>[/bold] to copy it to a directory."
    )


@scenario.command("show")
@click.argument("scenario_id")
@click.option("--raw", is_flag=True, default=False, help="Print raw YAML without syntax highlighting.")
def show_scenario(scenario_id: str, raw: bool) -> None:
    """Show the full YAML definitions for a scenario."""
    try:
        meta, docs = load_scenario_by_id(scenario_id)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    platform = meta.get("platform", "")
    title = meta.get("title", scenario_id)
    description = meta.get("description", "").strip()
    tags = meta.get("tags", [])

    console.rule(f"[bold cyan]{title}[/bold cyan]")
    console.print(f"[dim]Platform:[/dim] {PLATFORM_LABELS.get(platform, platform)}")
    if tags:
        console.print(f"[dim]Tags:[/dim] {', '.join(tags)}")
    if description:
        console.print()
        console.print(description)
    console.print()

    yaml_text = "---\n".join(yaml.dump(d, default_flow_style=False, sort_keys=False) for d in docs)

    if raw:
        click.echo(yaml_text)
    else:
        syntax = Syntax(yaml_text, "yaml", theme="monokai", line_numbers=False, word_wrap=True)
        console.print(syntax)


@scenario.command("load")
@click.argument("scenario_id")
@click.option(
    "--output-dir",
    "-o",
    default=".",
    show_default=True,
    help="Directory to write the scenario YAML file into.",
)
def load_scenario(scenario_id: str, output_dir: str) -> None:
    """Copy a scenario YAML file into an output directory."""
    try:
        _, docs = load_scenario_by_id(scenario_id)
        sdir = scenarios_dir()
    except (ValueError, FileNotFoundError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    # Locate the source file
    source_file: Path | None = None
    for f in sdir.glob("*.yaml"):
        raw = f.read_text()
        if f"scenario: {scenario_id}" in raw:
            source_file = f
            break

    if not source_file:
        console.print(f"[red]Error:[/red] Could not locate source file for scenario '{scenario_id}'")
        raise SystemExit(1)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / source_file.name
    shutil.copy2(source_file, dest)
    console.print(f"[green]✓[/green] Copied [bold]{source_file.name}[/bold] → [bold]{dest}[/bold]")
    console.print(
        f"\nNext steps:\n"
        f"  [dim]modellable validate {dest}[/dim]          — validate the definitions\n"
        f"  [dim]modellable describe {dest}[/dim]          — explain the scenario with AI\n"
        f"  [dim]modellable create model[/dim]             — add new model definitions\n"
    )
