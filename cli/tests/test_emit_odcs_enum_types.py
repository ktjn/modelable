"""ODCS emission tests for nominal enum-backed semantic declarations
(evolution plan E10)."""

from __future__ import annotations

from pathlib import Path

import yaml

from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
from modelable.emitters.odcs import emit_odcs


def _workspace(source: str):
    workspace = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("orders.mdl"), uri="file:///orders.mdl", text=source)]
    )
    assert not workspace.errors, workspace.errors
    return workspace


def _properties(artifact) -> dict[str, dict]:
    doc = yaml.safe_load(artifact.content)
    return {prop["name"]: prop for prop in doc["schema"][0]["properties"]}


def _custom(prop: dict, key: str):
    return next((entry["value"] for entry in prop["customProperties"] if entry["property"] == key), None)


def test_enum_ref_field_preserves_the_closed_value_set(tmp_path):
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 1 }
}
"""
    )
    artifacts = emit_odcs(workspace, tmp_path / "out")
    properties = _properties(next(a for a in artifacts if a.ref == "orders.Order@1"))
    status = properties["status"]

    assert status["logicalType"] == "string"
    assert _custom(status, "modelableEnum") == ["pending", "active", "done"]
    assert _custom(status, "modelableEnumType") == "orders.OrderStatus"
    assert _custom(status, "modelableType") == "orders.OrderStatus"


def test_record_projection_direct_mapped_enum_field_preserves_identity(tmp_path):
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
    artifacts = emit_odcs(workspace, tmp_path / "out")
    properties = _properties(next(a for a in artifacts if a.ref == "orders.OrderView@1"))
    status = properties["status"]
    assert _custom(status, "modelableEnum") == ["pending", "active", "done"]
    assert _custom(status, "modelableEnumType") == "orders.OrderStatus"


def test_cross_domain_enum_reference_resolves_declaring_domain(tmp_path):
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
    artifacts = emit_odcs(workspace, tmp_path / "out")
    properties = _properties(next(a for a in artifacts if a.ref == "fulfillment.Shipment@1"))
    status = properties["status"]
    assert _custom(status, "modelableEnumType") == "orders.OrderStatus"


def test_anonymous_enum_is_unaffected(tmp_path):
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) { @key orderId: uuid status: enum(pending, active, done) }
}
"""
    )
    artifacts = emit_odcs(workspace, tmp_path / "out")
    properties = _properties(next(a for a in artifacts if a.ref == "orders.Order@1"))
    status = properties["status"]
    assert _custom(status, "modelableEnum") == ["pending", "active", "done"]
    assert _custom(status, "modelableEnumType") is None
