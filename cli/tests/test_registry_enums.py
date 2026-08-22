"""Registry integration tests for enum contracts (evolution plan E4): semantic
types and enum projections as immutable snapshot objects with stable
signatures and explicit dependency edges."""

from __future__ import annotations

import json
from pathlib import Path

from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
from modelable.registry.snapshot import diff_snapshot_paths, resolve_workspace_snapshot, verify_snapshot


def _workspace():
    source = """
domain orders {
  owner: "orders-team"

  semantic OrderStatus @ 1 (additive): enum(active, blocked)
  semantic OrderRef @ 1 (additive): OrderStatus @ 1

  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: OrderStatus @ 1
    prior?: orders.OrderStatus @ 1
  }

  enum projection PublicStatus @ 1 (additive)
    from OrderStatus @ 1
    pick(active)
}
"""
    return load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("orders.mdl"), uri="file:///orders.mdl", text=source)]
    )


def test_snapshot_includes_enum_contracts_with_signatures_and_edges(tmp_path):
    workspace = _workspace()
    result = resolve_workspace_snapshot(workspace, tmp_path)

    identities = {
        entry["identity"]: entry for entry in json.loads(result.lock_path.read_text(encoding="utf-8"))["objects"]
    }
    assert "orders.OrderStatus@1" in identities
    assert "orders.OrderRef@1" in identities
    assert "orders.PublicStatus@1" in identities

    status_entry = identities["orders.OrderStatus@1"]
    assert status_entry["kind"] == "semantic"
    ref_entry = identities["orders.OrderRef@1"]
    assert ref_entry["dependencies"] == ["orders.OrderStatus@1"]
    public_entry = identities["orders.PublicStatus@1"]
    assert public_entry["kind"] == "enum_projection"
    assert public_entry["dependencies"] == ["orders.OrderStatus@1"]
    # The model's exact enum references are dependency edges too.
    order_entry = identities["orders.Order@1"]
    assert "OrderStatus@1" in order_entry["dependencies"]
    assert "orders.OrderStatus@1" in order_entry["dependencies"]

    errors = verify_snapshot(tmp_path)
    assert not errors


def test_snapshot_is_deterministic_across_loads(tmp_path):
    first = resolve_workspace_snapshot(_workspace(), tmp_path / "a")
    second = resolve_workspace_snapshot(_workspace(), tmp_path / "b")
    assert first.identities == second.identities
    a = json.loads((tmp_path / "a" / "registry.lock").read_text(encoding="utf-8"))
    b = json.loads((tmp_path / "b" / "registry.lock").read_text(encoding="utf-8"))
    assert a["objects"] == b["objects"]


def test_changing_enum_content_reports_the_identity_as_changed(tmp_path):
    v1 = """
domain orders {
  owner: "orders-team"

  semantic OrderStatus @ 1 (additive): enum(active, blocked)

  enum projection PublicStatus @ 1 (additive)
    from OrderStatus @ 1
    pick(active)
}
"""
    v2 = v1.replace("enum(active, blocked)", "enum(active, blocked, voided)")
    resolve_workspace_snapshot(
        load_workspace_from_sources([WorkspaceDocumentSource(path=Path("o.mdl"), uri="file:///o.mdl", text=v1)]),
        tmp_path,
    )

    candidate = tmp_path / "candidate"
    resolve_workspace_snapshot(
        load_workspace_from_sources([WorkspaceDocumentSource(path=Path("o.mdl"), uri="file:///o.mdl", text=v2)]),
        candidate,
    )
    diff = diff_snapshot_paths(tmp_path, candidate)
    assert not diff.added and not diff.removed
    # Same logical version, different canonical content -> changed, per the
    # existing immutability rule.
    assert any("orders.OrderStatus@1" in key for key in diff.changed)


def test_adding_a_later_enum_version_does_not_change_existing_entries(tmp_path):
    v1 = """
domain orders {
  owner: "orders-team"

  semantic OrderStatus @ 1 (additive): enum(active)

  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: OrderStatus @ 1
  }
}
"""
    v2 = v1.replace(
        "semantic OrderStatus @ 1 (additive): enum(active)",
        "semantic OrderStatus @ 1 (additive): enum(active)\n  semantic OrderStatus @ 2 (additive): enum(active, voided)",
    )
    before = resolve_workspace_snapshot(
        load_workspace_from_sources([WorkspaceDocumentSource(path=Path("o.mdl"), uri="file:///o.mdl", text=v1)]),
        tmp_path,
    )
    after = resolve_workspace_snapshot(
        load_workspace_from_sources([WorkspaceDocumentSource(path=Path("o.mdl"), uri="file:///o.mdl", text=v2)]),
        tmp_path / "after",
    )
    before_entries = {e["identity"]: e for e in json.loads(before.lock_path.read_text(encoding="utf-8"))["objects"]}
    after_entries = {e["identity"]: e for e in json.loads(after.lock_path.read_text(encoding="utf-8"))["objects"]}

    for identity, entry in before_entries.items():
        assert after_entries[identity] == entry
    assert "orders.OrderStatus@2" in after_entries
