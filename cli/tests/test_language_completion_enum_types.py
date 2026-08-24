"""Completion tests for enum-backed semantic declarations and enum
projections (evolution plan E11).

Field type positions reference a domain member directly (e.g. `status:
orders.OrderStatus @ 1`), which previously had no completion support at all
for any reference kind (model, projection, semantic, or enum projection) --
`_alias_field_candidates` only resolved projection-source aliases and
returned nothing otherwise. Extending it to fall back to "alias names an
actual domain" fixes that general gap and, as part of the same change,
surfaces semantic types and enum projections alongside models/projections.
"""

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
    pick(active, done)
  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: uuid
  }
}
""".strip("\n")


def _completions_for(edited_text: str, snippet: str) -> tuple:
    state = LanguageWorkspace()
    state.synchronize(1, (LanguageDocument.from_text(URI, BASE_TEXT, 1),))
    state.synchronize(2, (LanguageDocument.from_text(URI, edited_text, 2),))
    lines = edited_text.splitlines()
    line = next(index for index, value in enumerate(lines) if snippet in value)
    return complete(state, URI, LanguagePosition(line, len(lines[line])))


def test_completion_after_domain_dot_in_field_type_offers_all_domain_members() -> None:
    text = BASE_TEXT.replace("status: uuid", "status: orders.")

    result = _completions_for(text, "status: orders.")

    assert [item.label for item in result] == ["Order", "OrderStatus", "PublicStatus"]
    assert all(item.kind == "class" for item in result)


def test_completion_after_domain_dot_in_field_type_filters_by_prefix() -> None:
    text = BASE_TEXT.replace("status: uuid", "status: orders.Order")

    result = _completions_for(text, "status: orders.Order")

    assert [item.label for item in result] == ["Order", "OrderStatus"]


def test_completion_after_domain_dot_still_returns_empty_for_unknown_domain() -> None:
    text = BASE_TEXT.replace("status: uuid", "status: nosuchdomain.")

    result = _completions_for(text, "status: nosuchdomain.")

    assert result == ()
