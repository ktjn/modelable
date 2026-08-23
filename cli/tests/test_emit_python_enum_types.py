"""Python emission tests for nominal enum-backed semantic types
(evolution plan E8)."""

from __future__ import annotations

from pathlib import Path

from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
from modelable.emitters.python import emit_python


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
