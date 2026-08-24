"""Find-references for field names inside `remove`/`rename`/`replace`
operations of an `evolves @ N` block (evolution plan D8): a field name
referenced there resolves to the same field as its base-version
declaration, distinct from the literal `remove`/`rename`/`replace`
*operation* keyword next to it."""

from __future__ import annotations

from modelable.language.dto import LanguagePosition
from modelable.language.positions import codepoint_to_utf16
from modelable.language.references import references
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
    remove total
  }
  projection OrderSummary @ 1
    from orders.Order @ 1 as o
  {
    total <- o.total
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
    codepoint = lines[line].index(token) + 1
    return LanguagePosition(line, codepoint_to_utf16(lines[line], codepoint))


def test_references_on_remove_argument_include_base_declaration_and_projection_usage() -> None:
    state = _workspace()
    position = _position_at(WORKSPACE_TEXT, "remove total", "total")

    result = references(state, URI, position, include_declaration=True)

    assert len(result) == 3
    lines = WORKSPACE_TEXT.splitlines()
    result_lines = {location.range.start.line for location in result}
    assert lines.index("    total: decimal(10, 2)") in result_lines
    assert lines.index("    remove total") in result_lines
    assert lines.index("    total <- o.total") in result_lines


def test_references_without_declaration_excludes_the_base_field_declaration() -> None:
    state = _workspace()
    position = _position_at(WORKSPACE_TEXT, "remove total", "total")

    with_decl = references(state, URI, position, include_declaration=True)
    without_decl = references(state, URI, position, include_declaration=False)

    assert len(without_decl) == len(with_decl) - 1


def test_references_on_rename_source_argument_finds_the_base_declaration() -> None:
    text = WORKSPACE_TEXT.replace("remove total", "rename total -> amount")
    state = _workspace(text)
    position = _position_at(text, "rename total", "total")

    result = references(state, URI, position, include_declaration=True)

    lines = text.splitlines()
    result_lines = {location.range.start.line for location in result}
    assert lines.index("    total: decimal(10, 2)") in result_lines
    assert lines.index("    rename total -> amount") in result_lines


def test_references_on_replace_argument_finds_the_base_declaration() -> None:
    text = WORKSPACE_TEXT.replace("remove total", "replace total: decimal(12, 2)")
    state = _workspace(text)
    position = _position_at(text, "replace total", "total")

    result = references(state, URI, position, include_declaration=True)

    lines = text.splitlines()
    result_lines = {location.range.start.line for location in result}
    assert lines.index("    total: decimal(10, 2)") in result_lines
    assert lines.index("    replace total: decimal(12, 2)") in result_lines


def test_references_on_the_rename_target_name_are_not_treated_as_the_source_field() -> None:
    """`rename total -> amount` -- clicking the *new* name `amount` must not
    be confused with the source field `total`; `amount` doesn't exist as a
    field anywhere yet at this point in the sequence."""
    text = WORKSPACE_TEXT.replace("remove total", "rename total -> amount")
    state = _workspace(text)
    position = _position_at(text, "rename total", "amount")

    result = references(state, URI, position, include_declaration=True)

    assert result == ()
