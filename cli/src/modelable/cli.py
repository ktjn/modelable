from __future__ import annotations

import json
import sys
from pathlib import Path

import click
from rich.console import Console

from modelable.compiler.workspace import load_workspace
from modelable.commands.codegen import register_codegen_commands
from modelable.commands.llm import register_llm_commands
from modelable.commands.scenario import register_scenario_commands
from modelable.llm.context import parse_model_ref
from modelable.llm.render import render_model_version, render_projection_version
from modelable.parser.ir import ParseError
from modelable.planner.planner import expand_auto_projections
from modelable.planner.lineage import build_projection_lineage
from modelable.registry.index import build_registry
from modelable.registry.resolver import resolve_model_ref

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
            console.print(f"[red]ERROR[/red] {mdl_file}: {error}", soft_wrap=True)
        sys.exit(1)

    if len(workspace.sources) == 1:
        console.print(f"[green]OK[/green] {workspace.sources[0].path} is valid.")
    else:
        console.print(f"[green]OK[/green] {len(workspace.sources)} files valid.")

    sys.exit(0)


@cli.command()
@click.argument("ref")
@click.option("--path", "path", type=click.Path(exists=True, path_type=Path), default=".")
def resolve(ref: str, path: Path) -> None:
    """Resolve and print a normalized model or projection definition."""
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
            console.print(f"[red]ERROR[/red] {mdl_file}: {error}", soft_wrap=True)
        sys.exit(1)

    try:
        model_ref = parse_model_ref(ref)
        resolved = resolve_model_ref(workspace.mdl, model_ref.domain + "." + model_ref.name, model_ref.version)
    except (ValueError, LookupError) as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        sys.exit(1)

    domain = next((d for d in workspace.mdl.domains if d.name == resolved.domain_name), None)
    if domain is None:
        console.print(f"[red]ERROR[/red] domain '{resolved.domain_name}' not found.")
        sys.exit(1)

    model_versions = domain.models.get(resolved.model_name, [])
    model_version = next((version for version in model_versions if version.version == resolved.version.version), None)
    if model_version is not None:
        console.print(render_model_version(domain.name, resolved.model_name, model_version, domain.owner, domain.description), end="")
        sys.exit(0)

    projection_versions = domain.projections.get(resolved.model_name, [])
    projection_version = next(
        (version for version in projection_versions if version.version == resolved.version.version),
        None,
    )
    if projection_version is not None:
        console.print(
            render_projection_version(
                domain.name,
                resolved.model_name,
                projection_version,
                domain.owner,
                domain.description,
            ),
            end="",
        )
        sys.exit(0)

    console.print(f"[red]ERROR[/red] unresolved reference {ref}")
    sys.exit(1)


@cli.command()
@click.argument("ref")
@click.option("--path", "path", type=click.Path(exists=True, path_type=Path), default=".")
def lineage(ref: str, path: Path) -> None:
    """Show field-level lineage for a model or projection."""
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
            console.print(f"[red]ERROR[/red] {mdl_file}: {error}", soft_wrap=True)
        sys.exit(1)

    try:
        model_ref = parse_model_ref(ref)
        resolved = resolve_model_ref(
            workspace.mdl, model_ref.domain + "." + model_ref.name, model_ref.version
        )
    except (ValueError, LookupError) as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        sys.exit(1)

    domain = next((d for d in workspace.mdl.domains if d.name == resolved.domain_name), None)
    if domain is None:
        console.print(f"[red]ERROR[/red] domain '{resolved.domain_name}' not found.")
        sys.exit(1)

    model_versions = domain.models.get(resolved.model_name, [])
    model_version = next(
        (version for version in model_versions if version.version == resolved.version.version),
        None,
    )
    if model_version is not None:
        console.print(f"{domain.name}.{resolved.model_name}@{model_version.version}")
        console.print(f"kind: {model_version.model_kind.value}")
        for field in model_version.fields:
            flags = []
            if field.is_key:
                flags.append("key")
            if field.is_pii:
                flags.append("pii")
            if field.classification:
                flags.append(f"classification={field.classification.value}")
            suffix = f" [{', '.join(flags)}]" if flags else ""
            console.print(f"- {field.name}: {field.type.kind}{suffix}")
        sys.exit(0)

    projection_versions = domain.projections.get(resolved.model_name, [])
    projection_version = next(
        (version for version in projection_versions if version.version == resolved.version.version),
        None,
    )
    if projection_version is not None:
        lineage = build_projection_lineage(
            domain.name, resolved.model_name, projection_version, workspace.mdl
        )
        console.print(f"{domain.name}.{resolved.model_name}@{projection_version.version}")
        console.print(f"source: {projection_version.source.model} @ {_render_version_spec(projection_version.source.version)} as {projection_version.source.alias}")
        if projection_version.joins:
            for join in projection_version.joins:
                console.print(
                    f"join: {join.model} @ {_render_version_spec(join.version)} as {join.alias} on {join.on}"
                )
        if projection_version.group_by:
            console.print(f"group by: {', '.join(projection_version.group_by)}")
        by_name = {item.field_name: item for item in lineage.fields}
        for field in projection_version.fields:
            field_lineage = by_name.get(field.name)
            if field_lineage is None:
                console.print(f"- {field.name}: unknown")
                continue
            console.print(f"- {field.name}: {field_lineage.kind}")
            for source in field_lineage.lineage:
                console.print(f"  <- {source}")
            if field_lineage.expression:
                console.print(f"  expr: {field_lineage.expression}")
        sys.exit(0)

    console.print(f"[red]ERROR[/red] unresolved reference {ref}")
    sys.exit(1)


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
            console.print(f"[red]ERROR[/red] {mdl_file}: {error}", soft_wrap=True)
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


@cli.command()
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
            console.print(f"[red]ERROR[/red] {mdl_file}: {error}", soft_wrap=True)
        sys.exit(1)

    from modelable.emitters.markdown import emit_markdown

    output = out_dir or Path("./dist/docs")
    output.mkdir(parents=True, exist_ok=True)
    artifacts = emit_markdown(workspace, output)
    for art in artifacts:
        assert isinstance(art.content, str)
        art.path.write_text(art.content, encoding="utf-8")
        for warning in art.warnings:
            console.print(f"[yellow]WARN[/yellow] {warning}")
        console.print(f"[green]OK[/green] {art.path}")
    if not artifacts:
        console.print("[yellow]No artifacts generated.[/yellow]")
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


def _render_version_spec(version_spec) -> str:
    kind = getattr(version_spec, "kind", None)
    if kind == "exact":
        return str(version_spec.version)
    if kind == "range":
        return f">={version_spec.min_inclusive}<{version_spec.max_exclusive}"
    if kind == "min":
        return f">={version_spec.min_inclusive}"
    return "?"


_DEFAULT_OUT_DIRS: dict[str, Path] = {
    "json-schema": Path("./dist/jsonschema"),
    "markdown": Path("./dist/docs"),
    "typescript": Path("./dist/types"),
}


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

    from modelable.planner.plans import write_plans

    plans_dir = Path(".modelable/plans")
    plan_paths = write_plans(workspace, plans_dir)
    for plan_path in plan_paths:
        console.print(f"[green]OK[/green] wrote {plan_path}")

    output = out_dir or _DEFAULT_OUT_DIRS[target]
    output.mkdir(parents=True, exist_ok=True)

    if target == "json-schema":
        from modelable.emitters.json_schema import emit_json_schema

        artifacts = emit_json_schema(workspace, output)
        for art in artifacts:
            art.path.write_text(
                json.dumps(art.content, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            for warning in art.warnings:
                console.print(f"[yellow]WARN[/yellow] {warning}")
            console.print(f"[green]OK[/green] {art.path}")
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target == "markdown":
        from modelable.emitters.markdown import emit_markdown

        artifacts = emit_markdown(workspace, output)
        for art in artifacts:
            assert isinstance(art.content, str)
            art.path.write_text(art.content, encoding="utf-8")
            for warning in art.warnings:
                console.print(f"[yellow]WARN[/yellow] {warning}")
            console.print(f"[green]OK[/green] {art.path}")
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    elif target == "typescript":
        from modelable.emitters.typescript import emit_typescript

        artifacts = emit_typescript(workspace, output)
        for art in artifacts:
            assert isinstance(art.content, str)
            art.path.write_text(art.content, encoding="utf-8")
            for warning in art.warnings:
                console.print(f"[yellow]WARN[/yellow] {warning}")
            console.print(f"[green]OK[/green] {art.path}")
        if not artifacts:
            console.print("[yellow]No artifacts generated.[/yellow]")
    else:
        from modelable.emitters.diagnostics import deferred_target

        console.print(f"[yellow]{deferred_target(target)}[/yellow]")

    sys.exit(0)


register_llm_commands(cli)
register_codegen_commands(cli)
register_scenario_commands(cli)
