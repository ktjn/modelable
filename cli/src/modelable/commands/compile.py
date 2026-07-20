from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console

from modelable.commands.common import console, load_workspace_or_exit
from modelable.emitters.base import EmittedArtifact
from modelable.emitters.markdown import emit_markdown
from modelable.emitters.targets import list_implemented_codegen_targets
from modelable.operations.compilation import (
    CompilationError,
    CompilationEvent,
    CompilationRequest,
    CompilationService,
)


def register_compile_commands(cli_group: click.Group) -> None:
    cli_group.add_command(compile)
    cli_group.add_command(docs)


@click.command()
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--target",
    required=True,
    type=click.Choice([target.name for target in list_implemented_codegen_targets()]),
    help="Artifact target to compile after registry indexing.",
)
@click.option(
    "--out",
    "out_dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Directory for target artifacts.",
)
@click.option(
    "--registry",
    "registry_path",
    type=str,
    default=".modelable/registry.db",
    help="Path to the registry index file.",
)
@click.option(
    "--registry-ids",
    "registry_ids_path",
    type=click.Path(path_type=Path),
    default=Path("registry-ids.lock"),
    help="Path to the registry id allocation ledger (must be committed to git).",
)
@click.option(
    "--allow-orphaned-registry-ids",
    is_flag=True,
    help="Tolerate ledger entries with no matching 'registry: true' declaration instead of erroring.",
)
@click.option(
    "--domain",
    "domains",
    multiple=True,
    default=(),
    help="Restrict compilation to the named domain(s) (repeatable). Omit to compile the whole workspace.",
)
@click.option(
    "--descriptor-set",
    "descriptor_set",
    is_flag=True,
    help="For protobuf and grpc targets, compile generated .proto files into descriptor .pb artifacts.",
)
def compile(
    source: Path,
    target: str,
    out_dir: Path | None,
    registry_path: str,
    registry_ids_path: Path,
    allow_orphaned_registry_ids: bool,
    domains: tuple[str, ...],
    descriptor_set: bool,
) -> None:
    """Compile Modelable definitions and write the local registry index."""
    try:
        result = CompilationService().execute_direct(
            CompilationRequest(
                source=source,
                target=target,
                out_dir=out_dir,
                registry_path=registry_path,
                registry_ids_path=registry_ids_path,
                allow_orphaned_registry_ids=allow_orphaned_registry_ids,
                domains=domains,
                descriptor_set=descriptor_set,
            )
        )
    except CompilationError as error:
        raise click.ClickException(str(error)) from error

    for event in result.events:
        render_compilation_event(event, console)
    sys.exit(0)


def render_compilation_event(event: CompilationEvent, output_console: Console) -> None:
    if event.level == "ok":
        if event.content_hash is not None:
            output_console.print(f"[green]OK[/green] {event.message} [dim]{event.content_hash}[/dim]")
        else:
            output_console.print(f"[green]OK[/green] {event.message}")
    elif event.level == "warning":
        if event.message == "No artifacts generated." or event.message == "No .mdl files found.":
            output_console.print(f"[yellow]{event.message}[/yellow]")
        else:
            output_console.print(f"[yellow]WARN[/yellow] {event.message}")
    else:
        output_console.print(event.message)


@click.command()
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--out",
    "out_dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Directory for generated documentation.",
)
def docs(source: Path, out_dir: Path | None) -> None:
    """Generate Markdown documentation from Modelable definitions at SOURCE."""
    workspace = load_workspace_or_exit(source)

    output = out_dir or Path("./dist/docs")
    output.mkdir(parents=True, exist_ok=True)
    artifacts = emit_markdown(workspace, output)
    for artifact in artifacts:
        assert isinstance(artifact.content, str)
        Path(artifact.path).write_text(artifact.content, encoding="utf-8")
        _print_artifact_result(artifact)
    if not artifacts:
        console.print("[yellow]No artifacts generated.[/yellow]")
    sys.exit(0)


def _print_artifact_result(artifact: EmittedArtifact) -> None:
    for warning in artifact.warnings:
        console.print(f"[yellow]WARN[/yellow] {warning}")
    console.print(f"[green]OK[/green] {artifact.path} [dim]{artifact.content_hash}[/dim]")
