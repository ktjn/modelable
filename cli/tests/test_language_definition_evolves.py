"""Go-to-definition on the exact base version inside an `evolves @ N`
header (evolution plan D8)."""

from __future__ import annotations

from modelable.language.definition import definition
from modelable.language.dto import LanguagePosition
from modelable.language.positions import codepoint_to_utf16
from modelable.language.workspace import LanguageDocument, LanguageWorkspace

URI = "file:///orders.mdl"
WORKSPACE_TEXT = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    total: decimal(10, 2)
  }
  entity Order @ 2 (breaking) evolves @ 1 {
    rename total -> amount
    add note?: string
  }
}
""".strip("\n")


def _workspace(text: str = WORKSPACE_TEXT) -> LanguageWorkspace:
    state = LanguageWorkspace()
    state.synchronize(1, (LanguageDocument.from_text(URI, text, 1),))
    return state


def _position_at(text: str, snippet: str, token: str) -> LanguagePosition:
    lines = text.splitlines()
    line = next(index for index, value in enumerate(lines) if snippet in value)
    codepoint = lines[line].index(token)
    return LanguagePosition(line, codepoint_to_utf16(lines[line], codepoint))


def _line_range_text(text: str, location) -> str:
    lines = text.splitlines()
    line = lines[location.range.start.line]
    return line[location.range.start.character : location.range.end.character]


def test_definition_on_base_version_jumps_to_the_base_declaration() -> None:
    state = _workspace()
    position = _position_at(WORKSPACE_TEXT, "evolves @ 1", "1 {")

    result = definition(state, URI, position)

    assert result is not None
    assert result.range.start.line == 2
    assert _line_range_text(WORKSPACE_TEXT, result) == "Order"


def test_definition_chains_through_a_base_that_is_itself_evolved() -> None:
    """v3 evolves @ 2, and v2 itself evolves @ 1 -- jumping from v3's base
    version must land on v2's own (evolves-form) declaration line, not
    require the base to be a full-form declaration."""
    text = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
  }
  entity Order @ 2 (additive) evolves @ 1 {
    add note?: string
  }
  entity Order @ 3 (additive) evolves @ 2 {
    add extra?: string
  }
}
""".strip("\n")
    state = _workspace(text)
    position = _position_at(text, "evolves @ 2", "2 {")

    result = definition(state, URI, position)

    assert result is not None
    lines = text.splitlines()
    assert result.range.start.line == lines.index("  entity Order @ 2 (additive) evolves @ 1 {")


def test_definition_on_own_name_still_resolves_to_the_evolved_declaration() -> None:
    """Regression guard: adding the evolves-header base-version branch must
    not shadow ordinary go-to-definition on the declaration's own name."""
    state = _workspace()
    position = _position_at(WORKSPACE_TEXT, "evolves @ 1", "Order")

    result = definition(state, URI, position)

    assert result is not None
    assert result.range.start.line == 6
