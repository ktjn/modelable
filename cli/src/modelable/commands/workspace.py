from __future__ import annotations

import sys
from pathlib import Path

import click

from modelable.commands.common import console, load_workspace_or_exit, render_version_spec
from modelable.llm.context import parse_model_ref_version_spec
from modelable.llm.render import render_model_version, render_projection_version
from modelable.planner.lineage import build_projection_lineage
from modelable.registry.resolver import resolve_model_ref


def register_workspace_commands(cli_group: click.Group) -> None:
    cli_group.add_command(validate)
    cli_group.add_command(resolve)
    cli_group.add_command(lineage)
    cli_group.add_command(inspect)


@click.command()
@click.argument("path", default=".", type=click.Path(exists=True, path_type=Path))
@click.option("--strict", is_flag=True, help="Exit non-zero on any validation error.")
def validate(path: Path, strict: bool) -> None:
    """Validate Modelable definition files at PATH."""
    workspace = load_workspace_or_exit(path)

    if len(workspace.sources) == 1:
        console.print(f"[green]OK[/green] {workspace.sources[0].path} is valid.")
    else:
        console.print(f"[green]OK[/green] {len(workspace.sources)} files valid.")

    sys.exit(0)


@click.command()
@click.argument("ref")
@click.option("--path", "path", type=click.Path(exists=True, path_type=Path), default=".")
def resolve(ref: str, path: Path) -> None:
    """Resolve and print a normalized model or projection definition."""
    workspace = load_workspace_or_exit(path)

    try:
        domain, name, version_spec = parse_model_ref_version_spec(ref)
        resolved = resolve_model_ref(workspace.mdl, domain + "." + name, version_spec)
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
        console.print(
            render_model_version(domain.name, resolved.model_name, model_version, domain.owner, domain.description),
            end="",
        )
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


@click.command()
@click.argument("ref")
@click.option("--path", "path", type=click.Path(exists=True, path_type=Path), default=".")
def lineage(ref: str, path: Path) -> None:
    """Show field-level lineage for a model or projection."""
    workspace = load_workspace_or_exit(path)

    try:
        domain, name, version_spec = parse_model_ref_version_spec(ref)
        resolved = resolve_model_ref(workspace.mdl, domain + "." + name, version_spec)
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
            console.print(f"- {field.name}: {field.type.kind}{suffix}", markup=False)
        sys.exit(0)

    projection_versions = domain.projections.get(resolved.model_name, [])
    projection_version = next(
        (version for version in projection_versions if version.version == resolved.version.version),
        None,
    )
    if projection_version is not None:
        lineage = build_projection_lineage(domain.name, resolved.model_name, projection_version, workspace.mdl)
        console.print(f"{domain.name}.{resolved.model_name}@{projection_version.version}")
        console.print(
            f"source: {projection_version.source.model} @ {render_version_spec(projection_version.source.version)} as {projection_version.source.alias}"
        )
        if projection_version.joins:
            for join in projection_version.joins:
                console.print(f"join: {join.model} @ {render_version_spec(join.version)} as {join.alias} on {join.on}")
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


@click.command()
@click.argument("ref")
@click.option("--auto", is_flag=True, help="Display generated auto projections.")
@click.option("--path", "path", type=click.Path(exists=True, path_type=Path), default=".")
def inspect(ref: str, auto: bool, path: Path) -> None:
    """Inspect a model or projection at REF (domain.Model@version)."""
    workspace = load_workspace_or_exit(path)

    try:
        domain_name, model_name, version_spec = _parse_entity_ref_version_spec(ref)
    except click.BadParameter as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        sys.exit(1)

    domain = next((d for d in workspace.mdl.domains if d.name == domain_name), None)
    if domain is None:
        console.print(f"[red]ERROR[/red] domain '{domain_name}' not found.")
        sys.exit(1)

    try:
        resolved = resolve_model_ref(workspace.mdl, domain_name + "." + model_name, version_spec)
    except LookupError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        sys.exit(1)

    version = resolved.version.version

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
            console.print(f"[bold]{domain_name}.{projection_name}@{pv.version}[/bold] (auto {kind})")
            for field in pv.fields:
                console.print(f"  {field.name}")
        sys.exit(0)

    model_versions = domain.models.get(model_name, [])
    model_version = next((mv for mv in model_versions if mv.version == version), None)
    if model_version is not None:
        console.print(
            render_model_version(domain.name, model_name, model_version, domain.owner, domain.description), end=""
        )
        sys.exit(0)

    projection_versions = domain.projections.get(model_name, [])
    projection_version = next((pv for pv in projection_versions if pv.version == version), None)
    if projection_version is not None:
        console.print(
            render_projection_version(domain.name, model_name, projection_version, domain.owner, domain.description),
            end="",
        )
        sys.exit(0)

    console.print(f"[red]ERROR[/red] '{model_name}@{version}' not found in domain '{domain.name}'.")
    sys.exit(1)


def _parse_entity_ref_version_spec(ref: str) -> tuple[str, str, int | object]:
    if "@" not in ref:
        raise click.BadParameter("REF must be in the form domain.Model@version")
    model_ref, _version_str = ref.rsplit("@", 1)
    parts = model_ref.split(".")
    if len(parts) != 2:
        raise click.BadParameter("REF must be in the form domain.Model@version")
    try:
        _, _, version_spec = parse_model_ref_version_spec(ref)
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc
    return parts[0], parts[1], version_spec
