from __future__ import annotations

import difflib
from pathlib import Path

import click
from rich.console import Console

from modelable.llm.engine import (
    answer_model_question_cli,
    describe_path_or_ref,
    explain_validation,
    generate_entity_from_prompt,
    import_definition,
    recommend_cli,
    update_definition,
    suggest_projection,
    transform_ref_to_target,
    validate_generated_text,
)

console = Console()


def register_llm_commands(cli_group: click.Group) -> None:
    cli_group.add_command(describe)
    cli_group.add_command(generate)
    cli_group.add_command(import_model)
    cli_group.add_command(update)
    cli_group.add_command(transform)
    cli_group.add_command(suggest_projection_cmd)
    cli_group.add_command(ask)
    cli_group.add_command(recommend)
    cli_group.add_command(explain)


@click.command()
@click.argument("target", required=False)
@click.option("--path", "path", type=click.Path(exists=True, path_type=Path), default=None)
def describe(target: str | None, path: Path | None) -> None:
    """Describe a model, projection, or workspace."""
    if target is None and path is None:
        raise click.UsageError("provide a model ref or --path")
    console.print(describe_path_or_ref(path=path, ref=target))


@click.command()
@click.option("--from", "source", required=True, help="Natural language or source file path.")
@click.option("--format", "source_format", default=None, help="Source format for import paths.")
@click.option("--domain", "domain_name", default=None, help="Override the output domain.")
@click.option("--name", "model_name", default=None, help="Override the output model name.")
@click.option("--output", "output", type=click.Path(path_type=Path), default=None)
def generate(source: str, source_format: str | None, domain_name: str | None, model_name: str | None, output: Path | None) -> None:
    """Generate a draft entity definition."""
    source_path = Path(source)
    if source_path.exists():
        if source_format is not None:
            text = import_definition(source_path, source_format, domain_name=domain_name)
        else:
            text = source_path.read_text(encoding="utf-8")
    else:
        if source_format is not None:
            text = import_definition(source, source_format, domain_name=domain_name)
        else:
            text = generate_entity_from_prompt(source, domain_name=domain_name, model_name=model_name)

    mdl, errors = validate_generated_text(text)
    if errors:
        for error in errors:
            console.print(f"[red]ERROR[/red] {error}")
        raise click.ClickException("generated output failed validation")

    rendered = text if text.endswith("\n") else text + "\n"
    if output is not None:
        output.write_text(rendered, encoding="utf-8")
        console.print(f"[green]OK[/green] wrote {output}")
    else:
        console.print(rendered.rstrip())


@click.command(name="import")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option("--format", "source_format", required=True, help="json-schema, openapi, avro, protobuf, sql")
@click.option("--domain", "domain_name", default=None)
@click.option("--output", "output", type=click.Path(path_type=Path), default=None)
def import_model(source: Path, source_format: str, domain_name: str | None, output: Path | None) -> None:
    """Import a schema or DDL file into Modelable text."""
    text = import_definition(source, source_format, domain_name=domain_name)
    mdl, errors = validate_generated_text(text)
    if errors:
        for error in errors:
            console.print(f"[red]ERROR[/red] {error}")
        raise click.ClickException("imported definition failed validation")
    if output is not None:
        output.write_text(text, encoding="utf-8")
        console.print(f"[green]OK[/green] wrote {output}")
    else:
        console.print(text.rstrip())


@click.command()
@click.argument("ref")
@click.argument("instruction", nargs=-1)
@click.option("--path", "path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--output", "output", type=click.Path(path_type=Path), default=None)
@click.option("--preview", is_flag=True, help="Show the edit diff without writing changes.")
def update(ref: str, instruction: tuple[str, ...], path: Path, output: Path | None, preview: bool) -> None:
    """Apply a natural-language update to an existing model version."""
    try:
        result = update_definition(path, ref, " ".join(instruction), output=output, write=not preview)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if preview:
        diff = difflib.unified_diff(
            result.original_content.splitlines(),
            result.content.splitlines(),
            fromfile=str(result.path),
            tofile=f"{result.path} (preview)",
            lineterm="",
        )
        console.print("\n".join(diff))
    else:
        console.print(result.content.rstrip())
    for warning in result.warnings:
        console.print(f"[yellow]WARN[/yellow] {warning}")


@click.command()
@click.argument("ref")
@click.option("--path", "path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--to", "target", type=click.Choice(["json-schema", "markdown", "typescript"]), required=True)
@click.option("--out", "output", type=click.Path(path_type=Path), default=None)
def transform(ref: str, path: Path, target: str, output: Path | None) -> None:
    """Transform a model or projection into another artifact format."""
    result = transform_ref_to_target(path, ref, target)
    if output is not None:
        output.write_text(result.content, encoding="utf-8")
        console.print(f"[green]OK[/green] wrote {output}")
    else:
        console.print(result.content)
    for warning in result.warnings:
        console.print(f"[yellow]WARN[/yellow] {warning}")


@click.command(name="suggest-projection")
@click.option("--path", "path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--source", "source_ref", required=True)
@click.option("--consumer", "consumer_domain", required=True)
@click.option("--output", "output", type=click.Path(path_type=Path), default=None)
def suggest_projection_cmd(path: Path, source_ref: str, consumer_domain: str, output: Path | None) -> None:
    """Suggest a projection for a consuming domain."""
    text = suggest_projection(path, source_ref, consumer_domain)
    if output is not None:
        output.write_text(text, encoding="utf-8")
        console.print(f"[green]OK[/green] wrote {output}")
    else:
        console.print(text.rstrip())


@click.command()
@click.argument("question")
@click.option("--path", "path", type=click.Path(exists=True, path_type=Path), required=True)
def ask(question: str, path: Path) -> None:
    """Answer a question about the current model workspace."""
    console.print(answer_model_question_cli(path, question))


@click.command()
@click.option("--path", "path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--ref", "ref", default=None)
@click.option("--consumer", "consumer", default=None)
def recommend(path: Path, ref: str | None, consumer: str | None) -> None:
    """Provide a recommendation for a model or projection."""
    console.print(recommend_cli(path, ref=ref, consumer=consumer))


@click.command()
@click.option("--path", "path", type=click.Path(exists=True, path_type=Path), required=True)
def explain(path: Path) -> None:
    """Explain current validation errors."""
    console.print(explain_validation(path))
