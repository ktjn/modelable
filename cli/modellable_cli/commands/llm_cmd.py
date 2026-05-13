"""LLM-powered commands: describe (explain YAML) and generate (YAML from description)."""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.markdown import Markdown
from rich.prompt import Prompt
from rich.syntax import Syntax

from ..loader import load_multidoc
from ..validator import validate_file

console = Console()

PLATFORM_CHOICES = [
    "data-warehouse",
    "high-performance-service",
    "event-driven-microservices",
    "ml-feature-store",
    "api-consumer",
    "audit-compliance",
]


@click.command("describe")
@click.argument("path", type=click.Path(exists=True))
def describe(path: str) -> None:
    """Use AI to explain Modellable YAML definitions in plain English."""
    from ..llm import describe_definitions

    file_path = Path(path)
    yaml_content = file_path.read_text()

    console.print(f"[dim]Reading {file_path}...[/dim]")
    console.print("[dim]Asking Claude to explain these definitions...[/dim]")
    console.print()

    try:
        explanation = describe_definitions(yaml_content)
    except RuntimeError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    console.rule("[bold cyan]Explanation[/bold cyan]")
    console.print(Markdown(explanation))


@click.command("generate")
@click.option(
    "--platform",
    "-p",
    type=click.Choice(PLATFORM_CHOICES),
    default=None,
    help="Target platform type to guide generation.",
)
@click.option(
    "--context",
    "-c",
    type=click.Path(exists=True),
    default=None,
    help="Existing YAML file to use as context (e.g. existing domain/model definitions).",
)
@click.option(
    "--output",
    "-o",
    default=None,
    type=click.Path(),
    help="Write generated YAML to this file instead of stdout.",
)
@click.option(
    "--suggest-platform",
    is_flag=True,
    default=False,
    help="Ask AI to recommend a platform type before generating.",
)
def generate(
    platform: str | None,
    context: str | None,
    output: str | None,
    suggest_platform: bool,
) -> None:
    """Generate Modellable YAML definitions from a natural language description."""
    from ..llm import generate_definitions, suggest_platform as suggest_platform_fn

    console.rule("[bold cyan]Generate Definitions with AI[/bold cyan]")
    console.print(
        "Describe your scenario in natural language. Include the business context, "
        "what data needs to flow where, and any governance requirements.\n"
        "Press Enter twice (empty line) to finish.\n"
    )

    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line and lines and not lines[-1]:
            break
        lines.append(line)

    description = "\n".join(lines).strip()
    if not description:
        console.print("[yellow]No description provided. Exiting.[/yellow]")
        raise SystemExit(0)

    # Optionally suggest platform
    if suggest_platform and not platform:
        console.print("\n[dim]Asking AI to recommend a platform type...[/dim]")
        try:
            recommendation = suggest_platform_fn(description)
        except RuntimeError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise SystemExit(1)
        console.print()
        console.print(Markdown(f"**Platform recommendation:**\n\n{recommendation}"))
        console.print()
        platform = Prompt.ask(
            "Platform type to use for generation (or press Enter to skip)",
            choices=PLATFORM_CHOICES + [""],
            default="",
        ).strip() or None

    # Load context file if provided
    existing_context: str | None = None
    if context:
        existing_context = Path(context).read_text()

    console.print("\n[dim]Generating definitions with Claude...[/dim]")
    try:
        yaml_output = generate_definitions(description, platform=platform, existing_context=existing_context)
    except RuntimeError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    if output:
        Path(output).write_text(yaml_output + "\n")
        console.print(f"\n[green]✓[/green] Definitions written to [bold]{output}[/bold]")

        # Auto-validate
        console.print("[dim]Validating generated definitions...[/dim]")
        import yaml as _yaml
        try:
            docs = list(_yaml.safe_load_all(yaml_output))
            docs = [d for d in docs if d is not None]
            result = validate_file(output, docs)
            if result.ok:
                console.print("[green]✓[/green] Validation passed")
            else:
                console.print(f"[yellow]⚠[/yellow] {len(result.errors)} validation error(s) — review and fix:")
                for e in result.errors:
                    console.print(f"    [red]{e}[/red]")
        except Exception:
            pass  # Don't fail if auto-validation has issues
    else:
        console.print()
        console.rule("[bold]Generated YAML[/bold]")
        syntax = Syntax(yaml_output, "yaml", theme="monokai", word_wrap=True)
        console.print(syntax)
        console.print(
            "\n[dim]Tip: use --output <file.yaml> to save, "
            "or pipe stdout: modellable generate > my-defs.yaml[/dim]"
        )
