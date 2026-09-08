"""Rust emission tests for nominal enum-backed semantic types and enum
projection lineage conversions (evolution plan E7)."""

from __future__ import annotations

import pytest

from modelable.compiler.workspace import load_workspace
from modelable.emitters.rust import emit_rust
from modelable.registry.enum_numbers import allocate_enum_numbers


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


def test_enum_backed_semantic_declaration_gets_wire_stable_serde_impl_from_lock(tmp_path):
    """A Protobuf enum-numbers.lock allocation, when supplied, must be threaded
    into a hand-written Serialize/Deserialize impl so non-self-describing
    encodings (postcard, bincode) tag each variant by its locked number
    instead of serde derive's declaration-order index — verified empirically
    that derive ignores an explicit `= N` discriminant entirely for those
    formats, so this hand-rolled impl is required (issue #855)."""
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
    enum_numbers = allocate_enum_numbers(workspace.mdl, {})
    artifacts = emit_rust(workspace, tmp_path / "out", enum_numbers=enum_numbers)

    enum_artifact = next(a for a in artifacts if a.ref == "orders.OrderStatus")
    content = enum_artifact.content
    # No derive-based Serialize/Deserialize when wire numbers are locked.
    assert "#[derive(Debug, Clone, PartialEq)]" in content
    assert "serde::Serialize, serde::Deserialize" not in content
    # Hand-written impls exist and encode the locked numbers as the wire tag.
    assert "impl serde::Serialize for OrderStatus {" in content
    assert "impl<'de> serde::Deserialize<'de> for OrderStatus {" in content
    assert "OrderStatus::Pending => 1," in content
    assert "OrderStatus::Active => 2," in content
    assert "OrderStatus::Done => 3," in content
    # JSON round-trip is unaffected: the variant name string is still used.
    assert 'OrderStatus::Pending => "pending",' in content
    assert "1 => Ok(__Field::Pending)," in content
    assert '"pending" => Ok(__Field::Pending),' in content


def test_enum_backed_declaration_with_shared_variant_prefix_suppresses_clippy_lint(tmp_path):
    """A private helper enum whose variants all share a prefix (e.g. every
    member of a real-world PaymentEffectType starting with "Payment") trips
    clippy's `enum_variant_names` lint, which only fires on non-`pub` enums
    (confirmed empirically: the public nominal enum itself, with the same
    variant shape, does not trigger it). A `-D warnings` clippy gate would
    reject the generated code without this allow attribute on the private
    `__Field` helper."""
    _write(
        tmp_path,
        "model.mdl",
        """
domain payments {
  owner: "payments-team"
  semantic PaymentEffectType @ 1 (additive): enum(payment_authorize, payment_capture, payment_refund, payment_void)
  entity Payment @ 1 (additive) { @key paymentId: uuid effectType: PaymentEffectType @ 1 }
}
""",
    )
    workspace = load_workspace(tmp_path)
    enum_numbers = allocate_enum_numbers(workspace.mdl, {})
    artifacts = emit_rust(workspace, tmp_path / "out", enum_numbers=enum_numbers)

    enum_artifact = next(a for a in artifacts if a.ref == "payments.PaymentEffectType")
    assert "#[allow(non_camel_case_types, clippy::enum_variant_names)]" in enum_artifact.content
    assert "enum __Field {" in enum_artifact.content


def test_enum_backed_semantic_declaration_without_lock_uses_derive(tmp_path):
    """No enum_numbers allocation supplied (e.g. no --enum-numbers ledger
    configured) leaves the enum on the derive-based path, unchanged from
    prior behavior — there's no locked number to make wire-stable."""
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
    assert "serde::Serialize, serde::Deserialize" in enum_artifact.content
    assert "Pending," in enum_artifact.content
    assert "impl serde::Serialize for OrderStatus" not in enum_artifact.content


def test_enum_projection_wire_numbers_carry_source_lock_numbers(tmp_path):
    """An enum projection's included members must carry their source
    declaration's locked numbers into the same hand-written Serialize impl,
    mirroring Protobuf's ``resolve_projection_numbers`` reuse-by-value
    semantics."""
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
    enum_numbers = allocate_enum_numbers(workspace.mdl, {})
    artifacts = emit_rust(workspace, tmp_path / "out", enum_numbers=enum_numbers)

    projection_artifact = next(a for a in artifacts if a.ref == "orders.PublicStatus")
    assert "PublicStatus::Active => 2," in projection_artifact.content
    assert "PublicStatus::Done => 3," in projection_artifact.content
