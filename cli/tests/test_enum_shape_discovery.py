"""Discovery-only lint for repeated anonymous enum shapes (evolution plan
A1, instruction #1): finds `enum(...)` field types whose exact member set
recurs across the workspace, without asserting the fields represent the
same concept."""

from __future__ import annotations

from pathlib import Path

from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources


def _workspace(source: str):
    return load_workspace_from_sources([WorkspaceDocumentSource(path=Path("a.mdl"), uri="file:///a.mdl", text=source)])


def _enumshape_messages(source: str) -> list[str]:
    workspace = _workspace(source)
    assert not workspace.errors, workspace.errors
    return [warning.message for warning in workspace.warnings if warning.code == "ENUMSHAPE"]


def test_repeated_shape_across_two_models_is_reported() -> None:
    source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: enum(active, blocked, deleted)
  }
  entity OrderHistory @ 1 (additive) {
    @key historyId: uuid
    previousStatus: enum(deleted, blocked, active)
  }
}
"""
    messages = _enumshape_messages(source)

    assert len(messages) == 1
    assert "orders.Order@1.status" in messages[0]
    assert "orders.OrderHistory@1.previousStatus" in messages[0]
    assert "not a claim" in messages[0]


def test_member_order_does_not_prevent_matching() -> None:
    """Shape equality is order-independent -- (a, b, c) and (c, b, a) are
    the same shape for discovery purposes."""
    source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: enum(active, blocked, deleted)
  }
  entity OrderHistory @ 1 (additive) {
    @key historyId: uuid
    previousStatus: enum(deleted, blocked, active)
  }
}
"""
    messages = _enumshape_messages(source)
    assert len(messages) == 1


def test_unique_shape_is_not_reported() -> None:
    source = """
domain orders {
  owner: "orders-team"
  entity Widget @ 1 (additive) {
    @key widgetId: uuid
    color: enum(red, green, blue)
  }
}
"""
    assert _enumshape_messages(source) == []


def test_named_semantic_enum_reference_is_excluded() -> None:
    """A field referencing a `semantic` enum declaration (NamedType/
    EnumRefType) already has a name and its own evolution history -- it
    must not be treated as an anonymous shape, even if a second field
    elsewhere happens to declare an anonymous enum with the same members."""
    source = """
domain orders {
  owner: "orders-team"
  semantic AccountStatus @ 1 (additive): enum(active, blocked, deleted)
  entity Account @ 1 (additive) {
    @key accountId: uuid
    status: AccountStatus @ 1
  }
  entity OtherAccount @ 1 (additive) {
    @key otherAccountId: uuid
    status: AccountStatus @ 1
  }
}
"""
    assert _enumshape_messages(source) == []


def test_shape_inside_array_is_discovered() -> None:
    source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    tags: array<enum(new, sale, featured)>
  }
  entity Product @ 1 (additive) {
    @key productId: uuid
    labels: array<enum(featured, new, sale)>
  }
}
"""
    messages = _enumshape_messages(source)
    assert len(messages) == 1
    assert "orders.Order@1.tags" in messages[0]
    assert "orders.Product@1.labels" in messages[0]


def test_shape_inside_object_field_is_discovered_with_a_dotted_path() -> None:
    source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    shipping: object {
      status: enum(pending, shipped, delivered)
    }
  }
  entity Return @ 1 (additive) {
    @key returnId: uuid
    tracking: object {
      status: enum(delivered, shipped, pending)
    }
  }
}
"""
    messages = _enumshape_messages(source)
    assert len(messages) == 1
    assert "orders.Order@1.shipping.status" in messages[0]
    assert "orders.Return@1.tracking.status" in messages[0]


def test_three_or_more_occurrences_are_all_listed() -> None:
    source = """
domain orders {
  owner: "orders-team"
  entity A @ 1 (additive) {
    @key id: uuid
    status: enum(open, closed)
  }
  entity B @ 1 (additive) {
    @key id: uuid
    status: enum(open, closed)
  }
  entity C @ 1 (additive) {
    @key id: uuid
    status: enum(open, closed)
  }
}
"""
    messages = _enumshape_messages(source)
    assert len(messages) == 1
    assert "3 field(s)" in messages[0]
    assert "orders.A@1.status" in messages[0]
    assert "orders.B@1.status" in messages[0]
    assert "orders.C@1.status" in messages[0]


def test_evolves_declared_version_is_covered_after_expansion() -> None:
    """Discovery runs on the merged, expanded workspace (like the postcard
    binding warning it's modeled on) -- an evolves-declared version's
    anonymous enum fields must be visible to the scan, not just full-form
    ones."""
    source = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: enum(active, blocked)
  }
  entity Order @ 2 (additive) evolves @ 1 {
    add secondaryStatus?: enum(active, blocked)
  }
}
"""
    messages = _enumshape_messages(source)
    assert len(messages) == 1
    assert "orders.Order@1.status" in messages[0]
    assert "orders.Order@2.status" in messages[0]
    assert "orders.Order@2.secondaryStatus" in messages[0]
    assert "3 field(s)" in messages[0]
