"""Interactive commands for creating domain, model, and projection definitions."""

from __future__ import annotations

from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.prompt import Confirm, Prompt

console = Console()

FIELD_TYPES = [
    "string", "boolean", "integer", "decimal", "float",
    "timestamp", "date", "time", "duration", "uuid", "binary",
    "enum", "array", "object", "map", "reference",
]

MODEL_KINDS = ["entity", "event", "aggregate", "value_object"]

CLASSIFICATIONS = ["public", "internal", "confidential", "pii", "sensitive", "restricted"]


def _write_yaml(data: dict, output_path: Path) -> None:
    with open(output_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    console.print(f"[green]✓[/green] Written to [bold]{output_path}[/bold]")


def _prompt_fields() -> dict:
    """Interactively collect field definitions."""
    fields: dict = {}
    console.print("\n[bold]Define fields[/bold] (press Enter with empty name to finish):")
    while True:
        name = Prompt.ask("  Field name", default="").strip()
        if not name:
            break
        ftype = Prompt.ask(
            f"  Type for '{name}'",
            choices=FIELD_TYPES,
            default="string",
        )
        field: dict = {"type": ftype}
        if ftype == "enum":
            raw_values = Prompt.ask("  Enum values (comma-separated)")
            field["values"] = [v.strip() for v in raw_values.split(",")]
        required = Confirm.ask(f"  Is '{name}' required?", default=True)
        if required:
            field["required"] = True
        if Confirm.ask(f"  Add classification to '{name}'?", default=False):
            cls = Prompt.ask("  Classification", choices=CLASSIFICATIONS)
            field["classification"] = cls
        nullable = Confirm.ask(f"  Is '{name}' nullable?", default=not required)
        if nullable:
            field["nullable"] = True
        fields[name] = field
    return fields


@click.group()
def create() -> None:
    """Create new domain, model, or projection definition files."""


@create.command("domain")
@click.option("--output-dir", "-o", default=".", show_default=True, help="Output directory.")
def create_domain(output_dir: str) -> None:
    """Interactively create a domain definition YAML file."""
    console.rule("[bold cyan]Create Domain[/bold cyan]")

    name = Prompt.ask("Domain name (e.g. customer, commerce, payments)").strip()
    owner = Prompt.ask("Owner team or service account").strip()
    contact = Prompt.ask("Contact email", default="").strip()
    description = Prompt.ask("Description (one sentence)").strip()

    doc: dict = {
        "domain": name,
        "owner": owner,
        "description": description,
    }
    if contact:
        doc["contact"] = contact

    if Confirm.ask("Add governance policies?", default=False):
        policies: dict = {}
        default_cls = Prompt.ask(
            "Default classification",
            choices=CLASSIFICATIONS,
            default="internal",
        )
        policies["defaultClassification"] = default_cls
        if Confirm.ask("Does this domain contain PII?", default=False):
            pii_handling = Prompt.ask(
                "PII handling policy",
                choices=["pseudonymise_before_export", "strict_masking", "not_applicable"],
                default="pseudonymise_before_export",
            )
            policies["piiHandling"] = pii_handling
        retention = Prompt.ask("Retention years (leave empty to skip)", default="").strip()
        if retention:
            policies["retentionYears"] = int(retention)
        if policies:
            doc["policies"] = policies

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write_yaml(doc, out / f"domain-{name}.yaml")


@create.command("model")
@click.option("--output-dir", "-o", default=".", show_default=True, help="Output directory.")
def create_model(output_dir: str) -> None:
    """Interactively create a model version definition YAML file."""
    console.rule("[bold cyan]Create Model[/bold cyan]")

    domain = Prompt.ask("Domain name").strip()
    name = Prompt.ask("Model name (PascalCase, e.g. Customer, Order)").strip()
    kind = Prompt.ask("Kind", choices=MODEL_KINDS, default="entity")
    version = int(Prompt.ask("Version", default="1"))
    status = Prompt.ask("Status", choices=["draft", "published"], default="draft")
    description = Prompt.ask("Description (one sentence)").strip()

    doc: dict = {
        "domain": domain,
        "model": name,
        "kind": kind,
        "version": version,
        "status": status,
    }
    if description:
        doc["description"] = description

    if kind in ("entity", "aggregate"):
        identity_key = Prompt.ask("Identity key field name", default=f"{name[0].lower()}{name[1:]}Id")
        doc["identity"] = {"key": identity_key}

    doc["fields"] = _prompt_fields()

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write_yaml(doc, out / f"model-{domain}-{name.lower()}-v{version}.yaml")


@create.command("projection")
@click.option("--output-dir", "-o", default=".", show_default=True, help="Output directory.")
def create_projection(output_dir: str) -> None:
    """Interactively create a projection definition YAML file."""
    console.rule("[bold cyan]Create Projection[/bold cyan]")

    domain = Prompt.ask("Owning domain name").strip()
    name = Prompt.ask("Projection name (PascalCase)").strip()
    version = int(Prompt.ask("Version", default="1"))
    status = Prompt.ask("Status", choices=["draft", "published"], default="draft")
    description = Prompt.ask("Description (one sentence)").strip()

    doc: dict = {
        "domain": domain,
        "projection": name,
        "version": version,
        "status": status,
    }
    if description:
        doc["description"] = description

    # Sources
    sources = []
    console.print("\n[bold]Define sources[/bold] (press Enter with empty domain to finish):")
    while True:
        src_domain = Prompt.ask("  Source domain", default="").strip()
        if not src_domain:
            break
        src_model = Prompt.ask("  Source model name").strip()
        src_version = int(Prompt.ask("  Source version", default="1"))
        alias = Prompt.ask("  Alias (short name for field references)", default=src_model[:3].lower())
        src: dict = {"domain": src_domain, "model": src_model, "version": src_version, "alias": alias}
        if sources:
            join_field_left = Prompt.ask("  Join on (left.field)", default="").strip()
            join_field_right = Prompt.ask("  Join on (right.field)", default="").strip()
            if join_field_left and join_field_right:
                src["joinOn"] = {"left": join_field_left, "right": join_field_right}
        sources.append(src)
    doc["sources"] = sources

    # Fields
    console.print("\n[bold]Define projection fields[/bold] (press Enter with empty name to finish):")
    fields: dict = {}
    while True:
        fname = Prompt.ask("  Output field name", default="").strip()
        if not fname:
            break
        field_kind = Prompt.ask("  Field type", choices=["from", "expression"], default="from")
        fdef: dict = {}
        if field_kind == "from":
            source_ref = Prompt.ask("  From (alias.fieldName, e.g. c.customerId)").strip()
            fdef["from"] = source_ref
        else:
            expr = Prompt.ask("  CEL expression").strip()
            fdef["expression"] = expr
            out_type = Prompt.ask("  Output type", choices=FIELD_TYPES, default="string")
            fdef["type"] = out_type
        if Confirm.ask(f"  Add classification to '{fname}'?", default=False):
            cls = Prompt.ask("  Classification", choices=CLASSIFICATIONS)
            fdef["classification"] = cls
        fields[fname] = fdef
    doc["fields"] = fields

    # Materialisation
    if Confirm.ask("\nAdd materialisation config?", default=True):
        strategy = Prompt.ask(
            "Strategy",
            choices=["append", "upsert", "snapshot", "overwrite_partition"],
            default="upsert",
        )
        mat: dict = {"strategy": strategy}
        if strategy in ("upsert",):
            key = Prompt.ask("  Identity key field name").strip()
            if key:
                mat["key"] = key
        if strategy in ("append", "overwrite_partition"):
            partition_by = Prompt.ask("  Partition by field", default="").strip()
            if partition_by:
                mat["partitionBy"] = partition_by
        binding_name = Prompt.ask("  Binding name (leave empty to skip)", default="").strip()
        if binding_name:
            mat["binding"] = binding_name
        doc["materialisation"] = mat

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write_yaml(doc, out / f"projection-{domain}-{name.lower()}-v{version}.yaml")
