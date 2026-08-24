"""Editor symbol-rename on a field name inside `remove`/`rename`/`replace`
operations of an `evolves @ N` block (evolution plan D8): renaming the
field updates its base-version declaration, every operation line across
this model's evolves blocks that mentions it, and any projection usages
pinned to the base version -- distinct from the literal `rename` *operation*
keyword, which is never itself a renamable symbol."""

from __future__ import annotations

from modelable.language.dto import LanguagePosition
from modelable.language.positions import codepoint_to_utf16
from modelable.language.rename import InvalidRenameError, prepare_rename, rename
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


def test_prepare_rename_on_remove_argument_offers_the_field_name() -> None:
    state = _workspace()
    position = _position_at(WORKSPACE_TEXT, "remove total", "total")

    result = prepare_rename(state, URI, position)

    assert result is not None
    assert result.placeholder == "total"


def test_rename_on_remove_argument_updates_base_declaration_operation_and_projection() -> None:
    state = _workspace()
    position = _position_at(WORKSPACE_TEXT, "remove total", "total")

    edit = rename(state, URI, position, "grandTotal")

    lines = WORKSPACE_TEXT.splitlines()
    edited_line_numbers = {text_edit.range.start.line for text_edit in edit.edits}
    assert edited_line_numbers == {
        lines.index("    total: decimal(10, 2)"),
        lines.index("    remove total"),
        lines.index("    total <- o.total"),
    }
    assert all(text_edit.new_text == "grandTotal" for text_edit in edit.edits)


def test_rename_on_rename_source_argument_updates_the_base_declaration() -> None:
    text = WORKSPACE_TEXT.replace("remove total", "rename total -> amount")
    state = _workspace(text)
    position = _position_at(text, "rename total", "total")

    edit = rename(state, URI, position, "grandTotal")

    lines = text.splitlines()
    edited_line_numbers = {text_edit.range.start.line for text_edit in edit.edits}
    assert lines.index("    total: decimal(10, 2)") in edited_line_numbers
    assert lines.index("    rename total -> amount") in edited_line_numbers


def test_rename_leaves_the_rename_targets_new_name_untouched() -> None:
    """Renaming the source field `total` in `rename total -> amount` must
    not touch the literal `amount` token -- that is a fresh name being
    introduced, not a reference to the field being renamed."""
    text = WORKSPACE_TEXT.replace("remove total", "rename total -> amount")
    state = _workspace(text)
    position = _position_at(text, "rename total", "total")

    edit = rename(state, URI, position, "grandTotal")

    rewritten_texts = {text_edit.new_text for text_edit in edit.edits}
    assert rewritten_texts == {"grandTotal"}
    line_no = next(i for i, value in enumerate(text.splitlines()) if "rename total -> amount" in value)
    rename_line_edits = [text_edit for text_edit in edit.edits if text_edit.range.start.line == line_no]
    assert len(rename_line_edits) == 1
    assert rename_line_edits[0].range.start.character < text.splitlines()[line_no].index("amount")


def test_rename_on_the_literal_rename_keyword_is_unsupported() -> None:
    """The `rename` keyword itself (the operation, not a field) is never a
    renamable symbol."""
    text = WORKSPACE_TEXT.replace("remove total", "rename total -> amount")
    state = _workspace(text)
    position = _position_at(text, "rename total", "rename")

    try:
        rename(state, URI, position, "grandTotal")
    except InvalidRenameError:
        return
    raise AssertionError("expected InvalidRenameError")
