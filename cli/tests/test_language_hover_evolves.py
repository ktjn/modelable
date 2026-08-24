"""Hover on the exact base version inside an `evolves @ N` header
(evolution plan D8)."""

from __future__ import annotations

from modelable.language.dto import LanguagePosition
from modelable.language.hover import hover
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


def test_hover_on_base_version_shows_the_base_declarations_summary() -> None:
    state = _workspace()
    position = _position_at(WORKSPACE_TEXT, "evolves @ 1", "1 {")

    result = hover(state, URI, position)

    assert result is not None
    assert "orders.Order@1" in result.markdown
    assert "total: decimal(10, 2)" in result.markdown
    # Must resolve the base (v1), not the evolved declaration itself (v2).
    assert "amount" not in result.markdown


def test_hover_on_own_name_still_shows_the_evolved_declarations_summary() -> None:
    """Regression guard: adding the evolves-header base-version branch must
    not shadow ordinary hover on the declaration's own name."""
    state = _workspace()
    position = _position_at(WORKSPACE_TEXT, "evolves @ 1", "Order")

    result = hover(state, URI, position)

    assert result is not None
    assert "orders.Order@2" in result.markdown
    assert "amount" in result.markdown


def test_hover_on_base_version_returns_none_when_the_base_cannot_resolve() -> None:
    text = """
domain orders {
  owner: "orders-team"
  entity Order @ 2 (breaking) evolves @ 1 {
    add note?: string
  }
}
""".strip("\n")
    state = _workspace(text)
    position = _position_at(text, "evolves @ 1", "1 {")

    result = hover(state, URI, position)

    assert result is None
