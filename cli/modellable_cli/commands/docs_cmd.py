"""docs command — generate Markdown documentation for all model definitions."""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console

from ..compiler.markdown import write_markdown
from ..loader import detect_doc_type, load_definitions_from_path

console = Console()


@click.command("docs")
@click.argument("path", default=".", type=click.Path(exists=True))
@click.option(
    "--out", "-o",
    default="./dist/docs",
    show_default=True,
    help="Output directory for generated Markdown files.",
)
def docs(path: str, out: str) -> None:
    """Generate Markdown documentation for all models and projections.

    \b
    Examples:
      modellable docs ./models --out ./dist/docs
      modellable docs .
    """
    out_dir = Path(out)
    all_docs = [
        doc
        for _fpath, file_docs in load_definitions_from_path(path)
        for doc in file_docs
        if detect_doc_type(doc) in ("model", "projection")
    ]

    if not all_docs:
        console.print("[yellow]No model or projection definitions found.[/yellow]")
        raise SystemExit(0)

    count = 0
    for doc in all_docs:
        domain = doc.get("domain", "?")
        name = doc.get("model") or doc.get("projection", "?")
        version = doc.get("version", "?")
        try:
            artifact_path = write_markdown(doc, out_dir)
            console.print(
                f"[green]✓[/green] {domain}.{name}.v{version} "
                f"→ [dim]{artifact_path}[/dim]"
            )
            count += 1
        except Exception as exc:
            console.print(f"[red]✗[/red] {domain}.{name}.v{version}: {exc}")

    console.print(f"\n[bold green]{count} doc(s) written to {out_dir}[/bold green]")
