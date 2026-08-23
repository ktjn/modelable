"""JSON Schema emission tests for nominal enum-backed semantic declarations
(evolution plan E9)."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
from modelable.emitters.json_schema import emit_json_schema


def _workspace(source: str):
    workspace = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("orders.mdl"), uri="file:///orders.mdl", text=source)]
    )
    assert not workspace.errors, workspace.errors
    return workspace


def _content(artifact) -> dict:
    content = artifact.content
    if isinstance(content, (bytes, bytearray)):
        return json.loads(content.decode("utf-8"))
    return content


def test_enum_ref_field_becomes_a_reusable_ref_not_a_bare_object(tmp_path):
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 1 }
}
"""
    )
    artifacts = emit_json_schema(workspace, tmp_path / "out")
    schema = _content(artifacts[0])

    assert schema["properties"]["status"] == {"$ref": "#/$defs/OrdersOrderStatus"}
    assert schema["$defs"]["OrdersOrderStatus"] == {
        "title": "OrderStatus",
        "type": "string",
        "enum": ["pending", "active", "done"],
    }


def test_repeated_enum_ref_fields_reuse_the_same_def(tmp_path):
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: OrderStatus @ 1
    priorStatus: OrderStatus @ 1
    history: map<string, OrderStatus @ 1>
    tags: array<OrderStatus @ 1>
  }
}
"""
    )
    artifacts = emit_json_schema(workspace, tmp_path / "out")
    schema = _content(artifacts[0])

    ref = {"$ref": "#/$defs/OrdersOrderStatus"}
    assert schema["properties"]["status"] == ref
    assert schema["properties"]["priorStatus"] == ref
    assert schema["properties"]["history"]["additionalProperties"] == ref
    assert schema["properties"]["tags"]["items"] == ref
    assert len(schema["$defs"]) == 1


def test_generated_schema_validates_and_rejects_unknown_enum_values(tmp_path):
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 1 }
}
"""
    )
    artifacts = emit_json_schema(workspace, tmp_path / "out")
    schema = _content(artifacts[0])
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    valid = {"orderId": "123e4567-e89b-12d3-a456-426614174000", "status": "active"}
    invalid = {"orderId": "123e4567-e89b-12d3-a456-426614174000", "status": "not-a-status"}
    assert list(validator.iter_errors(valid)) == []
    errors = [error.message for error in validator.iter_errors(invalid)]
    assert any("not-a-status" in message for message in errors)


def test_anonymous_enum_stays_inline_not_a_ref(tmp_path):
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) { @key orderId: uuid status: enum(pending, active, done) }
}
"""
    )
    artifacts = emit_json_schema(workspace, tmp_path / "out")
    schema = _content(artifacts[0])
    assert schema["properties"]["status"] == {"type": "string", "enum": ["pending", "active", "done"]}
    assert "$defs" not in schema or schema["$defs"] == {}
