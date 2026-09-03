from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from jsonschema import Draft202012Validator

from modelable.cli import cli
from modelable.migration import MigrationError, migration_edges, parse_migration_document, validate_migration_references


def test_migration_document_normalizes_and_preserves_explicit_lineage() -> None:
    document = parse_migration_document(
        {
            "$schema": "modelable.migration/v1",
            "mappings": [
                {
                    "kind": "split",
                    "sources": ["orders.Order@1"],
                    "targets": ["orders.OrderHeader@1", "orders.OrderLine@1"],
                },
                {
                    "kind": "field_move",
                    "sources": ["orders.Order@1#customer_id"],
                    "targets": ["customer.Customer@1#id"],
                },
            ],
        }
    )

    assert document["mappings"] == [
        {
            "kind": "field_move",
            "sources": ["orders.Order@1#customer_id"],
            "targets": ["customer.Customer@1#id"],
        },
        {
            "kind": "split",
            "sources": ["orders.Order@1"],
            "targets": ["orders.OrderHeader@1", "orders.OrderLine@1"],
        },
    ]


@pytest.mark.parametrize(
    ("mapping", "message"),
    [
        (
            {"kind": "rename", "sources": ["orders.Order@1"], "targets": ["sales.Order@1", "sales.Order@2"]},
            "requires exactly one target",
        ),
        (
            {"kind": "split", "sources": ["orders.Order@1", "orders.Order@2"], "targets": ["sales.Order@1"]},
            "requires exactly one source",
        ),
        (
            {"kind": "field_move", "sources": ["orders.Order@1"], "targets": ["sales.Order@1#id"]},
            "must use semantic paths",
        ),
    ],
)
def test_migration_document_rejects_invalid_cardinality_and_paths(mapping: dict[str, object], message: str) -> None:
    with pytest.raises(MigrationError, match=message):
        parse_migration_document({"$schema": "modelable.migration/v1", "mappings": [mapping]})


def test_migration_document_rejects_cycles_and_ambiguous_sources() -> None:
    with pytest.raises(MigrationError, match="cycle"):
        parse_migration_document(
            {
                "$schema": "modelable.migration/v1",
                "mappings": [
                    {"kind": "rename", "sources": ["a.A@1"], "targets": ["b.B@1"]},
                    {"kind": "rename", "sources": ["b.B@1"], "targets": ["a.A@1"]},
                ],
            }
        )

    with pytest.raises(MigrationError, match="ambiguous"):
        parse_migration_document(
            {
                "$schema": "modelable.migration/v1",
                "mappings": [
                    {"kind": "rename", "sources": ["a.A@1"], "targets": ["b.B@1"]},
                    {"kind": "rename", "sources": ["a.A@1"], "targets": ["c.C@1"]},
                ],
            }
        )


def test_migration_edges_preserve_immediate_and_ultimate_sources() -> None:
    document = parse_migration_document(
        {
            "$schema": "modelable.migration/v1",
            "mappings": [
                {"kind": "rename", "sources": ["a.A@1"], "targets": ["b.B@1"]},
                {"kind": "split", "sources": ["b.B@1"], "targets": ["c.C@1", "c.D@1"]},
            ],
        }
    )

    assert migration_edges(document) == [
        {
            "kind": "rename",
            "source": "a.A@1",
            "target": "b.B@1",
            "immediate": "a.A@1",
            "ultimate": "a.A@1",
            "ultimate_sources": ["a.A@1"],
        },
        {
            "kind": "split",
            "source": "b.B@1",
            "target": "c.C@1",
            "immediate": "b.B@1",
            "ultimate": "a.A@1",
            "ultimate_sources": ["a.A@1"],
        },
        {
            "kind": "split",
            "source": "b.B@1",
            "target": "c.D@1",
            "immediate": "b.B@1",
            "ultimate": "a.A@1",
            "ultimate_sources": ["a.A@1"],
        },
    ]


def test_migration_references_can_be_validated_against_a_snapshot_identity_set() -> None:
    document = parse_migration_document(
        {
            "$schema": "modelable.migration/v1",
            "mappings": [{"kind": "rename", "sources": ["a.A@1"], "targets": ["b.B@1"]}],
        }
    )

    with pytest.raises(MigrationError, match="dangling"):
        validate_migration_references(document, {"a.A@1"})


def test_migration_schema_accepts_protocol_document() -> None:
    schema_path = Path(__file__).parents[1] / "src" / "modelable" / "data" / "modelable.migration.v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate({"$schema": "modelable.migration/v1", "mappings": []})


def test_migration_cli_validates_and_inspects_canonical_metadata(tmp_path) -> None:
    path = tmp_path / "migration.json"
    path.write_text(
        '{"$schema":"modelable.migration/v1","mappings":[{"kind":"rename","sources":["a.A@1"],"targets":["b.B@1"]}]}',
        encoding="utf-8",
    )

    validated = CliRunner().invoke(cli, ["migration", "validate", str(path)])
    inspected = CliRunner().invoke(cli, ["migration", "inspect", str(path)])

    assert validated.exit_code == 0, validated.output
    assert "valid: true" in validated.output
    assert inspected.exit_code == 0, inspected.output
    assert json.loads(inspected.output)["mappings"][0]["sources"] == ["a.A@1"]
