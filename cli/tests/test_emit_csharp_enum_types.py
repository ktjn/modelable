"""C# emission tests for nominal enum-backed semantic types
(evolution plan E8)."""

from __future__ import annotations

from pathlib import Path

from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
from modelable.emitters.csharp import emit_csharp


def _workspace(source: str):
    workspace = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("orders.mdl"), uri="file:///orders.mdl", text=source)]
    )
    assert not workspace.errors, workspace.errors
    return workspace


def test_enum_backed_semantic_declaration_emits_reusable_csharp_enum(tmp_path):
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 1 }
}
"""
    )
    artifacts = emit_csharp(workspace, tmp_path / "out")

    enum_artifact = next(a for a in artifacts if a.ref == "orders.OrderStatus")
    assert "public enum OrderStatus" in enum_artifact.content
    assert "Pending," in enum_artifact.content
    assert "Active," in enum_artifact.content
    assert "Done," in enum_artifact.content
    assert "public static class OrderStatusExtensions" in enum_artifact.content
    assert 'OrderStatus.Pending => "pending",' in enum_artifact.content
    assert '"pending" => OrderStatus.Pending,' in enum_artifact.content

    model_artifact = next(a for a in artifacts if a.ref == "orders.Order@1")
    assert "public required OrderStatus Status" in model_artifact.content
    # Same namespace, so no extra using is needed.
    assert "using Modelable.Orders;" not in model_artifact.content


def test_enum_ref_in_array_and_map_fields_use_the_nominal_type(tmp_path):
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) {
    @key orderId: uuid
    history: map<string, OrderStatus @ 1>
    tags: array<OrderStatus @ 1>
  }
}
"""
    )
    artifacts = emit_csharp(workspace, tmp_path / "out")
    model_artifact = next(a for a in artifacts if a.ref == "orders.Order@1")
    assert "Dictionary<string, OrderStatus> History" in model_artifact.content
    assert "List<OrderStatus> Tags" in model_artifact.content


def test_record_projection_direct_mapped_enum_field_uses_nominal_type(tmp_path):
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 1 }
  projection OrderView @ 1
    from orders.Order @ 1 as o
  {
    orderId <- o.orderId
    status <- o.status
  }
}
"""
    )
    artifacts = emit_csharp(workspace, tmp_path / "out")
    projection_artifact = next(a for a in artifacts if a.ref == "orders.OrderView@1")
    assert "public required OrderStatus Status" in projection_artifact.content


def test_cross_domain_enum_reference_imports_the_nominal_type(tmp_path):
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
    artifacts = emit_csharp(workspace, tmp_path / "out")
    shipment_artifact = next(a for a in artifacts if a.ref == "fulfillment.Shipment@1")
    assert "using Modelable.Orders;" in shipment_artifact.content
    assert "public required OrderStatus Status" in shipment_artifact.content
