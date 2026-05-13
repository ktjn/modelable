"""validate command — structural validation of Modellable YAML definitions."""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from ..loader import load_definitions_from_path
from ..validator import validate_file

console = Console()


@click.command("validate")
@click.argument("path", default=".", type=click.Path(exists=True))
@click.option("--strict", is_flag=True, default=False, help="Treat warnings as errors.")
def validate(path: str, strict: bool) -> None:
    """Validate Modellable YAML definitions at PATH (file or directory)."""
    file_docs = load_definitions_from_path(path)

    if not file_docs:
        console.print("[yellow]No YAML files found.[/yellow]")
        raise SystemExit(0)

    all_ok = True
    total_errors = 0
    total_warnings = 0

    for file_path, docs in file_docs:
        result = validate_file(str(file_path), docs)
        effective_errors = result.errors + (result.warnings if strict else [])

        if not effective_errors and not result.warnings:
            console.print(f"[green]✓[/green] {file_path}")
        elif not effective_errors and result.warnings:
            console.print(f"[yellow]⚠[/yellow] {file_path}")
            for w in result.warnings:
                console.print(f"    [yellow]warn[/yellow]  {w}")
        else:
            console.print(f"[red]✗[/red] {file_path}")
            for e in result.errors:
                console.print(f"    [red]error[/red] {e}")
            for w in result.warnings:
                console.print(f"    [yellow]warn[/yellow]  {w}")
            all_ok = False

        total_errors += len(result.errors)
        total_warnings += len(result.warnings)

    console.print()
    if strict:
        total_errors += total_warnings

    if total_errors == 0 and total_warnings == 0:
        console.print(f"[bold green]All {len(file_docs)} file(s) valid.[/bold green]")
    elif total_errors == 0:
        console.print(
            f"[bold yellow]{len(file_docs)} file(s) validated with {total_warnings} warning(s).[/bold yellow]"
        )
    else:
        console.print(
            f"[bold red]{total_errors} error(s)[/bold red], "
            f"{total_warnings} warning(s) across {len(file_docs)} file(s)."
        )
        raise SystemExit(1)
