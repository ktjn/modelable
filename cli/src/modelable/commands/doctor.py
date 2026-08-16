from __future__ import annotations

import json
from pathlib import Path

import click

from modelable.capabilities import build_capability_manifest
from modelable.commands.common import console
from modelable.compiler.workspace import load_workspace
from modelable.config import load_config
from modelable.registry.snapshot import snapshot_status


def register_doctor_commands(cli_group: click.Group) -> None:
    cli_group.add_command(doctor)


@click.command("doctor")
@click.argument("path", default=".", type=click.Path(exists=True, path_type=Path))
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def doctor(path: Path, output_format: str) -> None:
    """Check local compiler, configuration, and registry snapshot health offline."""
    workspace = load_workspace(path)
    config = load_config(path)
    snapshot = snapshot_status(path / ".modelable" if path.is_dir() else path.parent / ".modelable")
    capabilities = build_capability_manifest()
    healthy = not workspace.errors and snapshot["valid"] and Path(snapshot["lock"]).exists()
    payload = {
        "kind": "doctor_report",
        "workspace": {
            "sources": len(workspace.sources),
            "errors": len(workspace.errors),
            "warnings": len(workspace.warnings),
        },
        "config": {"path": str(config.path) if config.path is not None else None, "values": config.explain()},
        "snapshot": snapshot,
        "capabilities": {
            "count": len(capabilities.all()),
            "targets": [entry.name for entry in capabilities.targets],
        },
        "healthy": healthy,
    }
    workspace_sources = len(workspace.sources)
    snapshot_objects = snapshot["objects"]
    if output_format == "json":
        click.echo(json.dumps(payload, indent=2, sort_keys=True))
        if not healthy:
            raise click.exceptions.Exit(1)
        return
    state = "healthy" if healthy else "needs attention"
    console.print(f"{state}: {workspace_sources} workspace source(s), {snapshot_objects} snapshot object(s)")
    if workspace.errors:
        for error in workspace.errors:
            console.print(f"[red]ERROR[/red] {error.message}")
    for error in snapshot["errors"]:
        console.print(f"[red]ERROR[/red] {error}")
    if not healthy:
        raise click.exceptions.Exit(1)
