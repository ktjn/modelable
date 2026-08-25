from __future__ import annotations

import sys
from pathlib import Path

import click

from modelable.commands.common import console
from modelable.refactor.extract_enum import (
    ExtractEnumError,
    ExtractEnumPlan,
    apply_extract_enum,
    extract_enum,
    parse_field_location,
)


def register_extract_enum_commands(cli_group: click.Group) -> None:
    cli_group.add_command(extract_enum_command)


@click.command("extract-enum")
@click.option("--name", "canonical_name", required=True, help="Name for the new semantic enum declaration.")
@click.option("--domain", "owning_domain", required=True, help="Domain that will own the new semantic enum.")
@click.option(
    "--change-kind",
    type=click.Choice(["additive", "breaking"]),
    default="additive",
    show_default=True,
)
@click.option(
    "--field",
    "field_refs",
    multiple=True,
    required=True,
    help="domain.Model@version.field to convert to a reference. Repeat for each occurrence (at least two).",
)
@click.option("--path", "path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("--dry-run", is_flag=True, help="Print the diff without writing any files.")
def extract_enum_command(
    canonical_name: str,
    owning_domain: str,
    change_kind: str,
    field_refs: tuple[str, ...],
    path: Path,
    dry_run: bool,
) -> None:
    """Extract a shared semantic enum from selected identically-shaped
    anonymous enum(...) fields (see the ENUMSHAPE discovery lint).

    Requires explicit choices: a canonical name, an owning domain, and every
    field location to convert -- extraction never infers or merges shapes on
    its own. Every selected field must currently share the exact same member
    set; use `modelable validate` to see ENUMSHAPE findings first.
    """
    try:
        locations = tuple(parse_field_location(ref) for ref in field_refs)
        plan = ExtractEnumPlan(
            canonical_name=canonical_name,
            owning_domain=owning_domain,
            change_kind=change_kind,
            fields=locations,
        )
        result = extract_enum(path, plan) if dry_run else apply_extract_enum(path, plan)
    except ExtractEnumError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        sys.exit(1)

    console.print(result.diff_text, markup=False)
    if dry_run:
        console.print(
            f"[yellow]Dry run[/yellow] -- {canonical_name} @ 1 "
            f"({', '.join(result.canonical_members)}) would be extracted; no files written."
        )
    else:
        written = ", ".join(str(item) for item in result.written_paths)
        console.print(f"[green]OK[/green] extracted {owning_domain}.{canonical_name} @ 1; wrote: {written}")
