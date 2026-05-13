"""compile command — generate artifacts from Modellable model definitions."""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console

from ..compiler.json_schema import write_json_schema
from ..compiler.markdown import write_markdown
from ..compiler.typescript import write_typescript
from ..loader import detect_doc_type, load_definitions_from_path
from ..resolver import ModelRef, find_doc

console = Console()

_TARGETS = ["json-schema", "typescript", "markdown"]

_WRITERS = {
    "json-schema": write_json_schema,
    "typescript":  write_typescript,
    "markdown":    write_markdown,
}

_DEFAULT_SUBDIRS = {
    "json-schema": "jsonschema",
    "typescript":  "types",
    "markdown":    "docs",
}


@click.command("compile")
@click.argument("source")
@click.option(
    "--target", "-t",
    type=click.Choice(_TARGETS),
    required=True,
    help="Output artifact format.",
)
@click.option(
    "--out", "-o",
    default=None,
    help="Output directory (default: ./dist/<format>).",
)
@click.option(
    "--path", "-p",
    default=".",
    show_default=True,
    type=click.Path(exists=True),
    help="Search path when SOURCE is a model reference.",
)
def compile(source: str, target: str, out: str | None, path: str) -> None:
    """Compile model definitions to an artifact format.

    \b
    SOURCE can be a path to a YAML file or directory, or a model reference
    in the form domain.ModelName.vVersion.

    \b
    Examples:
      modellable compile ./models --target json-schema --out ./dist/jsonschema
      modellable compile customer.Customer.v1 --target json-schema
      modellable compile customer.Customer.v1 --target typescript
      modellable compile ./models --target markdown --out ./dist/docs
    """
    out_dir = Path(out) if out else Path("dist") / _DEFAULT_SUBDIRS[target]
    docs: list[dict] = []

    source_path = Path(source)
    if source_path.exists():
        for _fpath, file_docs in load_definitions_from_path(source_path):
            for doc in file_docs:
                if detect_doc_type(doc) in ("model", "projection"):
                    docs.append(doc)
    else:
        try:
            ref = ModelRef.parse(source)
        except ValueError:
            console.print(
                f"[red]Error:[/red] '{source}' is not a valid path or model reference.\n"
                "Expected a file/directory path or a reference like [bold]customer.Customer.v1[/bold]"
            )
            raise SystemExit(1)
        doc = find_doc(ref, path)
        if doc is None:
            console.print(f"[red]Not found:[/red] {source}")
            raise SystemExit(1)
        docs.append(doc)

    if not docs:
        console.print("[yellow]No model or projection definitions found.[/yellow]")
        raise SystemExit(0)

    write_fn = _WRITERS[target]
    count = 0
    for doc in docs:
        domain = doc.get("domain", "?")
        name = doc.get("model") or doc.get("projection", "?")
        version = doc.get("version", "?")
        try:
            artifact_path = write_fn(doc, out_dir)
            console.print(
                f"[green]✓[/green] {domain}.{name}.v{version} "
                f"→ [dim]{artifact_path}[/dim]"
            )
            count += 1
        except Exception as exc:
            console.print(f"[red]✗[/red] {domain}.{name}.v{version}: {exc}")

    console.print(f"\n[bold green]{count} artifact(s) written to {out_dir}[/bold green]")
