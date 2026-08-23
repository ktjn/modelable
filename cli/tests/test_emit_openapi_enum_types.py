"""OpenAPI emission tests for nominal enum-backed semantic declarations
(evolution plan E9)."""

from __future__ import annotations

from pathlib import Path

from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
from modelable.emitters.openapi import _validate_document, emit_openapi


def _workspace(source: str):
    workspace = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("orders.mdl"), uri="file:///orders.mdl", text=source)]
    )
    assert not workspace.errors, workspace.errors
    return workspace


_FIXTURE = """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 1 }

  auto projections Order @ 1 {
    db
    event on [created]
  }
}
"""


def test_enum_ref_field_becomes_a_reusable_component_ref(tmp_path):
    workspace = _workspace(_FIXTURE)
    artifacts = emit_openapi(workspace, tmp_path / "out")
    schemas = artifacts[0].content["components"]["schemas"]

    assert schemas["OrdersOrderStatus"] == {
        "title": "OrderStatus",
        "type": "string",
        "enum": ["pending", "active", "done"],
    }
    event_schema = schemas["orders.OrderEvent.v1"]
    assert event_schema["properties"]["status"] == {"$ref": "#/components/schemas/OrdersOrderStatus"}


def test_generated_document_passes_openapi_validation(tmp_path):
    workspace = _workspace(_FIXTURE)
    artifacts = emit_openapi(workspace, tmp_path / "out")
    errors = _validate_document(artifacts[0].content)
    assert errors == []
