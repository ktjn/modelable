from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console

from modelable.commands.common import console, load_workspace_or_exit
from modelable.diagnostics.model import render_diagnostic
from modelable.emitters.base import EmittedArtifact
from modelable.emitters.markdown import emit_markdown
from modelable.emitters.targets import list_implemented_codegen_targets
from modelable.operations.compilation import (
    CompilationDiagnosticsError,
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
    "--snapshot",
    "snapshot_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Validated local registry snapshot to use for offline external references.",
)
@click.option(
    "--registry-ids",
    "registry_ids_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to the registry id allocation ledger. Defaults beside the source workspace.",
)
@click.option(
    "--allow-orphaned-registry-ids",
    is_flag=True,
    help="Tolerate ledger entries with no matching 'registry: true' declaration instead of erroring.",
)
@click.option(
    "--enum-numbers",
    "enum_numbers_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to the Protobuf enum number allocation ledger. Defaults beside the source workspace.",
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
@click.option(
    "--package",
    "package",
    type=str,
    default=None,
    help="Restrict output to the named package (from workspace package {} blocks). Omit to emit every package.",
)
@click.option(
    "--overlay",
    "overlay_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Workspace overlay file for target-specific configuration.",
)
def compile(
    source: Path,
    target: str,
    out_dir: Path | None,
    registry_path: str,
    snapshot_path: Path | None,
    registry_ids_path: Path | None,
    allow_orphaned_registry_ids: bool,
    enum_numbers_path: Path | None,
    domains: tuple[str, ...],
    descriptor_set: bool,
    package: str | None,
    overlay_path: Path | None,
) -> None:
    """Compile Modelable definitions and write the local registry index."""
    try:
        source_root = source if source.is_dir() else source.parent
        if registry_ids_path is None:
            registry_ids_path = source_root / "registry-ids.lock"
        if enum_numbers_path is None:
            enum_numbers_path = source_root / "enum-numbers.lock"
        result = CompilationService().execute_direct(
            CompilationRequest(
                source=source,
                target=target,
                out_dir=out_dir,
                registry_path=registry_path,
                snapshot_path=snapshot_path,
                registry_ids_path=registry_ids_path,
                allow_orphaned_registry_ids=allow_orphaned_registry_ids,
                enum_numbers_path=enum_numbers_path,
                domains=domains,
                descriptor_set=descriptor_set,
                package=package,
                overlay_path=overlay_path,
            )
        )
    except CompilationDiagnosticsError as error:
        for diagnostic in error.diagnostics:
            message = f"[red]ERROR[/red] {render_diagnostic(diagnostic)}"
            if error.origin == "workspace":
                console.print(message, soft_wrap=True)
            else:
                console.print(message)
        sys.exit(1)
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
