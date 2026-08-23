"""Go-to-definition tests for enum-backed semantic declarations and enum
projections (evolution plan E11)."""

from __future__ import annotations

from modelable.language.definition import _definition_for_qualified_ref, definition
from modelable.language.dto import LanguagePosition
from modelable.language.positions import codepoint_to_utf16
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


def _line_range_text(text: str, location) -> str:
    lines = text.splitlines()
    line = lines[location.range.start.line]
    return line[location.range.start.character : location.range.end.character]


def test_definition_on_qualified_enum_ref_field_jumps_to_semantic_declaration() -> None:
    state = _workspace()
    position = _position_of(WORKSPACE_TEXT, "status: orders.OrderStatus", "OrderStatus")

    result = definition(state, URI, position)

    assert result is not None
    assert result.range.start.line == 2
    assert _line_range_text(WORKSPACE_TEXT, result) == "OrderStatus"


def test_definition_for_qualified_enum_projection_ref_jumps_to_its_declaration() -> None:
    """No valid syntax today lets a field reference an enum projection (E3),
    so this exercises the resolver directly rather than through a cursor
    position -- forward-compatible infrastructure for when that lands."""
    state = _workspace()
    semantic_workspace = state.semantic_workspace()
    assert semantic_workspace is not None

    result = _definition_for_qualified_ref(semantic_workspace, "orders.PublicStatus@1")

    assert result is not None
    assert _line_range_text(WORKSPACE_TEXT, result) == "PublicStatus"


def test_definition_scope_tracking_is_not_corrupted_by_an_intervening_semantic_decl() -> None:
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

    result = definition(state, URI, position)

    assert result is not None
    assert _line_range_text(text, result) == "orderId"
    # Must resolve to Shipment's own orderId field, not Order's (or nothing).
    assert result.range.start.line == text.splitlines().index("    orderId: uuid")
