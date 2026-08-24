"""Member-name completion inside `pick(...)`/`omit(...)` clauses of an enum
projection, resolved against the exact source semantic-type version
(evolution plan E11)."""

from __future__ import annotations

from modelable.language.completion import complete
from modelable.language.dto import LanguagePosition
from modelable.language.workspace import LanguageDocument, LanguageWorkspace

URI = "file:///orders.mdl"
BASE_TEXT = """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  enum projection PublicStatus @ 1 (additive)
    from OrderStatus @ 1
    pick(active)
}
""".strip("\n")


def _completions_for(base_text: str, edited_text: str, snippet: str) -> tuple:
    state = LanguageWorkspace()
    state.synchronize(1, (LanguageDocument.from_text(URI, base_text, 1),))
    state.synchronize(2, (LanguageDocument.from_text(URI, edited_text, 2),))
    lines = edited_text.splitlines()
    line = next(index for index, value in enumerate(lines) if snippet in value)
    return complete(state, URI, LanguagePosition(line, len(lines[line])))


def test_completion_inside_pick_offers_unselected_members() -> None:
    text = BASE_TEXT.replace("pick(active)", "pick(")

    result = _completions_for(BASE_TEXT.replace("pick(active)", "pick(active, done)"), text, "pick(")

    assert [item.label for item in result] == ["pending", "active", "done"]
    assert all(item.kind == "value" for item in result)


def test_completion_inside_pick_excludes_already_selected_members() -> None:
    text = BASE_TEXT.replace("pick(active)", "pick(active, ")

    result = _completions_for(BASE_TEXT, text, "pick(active, ")

    assert [item.label for item in result] == ["pending", "done"]


def test_completion_inside_pick_filters_by_prefix() -> None:
    text = BASE_TEXT.replace("pick(active)", "pick(active, d")

    result = _completions_for(BASE_TEXT, text, "pick(active, d")

    assert [item.label for item in result] == ["done"]


def test_completion_inside_omit_offers_source_members() -> None:
    text = BASE_TEXT.replace("pick(active)", "omit(")

    result = _completions_for(BASE_TEXT.replace("pick(active)", "omit(pending)"), text, "omit(")

    assert [item.label for item in result] == ["pending", "active", "done"]


def test_completion_resolves_the_correct_source_when_multiple_projections_exist() -> None:
    text = """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  semantic ShipStatus @ 1 (additive): enum(queued, shipped)
  enum projection PublicOrderStatus @ 1 (additive)
    from OrderStatus @ 1
    pick(active)
  enum projection PublicShipStatus @ 1 (additive)
    from ShipStatus @ 1
    pick(
}
""".strip("\n")
    base = text.replace("pick(\n}", "pick(queued)\n}")

    state = LanguageWorkspace()
    state.synchronize(1, (LanguageDocument.from_text(URI, base, 1),))
    state.synchronize(2, (LanguageDocument.from_text(URI, text, 2),))
    lines = text.splitlines()
    line = next(index for index, value in enumerate(lines) if value == "    pick(")
    result = complete(state, URI, LanguagePosition(line, len(lines[line])))

    assert [item.label for item in result] == ["queued", "shipped"]


def test_completion_inside_pick_returns_empty_when_source_cannot_resolve() -> None:
    text = """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  enum projection PublicStatus @ 1 (additive)
    from Unknown @ 1
    pick(
}
""".strip("\n")
    base = text.replace("    from Unknown @ 1\n    pick(\n}", "    from OrderStatus @ 1\n    pick(active)\n}")

    result = _completions_for(base, text, "    pick(")

    assert result == ()
