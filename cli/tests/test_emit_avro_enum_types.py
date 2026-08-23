"""Avro emission tests for nominal enum-backed semantic declarations
(evolution plan E9)."""

from __future__ import annotations

from pathlib import Path

from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
from modelable.emitters.avro import emit_avro


def _workspace(source: str):
    workspace = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("orders.mdl"), uri="file:///orders.mdl", text=source)]
    )
    assert not workspace.errors, workspace.errors
    return workspace


def test_enum_ref_field_gets_a_qualified_named_avro_enum(tmp_path):
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 1 }
}
"""
    )
    artifacts = emit_avro(workspace, tmp_path / "out")
    schema = next(a for a in artifacts if a.ref == "orders.Order@1").content
    status_field = next(f for f in schema["fields"] if f["name"] == "status")
    assert status_field["type"] == {
        "type": "enum",
        "name": "OrderStatus",
        "namespace": "orders",
        "symbols": ["pending", "active", "done"],
    }


def test_repeated_enum_ref_fields_reuse_the_named_type_by_reference(tmp_path):
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
    artifacts = emit_avro(workspace, tmp_path / "out")
    schema = next(a for a in artifacts if a.ref == "orders.Order@1").content
    fields = {f["name"]: f["type"] for f in schema["fields"]}

    assert isinstance(fields["status"], dict) and fields["status"]["type"] == "enum"
    # Every later reference is the bare Avro qualified-name string, not a
    # fresh redeclaration.
    assert fields["priorStatus"] == "orders.OrderStatus"
    assert fields["history"] == {"type": "map", "values": "orders.OrderStatus"}
    assert fields["tags"] == {"type": "array", "items": "orders.OrderStatus"}


def test_cross_domain_enum_reference_uses_declaring_domain_namespace(tmp_path):
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
}

domain fulfillment {
  owner: "fulfillment-team"
  entity Shipment @ 1 (additive) {
    @key shipmentId: uuid
    status: orders.OrderStatus @ 1
  }
}
"""
    )
    artifacts = emit_avro(workspace, tmp_path / "out")
    schema = next(a for a in artifacts if a.ref == "fulfillment.Shipment@1").content
    status_field = next(f for f in schema["fields"] if f["name"] == "status")
    assert status_field["type"]["namespace"] == "orders"
    assert status_field["type"]["name"] == "OrderStatus"
