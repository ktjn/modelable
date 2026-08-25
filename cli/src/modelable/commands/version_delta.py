from __future__ import annotations

import sys
from pathlib import Path

import click

from modelable.commands.common import console
from modelable.compiler.render import _render_evolution_operation
from modelable.llm.context import parse_model_ref
from modelable.refactor.compact_version import CompactVersionError, apply_compact_version, compact_version
from modelable.refactor.expand_version import ExpandVersionError, apply_expand_version, expand_version


def register_version_delta_commands(cli_group: click.Group) -> None:
    cli_group.add_command(expand_version_command)
    cli_group.add_command(compact_version_command)


@click.command("expand-version")
@click.argument("ref")
@click.option("--path", "path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("--dry-run", is_flag=True, help="Print the diff without writing any files.")
def expand_version_command(ref: str, path: Path, dry_run: bool) -> None:
    """Expand an evolves-declared model version (REF: domain.Model@version)
    into its complete full-form declaration, for review or to stop
    authoring that version as a delta.

    Purely an ergonomics change: every implemented codegen target's output
    is verified byte-identical before anything is written.
    """
    try:
        model_ref = parse_model_ref(ref)
    except ValueError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        sys.exit(1)

    try:
        if dry_run:
            result = expand_version(path, model_ref.domain, model_ref.name, model_ref.version)
        else:
            result = apply_expand_version(path, model_ref.domain, model_ref.name, model_ref.version)
    except ExpandVersionError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        sys.exit(1)

    console.print(result.diff_text, markup=False)
    if dry_run:
        console.print("[yellow]Dry run[/yellow] -- no files written.")
    else:
        console.print(f"[green]OK[/green] expanded {ref}; wrote: {result.written_path}")


@click.command("compact-version")
@click.argument("ref")
@click.option("--path", "path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("--dry-run", is_flag=True, help="Print the diff without writing any files.")
def compact_version_command(ref: str, path: Path, dry_run: bool) -> None:
    """Compact a full-form model version (REF: domain.Model@version) into an
    evolves delta against its base version.

    Only proposes add/remove/replace, plus a rename when the removed field
    carries @deprecated(replacedBy: "..."); any other removed/added pair
    stays a separate remove and add. Aborts if the result would reorder
    fields or otherwise change any implemented codegen target's output --
    A2 is authoring ergonomics only, never a contract or artifact change.
    """
    try:
        model_ref = parse_model_ref(ref)
    except ValueError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        sys.exit(1)

    try:
        if dry_run:
            result = compact_version(path, model_ref.domain, model_ref.name, model_ref.version)
        else:
            result = apply_compact_version(path, model_ref.domain, model_ref.name, model_ref.version)
    except CompactVersionError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        sys.exit(1)

    console.print(result.diff_text, markup=False)
    console.print(f"base: @ {result.base_version}")
    for operation in result.operations:
        console.print(f"  {_render_evolution_operation(operation).strip()}", markup=False)
    if dry_run:
        console.print("[yellow]Dry run[/yellow] -- no files written.")
    else:
        console.print(f"[green]OK[/green] compacted {ref}; wrote: {result.written_path}")
