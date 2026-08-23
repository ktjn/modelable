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


def test_csharp_go_are_unaffected_by_python_nominal_enum_opt_in(tmp_path):
    """Regression guard: named_types.py's shared resolver must stay opt-in per
    target so untouched emitters keep their existing (inline) behavior until
    their own E8 slice lands. Java has since gotten its own slice (see
    test_emit_java_enum_types.py) and is intentionally not checked here
    anymore; C# and Go have not."""
    from modelable.emitters.csharp import emit_csharp
    from modelable.emitters.go import emit_go

    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 1 }
}
"""
    )
    cs_content = next(a.content for a in emit_csharp(workspace, tmp_path / "cs") if a.ref == "orders.Order@1")
    go_content = next(a.content for a in emit_go(workspace, tmp_path / "go") if a.ref == "orders.Order@1")

    assert "string Status" in cs_content
    assert "Status string" in go_content
