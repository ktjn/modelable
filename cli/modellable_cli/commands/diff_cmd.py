"""diff command — compare two model or projection versions field by field."""

from __future__ import annotations

import click
from rich import box
from rich.console import Console
from rich.table import Table

from ..resolver import ModelRef, find_doc

console = Console()

_BREAKING = "[red]✗ breaking[/red]"
_COMPATIBLE = "[green]✓ compatible[/green]"
_CHECK = "[yellow]⚠ check[/yellow]"


def _summary(fdef: dict) -> str:
    parts = [fdef.get("type", "?")]
    for flag in ("required", "nullable", "deprecated"):
        if fdef.get(flag):
            parts.append(flag)
    if fdef.get("classification"):
        parts.append(fdef["classification"])
    return ", ".join(parts)


@click.command("diff")
@click.argument("ref_a")
@click.argument("ref_b")
@click.option(
    "--path", "-p",
    default=".",
    show_default=True,
    type=click.Path(exists=True),
    help="Directory to search for YAML definitions.",
)
def diff(ref_a: str, ref_b: str, path: str) -> None:
    """Compare two model or projection versions field by field.

    \b
    REF format: domain.ModelName.vVersion
    Examples:
      modellable diff customer.Customer.v1 customer.Customer.v2
    """
    try:
        mref_a = ModelRef.parse(ref_a)
        mref_b = ModelRef.parse(ref_b)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    doc_a = find_doc(mref_a, path)
    doc_b = find_doc(mref_b, path)

    if doc_a is None:
        console.print(f"[red]Not found:[/red] {ref_a}")
        raise SystemExit(1)
    if doc_b is None:
        console.print(f"[red]Not found:[/red] {ref_b}")
        raise SystemExit(1)

    fields_a: dict = doc_a.get("fields") or {}
    fields_b: dict = doc_b.get("fields") or {}
    all_fields = sorted(set(list(fields_a) + list(fields_b)))

    added   = [f for f in all_fields if f not in fields_a]
    removed = [f for f in all_fields if f not in fields_b]
    common  = [f for f in all_fields if f in fields_a and f in fields_b]

    console.print(f"\n[bold]Diff:[/bold] {ref_a} → {ref_b}\n")

    tbl = Table(box=box.SIMPLE_HEAD, show_header=True, pad_edge=False)
    tbl.add_column("", width=2)
    tbl.add_column("Field", no_wrap=True)
    tbl.add_column("Before")
    tbl.add_column("After")
    tbl.add_column("Compatible?", no_wrap=True)

    changes = 0

    for fname in added:
        fdef = fields_b[fname]
        req = isinstance(fdef, dict) and fdef.get("required", False)
        tbl.add_row(
            "[green]+[/green]", fname, "[dim]—[/dim]",
            _summary(fdef) if isinstance(fdef, dict) else str(fdef),
            _BREAKING if req else _COMPATIBLE,
        )
        changes += 1

    for fname in removed:
        fdef = fields_a[fname]
        tbl.add_row(
            "[red]-[/red]", fname,
            _summary(fdef) if isinstance(fdef, dict) else str(fdef),
            "[dim]—[/dim]",
            _BREAKING,
        )
        changes += 1

    for fname in common:
        fa, fb = fields_a[fname], fields_b[fname]
        if not isinstance(fa, dict) or not isinstance(fb, dict):
            continue
        sa, sb = _summary(fa), _summary(fb)
        if sa == sb:
            continue
        type_changed = fa.get("type") != fb.get("type")
        cls_changed = fa.get("classification") != fb.get("classification")
        compat = _CHECK if (type_changed or cls_changed) else _COMPATIBLE
        tbl.add_row("[yellow]~[/yellow]", fname, sa, sb, compat)
        changes += 1

    if changes:
        console.print(tbl)
        console.print(f"[dim]{changes} change(s)[/dim]")
    else:
        console.print("[green]No field-level differences.[/green]")
