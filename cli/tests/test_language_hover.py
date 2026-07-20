import pytest

from modelable.language.dto import LanguagePosition, LanguageRange
from modelable.language.hover import hover
from modelable.language.positions import codepoint_to_utf16
from modelable.language.workspace import LanguageDocument, LanguageWorkspace

URI = "file:///projection.mdl"
WORKSPACE_TEXT = """
domain sales {
  owner: "sales-team"
  entity Customer @ 1 (additive) {
    @key @pii @classification("confidential") customerId: uuid
    @deprecated(replacedBy: "customerName") legacyName?: string
    customerName: string
  }
}

domain reporting {
  owner: "reporting-team"
  projection CustomerView @ 1
    from sales.Customer @ 1 as c
  {
    id <- c.customerId
    displayName = c.customerName
  }
}
""".strip("\n")


def parsed_language_workspace(text: str = WORKSPACE_TEXT) -> LanguageWorkspace:
    state = LanguageWorkspace()
    state.synchronize(1, (LanguageDocument.from_text(URI, text, 1),))
    return state


def replace_document(
    state: LanguageWorkspace,
    text: str,
) -> tuple[LanguageDocument, ...]:
    return tuple(
        LanguageDocument.from_text(uri, text, document.version + 1) if uri == URI else document
        for uri, document in state.documents.items()
    )


def position_of(text: str, snippet: str, token: str) -> LanguagePosition:
    lines = text.splitlines()
    line = next(index for index, value in enumerate(lines) if snippet in value)
    codepoint = lines[line].index(token) + 1
    return LanguagePosition(line, codepoint_to_utf16(lines[line], codepoint))


def test_hover_uses_last_semantics_for_current_resolvable_text() -> None:
    state = parsed_language_workspace()
    current = WORKSPACE_TEXT.replace(
        "    from sales.Customer @ 1 as c",
        "    😀 from sales.Customer @ 1 as c",
    )
    state.synchronize(2, replace_document(state, current))

    result = hover(
        state,
        URI,
        position_of(current, "😀 from sales.Customer", "Customer"),
    )

    assert result is not None
    assert "sales.Customer@1" in result.markdown
    line = current.splitlines().index("    😀 from sales.Customer @ 1 as c")
    start = codepoint_to_utf16(current.splitlines()[line], 11)
    end = codepoint_to_utf16(current.splitlines()[line], 29)
    assert result.range == LanguageRange.at(line, start, line, end)


def test_hover_on_declaration_shows_identity_and_model_summary() -> None:
    result = hover(
        parsed_language_workspace(),
        URI,
        position_of(WORKSPACE_TEXT, "entity Customer", "Customer"),
    )

    assert result is not None
    assert "sales.Customer@1" in result.markdown
    assert "kind: entity" in result.markdown
    assert "owner: sales-team" in result.markdown


def test_hover_on_field_shows_type_optionality_and_governance_metadata() -> None:
    state = parsed_language_workspace()

    governed = hover(
        state,
        URI,
        position_of(WORKSPACE_TEXT, "customerId: uuid", "customerId"),
    )
    deprecated = hover(
        state,
        URI,
        position_of(WORKSPACE_TEXT, "legacyName?: string", "legacyName"),
    )

    assert governed is not None
    assert "type: uuid" in governed.markdown
    assert "optional: no" in governed.markdown
    assert "key" in governed.markdown
    assert "pii" in governed.markdown
    assert "classification=confidential" in governed.markdown
    assert deprecated is not None
    assert "type: string" in deprecated.markdown
    assert "optional: yes" in deprecated.markdown
    assert "deprecated" in deprecated.markdown
    assert "customerName" in deprecated.markdown


def test_hover_on_projection_field_and_source_field_shows_mapping_and_meaning() -> None:
    state = parsed_language_workspace()

    projection_field = hover(
        state,
        URI,
        position_of(WORKSPACE_TEXT, "displayName = c.customerName", "displayName"),
    )
    source_field = hover(
        state,
        URI,
        position_of(WORKSPACE_TEXT, "displayName = c.customerName", "c.customerName"),
    )

    assert projection_field is not None
    assert "reporting.CustomerView@1.displayName" in projection_field.markdown
    assert "mapping: computed c.customerName" in projection_field.markdown
    assert source_field is not None
    assert "sales.Customer@1.customerName" in source_field.markdown
    assert "type: string" in source_field.markdown


def test_hover_rejects_stale_projection_alias_after_current_rename() -> None:
    state = parsed_language_workspace()
    current = (
        WORKSPACE_TEXT.replace(
            "    from sales.Customer @ 1 as c",
            "    from sales.Customer @ 1 as d",
        )
        + "\ndomain broken {"
    )
    state.synchronize(2, replace_document(state, current))

    result = hover(
        state,
        URI,
        position_of(current, "displayName = c.customerName", "c.customerName"),
    )

    assert result is None


def test_hover_resolves_new_projection_alias_bound_to_same_semantic_source() -> None:
    state = parsed_language_workspace()
    current = (
        WORKSPACE_TEXT.replace(
            "    from sales.Customer @ 1 as c",
            "    from sales.Customer @ 1 as d",
        ).replace(
            "    displayName = c.customerName",
            "    displayName = d.customerName",
        )
        + "\ndomain broken {"
    )
    state.synchronize(2, replace_document(state, current))

    result = hover(
        state,
        URI,
        position_of(current, "displayName = d.customerName", "d.customerName"),
    )

    assert result is not None
    assert "sales.Customer@1.customerName" in result.markdown
    assert "type: string" in result.markdown


@pytest.mark.parametrize("join_keyword", ["join", "left join"])
def test_hover_resolves_current_join_alias(join_keyword: str) -> None:
    text = WORKSPACE_TEXT.replace(
        "    from sales.Customer @ 1 as c",
        f"    from sales.Customer @ 1 as c\n    {join_keyword} sales.Customer @ 1 as d on c.customerId == d.customerId",
    ).replace(
        "    displayName = c.customerName",
        "    displayName = d.customerName",
    )

    result = hover(
        parsed_language_workspace(text),
        URI,
        position_of(text, "displayName = d.customerName", "d.customerName"),
    )

    assert result is not None
    assert "sales.Customer@1.customerName" in result.markdown
    assert "type: string" in result.markdown


def test_hover_resolves_same_line_source_clause_with_noncanonical_whitespace() -> None:
    text = WORKSPACE_TEXT.replace(
        "  projection CustomerView @ 1\n    from sales.Customer @ 1 as c\n  {",
        "  projection CustomerView @ 1   from   sales . Customer @1   as c   {",
    )

    result = hover(
        parsed_language_workspace(text),
        URI,
        position_of(text, "displayName = c.customerName", "c.customerName"),
    )

    assert result is not None
    assert "sales.Customer@1.customerName" in result.markdown
    assert "type: string" in result.markdown


def test_hover_does_not_bind_alias_from_line_comment() -> None:
    state = parsed_language_workspace()
    current = (
        WORKSPACE_TEXT.replace(
            "    from sales.Customer @ 1 as c",
            "    from sales.Customer @ 1 as d",
        ).replace(
            "    id <- c.customerId",
            "    // from sales.Customer @ 1 as c\n    id <- d.customerId",
        )
        + "\ndomain broken {"
    )
    state.synchronize(2, replace_document(state, current))

    result = hover(
        state,
        URI,
        position_of(current, "displayName = c.customerName", "c.customerName"),
    )

    assert result is None


def test_hover_does_not_bind_alias_from_escaped_quoted_text() -> None:
    state = parsed_language_workspace()
    current = (
        WORKSPACE_TEXT.replace(
            "    from sales.Customer @ 1 as c",
            "    from sales.Customer @ 1 as d",
        ).replace(
            "    id <- c.customerId",
            '    note = "ignored \\" from sales.Customer @ 1 as c"\n    id <- d.customerId',
        )
        + "\ndomain broken {"
    )
    state.synchronize(2, replace_document(state, current))

    result = hover(
        state,
        URI,
        position_of(current, "displayName = c.customerName", "c.customerName"),
    )

    assert result is None


def test_hover_does_not_bind_alias_from_escaped_single_quoted_text() -> None:
    state = parsed_language_workspace()
    current = (
        WORKSPACE_TEXT.replace(
            "    from sales.Customer @ 1 as c",
            "    from sales.Customer @ 1 as d",
        ).replace(
            "    id <- c.customerId",
            "    note = 'ignored \\' from sales.Customer @ 1 as c'\n    id <- d.customerId",
        )
        + "\ndomain broken {"
    )
    state.synchronize(2, replace_document(state, current))

    result = hover(
        state,
        URI,
        position_of(current, "displayName = c.customerName", "c.customerName"),
    )

    assert result is None


def test_hover_does_not_bind_alias_from_incomplete_single_quoted_text() -> None:
    state = parsed_language_workspace()
    current = WORKSPACE_TEXT.replace(
        "    from sales.Customer @ 1 as c",
        "    from sales.Customer @ 1 as d",
    ).replace(
        "    id <- c.customerId",
        "    note = 'ignored from sales.Customer @ 1 as c\n    id <- d.customerId",
    )
    state.synchronize(2, replace_document(state, current))

    result = hover(
        state,
        URI,
        position_of(current, "displayName = c.customerName", "c.customerName"),
    )

    assert result is None


def test_hover_rejects_current_alias_retargeted_to_unavailable_source() -> None:
    state = parsed_language_workspace()
    current = (
        WORKSPACE_TEXT.replace(
            "    from sales.Customer @ 1 as c",
            "    from unavailable.Customer @ 1 as c",
        )
        + "\ndomain broken {"
    )
    state.synchronize(2, replace_document(state, current))

    result = hover(
        state,
        URI,
        position_of(current, "displayName = c.customerName", "c.customerName"),
    )

    assert result is None


def test_hover_markdown_has_no_active_content() -> None:
    text = WORKSPACE_TEXT.replace(
        '  owner: "sales-team"',
        '  owner: "<img src=x>[click](javascript:alert(1))"',
        1,
    )
    result = hover(
        parsed_language_workspace(text),
        URI,
        position_of(text, "entity Customer", "Customer"),
    )

    assert result is not None
    assert "<" not in result.markdown
    assert "](" not in result.markdown
    assert "&lt;img src=x&gt;" in result.markdown


def test_hover_converts_codepoint_span_to_utf16_range() -> None:
    state = parsed_language_workspace()
    current = WORKSPACE_TEXT.replace(
        "    customerName: string",
        "    😀 customerName",
    )
    state.synchronize(2, replace_document(state, current))
    line = current.splitlines().index("    😀 customerName")

    result = hover(
        state,
        URI,
        LanguagePosition(line, codepoint_to_utf16(current.splitlines()[line], 8)),
    )

    assert result is not None
    assert result.range == LanguageRange.at(line, 7, line, 19)


@pytest.mark.parametrize(
    ("uri", "position"),
    [
        ("file:///missing.mdl", LanguagePosition(0, 0)),
        (URI, LanguagePosition(-1, 0)),
        (URI, LanguagePosition(500, 0)),
        (URI, LanguagePosition(0, -1)),
        (URI, LanguagePosition(0, 500)),
        (URI, LanguagePosition(0, 1)),
    ],
)
def test_hover_returns_none_for_unknown_uri_or_position(
    uri: str,
    position: LanguagePosition,
) -> None:
    assert hover(parsed_language_workspace(), uri, position) is None
