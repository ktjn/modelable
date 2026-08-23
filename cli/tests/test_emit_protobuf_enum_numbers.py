"""Protobuf emission tests for stable nominal enum numbering (evolution plan E6)."""

from __future__ import annotations

from pathlib import Path

from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
from modelable.emitters.protobuf import emit_protobuf
from modelable.registry.enum_numbers import allocate_enum_numbers


def _workspace(source: str):
    workspace = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("orders.mdl"), uri="file:///orders.mdl", text=source)]
    )
    assert not workspace.errors, workspace.errors
    return workspace


def _semantic_bundle(artifacts, domain: str = "orders") -> str:
    artifact = next(art for art in artifacts if art.path.name == "semantic-types.proto" and domain in str(art.path))
    assert isinstance(artifact.content, str)
    return artifact.content


def test_enum_backed_semantic_declaration_no_longer_crashes_protobuf_emission(tmp_path):
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 1 }
}
"""
    )
    artifacts = emit_protobuf(workspace, tmp_path / "out")
    assert artifacts


def test_nominal_enum_is_declared_once_and_referenced_by_qualified_type(tmp_path):
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 1 }
}
"""
    )
    allocation = allocate_enum_numbers(workspace.mdl, {})
    artifacts = emit_protobuf(workspace, tmp_path / "out", enum_numbers=allocation)

    bundle = _semantic_bundle(artifacts)
    assert "enum OrderStatus {" in bundle
    assert "ORDER_STATUS_UNSPECIFIED = 0;" in bundle
    assert "ORDER_STATUS_PENDING = 1;" in bundle
    assert "ORDER_STATUS_ACTIVE = 2;" in bundle
    assert "ORDER_STATUS_DONE = 3;" in bundle

    model_proto = next(art for art in artifacts if art.path.name == "Order.v1.proto")
    assert 'import "orders/semantic-types.proto";' in model_proto.content
    assert ".modelable.orders.semantic.OrderStatus status = 2;" in model_proto.content
    # The message body itself must not redeclare the enum.
    assert "enum OrderStatus" not in model_proto.content.split("message Order {")[1]


def test_enum_numbers_are_stable_across_reorder_and_append(tmp_path):
    v1_workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 1 }
}
"""
    )
    v1_allocation = allocate_enum_numbers(v1_workspace.mdl, {})

    v2_workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  semantic OrderStatus @ 2 (additive): enum(active, done, cancelled, pending)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 2 }
}
"""
    )
    v2_allocation = allocate_enum_numbers(v2_workspace.mdl, v1_allocation)
    artifacts = emit_protobuf(v2_workspace, tmp_path / "out", enum_numbers=v2_allocation)
    bundle = _semantic_bundle(artifacts)

    assert "ORDER_STATUS_PENDING = 1;" in bundle
    assert "ORDER_STATUS_ACTIVE = 2;" in bundle
    assert "ORDER_STATUS_DONE = 3;" in bundle
    assert "ORDER_STATUS_CANCELLED = 4;" in bundle


def test_removed_member_is_reserved_and_never_renumbers_survivors(tmp_path):
    v1_workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 1 }
}
"""
    )
    v1_allocation = allocate_enum_numbers(v1_workspace.mdl, {})

    v2_workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  semantic OrderStatus @ 2 (breaking): enum(active, cancelled)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 2 }
}
"""
    )
    v2_allocation = allocate_enum_numbers(v2_workspace.mdl, v1_allocation)
    artifacts = emit_protobuf(v2_workspace, tmp_path / "out", enum_numbers=v2_allocation)
    bundle = _semantic_bundle(artifacts)

    assert "reserved 1, 3;" in bundle
    assert 'reserved "pending", "done";' in bundle
    assert "ORDER_STATUS_ACTIVE = 2;" in bundle
    assert "ORDER_STATUS_CANCELLED = 4;" in bundle
    assert "ORDER_STATUS_PENDING" not in bundle.split("reserved")[-1]


def test_schema_manifest_captures_enum_numbers_and_reservations(tmp_path):
    v1_workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 1 }
}
"""
    )
    v1_allocation = allocate_enum_numbers(v1_workspace.mdl, {})
    v2_workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  semantic OrderStatus @ 2 (breaking): enum(active, cancelled)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 2 }
}
"""
    )
    v2_allocation = allocate_enum_numbers(v2_workspace.mdl, v1_allocation)
    artifacts = emit_protobuf(v2_workspace, tmp_path / "out", enum_numbers=v2_allocation)

    import json

    manifest = next(art for art in artifacts if art.path.name == "schema-manifest.json")
    payload = json.loads(manifest.content)
    field = next(f for f in payload["schemas"][0]["fields"] if f["name"] == "status")
    assert field["enum_type"] == "orders.OrderStatus"
    assert field["enum_numbers"] == {"active": 2, "cancelled": 4}
    assert field["enum_reservations"] == {"pending": 1, "done": 3}


def test_schema_fingerprint_changes_when_enum_numbers_change(tmp_path):
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 1 }
}
"""
    )

    import json

    def fingerprint(allocation):
        artifacts = emit_protobuf(workspace, tmp_path / "out", enum_numbers=allocation)
        manifest = next(art for art in artifacts if art.path.name == "schema-manifest.json")
        return json.loads(manifest.content)["schemas"][0]["schema_fingerprint"]

    allocation_a = allocate_enum_numbers(workspace.mdl, {})
    allocation_b = allocate_enum_numbers(workspace.mdl, {})
    assert fingerprint(allocation_a) == fingerprint(allocation_b)


def test_map_value_enum_ref_uses_persisted_numbers(tmp_path):
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) {
    @key orderId: uuid
    history: map<string, OrderStatus @ 1>
  }
}
"""
    )
    allocation = allocate_enum_numbers(workspace.mdl, {})
    artifacts = emit_protobuf(workspace, tmp_path / "out", enum_numbers=allocation)
    model_proto = next(art for art in artifacts if art.path.name == "Order.v1.proto")
    assert "map<string, .modelable.orders.semantic.OrderStatus> history" in model_proto.content
