from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from modelable.commands.common import console, load_workspace_or_exit
from modelable.emitters.csharp import emit_csharp
from modelable.emitters.dbt_yaml import emit_dbt_yaml
from modelable.emitters.diagnostics import deferred_target
from modelable.emitters.fhir import emit_fhir_profile
from modelable.emitters.go import emit_go
from modelable.emitters.java import emit_java
from modelable.emitters.json_schema import emit_json_schema
from modelable.emitters.markdown import emit_markdown
from modelable.emitters.odcs import emit_odcs
from modelable.emitters.openlineage import emit_openlineage
from modelable.emitters.openmetadata import emit_openmetadata
from modelable.emitters.protobuf import emit_protobuf
from modelable.emitters.python import emit_python
from modelable.emitters.rust import emit_rust
from modelable.emitters.sql import emit_sql
from modelable.emitters.targets import list_implemented_codegen_targets
from modelable.emitters.typescript import emit_typescript
from modelable.planner.plans import write_plans
from modelable.registry.factory import get_registry
from modelable.registry.index import build_registry
from modelable.registry.oci import OCIRegistryError

_DEFAULT_OUT_DIRS: dict[str, Path] = {
    target.name: target.default_out_dir
    for target in list_implemented_codegen_targets()
    if target.default_out_dir is not None
}


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
def compile(source: Path, target: str, out_dir: Path | None, registry_path: str) -> None:
    """Compile Modelable definitions and write the local registry index."""
    workspace = load_workspace_or_exit(source)

    registry = get_registry(registry_path)
    if registry_path.startswith("oci://"):
        built_registry_path = build_registry(workspace, Path(".modelable"))
    else:
        local_registry_path = Path(registry_path)
        built_registry_path = build_registry(workspace, local_registry_path.parent)
    try:
        registry.push(built_registry_path)
    except OCIRegistryError as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(f"[green]OK[/green] wrote {registry_path}")

    plans_dir = Path(".modelable/plans")
    plan_paths = write_plans(workspace, plans_dir)
    for plan_path in plan_paths:
        console.print(f"[green]OK[/green] wrote {plan_path}")

    output = out_dir or _DEFAULT_OUT_DIRS[target]
    output.mkdir(parents=True, exist_ok=True)

    if target == "json-schema":
        artifacts = emit_json_schema(workspace, output)
        for art in artifacts:
            _write_artifact_text(art.path, json.dumps(art.content, indent=2, ensure_ascii=False) + "\n")
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target == "markdown":
        artifacts = emit_markdown(workspace, output)
        for art in artifacts:
            assert isinstance(art.content, str)
            _write_artifact_text(art.path, art.content)
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target == "typescript":
        artifacts = emit_typescript(workspace, output)
        for art in artifacts:
            assert isinstance(art.content, str)
            _write_artifact_text(art.path, art.content)
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target == "csharp":
        artifacts = emit_csharp(workspace, output)
        for art in artifacts:
            assert isinstance(art.content, str)
            _write_artifact_text(art.path, art.content)
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target == "java":
        artifacts = emit_java(workspace, output)
        for art in artifacts:
            assert isinstance(art.content, str)
            _write_artifact_text(art.path, art.content)
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target == "python":
        artifacts = emit_python(workspace, output)
        for art in artifacts:
            assert isinstance(art.content, str)
            _write_artifact_text(art.path, art.content)
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target == "rust":
        artifacts = emit_rust(workspace, output)
        for art in artifacts:
            assert isinstance(art.content, str)
            _write_artifact_text(art.path, art.content)
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target == "go":
        artifacts = emit_go(workspace, output)
        for art in artifacts:
            assert isinstance(art.content, str)
            _write_artifact_text(art.path, art.content)
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target == "dbt-yaml":
        artifacts = emit_dbt_yaml(workspace, output)
        for art in artifacts:
            assert isinstance(art.content, str)
            _write_artifact_text(art.path, art.content)
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target == "fhir-profile":
        artifacts = emit_fhir_profile(workspace, output)
        for art in artifacts:
            assert isinstance(art.content, str)
            _write_artifact_text(art.path, art.content)
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target == "openmetadata":
        artifacts = emit_openmetadata(workspace, output)
        for art in artifacts:
            content = (
                json.dumps(art.content, indent=2, ensure_ascii=False) + "\n"
                if isinstance(art.content, dict)
                else art.content
            )
            assert isinstance(content, str)
            _write_artifact_text(art.path, content)
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target == "openlineage":
        artifacts = emit_openlineage(workspace, output)
        for art in artifacts:
            assert isinstance(art.content, dict)
            _write_artifact_text(art.path, json.dumps(art.content, indent=2, ensure_ascii=False) + "\n")
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target == "odcs":
        artifacts = emit_odcs(workspace, output)
        for art in artifacts:
            assert isinstance(art.content, str)
            _write_artifact_text(art.path, art.content)
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target == "protobuf":
        artifacts = emit_protobuf(workspace, output)
        for art in artifacts:
            assert isinstance(art.content, str)
            _write_artifact_text(art.path, art.content)
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target in ("sql-postgres", "sql-clickhouse"):
        dialect = target.removeprefix("sql-")
        artifacts = emit_sql(workspace, output, dialect)
        for art in artifacts:
            assert isinstance(art.content, str)
            _write_artifact_text(art.path, art.content)
            _print_artifact_result(art)
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    else:
        console.print(f"[yellow]{deferred_target(target)}[/yellow]")

    sys.exit(0)


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
    for art in artifacts:
        assert isinstance(art.content, str)
        art.path.write_text(art.content, encoding="utf-8")
        _print_artifact_result(art)
    if not artifacts:
        console.print("[yellow]No artifacts generated.[/yellow]")
    sys.exit(0)


def _print_artifact_result(art) -> None:
    for warning in art.warnings:
        console.print(f"[yellow]WARN[/yellow] {warning}")
    console.print(f"[green]OK[/green] {art.path} [dim]{art.content_hash}[/dim]")


def _write_artifact_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
