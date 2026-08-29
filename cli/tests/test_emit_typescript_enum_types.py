"""TypeScript emission tests for nominal enum-backed semantic types
(evolution plan E8)."""

from __future__ import annotations

from pathlib import Path

from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
from modelable.emitters.typescript import emit_typescript


def _workspace(source: str):
    workspace = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("orders.mdl"), uri="file:///orders.mdl", text=source)]
    )
    assert not workspace.errors, workspace.errors
    return workspace


def test_enum_backed_semantic_declaration_emits_reusable_ts_enum(tmp_path):
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 1 }
}
"""
    )
    artifacts = emit_typescript(workspace, tmp_path / "out")

    enum_artifact = next(a for a in artifacts if a.ref == "orders.OrderStatus")
    assert "export enum OrderStatus {" in enum_artifact.content
    assert "Pending = 'pending'," in enum_artifact.content
    assert "Active = 'active'," in enum_artifact.content
    assert "Done = 'done'," in enum_artifact.content

    model_artifact = next(a for a in artifacts if a.ref == "orders.Order@1")
    assert 'import { OrderStatus } from "./orders.OrderStatus";' in model_artifact.content
    assert "status: OrderStatus;" in model_artifact.content
    # Value import (not `import type`), since a TS enum is also a runtime value.
    assert "import type { OrderStatus }" not in model_artifact.content


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
    artifacts = emit_typescript(workspace, tmp_path / "out")
    model_artifact = next(a for a in artifacts if a.ref == "orders.Order@1")
    assert "history: Record<string, OrderStatus>;" in model_artifact.content
    assert "tags: OrderStatus[];" in model_artifact.content


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
    artifacts = emit_typescript(workspace, tmp_path / "out")
    projection_artifact = next(a for a in artifacts if a.ref == "orders.OrderView@1")
    assert 'import { OrderStatus } from "./orders.OrderStatus";' in projection_artifact.content
    assert "status: OrderStatus;" in projection_artifact.content


def test_projection_typed_fields_emit_and_import_reusable_enum(tmp_path):
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  enum projection PublicOrderStatus @ 1
    from OrderStatus @ 1
    pick(pending, active)
  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: PublicOrderStatus @ 1
    history: map<string, PublicOrderStatus @ 1>
    tags: array<PublicOrderStatus @ 1>
  }
}
"""
    )
    artifacts = emit_typescript(workspace, tmp_path / "out")

    enum_artifact = next(a for a in artifacts if a.ref == "orders.PublicOrderStatus@1")
    assert "export enum PublicOrderStatus {" in enum_artifact.content
    assert "Pending = 'pending'," in enum_artifact.content
    assert "Active = 'active'," in enum_artifact.content
    assert "Done = 'done'," not in enum_artifact.content

    model_artifact = next(a for a in artifacts if a.ref == "orders.Order@1")
    assert 'import { PublicOrderStatus } from "./orders.PublicOrderStatus.v1";' in model_artifact.content
    assert "status: PublicOrderStatus;" in model_artifact.content
    assert "history: Record<string, PublicOrderStatus>;" in model_artifact.content
    assert "tags: PublicOrderStatus[];" in model_artifact.content


def test_projection_typed_fields_preserve_exact_projection_versions(tmp_path):
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  enum projection PublicOrderStatus @ 1
    from OrderStatus @ 1
    pick(pending)
  enum projection PublicOrderStatus @ 2
    from OrderStatus @ 1
    pick(pending, active)
  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: PublicOrderStatus @ 1
  }
  entity Order @ 2 (breaking) {
    @key orderId: uuid
    status: PublicOrderStatus @ 2
  }
}
"""
    )
    artifacts = emit_typescript(workspace, tmp_path / "out")

    v1 = next(a for a in artifacts if a.ref == "orders.PublicOrderStatus@1")
    v2 = next(a for a in artifacts if a.ref == "orders.PublicOrderStatus@2")
    assert "Pending = 'pending'," in v1.content
    assert "Active = 'active'," not in v1.content
    assert "Active = 'active'," in v2.content

    model_v1 = next(a for a in artifacts if a.ref == "orders.Order@1")
    model_v2 = next(a for a in artifacts if a.ref == "orders.Order@2")
    assert 'import { PublicOrderStatus } from "./orders.PublicOrderStatus.v1";' in model_v1.content
    assert 'import { PublicOrderStatus } from "./orders.PublicOrderStatus.v2";' in model_v2.content


def test_projection_typed_fields_alias_mixed_versions_in_one_model(tmp_path):
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  enum projection PublicOrderStatus @ 1
    from OrderStatus @ 1
    pick(pending)
  enum projection PublicOrderStatus @ 2
    from OrderStatus @ 1
    pick(pending, active)
  entity Order @ 1 (additive) {
    @key orderId: uuid
    oldStatus: PublicOrderStatus @ 1
    newStatus: PublicOrderStatus @ 2
  }
}
"""
    )
    artifacts = emit_typescript(workspace, tmp_path / "out")
    model = next(a for a in artifacts if a.ref == "orders.Order@1")
    assert 'import { PublicOrderStatus as PublicOrderStatusV1 } from "./orders.PublicOrderStatus.v1";' in model.content
    assert 'import { PublicOrderStatus as PublicOrderStatusV2 } from "./orders.PublicOrderStatus.v2";' in model.content
    assert "oldStatus: PublicOrderStatusV1;" in model.content
    assert "newStatus: PublicOrderStatusV2;" in model.content


def test_projection_typed_fields_alias_same_names_across_domains(tmp_path):
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic Status @ 1 (additive): enum(pending, active)
  enum projection PublicStatus @ 1
    from Status @ 1
    pick(pending)
  entity Order @ 1 (additive) {
    @key orderId: uuid
    internal: PublicStatus @ 1
    external: billing.PublicStatus @ 1
  }
}
domain billing {
  owner: "billing-team"
  semantic Status @ 1 (additive): enum(pending, active)
  enum projection PublicStatus @ 1
    from Status @ 1
    pick(active)
}
"""
    )
    artifacts = emit_typescript(workspace, tmp_path / "out")
    model = next(a for a in artifacts if a.ref == "orders.Order@1")
    assert 'import { PublicStatus as BillingPublicStatusV1 } from "./billing.PublicStatus.v1";' in model.content
    assert 'import { PublicStatus as OrdersPublicStatusV1 } from "./orders.PublicStatus.v1";' in model.content
    assert "internal: OrdersPublicStatusV1;" in model.content
    assert "external: BillingPublicStatusV1;" in model.content
