from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from modelable.cli import cli
from modelable.consequence_protocol import (
    CONSEQUENCE_SCHEMA,
    ConsequenceProtocolError,
    load_consequence_graph,
    serialize_consequence_graph,
    validate_consequence_graph,
)

GRAPH = {
    "$schema": CONSEQUENCE_SCHEMA,
    "kind": "consequence_graph",
    "nodes": [
        {"id": "customer.Customer@1", "kind": "reference", "label": "customer.Customer@1"},
        {
            "id": "change:removed_field:email",
            "kind": "change",
            "change_kind": "removed_field",
            "field": "email",
        },
    ],
    "edges": [
        {"kind": "causes", "source": "customer.Customer@1", "target": "change:removed_field:email"},
    ],
}


def test_consequence_graph_protocol_validates_and_serializes_deterministically() -> None:
    reordered = {
        **GRAPH,
        "nodes": list(reversed(GRAPH["nodes"])),
        "edges": list(reversed(GRAPH["edges"])),
    }

    assert validate_consequence_graph(GRAPH) == GRAPH
    assert serialize_consequence_graph(GRAPH) == serialize_consequence_graph(reordered)


def test_consequence_graph_protocol_rejects_unknown_edge_endpoint() -> None:
    invalid = {**GRAPH, "edges": [{"kind": "causes", "source": "missing", "target": "customer.Customer@1"}]}

    with pytest.raises(ConsequenceProtocolError, match="unknown source"):
        validate_consequence_graph(invalid)


def test_load_consequence_graph_validates_json(tmp_path: Path) -> None:
    path = tmp_path / "consequence.json"
    path.write_text(json.dumps(GRAPH), encoding="utf-8")

    assert load_consequence_graph(path) == GRAPH


def test_consequence_validate_command_prints_canonical_json(tmp_path: Path) -> None:
    path = tmp_path / "consequence.json"
    path.write_text(json.dumps(GRAPH), encoding="utf-8")

    result = CliRunner().invoke(cli, ["consequence", "validate", str(path), "--format", "json"])

    assert result.exit_code == 0, result.output
    assert result.output == serialize_consequence_graph(GRAPH)
