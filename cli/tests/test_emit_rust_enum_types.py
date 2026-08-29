"""Rust emission tests for nominal enum-backed semantic types and enum
projection lineage conversions (evolution plan E7)."""

from __future__ import annotations

import pytest

from modelable.compiler.workspace import load_workspace
from modelable.emitters.rust import emit_rust


def _write(tmp_path, name: str, text: str) -> None:
    (tmp_path / name).write_text(text, encoding="utf-8")


def test_enum_backed_semantic_declaration_emits_real_enum_not_string_wrapper(tmp_path):
    _write(
        tmp_path,
        "model.mdl",
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 1 }
}
""",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_rust(workspace, tmp_path / "out")

    enum_artifact = next(a for a in artifacts if a.ref == "orders.OrderStatus")
    assert "pub enum OrderStatus {" in enum_artifact.content
    assert "pub struct OrderStatus" not in enum_artifact.content
    assert '#[serde(rename = "pending")]' in enum_artifact.content
    assert "Pending," in enum_artifact.content

    entity_artifact = next(a for a in artifacts if a.ref == "orders.Order@1")
    assert "use super::order_status::OrderStatus;" in entity_artifact.content
    assert "pub status: OrderStatus," in entity_artifact.content


def test_enum_ref_in_array_and_map_fields_import_the_nominal_type(tmp_path):
    _write(
        tmp_path,
        "model.mdl",
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
""",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_rust(workspace, tmp_path / "out")
    entity_artifact = next(a for a in artifacts if a.ref == "orders.Order@1")
    assert "use super::order_status::OrderStatus;" in entity_artifact.content
    assert "pub history: HashMap<String, OrderStatus>," in entity_artifact.content
    assert "pub tags: Vec<OrderStatus>," in entity_artifact.content


def test_enum_projection_emits_own_type_and_total_projection_to_source_conversion(tmp_path):
    _write(
        tmp_path,
        "model.mdl",
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 1 }
  enum projection PublicStatus @ 1 (additive)
    from OrderStatus @ 1
    pick(active, done)
}
""",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_rust(workspace, tmp_path / "out")
    projection_artifact = next(a for a in artifacts if a.ref == "orders.PublicStatus")

    assert "pub enum PublicStatus {" in projection_artifact.content
    assert "Active," in projection_artifact.content
    assert "Done," in projection_artifact.content
    assert (
        "Pending"
        not in projection_artifact.content.split("impl From<PublicStatus>")[0].split("pub enum PublicStatus")[1]
    )

    # Projection -> source is always total.
    assert "impl From<PublicStatus> for OrderStatus {" in projection_artifact.content
    assert "PublicStatus::Active => OrderStatus::Active," in projection_artifact.content

    # Source -> projection is checked because the projection is a proper subset.
    assert "impl TryFrom<OrderStatus> for PublicStatus {" in projection_artifact.content
    assert "type Error = PublicStatusFromSourceError;" in projection_artifact.content
    assert "other => Err(PublicStatusFromSourceError(other))," in projection_artifact.content
    assert "impl From<OrderStatus> for PublicStatus {" not in projection_artifact.content


def test_enum_projection_covering_every_source_member_gets_total_conversions_both_ways(tmp_path):
    _write(
        tmp_path,
        "model.mdl",
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 1 }
  enum projection FullStatus @ 1 (additive)
    from OrderStatus @ 1
    pick(pending, active, done)
}
""",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_rust(workspace, tmp_path / "out")
    projection_artifact = next(a for a in artifacts if a.ref == "orders.FullStatus")

    assert "impl From<FullStatus> for OrderStatus {" in projection_artifact.content
    assert "impl From<OrderStatus> for FullStatus {" in projection_artifact.content
    assert "TryFrom" not in projection_artifact.content


def test_enum_projection_field_emits_nominal_rust_type(tmp_path):
    _write(
        tmp_path,
        "model.mdl",
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  enum projection PublicStatus @ 1 (additive)
    from OrderStatus @ 1
    pick(active, done)
  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: PublicStatus @ 1
    metadata: object { status: PublicStatus @ 1 }
  }
}
""",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_rust(workspace, tmp_path / "out")
    entity_artifact = next(a for a in artifacts if a.ref == "orders.Order@1")

    assert "use super::public_status::PublicStatus;" in entity_artifact.content
    assert entity_artifact.content.count("pub status: PublicStatus,") == 2


def test_direct_rust_emission_rejects_non_latest_projection_field_reference(tmp_path):
    _write(
        tmp_path,
        "model.mdl",
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  enum projection PublicStatus @ 2 (additive)
    from OrderStatus @ 1
    pick(active, done)
  enum projection PublicStatus @ 1 (additive)
    from OrderStatus @ 1
    pick(active)
  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: PublicStatus @ 1
  }
}
""",
    )

    with pytest.raises(ValueError, match="non-latest enum projection"):
        emit_rust(load_workspace(tmp_path), tmp_path / "out")


def test_clickhouse_bound_projection_forces_string_for_nominal_enum_field(tmp_path):
    _write(
        tmp_path,
        "model.mdl",
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 1 }
  projection OrderChView @ 1
    from orders.Order @ 1 as o
  {
    orderId <- o.orderId
    status <- o.status
  }
}
""",
    )
    _write(
        tmp_path,
        "bindings.mdl",
        """
binding ch-conn {
  adapter: clickhouse
}

binding order-binding {
  model: orders.Order @ 1
  adapter: ch-conn
  table: "orders"
}
""",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_rust(workspace, tmp_path / "out")
    projection_artifact = next(a for a in artifacts if a.ref == "orders.OrderChView@1")

    assert "pub status: String," in projection_artifact.content
    assert "status: match src.status {" in projection_artifact.content
    assert 'OrderStatus::Pending => "pending".to_string(),' in projection_artifact.content
    assert 'OrderStatus::Active => "active".to_string(),' in projection_artifact.content
    assert 'OrderStatus::Done => "done".to_string(),' in projection_artifact.content
