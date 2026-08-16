from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from modelable.commands.common import console, load_workspace_or_exit
from modelable.compat.checker import check_model_version_compatibility
from modelable.conversion import build_conversion_plans
from modelable.llm.context import parse_model_ref_version_spec
from modelable.migration import build_migration_facts
from modelable.registry.resolver import resolve_model_ref


def register_transform_commands(cli_group: click.Group) -> None:
    cli_group.add_command(conversions)
    cli_group.add_command(migration)


@click.command("conversions")
@click.option("--path", "source", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def conversions(source: Path, output_format: str) -> None:
    """Report proof classifications for projection conversions."""
    workspace = load_workspace_or_exit(source)
    plans = build_conversion_plans(workspace)
    payload = {"kind": "conversion_plans", "plans": [plan.as_dict() for plan in plans]}
    if output_format == "json":
        click.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    for plan in plans:
        console.print(f"{plan.classification}: {plan.source} -> {plan.target} ({plan.reason})")


@click.group("migration")
def migration() -> None:
    """Produce non-executable migration facts."""


@migration.command("plan")
@click.option("--from", "from_ref", required=True)
@click.option("--to", "to_ref", required=True)
@click.option("--path", "source", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def migration_plan(from_ref: str, to_ref: str, source: Path, output_format: str) -> None:
    """Report storage and backfill facts for a model change."""
    workspace = load_workspace_or_exit(source)
    try:
        from_domain, from_name, from_spec = parse_model_ref_version_spec(from_ref)
        to_domain, to_name, to_spec = parse_model_ref_version_spec(to_ref)
        if (from_domain, from_name) != (to_domain, to_name):
            raise ValueError("migration plan requires refs from the same model")
        old = resolve_model_ref(workspace.mdl, f"{from_domain}.{from_name}", from_spec)
        new = resolve_model_ref(workspace.mdl, f"{to_domain}.{to_name}", to_spec)
        report = check_model_version_compatibility(
            workspace.mdl, from_domain, from_name, old.version.version, new.version.version
        )
        facts = build_migration_facts(workspace, report)
    except (LookupError, ValueError) as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        sys.exit(1)
    payload = {"kind": "migration_plan", "from": from_ref, "to": to_ref, "facts": [fact.as_dict() for fact in facts]}
    if output_format == "json":
        click.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    for fact in facts:
        console.print(f"{fact.action}: {fact.subject} ({fact.reason})")
