from __future__ import annotations

from pathlib import Path

import click

from modelable.commands.common import console, load_workspace_or_exit
from modelable.compat.targets import (
    PASSING_STATUSES,
    TargetCompatibilityReport,
    compare_grpc_artifacts,
    compare_protobuf_manifests,
)
from modelable.emitters.grpc import emit_grpc
from modelable.emitters.protobuf import emit_protobuf


def register_validate_compat_commands(cli_group: click.Group) -> None:
    cli_group.add_command(validate_compat)


@click.command("validate-compat")
@click.option("--from", "from_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--to", "to_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--target", type=click.Choice(["protobuf", "grpc"]), required=True)
def validate_compat(from_path: Path, to_path: Path, target: str) -> None:
    """Validate target-specific compatibility between two Modelable workspaces."""
    old_workspace = load_workspace_or_exit(from_path)
    new_workspace = load_workspace_or_exit(to_path)

    if target == "protobuf":
        report = compare_protobuf_manifests(
            emit_protobuf(old_workspace, Path(".modelable/compat/old/protobuf")),
            emit_protobuf(new_workspace, Path(".modelable/compat/new/protobuf")),
        )
    else:
        report = compare_grpc_artifacts(
            emit_grpc(old_workspace, Path(".modelable/compat/old/grpc")),
            emit_grpc(new_workspace, Path(".modelable/compat/new/grpc")),
        )

    _render_report(report)
    if report.status not in PASSING_STATUSES:
        raise click.exceptions.Exit(1)


def _render_report(report: TargetCompatibilityReport) -> None:
    console.print(f"target: {report.target}", markup=False)
    console.print(f"status: {report.status}", markup=False)
    if not report.findings:
        console.print("- no target compatibility findings", markup=False)
        return

    for finding in report.findings:
        subject = finding.field or finding.index or finding.ref
        console.print(
            f"- [{finding.status}] {finding.code}: {subject}: {finding.message}",
            markup=False,
        )
