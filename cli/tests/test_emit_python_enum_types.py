"""Python emission tests for nominal enum-backed semantic types
(evolution plan E8)."""

from __future__ import annotations

from pathlib import Path

import pytest

from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
from modelable.emitters.python import _emit_enum_projection, _emit_versioned_enum_type, emit_python
from modelable.parser.ir import DomainDef, EnumProjectionDecl, EnumType, SemanticTypeDecl


def _workspace(source: str):
    workspace = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("orders.mdl"), uri="file:///orders.mdl", text=source)]
    )
    assert not workspace.errors, workspace.errors
    return workspace


def test_enum_backed_semantic_declaration_emits_reusable_strenum(tmp_path):
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 1 }
}
"""
    )
    artifacts = emit_python(workspace, tmp_path / "out")

    enum_artifact = next(a for a in artifacts if a.ref == "orders.OrderStatus")
    assert "from enum import StrEnum" in enum_artifact.content
    assert "class OrderStatus(StrEnum):" in enum_artifact.content
    assert "PENDING = 'pending'" in enum_artifact.content
    assert "ACTIVE = 'active'" in enum_artifact.content
    assert "DONE = 'done'" in enum_artifact.content

    model_artifact = next(a for a in artifacts if a.ref == "orders.Order@1")
    assert "from orders.order_status import OrderStatus" in model_artifact.content
    assert "status: OrderStatus" in model_artifact.content


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
    artifacts = emit_python(workspace, tmp_path / "out")
    model_artifact = next(a for a in artifacts if a.ref == "orders.Order@1")
    assert "history: dict[str, OrderStatus]" in model_artifact.content
    assert "tags: list[OrderStatus]" in model_artifact.content


def test_record_projection_direct_mapped_enum_field_imports_nominal_type(tmp_path):
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
    artifacts = emit_python(workspace, tmp_path / "out")
    projection_artifact = next(a for a in artifacts if a.ref == "orders.OrderView@1")
    assert "from orders.order_status import OrderStatus" in projection_artifact.content
    assert "status: OrderStatus" in projection_artifact.content


def test_generated_strenum_round_trips_as_wire_string(tmp_path):
    """The emitted module must actually import and behave like a str at runtime."""
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
}
"""
    )
    artifacts = emit_python(workspace, tmp_path / "out")
    enum_artifact = next(a for a in artifacts if a.ref == "orders.OrderStatus")

    module_globals: dict[str, object] = {}
    exec(compile(enum_artifact.content, "order_status.py", "exec"), module_globals)
    order_status = module_globals["OrderStatus"]
    assert order_status.ACTIVE == "active"
    assert isinstance(order_status.ACTIVE, str)


def test_default_emit_nominal_enums_stays_off_for_unmigrated_callers(tmp_path):
    """Regression guard: named_types.py's resolve_named_types/resolve_named_ref
    default to inline expansion. Every current caller (Python, TypeScript's own
    resolver, Java, C#, Go) has now migrated to emit_nominal_enums=True as of
    E8's Go slice, but the default itself must stay False so a future emitter
    that doesn't explicitly opt in can't silently reference a type name
    nothing emits, the exact bug this flag was added to prevent (see git log
    for the Python E8 slice)."""
    from modelable.emitters.named_types import resolve_named_types

    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
}
"""
    )
    names, shapes = resolve_named_types(workspace.mdl, current_domain="orders", model_name=lambda d, n, v: n)
    assert "OrderStatus" not in names
    assert "OrderStatus" in shapes


def test_projection_typed_field_emits_versioned_strenum(tmp_path):
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
    artifacts = emit_python(workspace, tmp_path / "out")
    enum_artifact = next(a for a in artifacts if a.ref == "orders.PublicOrderStatus@1")
    assert "class OrdersPublicOrderStatusV1(StrEnum):" in enum_artifact.content
    assert "PENDING = 'pending'" in enum_artifact.content

    model_artifact = next(a for a in artifacts if a.ref == "orders.Order@1")
    assert "from orders.orders_public_order_status_v1 import OrdersPublicOrderStatusV1" in model_artifact.content
    assert "status: OrdersPublicOrderStatusV1" in model_artifact.content


def test_exact_semantic_enum_versions_remain_distinct(tmp_path):
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic Status @ 1 (additive): enum(pending, active)
  semantic Status @ 2 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) {
    @key orderId: uuid
    oldStatus: Status @ 1
    newStatus: Status @ 2
  }
}
"""
    )
    artifacts = emit_python(workspace, tmp_path / "out")
    old_enum = next(a for a in artifacts if a.ref == "orders.Status@1")
    latest_enum = next(a for a in artifacts if a.ref == "orders.Status")
    assert "class OrdersStatusV1(StrEnum):" in old_enum.content
    assert "class Status(StrEnum):" in latest_enum.content
    assert "DONE = 'done'" not in old_enum.content
    model = next(a for a in artifacts if a.ref == "orders.Order@1")
    assert "oldStatus: OrdersStatusV1" in model.content
    assert "newStatus: Status" in model.content


def test_cross_domain_semantic_enums_use_distinct_import_aliases(tmp_path):
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: billing.Status @ 1
  }
}
domain billing {
  owner: "billing-team"
  semantic Status @ 1 (additive): enum(pending, active)
}
"""
    )
    artifacts = emit_python(workspace, tmp_path / "out")
    model = next(a for a in artifacts if a.ref == "orders.Order@1")
    assert "from billing.status import Status as BillingStatus" in model.content
    assert "status: BillingStatus" in model.content


def test_latest_enum_member_identifier_collisions_fail_python_emission(tmp_path):
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic Status @ 1 (additive): enum(foo-bar, foo_bar)
}
"""
    )

    with pytest.raises(ValueError, match=r"foo-bar.*foo_bar.*FOO_BAR"):
        emit_python(workspace, tmp_path / "out")


def test_versioned_enum_member_identifier_collisions_fail_python_emission(tmp_path):
    declaration = SemanticTypeDecl(
        name="Status",
        version=1,
        underlying=EnumType(values=["foo-bar", "foo_bar"]),
    )

    with pytest.raises(ValueError, match=r"foo-bar.*foo_bar.*FOO_BAR"):
        _emit_versioned_enum_type(DomainDef(name="orders"), declaration, tmp_path / "out")


def test_enum_projection_member_identifier_collisions_fail_python_emission(tmp_path):
    projection = EnumProjectionDecl(
        name="PublicStatus",
        version=1,
        source_name="Status",
        source_version=1,
        selection_kind="pick",
        members=["foo-bar", "foo_bar"],
    )

    with pytest.raises(ValueError, match=r"foo-bar.*foo_bar.*FOO_BAR"):
        _emit_enum_projection(DomainDef(name="orders"), projection, tmp_path / "out")
