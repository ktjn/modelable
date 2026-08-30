from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from modelable.commands.common import console, load_workspace_or_exit
from modelable.registry.index import build_registry_from_snapshot
from modelable.registry.snapshot import (
    diff_workspace_snapshot,
    prune_snapshot,
    resolve_workspace_snapshot,
    snapshot_status,
    update_workspace_snapshot,
    verify_snapshot,
)
from modelable.registry.sources import LocalSourceAdapter
from modelable.registry.usage import build_usage_graph, build_usage_manifest
from modelable.registry.usage_protocol import serialize_usage_manifest


def register_registry_commands(cli_group: click.Group) -> None:
    cli_group.add_command(registry)


@click.group()
def registry() -> None:
    """Manage explicit, offline registry snapshots."""


@registry.command("resolve")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option("--out", "output_dir", type=click.Path(path_type=Path), default=Path(".modelable"), show_default=True)
def resolve(source: Path, output_dir: Path) -> None:
    """Resolve SOURCE into an exact local registry snapshot."""
    workspace = load_workspace_or_exit(source, source_adapter=LocalSourceAdapter())
    try:
        result = resolve_workspace_snapshot(workspace, output_dir)
    except ValueError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        sys.exit(1)
    console.print(f"[green]OK[/green] wrote {result.object_count} object(s) to {result.lock_path}")


@registry.command("diff")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option("--out", "output_dir", type=click.Path(path_type=Path), default=Path(".modelable"), show_default=True)
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def diff(source: Path, output_dir: Path, output_format: str) -> None:
    """Compare SOURCE with the current local snapshot without changing it."""
    workspace = load_workspace_or_exit(source, source_adapter=LocalSourceAdapter())
    try:
        snapshot_diff = diff_workspace_snapshot(workspace, output_dir)
    except ValueError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        sys.exit(1)
    payload = snapshot_diff.as_dict()
    if output_format == "json":
        click.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    if snapshot_diff.empty:
        console.print("[green]OK[/green] snapshot is unchanged")
        return
    for category in ("added", "removed", "changed"):
        for identity in payload[category]:
            console.print(f"{category}: {identity}")


@registry.command("update")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option("--out", "output_dir", type=click.Path(path_type=Path), default=Path(".modelable"), show_default=True)
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def update(source: Path, output_dir: Path, output_format: str) -> None:
    """Stage and atomically install SOURCE as the local exact snapshot."""
    workspace = load_workspace_or_exit(source, source_adapter=LocalSourceAdapter())
    try:
        result, snapshot_diff = update_workspace_snapshot(workspace, output_dir)
    except ValueError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        sys.exit(1)
    payload = {"lock": str(result.lock_path), "objects": result.object_count, **snapshot_diff.as_dict()}
    if output_format == "json":
        click.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    console.print(
        f"[green]OK[/green] updated {result.lock_path} "
        f"({len(snapshot_diff.added)} added, {len(snapshot_diff.changed)} changed, "
        f"{len(snapshot_diff.removed)} removed from the lock)"
    )


@registry.command("verify")
@click.option("--out", "output_dir", type=click.Path(path_type=Path), default=Path(".modelable"), show_default=True)
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def verify(output_dir: Path, output_format: str) -> None:
    """Verify registry hashes, signatures, and lock/object consistency offline."""
    errors = verify_snapshot(output_dir)
    payload = {"valid": not errors, "errors": errors}
    if output_format == "json":
        click.echo(json.dumps(payload, indent=2))
    elif errors:
        for error in errors:
            console.print(f"[red]ERROR[/red] {error}")
    else:
        console.print("[green]OK[/green] registry snapshot is valid")
    if errors:
        sys.exit(1)


@registry.command("rebuild-index")
@click.option("--out", "output_dir", type=click.Path(path_type=Path), default=Path(".modelable"), show_default=True)
def rebuild_index(output_dir: Path) -> None:
    """Rebuild registry.db from the durable snapshot without source refresh."""
    try:
        registry_path = build_registry_from_snapshot(output_dir)
    except ValueError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        sys.exit(1)
    console.print(f"[green]OK[/green] rebuilt derived registry index at {registry_path}")


@registry.command("status")
@click.option("--out", "output_dir", type=click.Path(path_type=Path), default=Path(".modelable"), show_default=True)
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def status(output_dir: Path, output_format: str) -> None:
    """Report local snapshot state without contacting a source registry."""
    payload = snapshot_status(output_dir)
    if output_format == "json":
        click.echo(json.dumps(payload, indent=2))
    else:
        state = "valid" if payload["valid"] else "invalid"
        console.print(f"{state} snapshot: {payload['objects']} object(s) in {payload['lock']}")
        for error in payload["errors"]:
            console.print(f"[red]ERROR[/red] {error}")
    if not payload["valid"]:
        sys.exit(1)


@registry.command("prune")
@click.option("--out", "output_dir", type=click.Path(path_type=Path), default=Path(".modelable"), show_default=True)
def prune(output_dir: Path) -> None:
    """Remove unreferenced content-addressed objects from a valid snapshot."""
    try:
        removed = prune_snapshot(output_dir)
    except ValueError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        sys.exit(1)
    console.print(f"[green]OK[/green] removed {removed} unreachable object(s)")


@registry.command("usage")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option("--format", "output_format", type=click.Choice(["json", "manifest", "text"]), default="text")
def usage(source: Path, output_format: str) -> None:
    """Export application usage and exact contract references from SOURCE."""
    workspace = load_workspace_or_exit(source)
    payload = build_usage_manifest(workspace) if output_format == "manifest" else build_usage_graph(workspace)
    if output_format == "manifest":
        click.echo(serialize_usage_manifest(payload), nl=False)
        return
    if output_format == "json":
        click.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    console.print(
        f"[green]OK[/green] {len(payload['nodes'])} usage node(s), "
        f"{len(payload['edges'])} usage edge(s) for {payload['application']}"
    )
