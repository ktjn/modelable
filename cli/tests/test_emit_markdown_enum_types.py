"""Markdown emission tests for enum-backed semantic declarations
(evolution plan E10)."""

from __future__ import annotations

from pathlib import Path

from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
from modelable.emitters.markdown import emit_markdown


def _workspace(source: str):
    workspace = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("orders.mdl"), uri="file:///orders.mdl", text=source)]
    )
    assert not workspace.errors, workspace.errors
    return workspace


def test_enum_ref_field_shows_qualified_identity_not_unknown(tmp_path):
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 1 }
}
"""
    )
    artifacts = emit_markdown(workspace, tmp_path / "out")
    content = next(a.content for a in artifacts if a.ref == "orders.Order@1")
    assert "OrderStatus@1" in content
    assert "unknown" not in content.lower().split("status")[1].split("|")[1]


def test_anonymous_enum_is_unaffected(tmp_path):
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) { @key orderId: uuid status: enum(pending, active, done) }
}
"""
    )
    artifacts = emit_markdown(workspace, tmp_path / "out")
    content = next(a.content for a in artifacts if a.ref == "orders.Order@1")
    assert "enum(pending, active, done)" in content
