"""Tests for enum projections with pick/omit subset lineage (evolution plan E3)."""

from __future__ import annotations

from pathlib import Path

from modelable.compiler.render import render_mdl
from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
from modelable.parser.ir import EnumProjectionDecl
from modelable.parser.parse import parse_text_to_ir


def _workspace(source: str):
    return load_workspace_from_sources([WorkspaceDocumentSource(path=Path("a.mdl"), uri="file:///a.mdl", text=source)])


SOURCE = """
domain orders {
  owner: "orders-team"

  semantic OrderStatus @ 1 (additive): enum(draft, submitted, approved, rejected, cancelled, deleted)

  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: OrderStatus @ 1
  }

  enum projection PublicOrderStatus @ 1 (additive)
    from OrderStatus @ 1
    pick(submitted, approved, rejected, cancelled)

  enum projection HiddenDrafts @ 1 (additive)
    from OrderStatus @ 1
    omit(draft, deleted)
}
"""


def test_enum_projection_parses_and_round_trips():
    mdl = parse_text_to_ir(SOURCE)
    domain = next(item for item in mdl.domains if item.name == "orders")
    projections = {item.name: item for item in domain.enum_projections}

    public = projections["PublicOrderStatus"]
    assert isinstance(public, EnumProjectionDecl)
    assert public.selection_kind == "pick"
    assert public.selected == ["submitted", "approved", "rejected", "cancelled"]
    assert public.source_name == "OrderStatus"
    assert public.source_version == 1
    assert public.has_version_header and public.has_change_kind

    rendered = render_mdl(mdl)
    reparsed = parse_text_to_ir(rendered)
    redomain = next(item for item in reparsed.domains if item.name == "orders")
    assert [item.model_dump() for item in redomain.enum_projections] == [
        item.model_dump() for item in domain.enum_projections
    ]


def test_pick_normalizes_to_exact_source_member_identities():
    workspace = _workspace(SOURCE)
    assert not [d.message for d in workspace.errors]

    orders = next(domain for domain in workspace.mdl.domains if domain.name == "orders")
    public = next(item for item in orders.enum_projections if item.name == "PublicOrderStatus")
    # Ordered-independent exact subset of the source version's members.
    assert public.members == ["approved", "cancelled", "rejected", "submitted"]


def test_omit_normalizes_to_the_complement():
    workspace = _workspace(SOURCE)
    orders = next(domain for domain in workspace.mdl.domains if domain.name == "orders")
    hidden = next(item for item in orders.enum_projections if item.name == "HiddenDrafts")
    assert hidden.members == ["approved", "cancelled", "rejected", "submitted"]


def test_distinct_identity_for_identical_subsets():
    source = """
domain orders {
  owner: "orders-team"

  semantic OrderStatus @ 1 (additive): enum(draft, approved)

  enum projection A @ 1 (additive)
    from OrderStatus @ 1
    pick(approved)

  enum projection B @ 1 (additive)
    from OrderStatus @ 1
    omit(draft)
}
"""
    workspace = _workspace(source)
    assert not [d.message for d in workspace.errors]

    orders = next(domain for domain in workspace.mdl.domains if domain.name == "orders")
    by_name = {item.name: item for item in orders.enum_projections}
    # Same resulting subset, but both remain distinct nominal declarations.
    assert by_name["A"].members == ["approved"] == by_name["B"].members


def test_pick_does_not_grow_when_a_later_source_version_adds_members():
    source = """
domain orders {
  owner: "orders-team"

  semantic OrderStatus @ 1 (additive): enum(draft, approved)
  semantic OrderStatus @ 2 (additive): enum(draft, approved, voided)

  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: OrderStatus @ 2
  }

  enum projection PinnedPublic @ 1 (additive)
    from OrderStatus @ 1
    pick(approved)
}
"""
    workspace = _workspace(source)
    assert not [d.message for d in workspace.errors if "ENUMPROJ" in d.code]

    orders = next(domain for domain in workspace.mdl.domains if domain.name == "orders")
    pinned = next(item for item in orders.enum_projections if item.name == "PinnedPublic")
    assert pinned.members == ["approved"]


def test_omit_rebase_includes_newly_added_source_member():
    source = """
domain orders {
  owner: "orders-team"

  semantic OrderStatus @ 1 (additive): enum(draft, approved)
  semantic OrderStatus @ 2 (additive): enum(draft, approved, voided)

  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: OrderStatus @ 2
  }

  enum projection NoDrafts @ 1 (additive)
    from OrderStatus @ 2
    omit(draft)
}
"""
    workspace = _workspace(source)
    orders = next(domain for domain in workspace.mdl.domains if domain.name == "orders")
    no_drafts = next(item for item in orders.enum_projections if item.name == "NoDrafts")
    # The rebase onto v2 implicitly includes the new 'voided' member — E5 will
    # report this as an implicit member addition; here the normalized set must
    # simply be exact.
    assert no_drafts.members == ["approved", "voided"]


def test_unknown_pick_member_is_rejected():
    source = SOURCE.replace(
        "pick(submitted, approved, rejected, cancelled)",
        "pick(submitted, approved, vanished)",
    )
    workspace = _workspace(source)
    messages = [d.message for d in workspace.errors]
    assert any("vanished" in message and "missing from" in message for message in messages), messages


def test_empty_omit_result_is_rejected():
    source = """
domain orders {
  owner: "orders-team"

  semantic OrderStatus @ 1 (additive): enum(draft)

  enum projection Everything @ 1 (additive)
    from OrderStatus @ 1
    omit(draft)
}
"""
    workspace = _workspace(source)
    messages = [d.message for d in workspace.errors]
    assert any("empty member set" in message for message in messages), messages


def test_repeated_selection_is_rejected():
    source = SOURCE.replace(
        "pick(submitted, approved, rejected, cancelled)",
        "pick(submitted, submitted)",
    )
    workspace = _workspace(source)
    messages = [d.message for d in workspace.errors]
    assert any("more than once" in message and "submitted" in message for message in messages), messages


def test_wrong_source_kind_is_rejected():
    source = """
domain orders {
  owner: "orders-team"

  semantic CustomerId @ 1 (additive): string

  enum projection BadSource @ 1 (additive)
    from CustomerId @ 1
    pick(x)
}
"""
    workspace = _workspace(source)
    messages = [d.message for d in workspace.errors]
    assert any("enum-backed" in message for message in messages), messages


def test_unknown_source_is_rejected():
    source = SOURCE.replace("from OrderStatus @ 1\n    pick", "from NoSuchEnum @ 1\n    pick")
    workspace = _workspace(source)
    messages = [d.message for d in workspace.errors]
    assert any("NoSuchEnum" in message for message in messages), messages


def test_namespace_collision_with_semantic_type_is_rejected():
    source = """
domain orders {
  owner: "orders-team"

  semantic OrderStatus @ 1 (additive): enum(draft, approved)

  enum projection OrderStatus @ 1 (additive)
    from OrderStatus @ 1
    pick(approved)
}
"""
    workspace = _workspace(source)
    messages = [d.message for d in workspace.errors]
    assert any("collides with a semantic type" in message for message in messages), messages


def test_duplicate_enum_projection_declaration_is_rejected():
    source = """
domain orders {
  owner: "orders-team"

  semantic OrderStatus @ 1 (additive): enum(draft, approved)

  enum projection Public @ 1 (additive)
    from OrderStatus @ 1
    pick(approved)

  enum projection Public @ 1 (additive)
    from OrderStatus @ 1
    pick(approved)
}
"""
    workspace = _workspace(source)
    messages = [d.message for d in workspace.errors]
    assert any("orders.Public@1" in message and "more than once" in message for message in messages), messages


def test_model_name_collision_is_rejected():
    source = """
domain orders {
  owner: "orders-team"

  semantic OrderStatus @ 1 (additive): enum(draft, approved)

  entity Public @ 1 (additive) {
    @key publicId: uuid
  }

  enum projection Public @ 1 (additive)
    from OrderStatus @ 1
    pick(approved)
}
"""
    workspace = _workspace(source)
    messages = [d.message for d in workspace.errors]
    assert any("enum projection 'Public' collides with a model of the same name" in message for message in messages), (
        messages
    )


def test_non_positive_version_header_is_rejected():
    source = """
domain orders {
  owner: "orders-team"

  semantic OrderStatus @ 1 (additive): enum(draft, approved)

  enum projection Zero @ 0
    from OrderStatus @ 1
    pick(approved)
}
"""
    workspace = _workspace(source)
    messages = [d.message for d in workspace.errors]
    assert any("version must be positive" in message for message in messages), messages
