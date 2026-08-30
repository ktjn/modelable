from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from modelable.commands.common import console, load_workspace_or_exit
from modelable.compat.checker import (
    CompatibilityReport,
    ProjectionCompatibilityReport,
    check_model_version_compatibility,
    check_projection_version_compatibility,
)
from modelable.compat.targets import compare_model_storage_migration, compare_projection_rebuild
from modelable.consequence import (
    build_consequence_graph,
    build_model_consequences,
    build_projection_consequences,
    build_target_consequences,
    build_usage_consumer_consequences,
    change_nodes_for_report,
    projection_change_nodes,
)
from modelable.diagnostics.model import render_diagnostic
from modelable.llm.context import parse_model_ref_version_spec
from modelable.parser.ir import ProjectionVersion
from modelable.registry.resolver import resolve_model_ref
from modelable.registry.snapshot import load_workspace_with_snapshot
from modelable.registry.usage_protocol import UsageProtocolError, load_usage_manifest


def register_impact_commands(cli_group: click.Group) -> None:
    cli_group.add_command(impact)


@click.command("impact")
@click.option("--from", "from_ref", required=True, help="Previous exact model version reference.")
@click.option("--to", "to_ref", required=True, help="Candidate exact model version reference.")
@click.option("--path", "source", required=True, type=click.Path(exists=True, path_type=Path))
@click.option(
    "--snapshot",
    "snapshot_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Validated local registry snapshot containing additional contracts.",
)
@click.option(
    "--usage-manifest",
    "usage_manifest_paths",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Validated usage manifest for a known compiled consumer (repeatable).",
)
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def impact(
    from_ref: str,
    to_ref: str,
    source: Path,
    snapshot_path: Path | None,
    usage_manifest_paths: tuple[Path, ...],
    output_format: str,
) -> None:
    """Report compatibility consequences for a version change."""
    workspace = load_workspace_or_exit(source)
    if snapshot_path is not None:
        try:
            workspace = load_workspace_with_snapshot(workspace, snapshot_path)
        except (FileNotFoundError, ValueError) as exc:
            console.print(f"[red]ERROR[/red] Cannot load offline registry snapshot: {exc}")
            sys.exit(1)
        if workspace.errors:
            for diagnostic in workspace.errors:
                console.print(f"[red]ERROR[/red] {render_diagnostic(diagnostic)}", soft_wrap=True)
            sys.exit(1)
    try:
        usage_manifests = [load_usage_manifest(path) for path in usage_manifest_paths]
    except UsageProtocolError as exc:
        console.print(f"[red]ERROR[/red] Cannot load usage manifest: {exc}")
        sys.exit(1)
    try:
        from_domain, from_name, from_spec = parse_model_ref_version_spec(from_ref)
        to_domain, to_name, to_spec = parse_model_ref_version_spec(to_ref)
        if (from_domain, from_name) != (to_domain, to_name):
            raise ValueError("impact requires refs from the same domain and model")
        old = resolve_model_ref(workspace.mdl, from_ref.split("@", 1)[0], from_spec)
        new = resolve_model_ref(workspace.mdl, to_ref.split("@", 1)[0], to_spec)
        if old.version.__class__ is not new.version.__class__:
            raise ValueError("impact requires refs of the same definition kind")
        if not hasattr(old.version, "fields") or not hasattr(new.version, "fields"):
            raise ValueError("impact currently supports model and projection versions")
        report: CompatibilityReport | ProjectionCompatibilityReport
        if isinstance(old.version, ProjectionVersion):
            report = check_projection_version_compatibility(
                workspace.mdl,
                old.domain_name,
                old.model_name,
                old.version.version,
                new.version.version,
            )
        else:
            report = check_model_version_compatibility(
                workspace.mdl,
                old.domain_name,
                old.model_name,
                old.version.version,
                new.version.version,
            )
    except (LookupError, ValueError) as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        sys.exit(1)

    if isinstance(report, ProjectionCompatibilityReport):
        consequences = build_projection_consequences(
            report,
            compare_projection_rebuild(report.domain_name, report.projection_name, report.changes),
        )
        change_nodes = projection_change_nodes(report)
    else:
        consequences = build_model_consequences(workspace, report)
        consequences.extend(build_target_consequences(report, compare_model_storage_migration(report)))
        change_nodes = change_nodes_for_report(report)
    consequences.extend(build_usage_consumer_consequences(consequences, usage_manifests))
    payload = {
        "kind": "consequence_report",
        "from": from_ref,
        "to": to_ref,
        "status": report.status,
        "findings": report.findings,
        "consequences": [consequence.as_dict() for consequence in consequences],
        "consequence_graph": build_consequence_graph(consequences, change_nodes),
    }
    if output_format == "json":
        click.echo(json.dumps(payload, indent=2, sort_keys=True))
        if report.status == "breaking":
            sys.exit(1)
        return

    console.print(f"{from_ref} -> {to_ref}")
    console.print(f"status: {report.status}")
    for consequence in consequences:
        reason = f" ({consequence.reason})" if consequence.reason else ""
        console.print(f"- {consequence.action}: {consequence.subject}{reason}")
        if consequence.causal_path:
            console.print(f"  path: {' -> '.join(consequence.causal_path)}")
    if report.status == "breaking":
        sys.exit(1)
