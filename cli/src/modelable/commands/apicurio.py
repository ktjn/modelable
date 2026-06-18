from __future__ import annotations

import os
import sys
from pathlib import Path

import click

from modelable.commands.common import console, load_workspace_or_exit
from modelable.emitters.json_schema import emit_json_schema
from modelable.registry.apicurio import ApicurioArtifact, ApicurioRegistryClient, ApicurioRegistryError


def register_apicurio_commands(cli_group: click.Group) -> None:
    cli_group.add_command(publish)
    cli_group.add_command(pull)


@click.group()
def publish() -> None:
    """Publish generated artifacts to external registries."""


@publish.command(name="apicurio")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option("--url", required=True, help="Apicurio Registry base URL or /apis/registry/v3 URL.")
@click.option("--group", default="default", show_default=True, help="Apicurio artifact group.")
@click.option("--token", default=None, help="Bearer token. Defaults to MODELABLE_APICURIO_TOKEN.")
@click.option("--dry-run", is_flag=True, help="List artifacts without publishing.")
def publish_apicurio(source: Path, url: str, group: str, token: str | None, dry_run: bool) -> None:
    """Publish JSON Schema artifacts generated from SOURCE to Apicurio Registry."""
    workspace = load_workspace_or_exit(source)
    emitted = emit_json_schema(workspace, Path(".modelable/apicurio"))
    artifacts = [
        ApicurioArtifact(
            artifact_id=artifact.artifact_id,
            version=artifact.artifact_id.rsplit(".v", 1)[1],
            content=artifact.content,
        )
        for artifact in emitted
        if isinstance(artifact.content, dict)
    ]

    if dry_run:
        console.print(f"[yellow]DRY RUN[/yellow] would publish {len(artifacts)} JSON Schema artifact(s) to {url}")
        for artifact in artifacts:
            console.print(f"- {artifact.artifact_id} (group={group}, version={artifact.version})")
        sys.exit(0)

    client = ApicurioRegistryClient(url, token=token or os.getenv("MODELABLE_APICURIO_TOKEN"))
    try:
        for artifact in artifacts:
            client.publish_json_schema(artifact, group=group)
            console.print(f"[green]OK[/green] published {group}/{artifact.artifact_id}@{artifact.version}")
    except ApicurioRegistryError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        sys.exit(1)

    if not artifacts:
        console.print("[yellow]No JSON Schema artifacts generated.[/yellow]")
    sys.exit(0)


@click.group()
def pull() -> None:
    """Pull generated artifacts from external registries."""


@pull.command(name="apicurio")
@click.argument("ref")
@click.option("--url", required=True, help="Apicurio Registry base URL or /apis/registry/v3 URL.")
@click.option("--group", default="default", show_default=True, help="Apicurio artifact group.")
@click.option("--out", "out_dir", type=click.Path(path_type=Path), default=Path("./dist/jsonschema"))
@click.option("--token", default=None, help="Bearer token. Defaults to MODELABLE_APICURIO_TOKEN.")
def pull_apicurio(ref: str, url: str, group: str, out_dir: Path, token: str | None) -> None:
    """Pull a JSON Schema artifact by Modelable REF from Apicurio Registry."""
    client = ApicurioRegistryClient(url, token=token or os.getenv("MODELABLE_APICURIO_TOKEN"))
    try:
        path = client.pull_json_schema(ref, group=group, out_dir=out_dir)
    except ApicurioRegistryError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        sys.exit(1)
    console.print(f"[green]OK[/green] wrote {path}")
    sys.exit(0)
