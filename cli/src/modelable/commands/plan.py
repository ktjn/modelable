from __future__ import annotations

from pathlib import Path

import click

from modelable.planner.protocol import PLAN_V1_SCHEMA, PlanProtocolError, load_plan, migrate_plan, serialize_plan


def register_plan_commands(cli_group: click.Group) -> None:
    cli_group.add_command(plan)


@click.group()
def plan() -> None:
    """Inspect and validate standalone modelable.plan documents."""


@plan.command("validate")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text", show_default=True)
def validate(path: Path, output_format: str) -> None:
    """Validate PATH and optionally print its canonical JSON representation."""
    try:
        document = load_plan(path)
    except PlanProtocolError as error:
        raise click.ClickException(str(error)) from error

    if output_format == "json":
        click.echo(serialize_plan(document), nl=False)
        return

    click.echo("valid: true")
    click.echo(f"schema: {document['$schema']}")
    click.echo(f"identity: {document['domain']}.{document['projection']}@{document['version']}")


@plan.command("migrate")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--to",
    "target_schema",
    type=click.Choice([PLAN_V1_SCHEMA]),
    required=True,
    help="Target plan protocol schema.",
)
def migrate(path: Path, target_schema: str) -> None:
    """Migrate PATH to a compatible plan protocol and print canonical JSON."""
    try:
        document = migrate_plan(load_plan(path), target_schema)
    except PlanProtocolError as error:
        raise click.ClickException(str(error)) from error
    click.echo(serialize_plan(document), nl=False)
