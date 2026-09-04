from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from modelable.commands.common import console, load_workspace_or_exit
from modelable.config import load_config
from modelable.registry.index import build_registry_from_snapshot
from modelable.registry.snapshot import (
    ConfiguredRegistryPolicy,
    RegistryPolicyError,
    diff_workspace_snapshot,
    include_policy_consequences,
    preview_workspace_snapshot,
    prune_snapshot,
    resolve_workspace_snapshot,
    snapshot_status,
    update_workspace_snapshot,
    verify_snapshot,
)
from modelable.registry.sources import GitSourceAdapter, GitSourceError, LocalSourceAdapter
from modelable.registry.usage import aggregate_usage_graph, build_usage_graph, build_usage_manifest
from modelable.registry.usage_protocol import UsageProtocolError, load_usage_manifest, serialize_usage_manifest


def register_registry_commands(cli_group: click.Group) -> None:
    cli_group.add_command(registry)


@click.group()
def registry() -> None:
    """Manage explicit, offline registry snapshots."""


@registry.command("resolve")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option("--out", "output_dir", type=click.Path(path_type=Path), default=Path(".modelable"), show_default=True)
@click.option(
    "--artifact-manifest",
    "artifact_manifest_paths",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Generated artifact manifest to include as usage evidence (repeatable).",
)
@click.option(
    "--usage-manifest",
    "usage_manifest_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Validated usage manifest produced by compilation to persist in the snapshot lock.",
)
@click.option(
    "--package-manifest",
    "package_manifest_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Explicit semantic package manifest to persist in the snapshot lock (repeatable).",
)
@click.option(
    "--lifecycle",
    "lifecycle_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="External modelable.lifecycle/v1 metadata to persist in the snapshot lock.",
)
def resolve(
    source: Path,
    output_dir: Path,
    artifact_manifest_paths: tuple[Path, ...],
    usage_manifest_path: Path | None,
    package_manifest_path: tuple[Path, ...],
    lifecycle_path: Path | None,
) -> None:
    """Resolve SOURCE into an exact local registry snapshot."""
    workspace = load_workspace_or_exit(source, source_adapter=LocalSourceAdapter())
    try:
        result = resolve_workspace_snapshot(
            workspace,
            output_dir,
            artifact_manifests=_read_artifact_manifests(artifact_manifest_paths),
            usage_manifest=_read_usage_manifest(usage_manifest_path) if usage_manifest_path is not None else None,
            package_manifest_paths=package_manifest_path,
            lifecycle_path=lifecycle_path,
        )
    except ValueError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        sys.exit(1)
    console.print(f"[green]OK[/green] wrote {result.object_count} object(s) to {result.lock_path}")


@registry.command("resolve-git")
@click.argument("repository", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--ref", required=True)
@click.option("--out", "output_dir", type=click.Path(path_type=Path), default=Path(".modelable"), show_default=True)
@click.option(
    "--artifact-manifest",
    "artifact_manifest_paths",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Generated artifact manifest to include as usage evidence (repeatable).",
)
def resolve_git(repository: Path, ref: str, output_dir: Path, artifact_manifest_paths: tuple[Path, ...]) -> None:
    """Resolve tracked .mdl files from a local Git REPOSITORY ref."""
    try:
        workspace = load_workspace_or_exit(repository, source_adapter=GitSourceAdapter(repository, ref))
        result = resolve_workspace_snapshot(
            workspace, output_dir, artifact_manifests=_read_artifact_manifests(artifact_manifest_paths)
        )
    except GitSourceError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        sys.exit(1)
    except ValueError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        sys.exit(1)
    console.print(f"[green]OK[/green] wrote {result.object_count} object(s) to {result.lock_path}")


@registry.command("diff")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option("--out", "output_dir", type=click.Path(path_type=Path), default=Path(".modelable"), show_default=True)
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
@click.option(
    "--artifact-manifest",
    "artifact_manifest_paths",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Generated artifact manifest to include as usage evidence (repeatable).",
)
@click.option(
    "--package-manifest",
    "package_manifest_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Explicit semantic package manifest to compare in the snapshot lock (repeatable).",
)
@click.option(
    "--lifecycle",
    "lifecycle_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="External modelable.lifecycle/v1 metadata to compare with the snapshot lock.",
)
@click.option(
    "--migration",
    "migration_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="External modelable.migration/v1 metadata to include in change consequences.",
)
def diff(
    source: Path,
    output_dir: Path,
    output_format: str,
    artifact_manifest_paths: tuple[Path, ...],
    package_manifest_path: tuple[Path, ...],
    lifecycle_path: Path | None,
    migration_path: Path | None,
) -> None:
    """Compare SOURCE with the current local snapshot without changing it."""
    workspace = load_workspace_or_exit(source, source_adapter=LocalSourceAdapter())
    try:
        snapshot_diff = diff_workspace_snapshot(
            workspace,
            output_dir,
            artifact_manifests=_read_artifact_manifests(artifact_manifest_paths),
            package_manifest_paths=package_manifest_path,
            lifecycle_path=lifecycle_path,
            migration_path=migration_path,
        )
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
    for category in ("added", "removed", "changed"):
        for identity in payload["packages"].get(category, []):
            console.print(f"package {category}: {identity}")
    for category in ("added", "removed", "changed"):
        for entry in payload["lifecycle"].get(category, []):
            console.print(f"lifecycle {category}: {entry['identity']}")


@registry.command("update")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option("--out", "output_dir", type=click.Path(path_type=Path), default=Path(".modelable"), show_default=True)
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
@click.option("--dry-run", is_flag=True, help="Resolve and validate the candidate without replacing the snapshot.")
@click.option(
    "--artifact-manifest",
    "artifact_manifest_paths",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Generated artifact manifest to include as usage evidence (repeatable).",
)
@click.option(
    "--package-manifest",
    "package_manifest_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Explicit semantic package manifest to persist in the snapshot lock (repeatable).",
)
@click.option(
    "--lifecycle",
    "lifecycle_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="External modelable.lifecycle/v1 metadata to persist in the snapshot lock.",
)
@click.option(
    "--migration",
    "migration_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="External modelable.migration/v1 metadata to include in change consequences.",
)
def update(
    source: Path,
    output_dir: Path,
    output_format: str,
    dry_run: bool,
    artifact_manifest_paths: tuple[Path, ...],
    package_manifest_path: tuple[Path, ...],
    lifecycle_path: Path | None,
    migration_path: Path | None,
) -> None:
    """Stage and atomically install SOURCE as the local exact snapshot."""
    workspace = load_workspace_or_exit(source, source_adapter=LocalSourceAdapter())
    try:
        policy_evaluation = None
        artifact_manifests = _read_artifact_manifests(artifact_manifest_paths)
        config = load_config(source)
        blocked_actions = config.blocked_registry_actions()
        policy_evaluator = ConfiguredRegistryPolicy(
            blocked_actions=blocked_actions,
            pii_change_severity=config.registry_policy_severities()["pii_changes"],
            lifecycle_reference_severity=config.registry_policy_severities()["lifecycle_references"],
        )
        if dry_run:
            snapshot_diff, object_count = preview_workspace_snapshot(
                workspace,
                output_dir,
                artifact_manifests=artifact_manifests,
                package_manifest_paths=package_manifest_path,
                lifecycle_path=lifecycle_path,
                migration_path=migration_path,
            )
            policy_evaluation = policy_evaluator.evaluate(snapshot_diff)
            snapshot_diff = include_policy_consequences(snapshot_diff, policy_evaluation.consequences)
        else:
            result, snapshot_diff = update_workspace_snapshot(
                workspace,
                output_dir,
                blocked_actions=blocked_actions,
                policy_evaluator=policy_evaluator,
                artifact_manifests=artifact_manifests,
                package_manifest_paths=package_manifest_path,
                lifecycle_path=lifecycle_path,
                migration_path=migration_path,
            )
            object_count = result.object_count
    except RegistryPolicyError as exc:
        if output_format == "json":
            evaluation = exc.evaluation
            payload = {
                "dry_run": False,
                "lock": str(output_dir / "registry.lock"),
                "objects": exc.object_count,
                "candidate": {"retained": str(exc.retained_candidate)},
                "policy": {
                    "blocked_actions": list(blocked_actions),
                    "violations": list(evaluation.blocked_actions),
                    "findings": [finding.as_dict() for finding in evaluation.findings],
                },
                **exc.snapshot_diff.as_dict(),
            }
            click.echo(json.dumps(payload, indent=2, sort_keys=True))
        else:
            console.print(f"[red]ERROR[/red] {exc}")
        sys.exit(1)
    except ValueError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        sys.exit(1)
    if policy_evaluation is None:
        policy_evaluation = policy_evaluator.evaluate(snapshot_diff)
    payload = {
        "dry_run": dry_run,
        "lock": str(output_dir / "registry.lock"),
        "objects": object_count,
        "policy": {
            "blocked_actions": list(blocked_actions),
            "violations": list(policy_evaluation.blocked_actions),
            "findings": [finding.as_dict() for finding in policy_evaluation.findings],
        },
        **snapshot_diff.as_dict(),
    }
    if output_format == "json":
        click.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    action = "validated candidate" if dry_run else "updated"
    package_changes = sum(len(snapshot_diff.packages.get(category, [])) for category in ("added", "removed", "changed"))
    package_suffix = f", {package_changes} package change(s)" if package_changes else ""
    console.print(
        f"[green]OK[/green] {action} {output_dir / 'registry.lock'} "
        f"({len(snapshot_diff.added)} added, {len(snapshot_diff.changed)} changed, "
        f"{len(snapshot_diff.removed)} removed from the lock{package_suffix})"
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
@click.option(
    "--usage-manifest",
    "usage_manifest_paths",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Validated compiled-consumer usage manifest to aggregate (repeatable).",
)
@click.option(
    "--artifact-manifest",
    "artifact_manifest_paths",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Generated artifact manifest to include as usage evidence (repeatable).",
)
def usage(
    source: Path,
    output_format: str,
    usage_manifest_paths: tuple[Path, ...],
    artifact_manifest_paths: tuple[Path, ...],
) -> None:
    """Export application usage and exact contract references from SOURCE."""
    workspace = load_workspace_or_exit(source)
    try:
        artifact_manifests = [_load_artifact_manifest(path) for path in artifact_manifest_paths]
        usage_manifests = [load_usage_manifest(path) for path in usage_manifest_paths]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, UsageProtocolError, ValueError) as exc:
        console.print(f"[red]ERROR[/red] Cannot load usage or artifact manifest: {exc}")
        sys.exit(1)
    if output_format == "manifest" and usage_manifests:
        console.print("[red]ERROR[/red] --usage-manifest requires --format json or text")
        sys.exit(1)
    payload = (
        build_usage_manifest(workspace, artifact_manifests=artifact_manifests)
        if output_format == "manifest"
        else (
            aggregate_usage_graph(workspace, usage_manifests, artifact_manifests=artifact_manifests)
            if usage_manifests
            else build_usage_graph(workspace, artifact_manifests=artifact_manifests)
        )
    )
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


def _load_artifact_manifest(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("artifact manifest must be a JSON object")
    return payload


def _read_artifact_manifests(paths: tuple[Path, ...]) -> tuple[dict[str, object], ...]:
    try:
        return tuple(_load_artifact_manifest(path) for path in paths)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"Cannot load artifact manifest: {exc}") from exc


def _read_usage_manifest(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"Cannot load compiled usage manifest: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("compiled usage manifest must be a JSON object")
    return payload
