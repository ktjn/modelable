from __future__ import annotations

from pathlib import Path

import click

from modelable.commands.common import console, load_workspace_or_exit
from modelable.compat.checker import check_model_version_compatibility
from modelable.llm.context import parse_model_ref


def register_diff_commands(cli_group: click.Group) -> None:
    cli_group.add_command(diff)


@click.command()
@click.argument("from_ref")
@click.argument("to_ref")
@click.option("--path", "path", type=click.Path(exists=True, path_type=Path), required=True)
def diff(from_ref: str, to_ref: str, path: Path) -> None:
    """Compare two published model versions."""
    workspace = load_workspace_or_exit(path)
    try:
        from_model = parse_model_ref(from_ref)
        to_model = parse_model_ref(to_ref)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if from_model.domain != to_model.domain or from_model.name != to_model.name:
        raise click.ClickException("diff requires refs from the same domain and model")

    try:
        report = check_model_version_compatibility(
            workspace.mdl,
            from_model.domain,
            from_model.name,
            from_model.version,
            to_model.version,
        )
    except LookupError as exc:
        raise click.ClickException(str(exc)) from exc

    console.print(f"{from_ref} -> {to_ref}")
    console.print(f"status: {report.status}")
    if report.findings:
        for finding in report.findings:
            console.print(f"- {finding}")
    else:
        console.print("- no changes")
