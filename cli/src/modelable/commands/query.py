from __future__ import annotations

import json
from pathlib import Path

import click
from rich.console import Console

from modelable.commands.common import console, load_workspace_or_exit
from modelable.lifecycle import LifecycleError, load_lifecycle
from modelable.migration import MigrationError, load_migration
from modelable.query_protocol import QueryProtocolError, serialize_query_response
from modelable.query_service import WorkspaceQueryProtocolService
from modelable.registry.usage_protocol import UsageProtocolError, load_usage_manifest


def register_query_commands(cli_group: click.Group) -> None:
    cli_group.add_command(query)


@click.command()
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--request",
    "request_path",
    type=click.Path(dir_okay=False, path_type=Path),
    required=True,
    help="JSON file containing one modelable.query/v1 request envelope, or '-' for stdin.",
)
@click.option(
    "--usage-manifest",
    "usage_manifest_paths",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Compiled-consumer usage manifest for consumersOf queries (repeatable).",
)
@click.option(
    "--lifecycle",
    "lifecycle_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="External modelable.lifecycle/v1 metadata for lifecycle queries.",
)
@click.option(
    "--migration",
    "migration_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="External modelable.migration/v1 metadata for lineage queries.",
)
def query(
    source: Path,
    request_path: Path,
    usage_manifest_paths: tuple[Path, ...],
    lifecycle_path: Path | None,
    migration_path: Path | None,
) -> None:
    """Answer one read-only query/v1 request against SOURCE offline."""
    try:
        request_text = (
            click.get_text_stream("stdin").read()
            if request_path == Path("-")
            else request_path.read_text(encoding="utf-8")
        )
        request = json.loads(request_text)
        usage_manifests = [load_usage_manifest(path) for path in usage_manifest_paths]
        lifecycle = load_lifecycle(lifecycle_path) if lifecycle_path is not None else None
        migration = load_migration(migration_path) if migration_path is not None else None
        response = WorkspaceQueryProtocolService(
            load_workspace_or_exit(source, output_console=Console(stderr=True)),
            usage_manifests=usage_manifests,
            lifecycle=lifecycle,
            migration=migration,
        ).execute(request)
        click.echo(serialize_query_response(response), nl=False)
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        QueryProtocolError,
        UsageProtocolError,
        LifecycleError,
        MigrationError,
        ValueError,
    ) as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise click.exceptions.Exit(1) from exc
