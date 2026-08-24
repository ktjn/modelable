"""Operation-aware field-name completion inside `evolves @ N` blocks
(evolution plan D8): `remove`/`rename`/`replace` propose fields from the
*intermediate* expansion state at that point in the operation sequence, not
only the base version's original fields or the fully expanded final
version."""

from __future__ import annotations

from modelable.language.completion import complete
from modelable.language.dto import LanguagePosition
from modelable.language.workspace import LanguageDocument, LanguageWorkspace

URI = "file:///orders.mdl"
BASE_TEXT = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    total: decimal(10, 2)
  }
  entity Order @ 2 (breaking) evolves @ 1 {
    add note?: string
    remove note
    rename total -> amount
  }
}
""".strip("\n")


def _completions_for(base_text: str, edited_text: str, snippet: str) -> tuple:
    state = LanguageWorkspace()
    state.synchronize(1, (LanguageDocument.from_text(URI, base_text, 1),))
    state.synchronize(2, (LanguageDocument.from_text(URI, edited_text, 2),))
    lines = edited_text.splitlines()
    line = next(index for index, value in enumerate(lines) if snippet in value)
    col = lines[line].index(snippet) + len(snippet)
    return complete(state, URI, LanguagePosition(line, col))


def test_remove_offers_fields_added_earlier_in_the_same_block() -> None:
    edited = BASE_TEXT.replace("remove note", "remove ")

    result = _completions_for(BASE_TEXT, edited, "remove ")

    assert {item.label for item in result} == {"orderId", "total", "note"}
    assert all(item.kind == "property" for item in result)


def test_remove_does_not_offer_the_final_versions_renamed_field() -> None:
    """`amount` only exists after the later `rename` operation runs -- at the
    `remove` operation's point in the sequence it must not be offered."""
    edited = BASE_TEXT.replace("remove note", "remove ")

    result = _completions_for(BASE_TEXT, edited, "remove ")

    assert "amount" not in {item.label for item in result}


def test_rename_source_reflects_fields_removed_earlier_in_the_block() -> None:
    """By the `rename` operation, the earlier `remove note` has already run,
    so `note` must not be offered as a rename source."""
    edited = BASE_TEXT.replace("rename total -> amount", "rename t")

    result = _completions_for(BASE_TEXT, edited, "rename t")

    assert {item.label for item in result} == {"total"}


def test_replace_offers_the_intermediate_field_set() -> None:
    text = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    total: decimal(10, 2)
  }
  entity Order @ 2 (breaking) evolves @ 1 {
    add note?: string
    replace total: decimal(12, 2)
  }
}
""".strip("\n")
    edited = text.replace("replace total", "replace ")

    result = _completions_for(text, edited, "replace ")

    assert {item.label for item in result} == {"orderId", "total", "note"}


def test_completion_outside_an_evolves_block_is_unaffected() -> None:
    """Regression guard: a plain (non-evolves) model body has no base_version,
    so the operation-aware branch must never trigger there -- a field named
    `remove` still completes normally as an ordinary field declaration."""
    text = """
domain orders {
  owner: "orders-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
  }
}
""".strip("\n")
    edited = text.replace("@key orderId: uuid", "@key orderId: uuid\n    remove")

    result = _completions_for(text, edited, "remove")

    assert result == ()
