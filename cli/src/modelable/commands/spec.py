from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from pathlib import Path

import click
from rich.console import Console

from modelable.specs.tracking import (
    SpecEntry,
    add_spec,
    change_dicts,
    evaluate_spec,
    select_specs,
    spec_config_path,
)

console = Console()


def register_spec_commands(cli_group: click.Group) -> None:
    cli_group.add_command(spec)


@click.group()
def spec() -> None:
    """Track external specifications and detect drift."""


@spec.command(name="add")
@click.argument("spec_id")
@click.option("--kind", required=True, help="Tracked spec kind, for example dbt, fhir, or odcs.")
@click.option("--source", required=True, help="Local external specification path.")
@click.option("--ref", "model_ref", required=True, help="Modelable model reference, for example domain.Model@1.")
@click.option("--source-name", default=None, help="Named source object inside multi-object specs.")
@click.option("--path", "workspace_path", type=click.Path(exists=True, path_type=Path), default=Path("."))
@click.option(
    "--update-policy", default="preview", help="Default update policy. Currently informational; defaults to preview."
)
def add(
    spec_id: str,
    kind: str,
    source: str,
    model_ref: str,
    source_name: str | None,
    workspace_path: Path,
    update_policy: str,
) -> None:
    """Add a tracked external specification."""
    try:
        path = add_spec(
            workspace_path,
            SpecEntry(
                id=spec_id,
                kind=kind.lower(),
                source=source,
                ref=model_ref,
                source_name=source_name,
                update_policy=update_policy,
            ),
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(f"[green]OK[/green] added tracked spec {spec_id} to {path}")


@spec.command(name="status")
@click.option("--path", "workspace_path", type=click.Path(exists=True, path_type=Path), default=Path("."))
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
@click.option("--fail-on", default="", help="Comma-separated statuses that should return a non-zero exit code.")
@click.option("--poll-interval", default=None, type=float, help="Re-check every N seconds (useful in CI watch mode).")
@click.option("--max-polls", default=None, type=int, help="Stop after this many checks when --poll-interval is set.")
def status(
    workspace_path: Path,
    json_output: bool,
    fail_on: str,
    poll_interval: float | None,
    max_polls: int | None,
) -> None:
    """Report drift status for tracked external specifications."""
    token = os.getenv("MODELABLE_SPEC_TOKEN")
    fail_statuses = {item.strip() for item in fail_on.split(",") if item.strip()}
    polls = 0

    while True:
        entries = select_specs(workspace_path, None)
        evaluations = [evaluate_spec(workspace_path, entry, write=False, token=token) for entry in entries]
        payload = {"specs": [evaluation.as_status_dict() for evaluation in evaluations]}
        if json_output:
            click.echo(json.dumps(payload, indent=2, sort_keys=True))
        else:
            if not evaluations:
                console.print(f"[yellow]No tracked specs in {spec_config_path(workspace_path)}[/yellow]")
            for evaluation in evaluations:
                suffix = ""
                if evaluation.change_kind:
                    suffix = f" ({evaluation.change_kind}, {evaluation.change_count} change(s))"
                if evaluation.error:
                    suffix = f" ({evaluation.error})"
                console.print(f"{evaluation.entry.id}: {evaluation.status}{suffix}")

        polls += 1
        if poll_interval is None:
            break
        if max_polls is not None and polls >= max_polls:
            break
        time.sleep(poll_interval)

    if fail_statuses and any(evaluation.status in fail_statuses for evaluation in evaluations):
        raise click.ClickException("tracked spec status matched --fail-on")


@spec.command(name="diff")
@click.argument("spec_id")
@click.option("--path", "workspace_path", type=click.Path(exists=True, path_type=Path), default=Path("."))
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON.")
def diff(spec_id: str, workspace_path: Path, json_output: bool) -> None:
    """Compare one tracked specification against its bound Modelable model."""
    token = os.getenv("MODELABLE_SPEC_TOKEN")
    try:
        entry = select_specs(workspace_path, spec_id)[0]
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    evaluation = evaluate_spec(workspace_path, entry, write=False, token=token)
    payload = evaluation.as_status_dict()
    if evaluation.result is not None:
        payload["changes"] = change_dicts(evaluation.result)
    if json_output:
        click.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    if evaluation.error:
        raise click.ClickException(evaluation.error)
    if evaluation.status == "clean":
        console.print(f"[green]OK[/green] {spec_id} is clean")
        return
    console.print(f"{spec_id}: {evaluation.change_kind} drift")
    for change in payload.get("changes", []):
        console.print(f"- {change['kind']}: {change['field_name']}")


@spec.command(name="sync")
@click.argument("spec_id", required=False)
@click.option("--path", "workspace_path", type=click.Path(exists=True, path_type=Path), default=Path("."))
@click.option("--preview", is_flag=True, help="Show proposed changes without writing.")
@click.option("--write", "write_changes", is_flag=True, help="Write proposed .mdl changes.")
def sync(spec_id: str | None, workspace_path: Path, preview: bool, write_changes: bool) -> None:
    """Synchronize tracked specs into reviewed Modelable version updates."""
    if preview and write_changes:
        raise click.UsageError("choose either --preview or --write")
    write = write_changes
    try:
        entries = select_specs(workspace_path, spec_id)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if not preview and not write:
        preview = True

    token = os.getenv("MODELABLE_SPEC_TOKEN")
    for entry in entries:
        evaluation = evaluate_spec(workspace_path, entry, write=write, token=token)
        if evaluation.error:
            raise click.ClickException(f"{entry.id}: {evaluation.error}")
        result = evaluation.result
        if result is None:
            continue
        if not result.attached:
            console.print(f"[green]OK[/green] {entry.id} already matches {entry.ref}; no new version created")
            continue
        if preview:
            console.print(_render_preview(result.original_content, result.content))
            continue
        _write_spec_attachment_record(entry.id, result.path, evaluation)
        console.print(result.content.rstrip())
        console.print(f"[green]OK[/green] synced {entry.id}; new version {result.to_version} ({result.change_kind})")


def _render_preview(original: str, updated: str) -> str:
    import difflib

    return "\n".join(
        difflib.unified_diff(
            original.splitlines(),
            updated.splitlines(),
            fromfile="current",
            tofile="tracked-spec",
            lineterm="",
        )
    )


def _write_spec_attachment_record(spec_id: str, artifact_path: Path, evaluation) -> Path:
    result = evaluation.result
    if result is None:
        raise ValueError("cannot write attachment record without an attach result")
    sidecar_path = artifact_path.with_name(f"{artifact_path.name}.attachments.json")
    records: list[dict[str, object]] = []
    if sidecar_path.exists():
        records = json.loads(sidecar_path.read_text(encoding="utf-8"))
    records.append(
        {
            "spec_id": spec_id,
            "ref": result.ref,
            "source_format": result.source_format,
            "source_name": result.source_name,
            "source_path": result.source_descriptor,
            "source_hash": result.source_hash,
            "from_version": result.from_version,
            "to_version": result.to_version,
            "change_kind": result.change_kind,
            "changes": [asdict(change) for change in result.changes],
        }
    )
    sidecar_path.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return sidecar_path
