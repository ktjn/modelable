from __future__ import annotations

from pathlib import Path

import click

from modelable.commands.common import console, load_workspace_or_exit
from modelable.compat.checker import check_model_version_compatibility
from modelable.llm.context import parse_model_ref_version_spec
from modelable.registry.resolver import resolve_model_ref


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
        from_domain, from_name, from_version_spec = parse_model_ref_version_spec(from_ref)
        to_domain, to_name, to_version_spec = parse_model_ref_version_spec(to_ref)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if from_domain != to_domain or from_name != to_name:
        raise click.ClickException("diff requires refs from the same domain and model")

    try:
        from_model = resolve_model_ref(workspace.mdl, f"{from_domain}.{from_name}", from_version_spec)
        to_model = resolve_model_ref(workspace.mdl, f"{to_domain}.{to_name}", to_version_spec)
        report = check_model_version_compatibility(
            workspace.mdl,
            from_model.domain_name,
            from_model.model_name,
            from_model.version.version,
            to_model.version.version,
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
