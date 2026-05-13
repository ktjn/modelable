"""Commands for exploring supported artifact formats and language type mappings."""

from __future__ import annotations

import click
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich import box

from ..languages import (
    ARTIFACT_FORMATS,
    CATEGORY_LABELS,
    CATEGORY_ORDER,
    MODELLABLE_TYPES,
    formats_by_category,
    get_format,
)

console = Console()


@click.group("codegen")
def codegen() -> None:
    """Explore supported artifact formats and type mappings for code generation.

    \b
    Commands:
      list          List all supported artifact formats grouped by category
      types <fmt>   Show the type mapping table for a specific format
    """


@codegen.command("list")
@click.option(
    "--category",
    "-c",
    type=click.Choice(list(CATEGORY_LABELS.keys())),
    default=None,
    help="Filter by category.",
)
def codegen_list(category: str | None) -> None:
    """List all supported artifact formats, optionally filtered by category."""
    by_cat = formats_by_category()
    shown_any = False

    for cat in CATEGORY_ORDER:
        if category and cat != category:
            continue
        formats = by_cat.get(cat, [])
        if not formats:
            continue
        shown_any = True

        label = CATEGORY_LABELS[cat]
        console.rule(f"[bold cyan]{label}[/bold cyan]")

        tbl = Table(box=box.SIMPLE, show_header=True, pad_edge=False)
        tbl.add_column("Format ID", style="bold green", no_wrap=True)
        tbl.add_column("Name", style="bold")
        tbl.add_column("Extension", style="dim", no_wrap=True)
        tbl.add_column("Description")

        for fmt in formats:
            tbl.add_row(fmt.id, fmt.name, fmt.file_extension, fmt.description)

        console.print(tbl)

    if not shown_any:
        console.print("[yellow]No formats found for the specified filter.[/yellow]")
        return

    total = len(ARTIFACT_FORMATS)
    console.print(
        f"[dim]{total} formats total. Run [bold]modellable codegen types <format-id>[/bold] "
        f"to see type mappings for any format.[/dim]"
    )


@codegen.command("types")
@click.argument("format_id")
def codegen_types(format_id: str) -> None:
    """Show the Modellable → native type mapping table for FORMAT_ID.

    \b
    Example:
      modellable codegen types typescript
      modellable codegen types sql_postgresql
      modellable codegen types protobuf
    """
    fmt = get_format(format_id)
    if fmt is None:
        close = _suggest_close(format_id)
        msg = f"Unknown format: [bold red]{format_id}[/bold red]"
        if close:
            msg += f"\n\nDid you mean: [bold]{', '.join(close)}[/bold]?"
        msg += "\n\nRun [bold]modellable codegen list[/bold] to see all supported formats."
        console.print(msg)
        raise SystemExit(1)

    cat_label = CATEGORY_LABELS[fmt.category]
    console.rule(f"[bold cyan]{fmt.name}[/bold cyan]  [dim]({cat_label})[/dim]")
    console.print(f"[dim]{fmt.description}[/dim]\n")
    console.print(f"[bold]Format ID:[/bold]    [green]{fmt.id}[/green]")
    console.print(f"[bold]Extension:[/bold]    {fmt.file_extension}\n")

    tbl = Table(box=box.SIMPLE_HEAD, show_header=True, pad_edge=False)
    tbl.add_column("Modellable Type", style="bold", no_wrap=True)
    tbl.add_column(f"→  {fmt.name} Type", style="green")
    tbl.add_column("Notes", style="dim")

    for mtype in MODELLABLE_TYPES:
        native = escape(fmt.type_map.get(mtype, "—"))
        note = escape(fmt.notes.get(mtype, ""))
        tbl.add_row(mtype, native, note)

    console.print(tbl)

    if fmt.notes:
        console.print()
        for mtype, note in fmt.notes.items():
            console.print(f"  [yellow]⚠[/yellow]  [bold]{mtype}:[/bold] {note}")


def _suggest_close(query: str, max_results: int = 3) -> list[str]:
    """Return format IDs that share a prefix or substring with *query*."""
    q = query.lower()
    candidates = [
        fid for fid in ARTIFACT_FORMATS
        if q in fid or fid.startswith(q.split("_")[0])
    ]
    return candidates[:max_results]
