"""Modellable CLI entry point."""

import click

from .commands.scenario import scenario
from .commands.create import create
from .commands.validate_cmd import validate
from .commands.llm_cmd import describe, generate
from .commands.codegen_cmd import codegen
from .commands.resolve_cmd import resolve
from .commands.lineage_cmd import lineage
from .commands.diff_cmd import diff
from .commands.compile_cmd import compile
from .commands.docs_cmd import docs
from .commands.publish_cmd import publish
from .commands.pull_cmd import pull
from .commands.export_cmd import export


@click.group()
@click.version_option(version="0.1.0", prog_name="modellable")
def cli() -> None:
    """Modellable — define, trace, and govern domain-owned data models.

    \b
    Phase 1 — Local modelling compiler:
      validate   Validate YAML definition files
      resolve    Look up a model or projection by reference
      lineage    Show field-level lineage for a model or projection
      diff       Compare two model versions field by field
      compile    Compile definitions to JSON Schema, TypeScript, or Markdown
      docs       Generate Markdown documentation for all definitions

    \b
    Phase 2 — Artifact registry (Apicurio):
      publish apicurio   Push JSON Schema artifacts to Apicurio Registry
      pull apicurio      Pull a schema artifact from Apicurio Registry

    \b
    Phase 3 — Catalog / governance (OpenMetadata):
      export openmetadata    Export metadata for OpenMetadata ingestion
      publish openmetadata   Push metadata to a live OpenMetadata instance

    \b
    Phase 4 — Contract interchange (ODCS):
      export odcs   Export an Open Data Contract Standard document

    \b
    Utilities:
      scenario   Browse and load bundled sample scenarios
      create     Create new domain, model, or projection definitions
      describe   Explain definitions in plain English using AI
      generate   Generate definitions from a natural language description
      codegen    Explore supported artifact formats and type mappings

    \b
    Quick start:
      modellable validate ./models
      modellable resolve customer.Customer.v1
      modellable lineage billing.BillingCustomer.v1
      modellable diff customer.Customer.v1 customer.Customer.v2
      modellable compile ./models --target json-schema --out ./dist/jsonschema
      modellable compile ./models --target typescript --out ./dist/types
      modellable docs ./models --out ./dist/docs
    """


cli.add_command(scenario)
cli.add_command(create)
cli.add_command(validate)
cli.add_command(describe)
cli.add_command(generate)
cli.add_command(codegen)
cli.add_command(resolve)
cli.add_command(lineage)
cli.add_command(diff)
cli.add_command(compile)
cli.add_command(docs)
cli.add_command(publish)
cli.add_command(pull)
cli.add_command(export)
