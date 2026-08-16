from __future__ import annotations

import hashlib
import json
import sqlite3
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
    workspace_root = path if path.is_dir() else path.parent
    modelable_dir = workspace_root / ".modelable"
    snapshot = snapshot_status(modelable_dir)
    registry_index = _registry_index_status(modelable_dir / "registry.db")
    artifact_manifests = _artifact_manifest_status(workspace_root)
    capabilities = build_capability_manifest()
    healthy = (
        not workspace.errors
        and snapshot["valid"]
        and Path(snapshot["lock"]).exists()
        and registry_index["valid"]
        and not artifact_manifests["errors"]
    )
    payload = {
        "kind": "doctor_report",
        "workspace": {
            "sources": len(workspace.sources),
            "errors": len(workspace.errors),
            "warnings": len(workspace.warnings),
        },
        "config": {"path": str(config.path) if config.path is not None else None, "values": config.explain()},
        "snapshot": snapshot,
        "registry_index": registry_index,
        "artifact_manifests": artifact_manifests,
        "capabilities": {
            "count": len(capabilities.all()),
            "targets": [entry.name for entry in capabilities.targets],
        },
        "healthy": healthy,
    }
    workspace_sources = len(workspace.sources)
    snapshot_objects = snapshot["objects"]
    registry_errors = registry_index["errors"] if isinstance(registry_index["errors"], list) else []
    artifact_errors = artifact_manifests["errors"] if isinstance(artifact_manifests["errors"], list) else []
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
    for error in registry_errors + artifact_errors:
        console.print(f"[red]ERROR[/red] {error}")
    if not healthy:
        raise click.exceptions.Exit(1)


def _registry_index_status(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"path": str(path), "present": False, "valid": True, "errors": []}
    try:
        with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as error:
        return {"path": str(path), "present": True, "valid": False, "errors": [f"registry index: {error}"]}
    valid = result == ("ok",)
    return {
        "path": str(path),
        "present": True,
        "valid": valid,
        "errors": [] if valid else [f"registry index integrity check returned {result!r}"],
    }


def _artifact_manifest_status(workspace_root: Path) -> dict[str, object]:
    manifests: list[dict[str, object]] = []
    errors: list[str] = []
    for manifest_path in sorted(workspace_root.rglob("modelable-artifact-manifest.json")):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            errors.append(f"artifact manifest {manifest_path}: {error}")
            continue
        stale = False
        for artifact in payload.get("artifacts", []):
            artifact_path = manifest_path.parent / str(artifact.get("path", ""))
            expected = artifact.get("sha256")
            if not artifact_path.is_file() or not isinstance(expected, str):
                errors.append(f"artifact manifest {manifest_path}: missing artifact {artifact_path}")
                stale = True
            elif _sha256(artifact_path) != expected:
                errors.append(f"artifact manifest {manifest_path}: hash mismatch for {artifact_path}")
                stale = True
        manifests.append({"path": str(manifest_path), "stale": stale, "artifacts": len(payload.get("artifacts", []))})
    return {"count": len(manifests), "manifests": manifests, "errors": errors}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
