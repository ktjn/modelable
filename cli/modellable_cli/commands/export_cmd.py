"""export command — export model definitions to interchange formats."""

from __future__ import annotations

import json
from pathlib import Path

import click
import yaml
from rich.console import Console

from ..loader import detect_doc_type, load_definitions_from_path
from ..resolver import ModelRef, find_doc

console = Console()


@click.group("export")
def export() -> None:
    """Export model definitions to external interchange formats.

    \b
    Commands:
      openmetadata   Export catalog metadata JSON for OpenMetadata  [Phase 3]
      odcs           Export an Open Data Contract Standard document  [Phase 4]

    \b
    Examples:
      modellable export openmetadata ./models --out ./dist/openmetadata.json
      modellable export odcs customer.Customer.v1 --out ./dist/customer.contract.yaml
    """


@export.command("openmetadata")
@click.argument("path", default=".", type=click.Path(exists=True))
@click.option("--out", "-o", required=True, help="Output JSON file path.")
def export_openmetadata(path: str, out: str) -> None:
    """Export model metadata for OpenMetadata catalog ingestion.

    \b
    [Phase 3] Generates the export document. Use 'modellable publish openmetadata'
    to push to a live OpenMetadata instance.

    \b
    Modellable → OpenMetadata mapping:
      Domain     → Domain
      Model      → Custom asset
      Projection → Data product / custom asset
      Field classification → Tags / Glossary terms
      Lineage    → Lineage edges

    \b
    Example:
      modellable export openmetadata ./models --out ./dist/openmetadata.json
    """
    all_docs = [
        doc
        for _fpath, file_docs in load_definitions_from_path(path)
        for doc in file_docs
        if detect_doc_type(doc) in ("model", "projection", "domain")
    ]

    domains = [d for d in all_docs if detect_doc_type(d) == "domain"]
    assets_docs = [d for d in all_docs if detect_doc_type(d) in ("model", "projection")]

    export_doc: dict = {
        "domains": [
            {
                "name": d.get("domain"),
                "owner": d.get("owner"),
                "description": d.get("description", ""),
            }
            for d in domains
        ],
        "assets": [],
        "lineage": [],
    }

    for doc in assets_docs:
        dtype = detect_doc_type(doc)
        name_key = "model" if dtype == "model" else "projection"
        asset_fqn = f"{doc.get('domain')}.{doc.get(name_key)}.v{doc.get('version')}"

        classified_fields = [
            {"name": fname, "classification": fdef["classification"]}
            for fname, fdef in (doc.get("fields") or {}).items()
            if isinstance(fdef, dict) and fdef.get("classification")
        ]

        asset: dict = {
            "name": asset_fqn,
            "type": dtype,
            "domain": doc.get("domain"),
            "kind": doc.get("kind", dtype),
            "status": doc.get("status", "draft"),
        }
        if classified_fields:
            asset["fields"] = classified_fields
        export_doc["assets"].append(asset)

        if dtype == "projection":
            source_map = {
                src.get("alias", src.get("model")): src
                for src in (doc.get("sources") or [])
            }
            for fname, fdef in (doc.get("fields") or {}).items():
                if not isinstance(fdef, dict) or "from" not in fdef:
                    continue
                alias, _, src_field = str(fdef["from"]).partition(".")
                src_info = source_map.get(alias)
                if src_info:
                    src_fqf = (
                        f"{src_info.get('domain')}.{src_info.get('model')}."
                        f"v{src_info.get('version')}.{src_field}"
                    )
                    export_doc["lineage"].append(
                        {"from": src_fqf, "to": f"{asset_fqn}.{fname}"}
                    )

    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(export_doc, indent=2))

    n_assets = len(export_doc["assets"])
    n_edges = len(export_doc["lineage"])
    console.print(
        f"[green]✓[/green] OpenMetadata export written to [bold]{out_path}[/bold]\n"
        f"[dim]{n_assets} asset(s), {n_edges} lineage edge(s)[/dim]\n\n"
        f"[dim]Push with: modellable publish openmetadata {out_path}[/dim]"
    )


@export.command("odcs")
@click.argument("ref")
@click.option("--out", "-o", required=True, help="Output YAML file path.")
@click.option(
    "--path", "-p",
    default=".",
    show_default=True,
    type=click.Path(exists=True),
    help="Directory to search for YAML definitions.",
)
def export_odcs(ref: str, out: str, path: str) -> None:
    """Export a model as an Open Data Contract Standard (ODCS) document.

    \b
    [Phase 4] Generates a structural ODCS document.
    Lint the output with: datacontract lint <file>

    \b
    REF format: domain.ModelName.vVersion

    \b
    Example:
      modellable export odcs customer.Customer.v1 --out ./dist/customer.contract.yaml
      datacontract lint ./dist/customer.contract.yaml
    """
    try:
        model_ref = ModelRef.parse(ref)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    doc = find_doc(model_ref, path)
    if doc is None:
        console.print(f"[red]Not found:[/red] {ref}")
        raise SystemExit(1)

    is_projection = "projection" in doc
    name_key = "projection" if is_projection else "model"
    name = doc.get(name_key, "unknown")
    domain = doc.get("domain", "unknown")
    version = doc.get("version", 1)

    fields_schema: dict = {}
    for fname, fdef in (doc.get("fields") or {}).items():
        if not isinstance(fdef, dict):
            continue
        entry: dict = {"type": fdef.get("type", "string")}
        if fdef.get("required"):
            entry["required"] = True
        if fdef.get("classification"):
            entry["classification"] = fdef["classification"]
        if fdef.get("description"):
            entry["description"] = fdef["description"]
        fields_schema[fname] = entry

    odcs_doc = {
        "dataContractSpecification": "1.0.0",
        "id": f"modellable://{domain}/{name}/v{version}",
        "info": {
            "title": f"{domain}.{name}.v{version}",
            "version": str(version),
            "owner": domain,
            "description": doc.get("description", ""),
        },
        "schema": {
            name: {
                "type": "object",
                "properties": fields_schema,
            }
        },
    }

    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        yaml.dump(odcs_doc, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    console.print(
        f"[green]✓[/green] ODCS export written to [bold]{out_path}[/bold]\n"
        f"[dim]Lint with: datacontract lint {out_path}[/dim]"
    )
