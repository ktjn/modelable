"""Emit OpenLineage events from standalone ``modelable.plan/v1`` documents."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.identity import parse_semantic_path
from modelable.planner.protocol import validate_plan

PRODUCER = "https://github.com/ktjn/modelable"
RUN_EVENT_SCHEMA_URL = "https://openlineage.io/spec/1-0-5/OpenLineage.json#/definitions/RunEvent"
SCHEMA_FACET_URL = "https://openlineage.io/spec/facets/1-1-1/SchemaDatasetFacet.json"
COLUMN_LINEAGE_FACET_URL = "https://openlineage.io/spec/facets/1-2-0/ColumnLineageDatasetFacet.json"


def emit_openlineage_plan(plan: object, out_dir: Path) -> EmittedArtifact:
    """Emit one OpenLineage event from a validated plan without parser imports."""
    document = validate_plan(plan)
    domain = cast(str, document["domain"])
    projection = cast(str, document["projection"])
    version = cast(int, document["version"])
    artifact_id = f"{domain}.{projection}.v{version}"

    relations = [cast(dict[str, object], document["source"])] + [
        cast(dict[str, object], join) for join in cast(list[object], document["joins"])
    ]
    datasets_by_ref: dict[str, dict[str, object]] = {}
    inputs: list[dict[str, object]] = []
    for relation in relations:
        resolved = relation.get("resolved")
        if not isinstance(resolved, dict):
            continue
        declaration = cast(dict[str, object], resolved)
        relation_ref = f"{declaration['domain']}.{declaration['name']}@{declaration['version']}"
        if relation_ref not in datasets_by_ref:
            dataset = _dataset_from_declaration(declaration)
            datasets_by_ref[relation_ref] = dataset
            inputs.append(dataset)
    fields = cast(list[object], document["fields"])
    output_dataset = _dataset(
        domain,
        artifact_id,
        fields=[_output_field(cast(dict[str, object], field)) for field in fields],
    )
    facets = cast(dict[str, object], output_dataset["facets"])
    facets["columnLineage"] = _column_lineage(fields, datasets_by_ref)
    event = {
        "eventType": "COMPLETE",
        "eventTime": "1970-01-01T00:00:00.000Z",
        "run": {"runId": f"modelable-{artifact_id.replace('.', '-')}", "facets": {}},
        "job": {"namespace": f"modelable://{domain}", "name": f"compile/{artifact_id}"},
        "inputs": inputs,
        "outputs": [output_dataset],
        "producer": PRODUCER,
        "schemaURL": RUN_EVENT_SCHEMA_URL,
    }
    return EmittedArtifact(
        target="openlineage",
        ref=f"{domain}.{projection}@{version}",
        artifact_id=artifact_id,
        path=out_dir / f"{artifact_id}.openlineage.json",
        content=event,
        content_hash=compute_content_hash(event),
    )


def _dataset_from_declaration(declaration: dict[str, object]) -> dict[str, object]:
    domain = cast(str, declaration["domain"])
    name = cast(str, declaration["name"])
    version = cast(int, declaration["version"])
    fields = cast(list[object], declaration["fields"])
    return _dataset(
        domain,
        f"{domain}.{name}.v{version}",
        fields=[_declaration_field(cast(dict[str, object], field)) for field in fields],
    )


def _dataset(domain: str, name: str, *, fields: list[dict[str, str]]) -> dict[str, object]:
    return {
        "namespace": f"modelable://{domain}",
        "name": name,
        "facets": {
            "schema": {
                "_producer": PRODUCER,
                "_schemaURL": SCHEMA_FACET_URL,
                "fields": fields,
            }
        },
    }


def _declaration_field(field: dict[str, object]) -> dict[str, str]:
    return _schema_field(field)


def _output_field(field: dict[str, object]) -> dict[str, str]:
    return _schema_field(field)


def _schema_field(field: dict[str, object]) -> dict[str, str]:
    data = {
        "name": cast(str, field["name"]),
        "type": _type_name(field["type"]) if field.get("type") is not None else "string",
    }
    description_parts: list[str] = []
    classification = field.get("classification")
    if isinstance(classification, str):
        description_parts.append(f"classification={classification}")
    if field.get("pii") is True:
        description_parts.append("pii=true")
    owner = field.get("owner")
    if isinstance(owner, str):
        description_parts.append(f"owner={owner}")
    if description_parts:
        data["description"] = "; ".join(description_parts)
    return data


def _type_name(field_type: object) -> str:
    if not isinstance(field_type, dict):
        return "unknown"
    kind = field_type.get("kind")
    if not isinstance(kind, str):
        return "unknown"
    if kind == "decimal":
        return f"decimal({field_type.get('precision')},{field_type.get('scale')})"
    if kind == "array":
        return f"array<{_type_name(field_type.get('item'))}>"
    if kind == "map":
        return f"map<{_type_name(field_type.get('key'))},{_type_name(field_type.get('value'))}>"
    if kind == "fixed_binary":
        return f"fixed_binary({field_type.get('length')})"
    if kind == "ref":
        return f"ref<{field_type.get('target')}>"
    if kind == "enum":
        values = field_type.get("values")
        return "enum(" + ",".join(cast(list[str], values)) + ")" if isinstance(values, list) else "enum"
    if kind == "enum_ref":
        return f"enumRef<{field_type.get('name')}@{field_type.get('version')}>"
    if kind == "named":
        return cast(str, field_type.get("name", "named"))
    if kind == "object":
        return "object"
    if kind == "union":
        variants = field_type.get("variants")
        if isinstance(variants, list):
            return (
                "union<"
                + "|".join(_type_name(cast(dict[str, object], variant).get("type")) for variant in variants)
                + ">"
            )
    return kind


def _column_lineage(fields: list[object], datasets_by_ref: dict[str, dict[str, object]]) -> dict[str, object]:
    lineage_fields: dict[str, object] = {}
    for value in fields:
        field = cast(dict[str, object], value)
        lineage = cast(list[object], field["lineage"])
        input_fields = [
            input_field
            for source in lineage
            if (input_field := _lineage_input(cast(str, source), datasets_by_ref)) is not None
        ]
        entry: dict[str, object] = {"inputFields": input_fields}
        if field["kind"] == "computed":
            entry["transformationDescription"] = field["expression"]
            entry["transformationType"] = "TRANSFORMATION"
        lineage_fields[cast(str, field["name"])] = entry
    return {
        "_producer": PRODUCER,
        "_schemaURL": COLUMN_LINEAGE_FACET_URL,
        "fields": lineage_fields,
    }


def _lineage_input(source: str, datasets_by_ref: dict[str, dict[str, object]]) -> dict[str, str] | None:
    try:
        parsed = parse_semantic_path(source)
    except ValueError:
        return None
    source_ref = parsed.declaration
    if source_ref not in datasets_by_ref:
        return None
    dataset = datasets_by_ref[source_ref]
    return {
        "namespace": cast(str, dataset["namespace"]),
        "name": cast(str, dataset["name"]),
        "field": ".".join(parsed.segments),
    }
