"""Rename tests for enum-backed semantic declarations and enum projections
(evolution plan E11)."""

from __future__ import annotations

from modelable.language.dto import LanguagePosition
from modelable.language.positions import codepoint_to_utf16
from modelable.language.rename import prepare_rename, rename
from modelable.language.workspace import LanguageDocument, LanguageWorkspace

URI = "file:///orders.mdl"
WORKSPACE_TEXT = """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  enum projection PublicStatus @ 1 (additive)
    from OrderStatus @ 1
    pick(active, done)
  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: orders.OrderStatus @ 1
  }
}
""".strip("\n")


def _workspace(text: str = WORKSPACE_TEXT) -> LanguageWorkspace:
    state = LanguageWorkspace()
    state.synchronize(1, (LanguageDocument.from_text(URI, text, 1),))
    return state


def _position_of(text: str, snippet: str, token: str) -> LanguagePosition:
    lines = text.splitlines()
    line = next(index for index, value in enumerate(lines) if snippet in value)
    codepoint = lines[line].index(token) + 1
    return LanguagePosition(line, codepoint_to_utf16(lines[line], codepoint))


def test_rename_on_qualified_enum_ref_field_updates_declaration_and_usage() -> None:
    state = _workspace()
    position = _position_of(WORKSPACE_TEXT, "status: orders.OrderStatus", "OrderStatus")

    edit = rename(state, URI, position, "OrderState")

    assert len(edit.edits) == 2
    lines = {item.range.start.line for item in edit.edits}
    assert lines == {2, 8}
    assert all(item.new_text == "OrderState" for item in edit.edits)


def test_prepare_rename_on_semantic_declaration_own_name_returns_placeholder() -> None:
    state = _workspace()
    position = _position_of(WORKSPACE_TEXT, "semantic OrderStatus", "OrderStatus")

    result = prepare_rename(state, URI, position)

    assert result is not None
    assert result.placeholder == "OrderStatus"
    assert result.range.start.line == 2


def test_rename_on_semantic_declaration_own_name_updates_declaration_and_field_usage() -> None:
    state = _workspace()
    position = _position_of(WORKSPACE_TEXT, "semantic OrderStatus", "OrderStatus")

    edit = rename(state, URI, position, "OrderState")

    assert len(edit.edits) == 2
    lines = {item.range.start.line for item in edit.edits}
    assert lines == {2, 8}
    assert all(item.new_text == "OrderState" for item in edit.edits)


def test_rename_on_enum_projection_declaration_own_name_updates_declaration() -> None:
    state = _workspace()
    position = _position_of(WORKSPACE_TEXT, "enum projection PublicStatus", "PublicStatus")

    edit = rename(state, URI, position, "PublicStatus2")

    assert len(edit.edits) == 1
    assert edit.edits[0].range.start.line == 3
    assert edit.edits[0].new_text == "PublicStatus2"


def test_rename_scope_tracking_is_not_corrupted_by_an_intervening_semantic_decl() -> None:
    """Regression guard: extending _DECL_PATTERN to recognize `semantic` must
    not make _current_scope treat a semantic declaration as an enclosing
    model scope for unrelated bare-word field lookups."""
    text = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
  }
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Shipment @ 1 (additive) {
    @key shipmentId: uuid
    orderId: uuid
  }
}
""".strip("\n")
    state = _workspace(text)
    position = _position_of(text, "    orderId: uuid", "orderId")

    edit = rename(state, URI, position, "orderRef")

    assert len(edit.edits) == 1
    # Must resolve to Shipment's own orderId field, not Order's.
    assert edit.edits[0].range.start.line == text.splitlines().index("    orderId: uuid")
