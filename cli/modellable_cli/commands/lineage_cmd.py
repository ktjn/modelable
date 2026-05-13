"""lineage command — trace field lineage for a model or projection."""

from __future__ import annotations

import click
from rich.console import Console
from rich.tree import Tree

from ..loader import detect_doc_type
from ..resolver import ModelRef, find_doc

console = Console()


@click.command("lineage")
@click.argument("ref")
@click.option(
    "--path", "-p",
    default=".",
    show_default=True,
    type=click.Path(exists=True),
    help="Directory to search for YAML definitions.",
)
def lineage(ref: str, path: str) -> None:
    """Show field-level lineage for a model or projection.

    \b
    For projections: shows which source field each output field derives from.
    For models: shows fields with their type and classification.

    \b
    REF format: domain.ModelName.vVersion
    Examples:
      modellable lineage billing.BillingCustomer.v1
      modellable lineage customer.Customer.v2
    """
    try:
        model_ref = ModelRef.parse(ref)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    doc = find_doc(model_ref, path)
    if doc is None:
        console.print(f"[red]Not found:[/red] No definition for [bold]{ref}[/bold]")
        raise SystemExit(1)

    dtype = detect_doc_type(doc)
    fields = doc.get("fields") or {}

    if not fields:
        console.print(f"[yellow]No fields defined in {ref}[/yellow]")
        return

    tree = Tree(f"[bold cyan]{ref}[/bold cyan]")

    if dtype == "projection":
        source_map = {
            src.get("alias", src.get("model")): src
            for src in (doc.get("sources") or [])
        }
        for fname, fdef in fields.items():
            if not isinstance(fdef, dict):
                continue
            cls = fdef.get("classification", "")
            cls_tag = f" [dim][{cls}][/dim]" if cls else ""
            if "from" in fdef:
                alias, _, src_field = str(fdef["from"]).partition(".")
                src_info = source_map.get(alias)
                if src_info:
                    full_src = (
                        f"{src_info.get('domain','?')}."
                        f"{src_info.get('model','?')}."
                        f"v{src_info.get('version','?')}."
                        f"{src_field}"
                    )
                else:
                    full_src = fdef["from"]
                branch = tree.add(f"[green]{fname}[/green]{cls_tag}")
                branch.add(f"[dim]← {full_src}[/dim]")
            elif "expression" in fdef:
                branch = tree.add(f"[yellow]{fname}[/yellow]{cls_tag} [dim](computed)[/dim]")
                branch.add(f"[dim]= {fdef['expression']}[/dim]")
    else:
        for fname, fdef in fields.items():
            if not isinstance(fdef, dict):
                continue
            cls = fdef.get("classification", "")
            cls_tag = f" [dim][{cls}][/dim]" if cls else ""
            ftype = fdef.get("type", "?")
            tree.add(f"[green]{fname}[/green]: {ftype}{cls_tag}  [dim](canonical)[/dim]")

    console.print(tree)
