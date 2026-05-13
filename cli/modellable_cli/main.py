"""Modellable CLI entry point."""

import click

from .commands.scenario import scenario
from .commands.create import create
from .commands.validate_cmd import validate
from .commands.llm_cmd import describe, generate
from .commands.codegen_cmd import codegen


@click.group()
@click.version_option(version="0.1.0", prog_name="modellable")
def cli() -> None:
    """Modellable — define, trace, and govern domain-owned data models.

    \b
    Commands:
      scenario   Browse and load bundled sample scenarios
      create     Create new domain, model, or projection definitions
      validate   Validate YAML definition files
      describe   Explain definitions in plain English using AI
      generate   Generate definitions from a natural language description
      codegen    Explore supported artifact formats and type mappings

    \b
    Quick start:
      modellable scenario list
      modellable scenario load ecommerce-data-warehouse --output-dir ./my-project
      modellable validate ./my-project/
      modellable describe ./my-project/01-ecommerce-data-warehouse.yaml
      modellable generate --platform data-warehouse
      modellable codegen list
      modellable codegen types typescript
    """


cli.add_command(scenario)
cli.add_command(create)
cli.add_command(validate)
cli.add_command(describe)
cli.add_command(generate)
cli.add_command(codegen)
