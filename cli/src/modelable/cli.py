from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console

from modelable.compiler.workspace import load_workspace
from modelable.parser.ir import ParseError
from modelable.planner.planner import expand_auto_projections
from modelable.registry.index import build_registry

console = Console()


@click.group()
def cli() -> None:
    """Modelable domain-owned data model compiler."""


@cli.command()
@click.argument("path", default=".", type=click.Path(exists=True, path_type=Path))
@click.option("--strict", is_flag=True, help="Exit non-zero on any validation error.")
def validate(path: Path, strict: bool) -> None:
    """Validate Modelable definition files at PATH."""
    try:
        workspace = load_workspace(path)
    except FileNotFoundError:
        console.print("[yellow]No .mdl files found.[/yellow]")
        sys.exit(0)
    except ParseError as exc:
        console.print(f"[red]ERROR[/red] {path}: Syntax error: {exc}")
        sys.exit(1)

    if workspace.errors:
        for mdl_file, error in workspace.errors:
            console.print(f"[red]ERROR[/red] {mdl_file}: {error}")
        sys.exit(1)

    if len(workspace.sources) == 1:
        console.print(f"[green]OK[/green] {workspace.sources[0].path} is valid.")
    else:
        console.print(f"[green]OK[/green] {len(workspace.sources)} files valid.")

    sys.exit(0)


@cli.command()
@click.argument("ref")
@click.option("--auto", is_flag=True, help="Display generated auto projections.")
@click.option("--path", "path", type=click.Path(exists=True, path_type=Path), default=".")
def inspect(ref: str, auto: bool, path: Path) -> None:
    """Inspect a model or projection at REF (domain.Model@version)."""
    try:
        workspace = load_workspace(path)
    except FileNotFoundError:
        console.print("[yellow]No .mdl files found.[/yellow]")
        sys.exit(0)
    except ParseError as exc:
        console.print(f"[red]ERROR[/red] {path}: Syntax error: {exc}")
        sys.exit(1)

    if workspace.errors:
        for mdl_file, error in workspace.errors:
            console.print(f"[red]ERROR[/red] {mdl_file}: {error}")
        sys.exit(1)

    domain_name, model_name, version = _parse_entity_ref(ref)

    domain = next((d for d in workspace.mdl.domains if d.name == domain_name), None)
    if domain is None:
        console.print(f"[red]ERROR[/red] domain '{domain_name}' not found.")
        sys.exit(1)

    if auto:
        model_versions = domain.models.get(model_name)
        if not model_versions:
            console.print(f"[red]ERROR[/red] model '{model_name}' not found in domain '{domain_name}'.")
            sys.exit(1)

        targets = ["db", "request", "reply", "event"]
        for kind in targets:
            projection_name = f"{model_name}{kind.capitalize()}"
            if kind == "db":
                projection_name = f"{model_name}Db"
            versions = domain.projections.get(projection_name)
            if not versions:
                continue
            pv = next((v for v in versions if v.version == version), None)
            if pv is None:
                continue
            console.print(f"[bold]{domain_name}.{projection_name}@{version}[/bold] (auto {kind})")
            for field in pv.fields:
                console.print(f"  {field.name}")
        sys.exit(0)

    console.print(f"[yellow]Inspect without --auto is not yet implemented.[/yellow]")
    sys.exit(0)


def _parse_entity_ref(ref: str) -> tuple[str, str, int]:
    if "@" not in ref:
        raise click.BadParameter("REF must be in the form domain.Model@version")
    model_ref, version_str = ref.rsplit("@", 1)
    try:
        version = int(version_str)
    except ValueError:
        raise click.BadParameter("version must be an integer")
    parts = model_ref.split(".")
    if len(parts) != 2:
        raise click.BadParameter("REF must be in the form domain.Model@version")
    return parts[0], parts[1], version


@cli.command()
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--target",
    required=True,
    type=click.Choice(["json-schema", "markdown", "typescript"]),
    help="Artifact target to compile after registry indexing.",
)
@click.option(
    "--out",
    "out_dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Directory for target artifacts.",
)
def compile(source: Path, target: str, out_dir: Path | None) -> None:
    """Compile Modelable definitions and write the local registry index."""
    try:
        workspace = load_workspace(source)
    except FileNotFoundError:
        console.print("[yellow]No .mdl files found.[/yellow]")
        sys.exit(0)
    except ParseError as exc:
        console.print(f"[red]ERROR[/red] {source}: Syntax error: {exc}")
        sys.exit(1)

    if workspace.errors:
        for mdl_file, error in workspace.errors:
            console.print(f"[red]ERROR[/red] {mdl_file}: {error}")
        sys.exit(1)

    registry_path = build_registry(workspace, Path(".modelable"))
    console.print(f"[green]OK[/green] wrote {registry_path}")
    console.print(
        f"[yellow]Artifact target '{target}' is deferred; "
        "registry indexing completed.[/yellow]"
    )
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)

    sys.exit(0)
