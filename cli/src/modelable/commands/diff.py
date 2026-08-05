from __future__ import annotations

from pathlib import Path

import click

from modelable.commands.common import console
from modelable.compat.checker import (
    analyze_impact,
    check_model_version_compatibility,
    check_projection_version_compatibility,
)
from modelable.compiler.workspace import Workspace, load_workspace
from modelable.llm.context import parse_model_ref_version_spec
from modelable.parser.ir import ProjectionVersion
from modelable.registry.resolver import ResolvedModelRef, find_dependents, resolve_model_ref


def register_diff_commands(cli_group: click.Group) -> None:
    cli_group.add_command(diff)


def run_diff(from_ref: str, to_ref: str, path: Path) -> None:
    """Compare two published model or projection versions and print the compatibility report."""
    workspace = load_workspace(path)
    try:
        from_domain, from_name, from_version_spec = parse_model_ref_version_spec(from_ref)
        to_domain, to_name, to_version_spec = parse_model_ref_version_spec(to_ref)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if from_domain != to_domain or from_name != to_name:
        raise click.ClickException("diff requires refs from the same domain and model")

    try:
        from_resolved = resolve_model_ref(workspace.mdl, f"{from_domain}.{from_name}", from_version_spec)
        to_resolved = resolve_model_ref(workspace.mdl, f"{to_domain}.{to_name}", to_version_spec)
    except LookupError as exc:
        raise click.ClickException(str(exc)) from exc

    if isinstance(from_resolved.version, ProjectionVersion):
        _run_projection_diff(workspace, from_ref, to_ref, from_resolved, to_resolved)
        return

    _run_model_diff(workspace, from_ref, to_ref, from_resolved, to_resolved)


def _run_model_diff(
    workspace: Workspace,
    from_ref: str,
    to_ref: str,
    from_model: ResolvedModelRef,
    to_model: ResolvedModelRef,
) -> None:
    try:
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

    dependents = find_dependents(
        workspace.mdl, from_model.domain_name, from_model.model_name, from_model.version.version
    )
    if dependents:
        impacts = []
        for dep in dependents:
            impact = analyze_impact(workspace.mdl, report, dep)
            if impact.status != "compatible":
                impacts.append(impact)

        if impacts:
            console.print("\nImpacted Projections:")
            for impact in impacts:
                status_tag = f"[{impact.status.upper()}]"
                color = "red" if impact.status == "broken" else "yellow"
                line = (
                    f"- [{color}]{status_tag}[/{color}] {impact.domain_name}.{impact.projection_name}@{impact.version}"
                )
                if impact.reason:
                    line += f" ({impact.reason})"
                console.print(line)

    if report.status == "breaking":
        raise click.exceptions.Exit(1)


def _run_projection_diff(
    workspace: Workspace,
    from_ref: str,
    to_ref: str,
    from_projection: ResolvedModelRef,
    to_projection: ResolvedModelRef,
) -> None:
    # Downstream-impact analysis (find_dependents/analyze_impact) answers
    # "who depends on this model changing" and is not extended to
    # projection-of-projection dependents here — that's a distinct concern
    # from "did this projection's own definition change compatibly", and is
    # out of scope for Slice C1 (see the design doc's "Scope" section).
    try:
        report = check_projection_version_compatibility(
            workspace.mdl,
            from_projection.domain_name,
            from_projection.model_name,
            from_projection.version.version,
            to_projection.version.version,
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

    if report.status == "breaking":
        raise click.exceptions.Exit(1)


@click.command()
@click.argument("from_ref")
@click.argument("to_ref")
@click.option("--path", "path", type=click.Path(exists=True, path_type=Path), required=True)
def diff(from_ref: str, to_ref: str, path: Path) -> None:
    """Compare two published model or projection versions."""
    run_diff(from_ref, to_ref, path)
