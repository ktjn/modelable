from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from modelable.commands.common import console, load_workspace_or_exit
from modelable.compat.checker import CompatibilityReport, analyze_impact, check_model_version_compatibility
from modelable.compiler.workspace import Workspace
from modelable.consequence import (
    ACTION_BREAKING,
    ACTION_RECOMPILE,
    Consequence,
    action_for_projection_status,
    build_consequence_graph,
)
from modelable.llm.context import parse_model_ref_version_spec
from modelable.registry.resolver import find_dependents, resolve_model_ref


def register_impact_commands(cli_group: click.Group) -> None:
    cli_group.add_command(impact)


@click.command("impact")
@click.option("--from", "from_ref", required=True, help="Previous exact model version reference.")
@click.option("--to", "to_ref", required=True, help="Candidate exact model version reference.")
@click.option("--path", "source", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def impact(from_ref: str, to_ref: str, source: Path, output_format: str) -> None:
    """Report compatibility consequences for a version change."""
    workspace = load_workspace_or_exit(source)
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

    consequences = _model_consequences(workspace, report)
    change_nodes = _change_nodes(report)
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


def _model_consequences(workspace: Workspace, report: CompatibilityReport) -> list[Consequence]:
    source_subject = f"{report.domain_name}.{report.model_name}@{report.to_version}"
    change_ids = tuple(_change_node_id(change.kind, change.field_name) for change in report.changes)
    consequences = [
        Consequence(
            action=ACTION_RECOMPILE if report.status == "compatible" else ACTION_BREAKING,
            subject=source_subject,
            status=report.status,
            reason="direct contract change",
            causal_path=(f"{report.domain_name}.{report.model_name}@{report.from_version}", source_subject),
            causal_changes=change_ids,
        )
    ]
    for dependent in find_dependents(workspace.mdl, report.domain_name, report.model_name, report.from_version):
        projection_impact = analyze_impact(workspace.mdl, report, dependent)
        subject = f"{projection_impact.domain_name}.{projection_impact.projection_name}@{projection_impact.version}"
        consequences.append(
            Consequence(
                action=action_for_projection_status(projection_impact.status),
                subject=subject,
                status=projection_impact.status,
                reason=projection_impact.reason,
                causal_path=(
                    f"{report.domain_name}.{report.model_name}@{report.from_version}",
                    subject,
                ),
                causal_changes=_projection_change_ids(projection_impact.status, projection_impact.reason, report),
            )
        )
    return consequences


def _change_nodes(report: CompatibilityReport) -> list[dict[str, object]]:
    if report.status == "compatible":
        return []
    return [
        {
            "id": _change_node_id(change.kind, change.field_name),
            "kind": "change",
            "change_kind": change.kind,
            "field": change.field_name,
        }
        for change in report.changes
    ]


def _change_node_id(change_kind: str, field_name: str) -> str:
    return f"change:{change_kind}:{field_name}"


def _projection_change_ids(status: str, reason: str | None, report: CompatibilityReport) -> tuple[str, ...]:
    if status == "compatible":
        return ()
    if reason is None or reason == "unresolved projection" or "marked breaking" in reason:
        return tuple(_change_node_id(change.kind, change.field_name) for change in report.changes)
    return tuple(
        _change_node_id(change.kind, change.field_name)
        for change in report.changes
        if f"field '{change.field_name}'" in reason
    )
