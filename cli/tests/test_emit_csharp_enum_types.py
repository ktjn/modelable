"""C# emission tests for nominal enum-backed semantic types
(evolution plan E8)."""

from __future__ import annotations

from pathlib import Path

import pytest

from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
from modelable.emitters.csharp import _emit_enum_projection, _emit_enum_type, _emit_versioned_enum_type, emit_csharp
from modelable.parser.ir import DomainDef, EnumProjectionDecl, EnumType, SemanticTypeDecl


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


def test_projection_typed_field_emits_and_uses_versioned_csharp_enum(tmp_path):
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active)
  enum projection PublicOrderStatus @ 1
    from OrderStatus @ 1
    pick(pending)
  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: PublicOrderStatus @ 1
  }
}
"""
    )
    artifacts = emit_csharp(workspace, tmp_path / "out")
    enum_artifact = next(a for a in artifacts if a.ref == "orders.PublicOrderStatus@1")
    assert "public enum OrdersPublicOrderStatusV1" in enum_artifact.content
    assert "OrdersPublicOrderStatusV1.Pending" in enum_artifact.content

    model_artifact = next(a for a in artifacts if a.ref == "orders.Order@1")
    assert "public required OrdersPublicOrderStatusV1 Status" in model_artifact.content


def test_csharp_enum_member_identifier_collisions_fail_for_all_artifact_paths(tmp_path):
    domain = DomainDef(name="orders")
    projection = EnumProjectionDecl(
        name="PublicStatus",
        version=1,
        source_name="Status",
        source_version=1,
        selection_kind="pick",
        members=["foo-bar", "foo_bar"],
    )
    declaration = SemanticTypeDecl(name="Status", version=1, underlying=EnumType(values=["foo-bar", "foo_bar"]))

    for emit in (
        lambda: _emit_enum_type(domain, declaration, tmp_path / "out"),
        lambda: _emit_versioned_enum_type(domain, declaration, tmp_path / "out"),
        lambda: _emit_enum_projection(domain, projection, tmp_path / "out"),
    ):
        with pytest.raises(ValueError, match=r"foo-bar.*foo_bar.*FooBar"):
            emit()
