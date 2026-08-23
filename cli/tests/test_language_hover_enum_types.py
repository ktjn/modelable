"""Hover tests for enum-backed semantic declarations and enum projections
(evolution plan E11)."""

from __future__ import annotations

from pathlib import Path

from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
from modelable.language.dto import LanguagePosition
from modelable.language.hover import hover
from modelable.language.positions import codepoint_to_utf16
from modelable.language.workspace import LanguageDocument, LanguageWorkspace
from modelable.llm.context import build_enum_projection_summary, build_semantic_enum_summary

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


def test_hover_on_qualified_enum_ref_field_shows_declaration_summary() -> None:
    state = _workspace()
    position = _position_of(WORKSPACE_TEXT, "status: orders.OrderStatus", "OrderStatus")

    result = hover(state, URI, position)

    assert result is not None
    assert "orders.OrderStatus@1" in result.markdown
    assert "enum(pending, active, done)" in result.markdown


def test_hover_returns_none_for_unrelated_bare_word_before_this_slice_and_after() -> None:
    """Regression guard: a plain field name must never accidentally resolve
    against an enum declaration/projection name that happens to match."""
    state = _workspace()
    position = _position_of(WORKSPACE_TEXT, "@key orderId", "orderId")

    result = hover(state, URI, position)

    assert result is not None
    assert "orders.OrderStatus" not in result.markdown


def test_build_semantic_enum_summary_reports_members_and_change_kind() -> None:
    workspace = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("orders.mdl"), uri=URI, text=WORKSPACE_TEXT)]
    )
    assert not workspace.errors, workspace.errors

    summary = build_semantic_enum_summary(workspace, "orders.OrderStatus@1")

    assert summary == "orders.OrderStatus@1\nchange: additive\nenum(pending, active, done)\nowner: orders-team"


def test_build_enum_projection_summary_reports_source_and_members() -> None:
    workspace = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("orders.mdl"), uri=URI, text=WORKSPACE_TEXT)]
    )
    assert not workspace.errors, workspace.errors

    summary = build_enum_projection_summary(workspace, "orders.PublicStatus@1")

    assert summary == "orders.PublicStatus@1\npick from OrderStatus@1\nmembers: active, done"


def test_build_semantic_enum_summary_reports_unknown_for_missing_version() -> None:
    workspace = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("orders.mdl"), uri=URI, text=WORKSPACE_TEXT)]
    )
    assert not workspace.errors, workspace.errors

    summary = build_semantic_enum_summary(workspace, "orders.OrderStatus@99")

    assert summary == "Unknown semantic enum version: orders.OrderStatus@99"
