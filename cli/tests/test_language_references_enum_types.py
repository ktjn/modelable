"""Find-all-references tests for enum-backed semantic declarations and enum
projections (evolution plan E11)."""

from __future__ import annotations

from modelable.language.dto import LanguagePosition
from modelable.language.positions import codepoint_to_utf16
from modelable.language.references import _references_for_qualified_ref, references
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


def test_references_on_qualified_enum_ref_field_include_declaration_and_use() -> None:
    state = _workspace()
    position = _position_of(WORKSPACE_TEXT, "status: orders.OrderStatus", "OrderStatus")

    result = references(state, URI, position, True)

    assert len(result) == 2
    lines = {location.range.start.line for location in result}
    assert lines == {2, 8}
    declaration = next(location for location in result if location.range.start.line == 2)
    assert _line_range_text(WORKSPACE_TEXT, declaration) == "OrderStatus"
    usage = next(location for location in result if location.range.start.line == 8)
    assert _line_range_text(WORKSPACE_TEXT, usage) == "orders.OrderStatus @ 1"


def test_references_on_qualified_enum_ref_field_excludes_declaration_when_requested() -> None:
    state = _workspace()
    position = _position_of(WORKSPACE_TEXT, "status: orders.OrderStatus", "OrderStatus")

    result = references(state, URI, position, False)

    assert len(result) == 1
    assert result[0].range.start.line == 8


def test_references_for_qualified_enum_projection_ref_finds_its_declaration() -> None:
    """No valid syntax today lets a field reference an enum projection (E3),
    so this exercises the resolver directly rather than through a cursor
    position -- forward-compatible infrastructure for when that lands."""
    state = _workspace()
    semantic_workspace = state.semantic_workspace()
    assert semantic_workspace is not None

    result = _references_for_qualified_ref(semantic_workspace, "orders.PublicStatus@1", True)

    assert len(result) == 1
    assert _line_range_text(WORKSPACE_TEXT, result[0]) == "PublicStatus"


def test_references_scope_tracking_is_not_corrupted_by_an_intervening_semantic_decl() -> None:
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

    result = references(state, URI, position, True)

    assert len(result) == 1
    # Must resolve to Shipment's own orderId field, not Order's (or nothing).
    assert result[0].range.start.line == text.splitlines().index("    orderId: uuid")
