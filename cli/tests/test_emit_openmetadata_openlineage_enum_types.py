"""OpenMetadata/OpenLineage emission tests for enum-backed semantic
declarations (evolution plan E10)."""

from __future__ import annotations

from pathlib import Path

from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
from modelable.emitters.openlineage import emit_openlineage
from modelable.emitters.openmetadata import emit_openmetadata


def _workspace(source: str):
    workspace = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("orders.mdl"), uri="file:///orders.mdl", text=source)]
    )
    assert not workspace.errors, workspace.errors
    return workspace


_FIXTURE = """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 1 }
}
"""


def test_openmetadata_enum_ref_field_carries_qualified_identity(tmp_path):
    workspace = _workspace(_FIXTURE)
    artifacts = emit_openmetadata(workspace, tmp_path / "out")
    asset = next(a for a in artifacts if a.ref == "orders.openmetadata" or "openmetadata" in a.artifact_id)
    fields = asset.content["assets"][0]["fields"]
    status = next(f for f in fields if f["name"] == "status")
    assert status["type"] == "enumRef<OrderStatus@1>"
    assert status["type"] != "unknown"


def test_openlineage_enum_ref_field_carries_qualified_identity(tmp_path):
    workspace = _workspace(_FIXTURE)
    artifacts = emit_openlineage(workspace, tmp_path / "out")
    event = next(a for a in artifacts if a.ref == "orders.Order@1")
    fields = event.content["outputs"][0]["facets"]["schema"]["fields"]
    status = next(f for f in fields if f["name"] == "status")
    assert status["type"] == "enumRef<OrderStatus@1>"
    assert status["type"] != "unknown"


def test_openmetadata_and_openlineage_anonymous_enum_is_unaffected(tmp_path):
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) { @key orderId: uuid status: enum(pending, active, done) }
}
"""
    )
    om_asset = next(a for a in emit_openmetadata(workspace, tmp_path / "om") if "openmetadata" in a.artifact_id)
    om_status = next(f for f in om_asset.content["assets"][0]["fields"] if f["name"] == "status")
    assert om_status["type"] == "enum(pending,active,done)"

    ol_event = next(a for a in emit_openlineage(workspace, tmp_path / "ol") if a.ref == "orders.Order@1")
    ol_status = next(f for f in ol_event.content["outputs"][0]["facets"]["schema"]["fields"] if f["name"] == "status")
    assert ol_status["type"] == "enum(pending,active,done)"
