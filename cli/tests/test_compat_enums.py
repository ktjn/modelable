"""Declaration-level enum compatibility tests (evolution plan E5)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from modelable.compat.checker import check_model_version_compatibility
from modelable.compat.diff import compare_model_versions, is_field_change_breaking
from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources


def _workspace(source: str):
    return load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("orders.mdl"), uri="file:///orders.mdl", text=source)]
    )


ADDITIVE_SOURCE = """
domain orders {
  owner: "orders-team"

  semantic OrderStatus @ 1 (additive): enum(draft, approved)
  semantic OrderStatus @ 2 (additive): enum(draft, approved, voided)

  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: OrderStatus @ 1
  }

  entity Order @ 2 (additive) {
    @key orderId: uuid
    status: OrderStatus @ 2
  }
}
"""

REMOVING_SOURCE = ADDITIVE_SOURCE.replace(
    "semantic OrderStatus @ 2 (additive): enum(draft, approved, voided)",
    "semantic OrderStatus @ 2 (breaking): enum(draft, voided)",
)


def test_member_addition_is_additive_with_exhaustive_consumer_consequence():
    workspace = _workspace(ADDITIVE_SOURCE)
    report = check_model_version_compatibility(workspace.mdl, "orders", "Order", 1, 2)

    assert report.status == "compatible"
    change = next(c for c in report.changes if c.kind == "enum_version_changed")
    assert is_field_change_breaking(change) is False
    assert "adds member 'voided'" in change.note
    assert "exhaustive consumers" in change.note
    assert any("adds member 'voided'" in finding for finding in report.findings)


def test_member_removal_through_a_version_bump_is_breaking():
    workspace = _workspace(REMOVING_SOURCE)
    report = check_model_version_compatibility(workspace.mdl, "orders", "Order", 1, 2)

    assert report.status == "breaking"
    change = next(c for c in report.changes if c.kind == "enum_version_changed")
    assert is_field_change_breaking(change) is True
    assert "removes member 'approved'" in change.note
    assert any("removes member 'approved'" in finding for finding in report.findings)


def test_projection_typed_field_version_bump_reports_projection_cause():
    source = """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, paid, shipped)

  enum projection PublicStatus @ 1 (additive)
    from OrderStatus @ 1
    pick(pending, paid)
  enum projection PublicStatus @ 2 (breaking)
    from OrderStatus @ 1
    pick(pending)

  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: PublicStatus @ 1
  }
  entity Order @ 2 (breaking) {
    @key orderId: uuid
    status: PublicStatus @ 2
  }
}
"""
    workspace = _workspace(source)
    report = check_model_version_compatibility(workspace.mdl, "orders", "Order", 1, 2)

    change = next(c for c in report.changes if c.kind == "enum_version_changed")
    assert change.breaking_override is True
    assert "projection removes member 'paid'" in change.note


def test_mixed_semantic_and_projection_replacement_is_explicitly_breaking():
    source = """
domain orders {
  owner: "orders-team"
  semantic Status @ 1 (additive): enum(active)
  enum projection PublicStatus @ 1 (additive)
    from Status @ 1
    pick(active)
  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: Status @ 1
  }
  entity Order @ 2 (breaking) {
    @key orderId: uuid
    status: PublicStatus @ 1
  }
}
"""
    workspace = _workspace(source)
    report = check_model_version_compatibility(workspace.mdl, "orders", "Order", 1, 2)

    change = next(c for c in report.changes if c.kind == "enum_reference_changed")
    assert change.breaking_override is True
    assert "semantic enum and an enum projection" in change.note


def test_nominal_replacement_is_breaking_even_with_identical_members():
    source = """
domain orders {
  owner: "orders-team"

  semantic OrderStatus @ 1 (additive): enum(active, blocked)
  semantic FulfilmentState @ 1 (additive): enum(active, blocked)

  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: OrderStatus @ 1
  }

  entity Order @ 2 (breaking) {
    @key orderId: uuid
    status: FulfilmentState @ 1
  }
}
"""
    workspace = _workspace(source)
    report = check_model_version_compatibility(workspace.mdl, "orders", "Order", 1, 2)

    assert report.status == "breaking"
    change = next(c for c in report.changes if c.kind == "enum_reference_changed")
    assert is_field_change_breaking(change) is True


def test_anonymous_enums_keep_conservative_enum_changed_behavior():
    source = """
domain orders {
  owner: "orders-team"

  entity Order @ 1 (additive) {
    @key orderId: uuid
    state: enum(active, blocked)
  }

  entity Order @ 2 (breaking) {
    @key orderId: uuid
    state: enum(active, blocked, voided)
  }
}
"""
    workspace = _workspace(source)
    changes = compare_model_versions(
        next(v for v in workspace.mdl.domains[0].models["Order"] if v.version == 1),
        next(v for v in workspace.mdl.domains[0].models["Order"] if v.version == 2),
    )
    kinds = [change.kind for change in changes]
    assert "enum_changed" in kinds
    changed = next(change for change in changes if change.kind == "enum_changed")
    assert is_field_change_breaking(changed) is True


def test_declaration_level_diff_classifies_additions_and_removals():
    workspace = _workspace(ADDITIVE_SOURCE)
    from modelable.compat.enums import compare_semantic_enum_versions

    domain = next(item for item in workspace.mdl.domains if item.name == "orders")
    v1 = next(item for item in domain.semantic_types if item.name == "OrderStatus" and item.version == 1)
    v2 = next(item for item in domain.semantic_types if item.name == "OrderStatus" and item.version == 2)

    changes = compare_semantic_enum_versions(v1, v2)
    assert [(c.kind, c.member, c.breaking) for c in changes] == [
        ("enum_member_added", "voided", False),
    ]
    assert changes[0].consequences == ("exhaustive_match",)


def test_projection_diff_distinguishes_explicit_and_implicit_growth():
    from modelable.compat.enums import compare_enum_projections

    pick_v1 = """
domain orders {
  owner: "o"
  semantic S @ 1 (additive): enum(a, b)
  semantic S @ 2 (additive): enum(a, b, c)

  enum projection P @ 1 (additive)
    from S @ 1
    pick(a)

  enum projection P @ 2 (additive)
    from S @ 2
    pick(a)
}
"""
    workspace = _workspace(pick_v1)
    domain = workspace.mdl.domains[0]
    p1, p2 = domain.enum_projections[0], domain.enum_projections[1]

    # The pinned pick stays identical across the source bump.
    assert compare_enum_projections("orders.S", p1, p1) == []
    explicit = compare_enum_projections("orders.S", p1, p2)
    assert [(c.kind, c.member) for c in explicit] == [("enum_projection_source_changed", None)]

    omit_v1 = """
domain orders {
  owner: "o"
  semantic S @ 1 (additive): enum(a, b)
  semantic S @ 2 (additive): enum(a, b, c)

  enum projection Q @ 1 (additive)
    from S @ 1
    omit(b)

  enum projection Q @ 2 (additive)
    from S @ 2
    omit(b)
}
"""
    workspace = _workspace(omit_v1)
    domain = workspace.mdl.domains[0]
    q1, q2 = domain.enum_projections[0], domain.enum_projections[1]

    implicit = compare_enum_projections("orders.S", q1, q2)
    kinds = {(c.kind, c.member) for c in implicit}
    assert ("enum_projection_implicit_member_added", "c") in kinds
    growth = next(c for c in implicit if c.member == "c")
    assert growth.consequences == ("implicit_growth",)
    assert growth.breaking is False


def test_projection_member_removal_is_breaking():
    source = """
domain orders {
  owner: "o"
  semantic S @ 1 (additive): enum(a, b)

  enum projection P @ 1 (additive)
    from S @ 1
    pick(a)

  enum projection P @ 2 (breaking)
    from S @ 1
    pick(a, b)
}
"""
    workspace = _workspace(source)
    domain = workspace.mdl.domains[0]
    p1, p2 = domain.enum_projections[0], domain.enum_projections[1]

    from modelable.compat.enums import compare_enum_projections

    changes = compare_enum_projections("orders.S", p1, p2)
    removed = [c for c in changes if c.kind == "enum_projection_member_removed"]
    assert not removed
    added = [c for c in changes if c.kind == "enum_projection_member_added"]
    assert [(c.member, c.breaking) for c in added] == [("b", False)]


def test_replace_helper_keeps_frozen_dataclass_semantics():

    from modelable.compat.diff import FieldChange, is_field_change_breaking

    original = FieldChange(kind="enum_version_changed", field_name="status", breaking_override=None)
    refined = replace(original, breaking_override=False, note="adds member 'x'")
    assert is_field_change_breaking(refined) is False
    assert is_field_change_breaking(original) is True
