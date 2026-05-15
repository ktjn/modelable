from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console

from modelable.compiler.compiler import compile_file
from modelable.parser.ir import ParseError

console = Console()


@click.group()
def cli() -> None:
    """Modelable domain-owned data model compiler."""


@cli.command()
@click.argument("path", default=".", type=click.Path(exists=True, path_type=Path))
@click.option("--strict", is_flag=True, help="Exit non-zero on any validation error.")
def validate(path: Path, strict: bool) -> None:
    """Validate Modelable definition files at PATH."""
    files = [path] if path.is_file() else sorted(path.rglob("*.mdl"))

    if not files:
        console.print("[yellow]No .mdl files found.[/yellow]")
        sys.exit(0)

    total_errors: list[tuple[Path, str]] = []
    for mdl_file in files:
        try:
            _, errors = compile_file(mdl_file)
        except ParseError as exc:
            total_errors.append((mdl_file, f"Syntax error: {exc}"))
            continue

        total_errors.extend((mdl_file, error) for error in errors)

    if total_errors:
        for mdl_file, error in total_errors:
            console.print(f"[red]ERROR[/red] {mdl_file}: {error}")
        sys.exit(1)

    if len(files) == 1:
        console.print(f"[green]OK[/green] {files[0]} is valid.")
    else:
        console.print(f"[green]OK[/green] {len(files)} files valid.")

    sys.exit(0)
